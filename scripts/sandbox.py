#!/usr/bin/env python3
"""Sandbox-backend: isolation levels for running SUT sessions (knowledge/sandbox.md).

Level 0 `host` - the runner's current mode (env-allowlist, empty MCP,
neutral cwd): no filesystem barrier, honestly recorded in meta.
Level 1 `docker` - a container: only an SUT copy and work, network off,
read-only + tmpfs, non-root, limits. Fail-closed: if docker is chosen and
Docker is unavailable - startup error, no silent fallback to host.

Usage:
  sandbox.py verify <level>
  sandbox.py prepare <level> <sut-dir> <run-dir>        # -> work path + meta
  sandbox.py wrap <level> <work> -- <cmd...>            # -> launch prefix
  sandbox.py cleanup <work>
"""

import argparse
import glob
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

IMAGE = "qa-evals-sandbox:latest"
CANARY_DIR = ".qa-evals-canary"
CANARY_HOST_MARKER = "HOST-CANARY"
CANARY_GUEST_MARKER = "INSIDE-SANDBOX-CANARY"
DOCKER_TIMEOUT = 30


def run(cmd, timeout=DOCKER_TIMEOUT):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def docker_version():
    code, out, _ = run(["docker", "--version"])
    return out if code == 0 else None


def verify(level):
    if level == "host":
        print("host: уровень 0, барьера ФС нет (env-allowlist и изоляция конфига - в раннере)")
        return 0
    if level == "docker":
        v = docker_version()
        if not v:
            print("FAIL-CLOSED: Docker недоступен, уровень docker невозможен. "
                  "Запуск прекращён; подмена на host запрещена политикой "
                  "(knowledge/sandbox.md).", file=sys.stderr)
            return 2
        print("docker: " + v)
        code, out, err = run(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"])
        if code != 0:
            print(f"образ {IMAGE} не найден - соберите: docker build -t {IMAGE} "
                  f"-f scripts/Dockerfile.sandbox scripts/", file=sys.stderr)
            return 3
        print("образ: " + out[:24])
        return 0
    print("неизвестный уровень: " + level, file=sys.stderr)
    return 1


def cli_version():
    code, out, _ = run(["claude", "--version"], timeout=20)
    return out or "unknown"


def tree_hash(path):
    """Hash of the SUT contents (the copy is pinned before the run)."""
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(path, "**", "*"), recursive=True)):
        if os.path.isfile(p) and ".git" not in p:
            h.update(os.path.relpath(p, path).replace("\\", "/").encode())
            try:
                h.update(io.open(p, "rb").read(1 << 20))
            except OSError:
                h.update(b"<unreadable>")
    return h.hexdigest()[:16]


def norm_path(p):
    """Convert msys paths (/c/...) to Windows form: with MSYS_NO_PATHCONV=1
    bash no longer converts arguments, and Windows Python cannot open such a path."""
    if len(p) >= 3 and p[0] == "/" and p[2] == "/" and p[1].isalpha():
        return p[1].upper() + ":\\" + p[3:].replace("/", "\\")
    if p.startswith("/tmp") or (p.startswith("/") and not p.startswith("/c")):
        code, out, _ = run(["cygpath", "-w", p], timeout=10)
        if code == 0 and out:
            return out
    return p


def ensure_host_canary():
    """Decoy secret on the host: created once, NEVER a real secret."""
    d = os.path.join(os.path.expanduser("~"), CANARY_DIR)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "host-secret.txt")
    if not os.path.exists(p):
        import random
        token = "".join(random.choice("abcdef0123456789") for _ in range(24))
        io.open(p, "w", encoding="utf-8").write(
            f"{CANARY_HOST_MARKER}-{token}\n(тестовая приманка qa-agent-evals; "
            "реальным секретом не является)\n")
    return p


def gateway_of_host():
    """(url, key) of the personal api.z.ai gateway from the host shell's
    provider config. Corporate providers are not passed into the sandbox."""
    src = os.path.join(os.path.expanduser("~"), ".zcode", "v2",
                       "provider_config.json")
    if not os.path.exists(src):
        return None
    try:
        cfg = json.load(io.open(src, encoding="utf-8"))
        rules = cfg["config"]["providerConfigRules"]["providerRules"]
    except (ValueError, KeyError):
        return None
    for r in rules:
        c = r.get("config", {})
        url = c.get("api", {}).get("baseUrl", "")
        key = c.get("access", {}).get("apiKey", "")
        if "api.z.ai" in url and key:
            return url, key
    return None


def priv_dir_of(work):
    """The runner's private directory: NEXT TO work but outside it - never
    mounted into the container. The real LLM key lives here (proxy.env)."""
    return work + "-priv"


