#!/usr/bin/env python3
"""Sandbox-backend: уровни изоляции для запуска SUT-сессий (knowledge/sandbox.md).

Уровень 0 `host` - теперешний режим раннера (env-allowlist, пустой MCP,
нейтральный cwd): барьера ФС нет, честно помечается в meta.
Уровень 1 `docker` - контейнер: только копия SUT и work, сеть off,
read-only + tmpfs, non-root, лимиты. Fail-closed: выбрали docker, а Docker
недоступен - ошибка запуска, тихой подмены на host нет.

Usage:
  sandbox.py verify <level>
  sandbox.py prepare <level> <sut-dir> <run-dir>        # -> work-путь + meta
  sandbox.py wrap <level> <work> -- <cmd...>            # -> префикс запуска
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
    """Хеш содержимого SUT (копия фиксируется до прогона)."""
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
    """msys-пути (/c/...) в Windows-вид: при MSYS_NO_PATHCONV=1 bash больше
    не конвертирует аргументы, и Windows-питон такой путь не откроет."""
    if len(p) >= 3 and p[0] == "/" and p[2] == "/" and p[1].isalpha():
        return p[1].upper() + ":\\" + p[3:].replace("/", "\\")
    if p.startswith("/tmp") or (p.startswith("/") and not p.startswith("/c")):
        code, out, _ = run(["cygpath", "-w", p], timeout=10)
        if code == 0 and out:
            return out
    return p


def ensure_host_canary():
    """Секрет-приманка на хосте: создаётся один раз, НИКОГДА не реальный секрет."""
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
    """(url, key) личного шлюза api.z.ai из provider-конфига хост-оболочки.
    Корпоративные провайдеры в песочницу не передаются."""
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
    """Приватный каталог раннера: РЯДОМ с work, но вне его - никогда не
    монтируется в контейнер. Здесь живёт настоящий LLM-ключ (proxy.env)."""
    return work + "-priv"


def start_proxy(work):
    """Сетевая изоляция уровня docker: internal-сеть + прокси-контейнер с
    двумя интерфейсами. SUT ходит наружу ТОЛЬКО через прокси и ТОЛЬКО к
    LLM-шлюзу. Настоящий ключ передаётся прокси через env-файл из
    приватного каталога хоста (P0-2: секрет недоступен SUT ни файлом,
    ни переменной). Нет ключа - прокси стартует с плейсхолдером
    (годится для sec-проверок среды без LLM и для CI)."""
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
    # секрет на хосте читается только владельцем (ТЗ п.5)
    try:
        os.chmod(proxy_env, 0o600)
        os.chmod(priv, 0o700)
    except OSError:
        pass
    proxy = "qa-sbx-proxy-" + os.path.basename(work)[-6:].lower()
    proxy_src = os.path.join(scripts_dir(), "sandbox-proxy.py")
    if os.name == "nt":
        proxy_src = win_path(proxy_src)
    # прокси - доверенный держатель ключа: минимальная поверхность компрометации
    # (ТЗ п.5): non-root, read-only корень, без capabilities, лимиты ресурсов;
    # секрет только через env-файл (не в аргументах), каталоги SUT не монтируются
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
    # второй интерфейс - выходной (только у прокси, не у SUT)
    run(["docker", "network", "connect", "bridge", proxy], timeout=30)
    return net


def scripts_dir():
    return os.path.dirname(os.path.abspath(__file__))


def stop_proxy(work):
    net = "qa-sbx-" + os.path.basename(work)[-6:].lower()
    proxy = "qa-sbx-proxy-" + os.path.basename(work)[-6:].lower()
    # идемпотентно: повторный вызов не ошибка, чужие ресурсы не трогаем
    # (имена содержат суффикс work - уникальны на запуск)
    run(["docker", "rm", "-f", proxy], timeout=60)
    # застрявшие контейнеры этого запуска (напр. sleep из таймаут-пробы,
    # переживший убийство docker-клиента) держат сеть - добиваем по фильтру сети
    code, ids, _ = run(["docker", "ps", "-aq", "--filter", "network=" + net],
                       timeout=30)
    if ids.strip():
        run(["docker", "rm", "-f"] + ids.split(), timeout=60)
    # сеть нельзя удалить, пока контейнер отваливается (async): retry,
    # иначе qa-sbx-сети копятся как мусор
    for _ in range(4):
        code, _, _ = run(["docker", "network", "rm", net], timeout=30)
        if code == 0:
            break
        time.sleep(1.0)
    priv = priv_dir_of(work)
    shutil.rmtree(priv, ignore_errors=True)


def build_llm_env(work, net_started):
    """env-файл SUT: ТОЛЬКО адрес прокси и ПЛЕЙСХОЛДЕР токена (P0-2).
    CLI требует непустой ANTHROPIC_AUTH_TOKEN - настоящий ключ живёт
    в прокси и подставляется им; в среде SUT секрета нет."""
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
    # linux: bind-том наследует владельца раннера, контейнер работает uid 1000;
    # без sticky-writable запись результатов запрещена (SEC-05 CI). На Windows chmod безвреден.
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
        # LLM-доступ внутрь песочницы: ТОЛЬКО личный шлюз (api.z.ai) из
        # provider-конфига хост-оболочки; корпоративные провайдеры не
        # прокидываются. Единственный секрет в песочнице - см. политику.
        net = start_proxy(work)
        meta["sbx_net"] = net
        if not net:
            print("FAIL-CLOSED: сетевой прокси песочницы не поднялся - docker-уровень невозможен", file=sys.stderr)
            return 4
        env_path = build_llm_env(work, net)
        meta["llm_env"] = env_path or "НЕ НАЙДЕН шлюз api.z.ai - контейнер без LLM"
        meta["llm_secret_location"] = "только в env прокси (приватный каталог хоста); в среде SUT - плейсхолдер"
        # канарейка внутри песочницы: ДРУГОЕ содержимое на том же относительном
        # пути. Пишем ДО probe: самопроверка прав требует полной конфигурации.
        canary_guest = os.path.join(work, "cli-config", CANARY_DIR)
        try:
            os.makedirs(canary_guest, exist_ok=True)
            io.open(os.path.join(canary_guest, "host-secret.txt"), "w",
                    encoding="utf-8").write(
                f"{CANARY_GUEST_MARKER}-fake\n(это файл ВНУТРИ песочницы: если SUT "
                "прочитал его вместо хостового - изоляция работает)\n")
            meta["canary_guest"] = canary_guest
        except OSError as e:
            # отдельные CI-среды не дают писать скрытые подкаталоги work:
            # канарейка переезжает в приватный каталог, монтируется файлом
            alt = os.path.join(priv_dir_of(work), "canary")
            os.makedirs(alt, exist_ok=True)
            io.open(os.path.join(alt, "host-secret.txt"), "w",
                    encoding="utf-8").write(
                f"{CANARY_GUEST_MARKER}-fake\n(это файл ВНУТРИ песочницы)\n")
            meta["canary_guest"] = alt
            print(f"канарейка перенесена в priv ({type(e).__name__})", file=sys.stderr)
        # самопроверка фактических прав до прогона (fail-closed); причина отказа - в meta
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
    """Docker на Windows понимает C:\\...; из Git Bash приходит POSIX-вид.
    Конвертация только через cygpath - наивная замена /tmp -> C:\\tmp даёт
    несуществующий путь, который Docker молча создаёт пустым (тихая поломка
    монтирования). На Linux пути остаются как есть."""
    if os.name != "nt" or not p.startswith("/"):
        return p
    code, out, _ = run(["cygpath", "-w", p], timeout=10)
    if code == 0 and out:
        return out
    if len(p) >= 3 and p[0] == "/" and p[2] == "/" and p[1].isalpha():
        return p[1].upper() + ":\\" + p[3:].replace("/", "\\")
    return p


def norm_work(work):
    """POSIX-вид (из bash) - через cygpath ДО abspath: os.path.abspath на
    Windows разворачивает /tmp в C:\\tmp - корень текущего диска, а не TEMP
    пользователя, и Docker молча монтирует пустой каталог."""
    if work.startswith("/"):
        return win_path(work)
    return os.path.abspath(work)


def wrap(level, work, cmd):
    work = norm_path(work)
    """Префикс запуска: host - как есть; docker - контейнер с флагами из
    политики. P0-1: копия SUT монтируется read-only, запись - только в
    /workspace/out и ephemeral-корень /workspace; общий work больше не
    монтируется целиком."""
    if level == "host":
        return list(cmd)
    w = norm_work(work)

    def m(*parts):
        """Путь хоста для -v: os-разделители; на Windows Docker ждёт C:\\..."""
        p = os.path.join(w, *parts)
        return win_path(p) if os.name == "nt" else p

    prefix = [
        "docker", "run", "--rm", "-i",
        "--entrypoint", "",
        "--network", "qa-sbx-" + os.path.basename(norm_work(work))[-6:].lower(),
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        # CLI требует записываемый HOME (~/.claude) - иначе EROFS валит
        # каждую сессию; tmpfs умирает вместе с контейнером
        "--tmpfs", "/home/node:rw,noexec,nosuid,size=96m,uid=1000,gid=1000",
        # /workspace - ephemeral: писать можно (сессии создают файлы),
        # но вне out/ всё умирает с контейнером
        "--tmpfs", "/workspace:rw,nosuid,size=96m,uid=1000,gid=1000",
        "--user", "1000:1000",
        "--pids-limit", "64",
        "--memory", "1g",
        "--cpus", "1",
        "-v", m("sut") + ":/workspace/sut:ro",
        "-v", m("out") + ":/workspace/out:rw",
        # канарейка: cli-config внутри work, либо priv/canary (CI-fallback)
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
    """Самопроверка фактических прав (ТЗ финального усиления, P1): попытка
    записи в исходники SUT изнутри боевого профиля. Успех ТОЛЬКО при
    подтверждённой блокировке: rc==0, в выводе ровно маркер BLOCKED и нет
    WROTE. Любая неоднозначность (docker упал, контейнер не стартовал,
    таймаут, пустой вывод, оба маркера) = отказ запуска (fail-closed).
    Возвращает (ok: bool, reason: str)."""
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
        # rest, не cmd: REMAINDER-аргумент с dest="cmd" затирал имя подкоманды
        # и все ветки молча пропускались (пустой вывод, rc=0)
        args = [x for x in (a.rest or []) if x != "--"]
        print(json.dumps(wrap(a.level, a.work, args)))
        return 0
    if a.cmd == "cleanup":
        return cleanup(a.work)


if __name__ == "__main__":
    sys.exit(main())
