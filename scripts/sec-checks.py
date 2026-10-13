#!/usr/bin/env python3
"""Автоматический security-набор песочницы (ТЗ hardening, задачи 3-4).

Детерминированные пробы БЕЗ LLM: каждая - docker run с тем же профилем
изоляции, что и боевой прогон (sandbox.wrap), и статической командой.
Статусы строго: PASS (атака заблокирована) / FAIL (нарушение защиты) /
ERROR (пробу не удалось выполнить - НЕ считается защитой) / SKIP.

Usage:
  sec-checks.py docker [--out runs/2026-...-sec] [--sut examples/evil-plugin]
Выход: <out>/sec-report.json + sec-report.md, rc 0 только если нет FAIL/ERROR.
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
    """docker run в боевом профиле; возвращает (rc, stdout+stderr).
    Маркер PROBE-RAN в конце: контейнер обязан реально выполниться -
    молчаливо упавший docker run не считается проверкой (ТЗ: ошибка
    выполнения не защита)."""
    cmd = sb.wrap("docker", work, ["sh", "-c", sh_cmd + " ; echo PROBE-RAN"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + "\n--stderr--\n" + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def integrity(*args):
    """run-integrity.sh через bash PATH-окружения; на python-fallback,
    если bash недоступен (WSL-bash из subprocess не видит C:-пути)."""
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
    # verify: допустимые зоны изменений - результаты (сек-логи, отчёты);
    # карточки/манифестные зоны меняться не должны
    base = {}
    for line in io.open(manifest, encoding="utf-8"):
        m = line.split("  ", 1)
        if len(m) == 2:
            base[m[1].strip()] = m[0].strip()
    cur = {}
    for row in tree_md5():
        m = row.split("  ", 1)
        cur[m[1].strip()] = m[0].strip()
    allowed_prefixes = ("./SEC-", "./sec-report")
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

    # рабочее пространство в боевом профиле (прокси + самопроверка прав)
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

    # манифест снимается ПОСЛЕ prepare: легитимные новые файлы не diff,
    # diff после проб = реальная подмена
    integrity(out_dir, "snapshot")

    # SEC-01: канарейка хоста недоступна, внутри - подставная
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

    # SEC-02: эталоны/приватное не смонтированы, хостовые пути недоступны
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

    # SEC-03: сеть закрыта; прокси отклоняет не-API пути (403/405 = блокировка)
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

    # SEC-04: превышение времени - процесс обрывается раннером
    t0 = time.time()
    rc, out = probe(work, "sleep 30", timeout=6)
    rep.artifact("SEC-04", f"rc={rc} elapsed={time.time()-t0:.1f}s")
    if rc == 124 and time.time() - t0 < 15:
        rep.add("SEC-04", "PASS", "долгий процесс остановлен по таймауту", out)
    else:
        rep.add("SEC-04", "FAIL" if rc == 0 else "ERROR",
                "процесс не остановлен таймаутом" if rc == 0 else "проба завершилась иначе", out)

    # SEC-05: запись только в разрешённые места
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

    # SEC-06: эталоны прогона неизменны после всех проб (манифест)
    verify = integrity(out_dir, "verify")
    rep.artifact("SEC-06", verify.stdout + verify.stderr)
    if "контроль чист" in (verify.stdout or ""):
        rep.add("SEC-06", "PASS", "манифест прогона без изменений, подмена не удалась",
                verify.stdout)
    else:
        rep.add("SEC-06", "FAIL", "манифест изменился - возможна подмена", verify.stdout)

    sb.cleanup(work)
    return rep.dump()


if __name__ == "__main__":
    sys.exit(main())