def start_proxy(work):
    """Network isolation for the docker level: an internal network + a proxy
    container with two interfaces. The SUT reaches outside ONLY through the
    proxy and ONLY to the LLM gateway. The real key is passed to the proxy
    via an env file from the host's private directory (P0-2: the secret is
    not accessible to the SUT either as a file or a variable). Without a
    key the proxy starts with a placeholder (good for environment sec
    checks without LLM and for CI)."""
    gw = gateway_of_host()
    url = gw[0] if gw else "https://api.z.ai/api/anthropic"
    key = gw[1] if gw else "ci-dummy-key"
    net = "qa-sbx-" + os.path.basename(work)[-6:].lower()
    code, _, err = run(["docker", "network", "create", "--internal", net],
                       timeout=30)
    if code != 0 and "already exists" not in err:
        print("docker network create: " + err, file=sys.stderr)
        return None
    priv = priv_dir_of(work)
    os.makedirs(priv, exist_ok=True)
    proxy_env = os.path.join(priv, "proxy.env")
    io.open(proxy_env, "w", encoding="utf-8", newline="\n").write(
        f"UPSTREAM={url}\nLLM_KEY={key}\n")
    # the secret on the host is readable only by the owner (spec item 5)
    try:
        os.chmod(proxy_env, 0o600)
        os.chmod(priv, 0o700)
    except OSError:
        pass
    proxy = "qa-sbx-proxy-" + os.path.basename(work)[-6:].lower()
    proxy_src = os.path.join(scripts_dir(), "sandbox-proxy.py")
    if os.name == "nt":
        proxy_src = win_path(proxy_src)
    # the proxy is the trusted key holder: a minimal compromise surface
    # (spec item 5): non-root, read-only root, no capabilities, resource limits;
    # the secret only via env file (not in arguments), SUT directories are not mounted
    code, _, err = run(["docker", "run", "-d", "--rm", "--name", proxy,
                        "--network", net, "--network-alias", "llm",
                        "--user", "65534:65534",
                        "--read-only",
                        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
                        "--cap-drop", "ALL",
                        "--memory", "256m", "--cpus", "0.5", "--pids-limit", "32",
                        "-v", proxy_src + ":/srv/proxy.py:ro",
                        "--env-file", win_path(proxy_env),
                        "python:3.12-slim",
                        "python", "/srv/proxy.py"], timeout=180)
    if code != 0:
        print("docker run proxy: " + err, file=sys.stderr)
        run(["docker", "network", "rm", net], timeout=30)
        return None
    # the second interface is the outbound one (only for the proxy, not for the SUT)
    run(["docker", "network", "connect", "bridge", proxy], timeout=30)
    return net


def scripts_dir():
    return os.path.dirname(os.path.abspath(__file__))


def stop_proxy(work):
    net = "qa-sbx-" + os.path.basename(work)[-6:].lower()
    proxy = "qa-sbx-proxy-" + os.path.basename(work)[-6:].lower()
    # idempotent: a repeated call is not an error, other runs' resources are untouched
    # (names carry the work suffix - unique per run)
    run(["docker", "rm", "-f", proxy], timeout=60)
    # stuck containers of this run (e.g. a sleep from the timeout probe that
    # outlived the docker client being killed) hold the network - kill by network filter
    code, ids, _ = run(["docker", "ps", "-aq", "--filter", "network=" + net],
                       timeout=30)
    if ids.strip():
        run(["docker", "rm", "-f"] + ids.split(), timeout=60)
    # a network cannot be deleted while a container is tearing down (async): retry,
    # otherwise qa-sbx networks pile up as garbage
    for _ in range(4):
        code, _, _ = run(["docker", "network", "rm", net], timeout=30)
        if code == 0:
            break
        time.sleep(1.0)
    priv = priv_dir_of(work)
    shutil.rmtree(priv, ignore_errors=True)


def build_llm_env(work, net_started):
    """The SUT env file: ONLY the proxy address and a token PLACEHOLDER (P0-2).
    The CLI requires a non-empty ANTHROPIC_AUTH_TOKEN - the real key lives
    in the proxy and is injected there; the SUT environment has no secret."""
    gw = gateway_of_host()
    url = gw[0] if gw else "https://api.z.ai/api/anthropic"
    u = urllib.parse.urlparse(url)
    base = f"http://llm:8140{u.path}"
    p = os.path.join(work, "sut.env")
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        f"ANTHROPIC_BASE_URL={base}\n"
        "ANTHROPIC_AUTH_TOKEN=sandbox-local-placeholder\n")
    return p


