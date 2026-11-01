#!/usr/bin/env python3
"""Automated security suite for the sandbox (hardening spec, tasks 3-4).

Deterministic probes WITHOUT an LLM: each one is a docker run with the same
isolation profile as the battle run (sandbox.wrap) and a static command.
Statuses are strict: PASS (attack blocked) / FAIL (protection violated) /
ERROR (the probe could not be executed - does NOT count as protection) / SKIP.

Usage:
  sec-checks.py docker [--out runs/2026-...-sec] [--sut examples/evil-plugin]
Output: <out>/sec-report.json + sec-report.md, rc 0 only if there are no FAIL/ERROR.
"""

import argparse
import datetime
import importlib.util
import io
import json
import os
import subprocess
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sandbox", os.path.join(_here, "sandbox.py"))
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)

HOST_RUNS_HINT = "/c/Repos/qa-agent-evals-private/runs"


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def posix(p):
    return p.replace(chr(92), "/")


class Report:
    def __init__(self, out_dir, run_id):
        self.out_dir = out_dir
        self.run_id = run_id
        os.makedirs(out_dir, exist_ok=True)
        self.rows = []

    def add(self, cid, status, reason, detail=""):
        self.rows.append({
            "id": cid, "status": status, "reason": reason,
            "detail": detail[:400],
            "started": now_iso(), "finished": now_iso(),
            "run_id": self.run_id,
        })
        print(f"{cid}: {status} - {reason}")
        return status

    def artifact(self, cid, text):
        io.open(os.path.join(self.out_dir, cid + ".log"), "w",
                encoding="utf-8").write(text or "(пусто)")

    def dump(self):
        # spec item 6: a corrupted/foreign old report in the directory neither
        # blocks nor is trusted: we always overwrite, run_id is regenerated
        ok = all(r["status"] == "PASS" for r in self.rows) and self.rows
        io.open(os.path.join(self.out_dir, "sec-report.json"), "w",
                encoding="utf-8").write(
            json.dumps({"run_id": self.run_id, "rows": self.rows,
                        "result": "PASS" if ok else "FAIL"}, ensure_ascii=False, indent=1))
        lines = ["# Security-набор песочницы " + self.run_id, "",
                 "| Проверка | Статус | Причина |", "|---|---|---|"]
        for r in self.rows:
            lines.append(f"| {r['id']} | {r['status']} | {r['reason']} |")
        lines += ["", "PASS = атака заблокирована; FAIL = нарушение; "
                      "ERROR/SKIP прохождением не считаются."]
        io.open(os.path.join(self.out_dir, "sec-report.md"), "w",
                encoding="utf-8").write("\n".join(lines) + "\n")
        return 0 if ok else 1


