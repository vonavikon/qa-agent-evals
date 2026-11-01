#!/usr/bin/env python3
"""A diff of two runs of one SUT (review P1-6, a VIEW - not a criterion).

Compares the index.jsonl of two runs by card id: outcome changes, new
negatives (regression candidates), closed negatives, split changes. The
project principle is unchanged: every acceptance run is self-contained;
the diff is a report on diverging behavior, not a "got better/worse"
verdict.

Usage: diff-runs.py <run-a> <run-b>
Writes: stdout (markdown).
"""

import io
import json
import os
import sys

NEG = {"FAIL", "ATTACK_PASSED"}


def load(rd):
    rows = {}
    for line in io.open(os.path.join(rd, "index.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        rows[r["id"]] = r
    return rows


def main():
    a, b = sys.argv[1], sys.argv[2]
    ra, rb = load(a), load(b)
    lines = [f"# Diff прогонов", "",
             f"A: `{a}` — {ra[next(iter(ra))].get('meta', {}).get('sut', '?')}" if ra else "",
             f"B: `{b}` — {rb[next(iter(rb))].get('meta', {}).get('sut', '?')}" if rb else "",
             "", "| Карточка | A | B | Изменение |", "|---|---|---|---|"]
    changed = same = 0
    for cid in sorted(set(ra) | set(rb)):
        x, y = ra.get(cid), rb.get(cid)
        if x is None:
            lines.append(f"| {cid} | — | {y['result']} | новая карточка в B |")
            changed += 1
            continue
        if y is None:
            lines.append(f"| {cid} | {x['result']} | — | нет в B |")
            changed += 1
            continue
        if x["result"] == y["result"]:
            same += 1
            continue
        note = []
        xn = x["result"] in NEG or "split" == x["result"]
        yn = y["result"] in NEG or "split" == y["result"]
        if not xn and yn:
            note.append("**кандидат регрессии** (негатив появился)")
        if xn and not yn:
            note.append("негатив закрылся (не доказано: см. асимметрию)")
        if x["result"] == "split" or y["result"] == "split":
            note.append("расхождение повторов - см. votes/det_judge")
        lines.append(f"| {cid} | {x['result']} ({x['votes']}) "
                     f"| {y['result']} ({y['votes']}) | {', '.join(note) or 'смена итога'} |")
        changed += 1
    lines += ["", f"Итогов совпало: {same}, изменилось/новых: {changed}.",
              "Diff - вид над index.jsonl для навигации; выводы о версиях SUT",
              "принимает человек (самодостаточный аудит, принцип 6)."]
    print("\n".join(l for l in lines if l != ""))


if __name__ == "__main__":
    main()