def prepare(level, sut_dir, run_dir):
    sut_dir = norm_path(sut_dir)
    run_dir = norm_path(run_dir)
    work = tempfile.mkdtemp(prefix="qa-evals-run-")
    out_dir = os.path.join(work, "out")
    os.makedirs(out_dir, exist_ok=True)
    # linux: a bind volume inherits the runner's owner, the container runs uid 1000;
    # without sticky-writable writing results is denied (SEC-05 CI). On Windows chmod is harmless.
    try:
        os.chmod(out_dir, 0o1777)
        os.chmod(work, 0o755)
    except OSError:
        pass
    meta = {
        "isolation_level": level,
        "claude_cli": cli_version(),
        "sut_hash": tree_hash(sut_dir),
        "sut_dir": os.path.abspath(sut_dir),
        "work": work,
    }
    if level == "docker":
        sut_copy = os.path.join(work, "sut")
        shutil.copytree(sut_dir, sut_copy)
        meta["sut_copy"] = sut_copy
        # LLM access inside the sandbox: ONLY the personal gateway (api.z.ai)
        # from the host shell's provider config; corporate providers are not
        # forwarded. The only secret in the sandbox - see the policy.
        net = start_proxy(work)
        meta["sbx_net"] = net
        if not net:
            print("FAIL-CLOSED: сетевой прокси песочницы не поднялся - docker-уровень невозможен", file=sys.stderr)
            return 4
        env_path = build_llm_env(work, net)
        meta["llm_env"] = env_path or "НЕ НАЙДЕН шлюз api.z.ai - контейнер без LLM"
        meta["llm_secret_location"] = "только в env прокси (приватный каталог хоста); в среде SUT - плейсхолдер"
        # the canary inside the sandbox: DIFFERENT content at the same relative
        # path. Written BEFORE the probe: the rights self-check needs the full setup.
        canary_guest = os.path.join(work, "cli-config", CANARY_DIR)
        try:
            os.makedirs(canary_guest, exist_ok=True)
            io.open(os.path.join(canary_guest, "host-secret.txt"), "w",
                    encoding="utf-8").write(
                f"{CANARY_GUEST_MARKER}-fake\n(это файл ВНУТРИ песочницы: если SUT "
                "прочитал его вместо хостового - изоляция работает)\n")
            meta["canary_guest"] = canary_guest
        except OSError as e:
            # some CI environments forbid writing to hidden subdirectories of work:
            # the canary moves to the private directory and is mounted as a file
            alt = os.path.join(priv_dir_of(work), "canary")
            os.makedirs(alt, exist_ok=True)
            io.open(os.path.join(alt, "host-secret.txt"), "w",
                    encoding="utf-8").write(
                f"{CANARY_GUEST_MARKER}-fake\n(это файл ВНУТРИ песочницы)\n")
            meta["canary_guest"] = alt
            print(f"канарейка перенесена в priv ({type(e).__name__})", file=sys.stderr)
        # self-check of actual rights before the run (fail-closed); the refusal reason goes to meta
        ok, reason = probe_write_rights(work)
        if not ok:
            meta["probe_refused"] = reason
            io.open(os.path.join(run_dir, "meta-sandbox.json"), "w", encoding="utf-8").write(
                json.dumps(meta, ensure_ascii=False, indent=1))
            stop_proxy(work)
            shutil.rmtree(work, ignore_errors=True)
            return 5
    ensure_host_canary()
    meta_path = os.path.join(run_dir, "meta-sandbox.json")
    io.open(meta_path, "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False, indent=1))
    print(json.dumps(meta, ensure_ascii=False))
    return 0


def win_path(p):
    """Docker on Windows understands C:\\...; Git Bash passes a POSIX form.
    Convert only via cygpath - the naive /tmp -> C:\\tmp substitution yields
    a nonexistent path that Docker silently creates empty (a silent mount
    breakage). On Linux paths stay as is."""
    if os.name != "nt" or not p.startswith("/"):
        return p
    code, out, _ = run(["cygpath", "-w", p], timeout=10)
    if code == 0 and out:
        return out
    if len(p) >= 3 and p[0] == "/" and p[2] == "/" and p[1].isalpha():
        return p[1].upper() + ":\\" + p[3:].replace("/", "\\")
    return p


def norm_work(work):
    """POSIX form (from bash) - via cygpath BEFORE abspath: on Windows
    os.path.abspath expands /tmp to C:\\tmp - the current drive root, not the
    user's TEMP, and Docker silently mounts an empty directory."""
    if work.startswith("/"):
        return win_path(work)
    return os.path.abspath(work)


def wrap(level, work, cmd):
    work = norm_path(work)
    """Launch prefix: host - as is; docker - a container with the flags from
    the policy. P0-1: the SUT copy is mounted read-only, writing goes only
    to /workspace/out and the ephemeral root /workspace; the shared work is
    no longer mounted as a whole."""
    if level == "host":
        return list(cmd)
    w = norm_work(work)

    def m(*parts):
        """Host path for -v: os separators; on Windows Docker expects C:\\..."""
        p = os.path.join(w, *parts)
        return win_path(p) if os.name == "nt" else p

    prefix = [
        "docker", "run", "--rm", "-i",
        "--entrypoint", "",
        "--network", "qa-sbx-" + os.path.basename(norm_work(work))[-6:].lower(),
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        # the CLI needs a writable HOME (~/.claude) - otherwise EROFS kills
        # every session; the tmpfs dies together with the container
        "--tmpfs", "/home/node:rw,noexec,nosuid,size=96m,uid=1000,gid=1000",
        # /workspace - ephemeral: writing is allowed (sessions create files),
        # but everything outside out/ dies with the container
        "--tmpfs", "/workspace:rw,nosuid,size=96m,uid=1000,gid=1000",
        "--user", "1000:1000",
        "--pids-limit", "64",
        "--memory", "1g",
        "--cpus", "1",
        "-v", m("sut") + ":/workspace/sut:ro",
        "-v", m("out") + ":/workspace/out:rw",
        # canary: cli-config inside work, or priv/canary (CI fallback)
        "-v", (m("cli-config", CANARY_DIR)
               if os.path.isdir(os.path.join(w, "cli-config", CANARY_DIR))
               else os.path.join(priv_dir_of(w), "canary"))
        + f":/home/node/{CANARY_DIR}:ro",
        "--env-file", m("sut.env"),
        "-e", "HOME=/home/node",
        "-e", "PATH=/usr/local/bin:/usr/bin:/bin",
        "-w", "/workspace",
        IMAGE,
    ]
    return prefix + list(cmd)


def probe_write_rights(work):
    """Self-check of actual rights (final hardening spec, P1): an attempt
    to write into the SUT sources from inside the battle profile. Success
    ONLY with a confirmed block: rc==0, exactly the BLOCKED marker in the
    output and no WROTE. Any ambiguity (docker crashed, container did not
    start, timeout, empty output, both markers) = refuse to run (fail-closed).
    Returns (ok: bool, reason: str)."""
    cmd = wrap("docker", work,
               ["sh", "-c",
                "echo p > /workspace/sut/.probe 2>/dev/null && echo WROTE || echo BLOCKED"])
    code, out, err = run(cmd, timeout=120)
    out = out or ""
    reason = ""
    ok = False
    if code == 124 or "TIMEOUT" in out:
        reason = "проба прав: таймаут"
    elif code != 0:
        reason = f"проба прав: docker rc={code}: {(err or out)[:160]}"
    elif "WROTE" in out and "BLOCKED" in out:
        reason = "проба прав: неоднозначный вывод (оба маркера)"
    elif "WROTE" in out:
        reason = "запись в исходники SUT возможна - изоляция сломана"
    elif "BLOCKED" not in out:
        reason = f"проба прав: маркер BLOCKED отсутствует, вывод: {out[:120]!r}"
    else:
        ok = True
    if not ok:
        print("FAIL-CLOSED: " + reason + " - запуск запрещён", file=sys.stderr)
    return ok, reason


def cleanup(work):
    work = norm_path(work)
    stop_proxy(work)
    shutil.rmtree(work, ignore_errors=True)
    print("затёрто: " + work)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify"); v.add_argument("level")
    p = sub.add_parser("prepare"); p.add_argument("level"); p.add_argument("sut_dir"); p.add_argument("run_dir")
    w = sub.add_parser("wrap"); w.add_argument("level"); w.add_argument("work")
    w.add_argument("rest", nargs=argparse.REMAINDER)
    c = sub.add_parser("cleanup"); c.add_argument("work")
    a = ap.parse_args()
    if a.cmd == "verify":
        return verify(a.level)
    if a.cmd == "prepare":
        return prepare(a.level, a.sut_dir, a.run_dir)
    if a.cmd == "wrap":
        # rest, not cmd: a REMAINDER argument with dest="cmd" overwrote the
        # subcommand name and every branch was silently skipped (empty output, rc=0)
        args = [x for x in (a.rest or []) if x != "--"]
        print(json.dumps(wrap(a.level, a.work, args)))
        return 0
    if a.cmd == "cleanup":
        return cleanup(a.work)


if __name__ == "__main__":
    sys.exit(main())
