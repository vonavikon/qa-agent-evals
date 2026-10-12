#!/usr/bin/env python3
"""Разбор лога прогона SUT-сессии (events.jsonl -> txt/prov/diag).

Модуль логирования приёмки: единая точка превращения потока событий
headless-сессии (claude -p --output-format stream-json --verbose) в три
артефакта прогона. Используется раннером run-cards.sh и исполнителями
многоходовых карточек (после каждого хода).

Usage: parse-events.py <run-dir> <id> <rep>
  <run-dir> - каталог прогона (Windows- или POSIX-путь: /c/... конвертируется)
Пишет в <run-dir>/прогоны/<id>-r<rep>:
  .txt      - текст ответа SUT (промежуточные assistant-блоки + финальный result;
              при max-turns/ошибке result бывает пуст - промежуточные спасают)
  .prov.txt - провенанс: уникальные "Read: <путь>" по tool-вызовам Read/Grep/Glob
  .diag.txt - диагностика класса ошибки (см. adapters.md, «Диагностика прогона»)

Выход: 0 - артефакты записаны; 1 - events.jsonl отсутствует/пуст (диагностика
«сессия не стартовала» всё равно записана).
"""

import io
import json
import os
import sys


def norm(path: str) -> str:
    """POSIX-путь Git Bash (/c/...) -> Windows (C:\\...); прочее как есть."""
    if len(path) >= 3 and path[0] == "/" and path[2] == "/" and path[1].isalpha():
        return path[1] + ":\\" + path[3:].replace("/", "\\")
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
