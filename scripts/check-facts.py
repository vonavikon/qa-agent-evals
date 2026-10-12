#!/usr/bin/env python3
"""Детерминированный слой проверки фактов (deterministic-scorer).

Грепает маркеры facts_must / facts_must_not из карточек по транскриптам
прогонов ДО судьи. Судья получает артефакты facts/ как исполнимые
свидетельства: что доказано grep'ом, то не пересуживается.

Источник текста повтора: прогоны/<id>-r<N>*.txt (без .replica/.err; включает
многоходовые -hK файлы одного повтора) плюс артефакты, написанные SUT
(прогоны/<id>-r<N>.artifacts/). Если транскрипта нет - протокол исполнителя
(приближение: маркер может совпасть с текстом протокола, не с ответом SUT;
помечается source=протокол).

Usage: check-facts.py <run-dir>
Пишет: facts/<id>-r<N>.facts.md + facts/index-facts.jsonl. Выход 0.
Вердикты слоя: DET_OK / DET_MISSING / DET_LEAK / DET_NA / DET_NO_DATA.
"""

import glob
import io
import json
import os
import re
import sys


def norm(path):
    if len(path) >= 3 and path[0] == "/" and path[2] == "/" and path[1].isalpha():
        return path[1] + ":\\" + path[3:].replace("/", "\\")
    return path


def parse_facts(path):
    """Мини-парсер секций facts_must / facts_must_not карточки."""
    must, must_not = [], []
    target = None
    for line in io.open(path, encoding="utf-8").read().splitlines():
        m = re.match(r"^\s{2}(facts_must|facts_must_not):\s*$", line)
        if m:
            target = m.group(1)
            continue
        if re.match(r"^\S", line):  # новый ключ верхнего уровня - конец секции
            target = None
            continue
        item = re.match(r'^\s*-\s*"?([^"#]+)"?\s*$', line)
        if item and target:
            (must if target == "facts_must" else must_not).append(item.group(1).strip())
    return must, must_not


def transcript_text(run_dir, cid, rep):
    """Текст повтора: транскрипты (то, что отвечала SUT), иначе протокол."""
    files = [f for f in glob.glob(os.path.join(run_dir, "прогоны", f"{cid}-r{rep}*.txt"))
             if not f.endswith((".replica.txt", ".prov.txt", ".diag.txt"))]
    if files:
        return "\n".join(io.open(f, encoding="utf-8", errors="replace").read()
                         for f in sorted(files)), "транскрипт", sorted(files)
    proto = os.path.join(run_dir, "протоколы", f"{cid}-r{rep}.md")
    if os.path.exists(proto):
        return io.open(proto, encoding="utf-8", errors="replace").read(), \
               "протокол (приближение)", [proto]
    return "", "нет артефакта", []


def artifact_text(run_dir, cid, rep):
    """Тексты артефактов, написанных SUT в рабочей папке прогона
    (прогоны/<id>-r<N>.artifacts/, собирает run-cards.sh). Артефакт вне
    транскрипта - такое же доказательство, как и ответ в чате."""
    base = os.path.join(run_dir, "прогоны", f"{cid}-r{rep}.artifacts")
    out, files = [], []
    if not os.path.isdir(base):
        return out, files
    for root, dirs, fs in os.walk(base):
        for name in sorted(fs):
            p = os.path.join(root, name)
            try:
                data = io.open(p, "rb").read(200 * 1024)
            except OSError:
                continue
            out.append(data.decode("utf-8", errors="replace"))
            files.append(p)
    return out, files


