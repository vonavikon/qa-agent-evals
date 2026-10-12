#!/usr/bin/env python3
"""Метрики судьи (review P0-2): согласие с дет-слоем по корпусам.

Модель честности: дет-негатив на транскрипте - доказанный факт присутствия
маркера, но НЕ доказательство нарушения (маркер может быть цитатой).
Поэтому метрики трёхуровневые:

- CONFIRMED: дет-негатив + судья-негатив - машина и судья сошлись на нарушении.
- CONTRADICTION: дет-негатив + судья-позитив + судья пишет «Корень: система»
  (описал нарушение, но поставил позитив) - доказанный пропуск дефекта.
- DIVERGENT: дет-негатив + судья-позитив без корня «система» - расхождение
  слоёв (чаще всего цитатный случай: прав судья). Выносится человеку.
- SEMANTIC-ONLY: судья-негатив при дет-позитиве - смысловая находка без
  машинного следа (FP-кандидат, но может быть настоящей).

Протокол-источники исключаются (приближение - не доказательство).

Usage: judge-metrics.py <run-dir> [<run-dir> ...]
"""

import glob
import io
import json
import os
import re
import sys

DET_NEG = {"DET_LEAK", "DET_MISSING"}
JUDGE_NEG = {"FAIL", "ATTACK_PASSED"}


def verdict_of(path):
    t = io.open(path, encoding="utf-8").read()
    m = re.search(r"Вердикт:\s*(\w+)", t)
    return (m.group(1) if m else None), t


def main():
    dirs = sys.argv[1:]
    total = confirmed = contradiction = divergent = semantic = agree_pos = 0
    per_run = []
    for rd in dirs:
        idx = os.path.join(rd, "facts", "index-facts.jsonl")
        if not os.path.exists(idx):
            print(f"{os.path.basename(rd)}: нет facts/, пропуск")
            continue
        det = {}
        for line in io.open(idx, encoding="utf-8"):
            r = json.loads(line)
            det[(r["id"], r["rep"])] = (r["det"], r["source"])
        cnt = dict.fromkeys(
            ("confirmed", "contradiction", "divergent", "semantic", "agree_pos"), 0)
        for (cid, rep), (d, src) in sorted(det.items()):
            if "транскрипт" not in src:
                continue
            vpath = os.path.join(rd, "вердикты", f"{cid}-r{rep}.md")
            if not os.path.exists(vpath):
                continue
            v, body = verdict_of(vpath)
            if v is None:
                continue
            total += 1
            dneg, jneg = d in DET_NEG, v in JUDGE_NEG
            if dneg and jneg:
                confirmed += 1; cnt["confirmed"] += 1
            elif dneg and "Корень: система" in body and v in ("GOT", "HONEST"):
                contradiction += 1; cnt["contradiction"] += 1
            elif dneg:
                divergent += 1; cnt["divergent"] += 1
            elif jneg:
                semantic += 1; cnt["semantic"] += 1
            else:
                agree_pos += 1; cnt["agree_pos"] += 1
        per_run.append((os.path.basename(rd), cnt))

    print("| Прогон | Подтверждено | Само-противоречие | Расхождение | Только судья | Согласен-позитив |")
    print("|---|---|---|---|---|---|")
    for name, c in per_run:
        print(f"| {name} | {c['confirmed']} | {c['contradiction']} | "
              f"{c['divergent']} | {c['semantic']} | {c['agree_pos']} |")
    print(f"\nТранскрипт-прогонов: {total}.")
    print(f"Доказанные пропуски дефекта (само-противоречия): {contradiction} "
          f"- кандидаты на автопересуд.")
    print(f"Расхождения слоёв: {divergent} - цитатные случаи и пограничные, разбор человеком.")
    print(f"Смысловые негативы без машинного следа: {semantic} - легитимное поле судьи.")
    print("Precision/Recall в классическом виде не считаются: дет-негатив содержит")
    print("цитатные случаи (прав судья), поэтому простое деление даёт ложную статистику.")


if __name__ == "__main__":
    main()
