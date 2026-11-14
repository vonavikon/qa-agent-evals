#!/usr/bin/env python3
"""A run's cost aggregator (review P1-8): tokens, duration, cost.

Reads result events from прогоны/*.events.jsonl (usage/duration_ms/
total_cost_usd are written by the CLI), aggregates per card and per run.
A multi-turn card driven by hand leaves one <id>-r<N>-h<K>.events.jsonl
per turn; every file is a CLI call and counts into its card (field run
2026-11-12: CV-01's six h-files had to be aggregated by hand).
A budget limit (USD) via --budget: exceeding it is flagged in the report
(the runner continues; a hard stop is not implemented - the decision stays
with the human, see the conclusion asymmetry).

Usage: cost-report.py <run-dir> [--budget 10]
Writes: <run-dir>/cost.md. Exit 0.
"""

import argparse
import glob
import io
import json
import os
import re


def run_stats(path):
    """One events.jsonl's stats: the last result event."""
    for line in reversed(list(io.open(path, encoding="utf-8", errors="replace"))):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            u = ev.get("usage") or {}
            return {
                "in": u.get("input_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "out": u.get("output_tokens", 0),
                "ms": ev.get("duration_ms") or 0,
                "usd": ev.get("total_cost_usd") or 0.0,
            }
    return None


def judge_stats(rd):
    """The sum of judge calls from вердикты/judge-usage.jsonl (judge-batch,
    v0.4.1). No file (a pre-instrumentation run) - the judge's economics
    are unmeasured."""
    path = os.path.join(rd, "вердикты", "judge-usage.jsonl")
    if not os.path.exists(path):
        return None
    tot = {"in": 0, "out": 0, "cache_read": 0, "usd": 0.0, "dur_s": 0.0, "n": 0}
    for line in io.open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        tot["in"] += r.get("in", 0)
        tot["out"] += r.get("out", 0)
        tot["cache_read"] += r.get("cache_read", 0)
        tot["usd"] += r.get("cost_usd", 0) or 0
        tot["dur_s"] += r.get("dur_s", 0) or 0
        tot["n"] += 1
    return tot


def norm(path):
    """A Git Bash drive path (/c/...) -> a Windows drive path, like
    build-index.py: the drive check runs BEFORE "/"->os.sep (after the
    replace "/" no longer starts the path on Windows and the branch
    never fires, the report comes out empty)."""
    if len(path) >= 3 and path[0] == "/" and path[2] == "/" and path[1].isalpha():
        return path[1] + ":\\" + path[3:].replace("/", "\\")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--budget", type=float, default=0, help="лимит USD на прогон")
    a = ap.parse_args()
    rd = norm(a.run_dir).replace("/", os.sep)

    rows = []
    for evf in sorted(glob.glob(os.path.join(rd, "прогоны", "*.events.jsonl"))):
        # -r<N> repeats plus the -h<K> manual-turn files of multi-turn cards
        m = re.search(r"([A-Za-z0-9\-]+)-r(\d+)(?:-h(\d+))?\.events\.jsonl$",
                      os.path.basename(evf))
        if not m:
            continue
        s = run_stats(evf)
        if s:
            rows.append((m.group(1), m.group(2), s))

    per_card = {}
    tot = {"in": 0, "out": 0, "cache_read": 0, "ms": 0, "usd": 0.0, "n": 0}
    for cid, rep, s in rows:
        c = per_card.setdefault(cid, {"in": 0, "out": 0, "ms": 0, "usd": 0.0, "n": 0})
        for k in ("in", "out", "ms"):
            c[k] += s[k]
        c["usd"] += s["usd"]
        c["n"] += 1
        for k in ("in", "out", "cache_read", "ms"):
            tot[k] += s[k]
        tot["usd"] += s["usd"]
        tot["n"] += 1

    lines = ["# Стоимость прогона", "",
             f"Прогонов: {tot['n']}. Токены: input {tot['in']:,} "
             f"(cache read {tot['cache_read']:,}), output {tot['out']:,}. "
             f"Длительность: {tot['ms']/1000:.1f} с. "
             f"Стоимость: ${tot['usd']:.3f}.", ""]
    if a.budget and tot["usd"] > a.budget:
        lines.append(f"**БЮДЖЕТ ПРЕВЫШЕН**: ${tot['usd']:.3f} > ${a.budget:.3f}.")
    lines += ["| Карточка | Прогонов | In | Out | Сек | $ |", "|---|---|---|---|---|---|"]
    for cid in sorted(per_card):
        c = per_card[cid]
        lines.append(f"| {cid} | {c['n']} | {c['in']:,} | {c['out']:,} | "
                     f"{c['ms']/1000:.1f} | {c['usd']:.3f} |")
    j = judge_stats(rd)
    if j:
        lines += ["", "## Судья (вызовы CLI judge-batch)", "",
                  f"Вызовов: {j['n']} (включая автопересуды). Токены: input {j['in']:,} "
                  f"(cache read {j['cache_read']:,}), output {j['out']:,}. "
                  f"Суммарная длительность: {j['dur_s']:.0f} с. "
                  f"Стоимость: ${j['usd']:.4f}.",
                  "", f"**Прогон целиком: ${tot['usd'] + j['usd']:.3f}** "
                  f"(SUT ${tot['usd']:.3f} + судья ${j['usd']:.4f})."]
    else:
        lines += ["", "Судья: вызовы не инструментированы (прогон до v0.4.1); "
                      "экономика судьи - по оценке артефактов."]
    out = os.path.join(rd, "cost.md")
    io.open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"cost.md: {tot['n']} прогонов, ${tot['usd']:.3f}, "
          f"{tot['ms']/1000:.1f} с, in {tot['in']:,} / out {tot['out']:,} токенов"
          + (f"; судья: {j['n']} вызовов, ${j['usd']:.4f}" if j else ""))


if __name__ == "__main__":
    main()
