#!/usr/bin/env python3
"""Cost-агрегатор прогона (review P1-8): токены, длительность, стоимость.

Читает result-события из прогоны/*.events.jsonl (usage/duration_ms/total_cost_usd
пишет CLI), агрегирует по карточкам и прогону. Лимит бюджета (USD) - через
--budget: превышение помечается в отчёте (раннер продолжает; жёсткая остановка
не реализована - решение за человеком, см. асимметрию выводов).

Usage: cost-report.py <run-dir> [--budget 10]
Пишет: <run-dir>/cost.md. Выход 0.
"""

import argparse
import glob
import io
import json
import os
import re


def run_stats(path):
    """Статистика одного events.jsonl: последнее result-событие."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--budget", type=float, default=0, help="лимит USD на прогон")
    a = ap.parse_args()
    rd = a.run_dir.replace("/", os.sep)
    if len(rd) >= 3 and rd[0] == "/" and rd[2] == "/":
        rd = rd[1] + ":\\" + rd[3:].replace("/", "\\")

    rows = []
    for evf in sorted(glob.glob(os.path.join(rd, "прогоны", "*.events.jsonl"))):
        m = re.search(r"([A-Za-z0-9\-]+)-r(\d+)\.events\.jsonl$", os.path.basename(evf))
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
    out = os.path.join(rd, "cost.md")
    io.open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"cost.md: {tot['n']} прогонов, ${tot['usd']:.3f}, "
          f"{tot['ms']/1000:.1f} с, in {tot['in']:,} / out {tot['out']:,} токенов")


if __name__ == "__main__":
    main()