def check_run(run_dir, cid, must, must_not):
    reps = []
    for pat, rx in [("вердикты", r"-r(\d+)\.md$"), ("прогоны", r"-r(\d+)(?:-h\d+)?\.txt$")]:
        for p in glob.glob(os.path.join(run_dir, pat, f"{cid}-r*")):
            if pat == "прогоны" and (p.endswith(".replica.txt") or p.endswith(".err")
                                     or p.endswith(".prov.txt") or p.endswith(".diag.txt")
                                     or p.endswith(".events.jsonl")):
                continue
            m = re.search(rx, os.path.basename(p))
            if m:
                reps.append(m.group(1))
    reps = sorted(set(reps))
    out = []
    for rep in reps:
        text, source, files = transcript_text(run_dir, cid, rep)
        atexts, afiles = artifact_text(run_dir, cid, rep)
        if atexts:
            text = (text + "\n" + "\n".join(atexts)) if text else "\n".join(atexts)
            source = f"{source} + артефакт" if source != "нет артефакта" else "артефакт"
            files = files + afiles
        low = text.lower()
        if not text:
            verdict = "DET_NO_DATA"
        elif any(m.lower() in low for m in must_not):
            verdict = "DET_LEAK"
        elif not must and not must_not:
            verdict = "DET_NA"
        elif all(m.lower() in low for m in must):
            verdict = "DET_OK"
        else:
            verdict = "DET_MISSING"
        row = {
            "id": cid, "rep": rep, "source": source, "det": verdict,
            "missing": [m for m in must if m.lower() not in low],
            "leaked": [m for m in must_not if m.lower() in low],
            "files": [os.path.relpath(f, run_dir) for f in files],
        }
        out.append(row)
        lines = [f"# Детерминированная проверка фактов: {cid}-r{rep}",
                 f"Источник: {source}. Вердикт слоя: **{verdict}**.", ""]
        if must:
            lines.append("## facts_must")
            lines += [f"- {'НАЙДЕНО' if m.lower() in low else 'НЕ НАЙДЕНО'}: {m}"
                      for m in must]
        if must_not:
            lines += ["", "## facts_must_not"]
            lines += [f"- {'НАЙДЕНО (нарушение!)' if m.lower() in low else 'не найдено'}: {m}"
                      for m in must_not]
        d = os.path.join(run_dir, "facts")
        if not os.path.isdir(d):
            os.makedirs(d)
        io.open(os.path.join(d, f"{cid}-r{rep}.facts.md"), "w",
                encoding="utf-8").write("\n".join(lines) + "\n")
    return out


def main():
    run_dir = norm(sys.argv[1])
    rows = []
    for card in sorted(glob.glob(os.path.join(run_dir, "карточки", "*.yaml"))):
        cid = os.path.splitext(os.path.basename(card))[0]
        must, must_not = parse_facts(card)
        rows += check_run(run_dir, cid, must, must_not)
    d = os.path.join(run_dir, "facts")
    if not os.path.isdir(d):
        os.makedirs(d)
    io.open(os.path.join(d, "index-facts.jsonl"), "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    tally = {}
    for r in rows:
        tally[r["det"]] = tally.get(r["det"], 0) + 1
    # Срабатываемость маркеров (AIDE²: мёртвый код оракула виден машиной)
    by_card = {}
    for r in rows:
        by_card.setdefault(r["id"], []).append(r)
    cov = []
    for card in sorted(glob.glob(os.path.join(run_dir, "карточки", "*.yaml"))):
        cid = os.path.splitext(os.path.basename(card))[0]
        must, must_not = parse_facts(card)
        reps = by_card.get(cid, [])
        for m in must:
            fired = sum(1 for r in reps if m not in r["missing"])
            cov.append((cid, "must", m, fired, len(reps)))
        for m in must_not:
            fired = sum(1 for r in reps if m in r["leaked"])
            cov.append((cid, "must_not", m, fired, len(reps)))
    lines = ["# Срабатываемость оракула (корпус)", "",
             "| Карточка | Список | Маркер | Сработал | Повторов |", "|---|---|---|---|---|"]
    dead = 0
    for cid, kind, m, fired, total in cov:
        lines.append(f"| {cid} | {kind} | {m} | {fired} | {total} |")
        if kind == "must" and total and fired == 0:
            dead += 1
    io.open(os.path.join(run_dir, "facts", "oracle-coverage.md"), "w",
            encoding="utf-8").write(chr(10).join(lines) + chr(10))
    print(f"facts: {len(rows)} прогонов, " +
          ", ".join(f"{k}={v}" for k, v in sorted(tally.items())) +
          f"; маркеров: {len(cov)}, несработавших must: {dead}")


if __name__ == "__main__":
    main()