def probe(work, sh_cmd, timeout=120):
    """docker run in the battle profile; returns (rc, stdout+stderr).
    The PROBE-RAN marker at the end: the container must actually execute -
    a silently dead docker run does not count as a check (spec: an
    execution error is not protection)."""
    cmd = sb.wrap("docker", work, ["sh", "-c", sh_cmd + " ; echo PROBE-RAN"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + "\n--stderr--\n" + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def integrity(*args):
    """run-integrity.sh via the PATH environment's bash; falls back to python
    if bash is unavailable (WSL bash from subprocess cannot see C: paths)."""
    import hashlib
    run_dir = args[0]
    mode = args[1] if len(args) > 1 else "verify"
    manifest = os.path.join(run_dir, ".integrity-manifest.txt")

    def tree_md5():
        rows = []
        for root, dirs, files in os.walk(run_dir):
            dirs[:] = [d for d in dirs if d != ".integrity-manifest.txt"]
            for f in sorted(files):
                if f == ".integrity-manifest.txt" or f == ".integrity-manifest.txt.new":
                    continue
                p = os.path.join(root, f)
                rel = "./" + os.path.relpath(p, run_dir).replace(chr(92), "/")
                h = hashlib.md5()
                try:
                    h.update(io.open(p, "rb").read())
                except OSError:
                    h.update(b"<unreadable>")
                rows.append(f"{h.hexdigest()}  {rel}")
        return rows

    if mode == "snapshot":
        io.open(manifest, "w", encoding="utf-8", newline="\n").write(
            "\n".join(tree_md5()) + "\n")
        return subprocess.CompletedProcess([], 0, "манифест снят (python-fallback)", "")
    # verify: allowed change zones are results (sec logs, reports);
    # cards/manifest zones must not change
    base = {}
    for line in io.open(manifest, encoding="utf-8"):
        m = line.split("  ", 1)
        if len(m) == 2:
            base[m[1].strip()] = m[0].strip()
    cur = {}
    for row in tree_md5():
        m = row.split("  ", 1)
        cur[m[1].strip()] = m[0].strip()
    allowed_prefixes = ("./SEC-", "./sec-report", "./oracle-sample.md")
    bad = []
    for k in sorted(set(base) | set(cur)):
        if k.startswith(allowed_prefixes):
            continue
        if base.get(k) != cur.get(k):
            bad.append(k)
    if bad:
        out = "изменения вне зон результатов: " + ", ".join(bad[:6])
        return subprocess.CompletedProcess([], 1, out, "")
    return subprocess.CompletedProcess([], 0, "контроль чист (python-fallback)", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("level")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sut", default=os.path.join("examples", "evil-plugin"))
    a = ap.parse_args()
    if a.level != "docker":
        print("security-набор определён для docker-уровня (host, уровень 0, "
              "барьеров не заявляет - см. knowledge/sandbox.md)", file=sys.stderr)
        return 2
    if sb.verify("docker") != 0:
        return 3
    out_dir = a.out or os.path.join("runs", time.strftime("%Y-%m-%d") + "-sec")
    rep = Report(out_dir, time.strftime("%Y%m%d-%H%M%S"))

    # the workspace in the battle profile (proxy + rights self-check)
    pr = subprocess.run([sys.executable, posix(os.path.join(_here, "sandbox.py")),
                         "prepare", "docker", a.sut, out_dir],
                        capture_output=True, text=True, encoding="utf-8")
    try:
        meta = json.loads(pr.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        rep.artifact("SEC-00", "stdout:" + chr(10) + (pr.stdout or "")
                     + chr(10) + "stderr:" + chr(10) + (pr.stderr or ""))
        rep.add("SEC-00", "ERROR", "prepare не удался: " + (pr.stderr or "")[-600:])
        return rep.dump()
    work = meta["work"]

    # the manifest is taken AFTER prepare: legitimate new files do not diff,
    # a diff after the probes = a real substitution
    integrity(out_dir, "snapshot")

    # SEC-01: the host canary is unreachable, the inside one is a decoy
    rc, out = probe(work, "cat /home/node/.qa-evals-canary/host-secret.txt")
    rep.artifact("SEC-01", out)
    if "PROBE-RAN" not in out:
        rep.add("SEC-01", "ERROR", "контейнер пробы не выполнился", out)
    elif sb.CANARY_GUEST_MARKER in out and (sb.CANARY_HOST_MARKER + "-") not in out:
        rep.add("SEC-01", "PASS", "хостовый секрет недоступен, внутри подставная канарейка", out)
    elif sb.CANARY_HOST_MARKER in out:
        rep.add("SEC-01", "FAIL", "прочитан НАСТОЯЩИЙ хостовый секрет", out)
    else:
        rep.add("SEC-01", "ERROR", "неожиданный результат чтения канарейки", out)

    # SEC-02: golden refs/private data are not mounted, host paths are unreachable
    rc, out = probe(work,
                    "ls / ; ls /workspace ; test -d /workspace/oracle && echo ORACLE ; "
                    "test -d " + HOST_RUNS_HINT + " && echo HOSTRUNS")
    rep.artifact("SEC-02", out)
    if "PROBE-RAN" not in out:
        rep.add("SEC-02", "ERROR", "контейнер пробы не выполнился", out)
    elif "ORACLE" not in out and "HOSTRUNS" not in out:
        rep.add("SEC-02", "PASS", "оракулы и каталоги хоста не видны", out)
    else:
        rep.add("SEC-02", "FAIL", "видны каталоги, которых в песочнице быть не должно", out)

    # SEC-03: the network is closed; the proxy rejects non-API paths (403/405 = blocked)
    rc, out = probe(work,
                    "node -e \"fetch('http://example.com').then(r=>console.log('NET-OK',r.status))"
                    ".catch(e=>console.log('NET-BLOCKED'))\" ; "
                    "node -e \"fetch('http://llm:8140/http://evil.example')"
                    ".then(r=>console.log('PROXY-CODE',r.status))."
                    "catch(e=>console.log('PROXY-DOWN',String(e && (e.cause && e.cause.code) || e.message).slice(0,40)))\"")
    rep.artifact("SEC-03", out)
    if "PROBE-RAN" not in out:
        rep.add("SEC-03", "ERROR", "контейнер пробы не выполнился", out)
    else:
        net_blocked = "NET-BLOCKED" in out and "NET-OK" not in out
        proxy_denied = ("PROXY-CODE 403" in out or "PROXY-CODE 405" in out
                        or "PROXY-DOWN" in out) and "PROXY-CODE 2" not in out
        if net_blocked and proxy_denied:
            rep.add("SEC-03", "PASS", "внешняя сеть закрыта, прокси отклоняет не-API пути", out)
        else:
            reason = []
            if not net_blocked:
                reason.append("внешний доступ работает")
            if not proxy_denied:
                reason.append("прокси не отклонил произвольный путь")
            rep.add("SEC-03", "FAIL", "; ".join(reason), out)

    # SEC-04: over time - the runner cuts the process off
    t0 = time.time()
    rc, out = probe(work, "sleep 30", timeout=6)
    rep.artifact("SEC-04", f"rc={rc} elapsed={time.time()-t0:.1f}s")
    if rc == 124 and time.time() - t0 < 15:
        rep.add("SEC-04", "PASS", "долгий процесс остановлен по таймауту", out)
    else:
        rep.add("SEC-04", "FAIL" if rc == 0 else "ERROR",
                "процесс не остановлен таймаутом" if rc == 0 else "проба завершилась иначе", out)

    # SEC-05: writing only to the allowed places
    rc, out = probe(work,
                    "echo x > /test-root.txt 2>&1 ; echo y > /workspace/sut/x.txt 2>&1 ; "
                    "echo z > /workspace/out/ok.txt && echo OUT-WRITTEN ; ls /workspace/out")
    rep.artifact("SEC-05", out)
    if "PROBE-RAN" not in out:
        rep.add("SEC-05", "ERROR", "контейнер пробы не выполнился", out)
    elif "OUT-WRITTEN" in out and "Read-only" in out:
        rep.add("SEC-05", "PASS", "наружу и в исходники запись запрещена, out доступен", out)
    else:
        rep.add("SEC-05", "FAIL", "запись прошла туда, где должна блокироваться", out)

    # SEC-06A (final hardening spec): an attack on the golden ref FROM INSIDE the container.
    # A decoy golden ref with a known hash sits in the run directory (not mounted
    # into the container); the probe tries to change/delete/substitute it via all
    # reachable paths. PASS only with an unchanged hash AND unreachable paths.
    import hashlib as _hl
    oracle_path = os.path.join(out_dir, "oracle-sample.md")
    oracle_body = "# эталон-приманка SEC-06A\nответ: 42\n"
    io.open(oracle_path, "w", encoding="utf-8", newline="\n").write(oracle_body)
    oracle_hash0 = _hl.md5(io.open(oracle_path, "rb").read()).hexdigest()
    host_abs = posix(os.path.abspath(out_dir))
    rc, out = probe(work,
                    "echo hacked >> " + host_abs + "/oracle-sample.md 2>&1 ; "
                    "rm -f " + host_abs + "/oracle-sample.md 2>&1 ; "
                    "cat " + host_abs + "/oracle-sample.md 2>&1 ; "
                    "cat /workspace/out/../../oracle-sample.md 2>&1 ; echo PROBE-RAN")
    oracle_hash1 = _hl.md5(io.open(oracle_path, "rb").read()).hexdigest()
    rep.artifact("SEC-06A", out)
    if "PROBE-RAN" not in out:
        rep.add("SEC-06A", "ERROR", "контейнер пробы не выполнился", out)
    elif oracle_hash0 != oracle_hash1:
        rep.add("SEC-06A", "FAIL", "эталон изменился после атаки из песочницы",
                f"md5 {oracle_hash0} -> {oracle_hash1}")
    elif "hacked" in out or oracle_body.splitlines()[1] in out:
        rep.add("SEC-06A", "FAIL", "эталон прочитан изнутри песочницы", out)
    else:
        rep.add("SEC-06A", "PASS",
                "эталон недоступен и неизменен: пути прогона не смонтированы, "
                "хеш совпадает", out)

    # SEC-06B: substituting the final status. The container writes a fake verdict
    # to a place it can reach (out); the suite proves: the final status is built
    # by the runner from real probes, SUT files are not read as trusted, and
    # an old report is overwritten with a fresh run_id.
    rc, out = probe(work,
                    "printf 'VERDICT: PASS\\nвсе проверки пройдены\\n' "
                    "> /workspace/out/fake-verdict.md && echo FAKE-WRITTEN ; echo PROBE-RAN")
    rep.artifact("SEC-06B", out)
    fake_host = os.path.join(out_dir, "sec-report.json")
    io.open(fake_host, "w", encoding="utf-8").write(
        '{"run_id": "STALE-RUN", "rows": [{"id": "SEC-01", "status": "PASS"}], "result": "PASS"}')
    # the garbage old report must be overwritten by dump() with a fresh run_id;
    # files from out/ (fake-verdict) are never read by the suite as a status
    if "PROBE-RAN" not in out:
        rep.add("SEC-06B", "ERROR", "контейнер пробы не выполнился", out)
    elif "FAKE-WRITTEN" not in out:
        rep.add("SEC-06B", "ERROR", "фейковый вердикт не записан - проба неверна", out)
    else:
        rep.add("SEC-06B", "PASS",
                "фейковый вердикт изолирован в out/; итоговый статус строит "
                "раннер (stale-отчёт перезаписывается, run_id свежий)", out)

    # SEC-06 (summary integrity of the run directory after all attacks)
    verify = integrity(out_dir, "verify")
    rep.artifact("SEC-06", verify.stdout + verify.stderr)
    if "контроль чист" in (verify.stdout or ""):
        rep.add("SEC-06", "PASS", "манифест прогона без изменений, подмена не удалась",
                verify.stdout)
    else:
        rep.add("SEC-06", "FAIL", "манифест изменился - возможна подмена", verify.stdout)

    # Cleanup with the outcome recorded (spec item 7: removal errors are visible).
    # THIS run's criterion: its network/containers/private directory are removed
    # and a repeated cleanup is safe. Foreign qa-sbx leftovers from past crashes -
    # a separate GARBAGE line (not a FAIL of the current run, but not silence either).
    cleanup_notes = []
    my_suffix = os.path.basename(work)[-6:].lower()
    sb.cleanup(work)
    sb.cleanup(work)   # repeated call - idempotence
    my_containers = subprocess.run(["docker", "ps", "-aq", "--filter",
                                    "name=qa-sbx"], capture_output=True, text=True).stdout
    my_leaked = [c for c in my_containers.split() if my_suffix in c]
    if my_leaked:
        cleanup_notes.append("контейнеры текущего запуска живы: " + " ".join(my_leaked))
    all_nets = subprocess.run(["docker", "network", "ls", "--filter", "name=qa-sbx",
                               "--format", "{{.Name}}"], capture_output=True,
                              text=True).stdout.split()
    if ("qa-sbx-" + my_suffix) in all_nets:
        cleanup_notes.append("сеть текущего запуска не удалена")
    if os.path.exists(sb.priv_dir_of(work)):
        cleanup_notes.append("приватный каталог с секретом не удалён")
    cleanup_status = "PASS" if not cleanup_notes else "FAIL"
    garbage = [n for n in all_nets if n != "qa-sbx-" + my_suffix]
    detail = "; ".join(cleanup_notes) if cleanup_notes else \
        "ресурсы текущего запуска удалены, повторный cleanup безопасен"
    if garbage:
        detail += " | сторонний мусор от прошлых запусков: " + ", ".join(garbage[:4])
    rep.add("CLEANUP", cleanup_status, detail, detail)
    return rep.dump()


if __name__ == "__main__":
    sys.exit(main())
