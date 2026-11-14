#!/usr/bin/env python3
"""Parse a SUT session run log (events.jsonl -> txt/prov/diag).

The acceptance logging module: a single point that turns the event stream
of a headless session (claude -p --output-format stream-json --verbose)
into three run artifacts. Used by the run-cards.sh runner and by the
multi-turn card executors (after every turn).

Usage: parse-events.py <run-dir> <id> <rep>
  <run-dir> - the run directory (a Windows or POSIX path: /c/... is converted)
Writes into <run-dir>/прогоны/<id>-r<rep>:
  .txt      - the SUT's answer text (intermediate assistant blocks + the
              final result; on max-turns/error the result can be empty -
              the intermediate blocks save it)
  .prov.txt - provenance: unique "Read: <path>" from Read/Grep/Glob tool calls
  .diag.txt - error-class diagnostics (see adapters.md, "Run diagnostics")

Exit: 0 - artifacts written; 1 - events.jsonl missing/empty (the
"session did not start" diagnostic is still written).
"""

import io
import json
import os
import sys
import tempfile


def norm(path: str) -> str:
    """A Git Bash POSIX path (/c/...) -> Windows (C:\\...); anything else as is.

    /tmp is Git Bash's mount of the user's temp dir: on Windows it resolves to
    the real %TEMP% (a /tmp run dir reached the parser unconverted and the
    transcripts were restored by hand, field run 2026-11-12). On POSIX /tmp is
    a real directory and stays as is."""
    if len(path) >= 3 and path[0] == "/" and path[2] == "/" and path[1].isalpha():
        return path[1] + ":\\" + path[3:].replace("/", "\\")
    if os.name == "nt" and (path == "/tmp" or path.startswith("/tmp/")):
        rest = path[5:]  # "" for /tmp itself
        return os.path.join(tempfile.gettempdir(), rest) if rest else tempfile.gettempdir()
    return path


def parse(events_path: str, base: str) -> list:
    texts, prov, diag = [], [], []
    if not os.path.exists(events_path) or os.path.getsize(events_path) == 0:
        diag.append("среда: сессия не стартовала (событий нет; смотреть .err)")
        return texts, prov, diag
    for line in io.open(events_path, encoding="utf-8", errors="replace"):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for blk in content:
                if blk.get("type") == "text" and (blk.get("text") or "").strip():
                    texts.append(blk["text"])
                if blk.get("type") == "tool_use" and blk.get("name") in ("Read", "Grep", "Glob"):
                    inp = blk.get("input", {})
                    p = inp.get("file_path") or inp.get("path") or ""
                    if p:
                        prov.append(f"{blk['name']}: {p}")
        if ev.get("type") == "result":
            r = ev.get("result")
            if isinstance(r, str) and r.strip():
                texts.append(r)
                if ev.get("is_error") or ev.get("subtype") == "error_during_execution":
                    diag.append("среда/ошибка: " + r[:200])
            if ev.get("subtype") == "error_during_execution" and not (isinstance(r, str) and r.strip()):
                diag.append("среда: error_during_execution без текста")
    if not texts:
        diag.append("адаптер: ответа нет (max-turns исчерпан до текста или пустой result)")
    return texts, prov, diag


def main() -> int:
    if len(sys.argv) != 4:
        sys.exit("usage: parse-events.py <run-dir> <id> <rep-суффикс>")
    run_dir, cid, rep = norm(sys.argv[1]), sys.argv[2], sys.argv[3]
    runs = os.path.join(run_dir, "прогоны")
    base = os.path.join(runs, f"{cid}-{rep}")
    events_path = base + ".events.jsonl"
    texts, prov, diag = parse(events_path, base)
    if texts:
        io.open(base + ".txt", "w", encoding="utf-8").write("\n".join(texts))
    io.open(base + ".prov.txt", "w", encoding="utf-8").write(
        "".join(p + "\n" for p in dict.fromkeys(prov)))
    io.open(base + ".diag.txt", "w", encoding="utf-8").write(
        ("; ".join(dict.fromkeys(diag)) + "\n") if diag else "ок\n")
    return 0 if texts else 1


if __name__ == "__main__":
    sys.exit(main())
