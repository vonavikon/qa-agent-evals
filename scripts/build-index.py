#!/usr/bin/env python3
"""Машиночитаемый индекс прогона (runs/<дата>-<sut>/index.jsonl).

По образцу .eval-лога Inspect AI: одна строка JSON на прогон - вердикты,
редьюсер-итог, пути артефактов. Открывает re-scoring (пересуд по протоколам
без новых прогонов), программные сводки и сравнение приёмок.

Usage: build-index.py <run-dir> [--reducer majority|unanimous|at_least_k]
  majority  - итог за большинством повторов, расхождение = "split"
  unanimous - итог только при единодушии, иначе "split" (дефолт N=2)
Читает: карточки/*.yaml, вердикты/*.md (строка «- Вердикт: X»), прогоны/ (наличие).
Пишет: index.jsonl. Выход 0.
"""

import glob
import io
import json
import os
import re
import sys

NEG = {"FAIL", "ATTACK_PASSED"}


def norm(path):
    if len(path) >= 3 and path[0] == "/" and path[2] == "/" and path[1].isalpha():
        return path[1] + ":\\" + path[3:].replace("/", "\\")
    return path


def card_meta(path):
    t = io.open(path, encoding="utf-8").read()
    def f(key):
        m = re.search(rf"^{key}:\s*(.+)$", t, re.M)
        return m.group(1).strip() if m else ""
    return f("id"), f("type"), f("feature")


def verdict_of(path):
    t = io.open(path, encoding="utf-8").read()
    m = re.search(r"Вердикт:\s*(\w+)", t)
    inv = "INVALID" in t and re.search(r"Супервизия:\s*INVALID", t)
    return (m.group(1) if m else "UNKNOWN"), bool(inv)


def reduce_verdicts(vs, reducer):
    uniq = set(vs)
    if len(uniq) == 1:
        return vs[0]
    if reducer == "majority" and len(uniq) == 2:
        for v in uniq:
            if vs.count(v) * 2 > len(vs):
                return v
    return "split"


def main():
    args = [a for a in sys.argv[2:]]
    reducer = "majority" if "--reducer" not in args else \
        args[args.index("--reducer") + 1]
    run_dir = norm(sys.argv[1])
    rows = []
    for card in sorted(glob.glob(os.path.join(run_dir, "карточки", "*.yaml"))):
        cid, ctype, feature = card_meta(card)
        reps = {}
        for vpath in sorted(glob.glob(os.path.join(run_dir, "вердикты", f"{cid}-r*.md"))):
            m = re.search(r"-r(r?\d+)\.md$", vpath.replace("\\", "/"))
            rep = m.group(1) if m else "?"
            v, inv = verdict_of(vpath)
            reps[rep] = ("INVALID" if inv else v)
        verdicts = [reps[k] for k in sorted(reps)]
        row = {
            "id": cid, "type": ctype, "feature": feature,
            "repeats": sorted(reps), "verdicts": reps,
            "reducer": reducer,
            "result": reduce_verdicts(verdicts, reducer) if verdicts else "NO_VERDICT",
            "any_negative": any(v in NEG or v == "split" for v in verdicts),
        }
        arts = {}
        for rep, suffix in [(k, f"-r{k}") for k in sorted(reps)]:
            for ext, key in [(".txt", "transcript"), (".prov.txt", "provenance"),
                             (".diag.txt", "diag"), (".events.jsonl", "events")]:
                p = os.path.join(run_dir, "прогоны", cid + suffix + ext)
                if os.path.exists(p):
                    arts.setdefault(rep, {})[key] = os.path.relpath(p, run_dir)
        row["artifacts"] = arts
        rows.append(json.dumps(row, ensure_ascii=False))
    out = os.path.join(run_dir, "index.jsonl")
    io.open(out, "w", encoding="utf-8").write("\n".join(rows) + "\n")
    neg = sum(1 for r in rows if json.loads(r)["any_negative"])
    print(f"index.jsonl: {len(rows)} карточек, редьюсер {reducer}, карточек с негативом/расхождением: {neg}")


if __name__ == "__main__":
    main()
