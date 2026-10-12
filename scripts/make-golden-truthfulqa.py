#!/usr/bin/env python3
"""Конвертер TruthfulQA -> драфт golden-кейсов для judge-control.py.

TruthfulQA (Lin, Hilton, Evans 2021, Apache 2.0, github.com/sylinrl/TruthfulQA):
817 вопросов, у каждого - эталонный правдивый ответ (Best Answer) и эталонный
ложный ответ-заблуждение (Best Incorrect Answer). Метки проставлены авторами
бенчмарка вручную, это экспертные метки, а не вердикты судьи плагина -
требование ревью P0-2 соблюдено.

Одна строка датасета даёт три кейса (одинаковый вопрос и оракул, разный ответ):
  GOT    - ответ = Best Answer (полное попадание)
  FAIL   - ответ = Best Incorrect Answer (заблуждение, противоречит оракулу)
  HONEST - ответ = "I have no comment." (по методике бенчмарка это правдивое
           незнание; в нашей шкале - честное незнание)

ID идут с G-101, чтобы не пересекаться с ручным набором G-01..G-08.
Скрипт детерминирован (фиксированный seed) - повторный запуск даёт тот же файл.

Usage:
  make-golden-truthfulqa.py <TruthfulQA.csv> <out.md> [--per-class 15] [--seed 42] [--start-id 101]
"""

import argparse
import csv
import io
import random

HEADER = """# Golden-набор из TruthfulQA (драфт, домен: правдивость)

Источник: TruthfulQA (Lin, Hilton, Evans 2021), 817 вопросов с экспертными
метками авторов: правдивый ответ и типовое заблуждение на каждый вопрос.
Канонический файл: github.com/sylinrl/TruthfulQA (Apache 2.0), скачан
2026-10-11 без аккаунта - Kaggle-канал (kagglehub, MCP, прямой endpoint)
отдаёт данные только после авторизации, см. docs/research-2026-10-11-kaggle-golden.md.

Правило маппинга (детерминированное, без суждения судьи плагина):
Best Answer -> GOT, Best Incorrect Answer -> FAIL, "I have no comment." -> HONEST.
Оракул кейса содержит правдивый ответ и явно допускает честное незнание -
судья обязан различить попадание, ложный ответ и честное незнание.

Назначение: расширение контрольной выборки судьи (ревью P0-2, цель 50-100
кейсов). Домен открытый (здоровье, право, финансы, политика) - проверяет
судью вне привычного домена приёмок. Перед включением в отчёты приёмок
владелец просматривает драфт.
"""


def one_line(s):
    return " ".join(s.split())


def load_rows(csv_path):
    rows = []
    with io.open(csv_path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            best = one_line(r.get("Best Answer", ""))
            wrong = one_line(r.get("Best Incorrect Answer", ""))
            q = one_line(r.get("Question", ""))
            if not (q and best and wrong):
                continue
            if "no comment" in best.lower():
                continue  # эталон сам - незнание, кейс GOT вырождается
            rows.append({"q": q, "best": best, "wrong": wrong})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("out_path")
    ap.add_argument("--per-class", type=int, default=15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start-id", type=int, default=101)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    rows = load_rows(a.csv_path)
    picked = rng.sample(rows, a.per_class)

    def expectation(r):
        return (f'Правдивый ответ: "{r["best"]}". '
                'Честное незнание ("I have no comment.") допустимо и ошибкой не является.')

    out = [HEADER]
    cid = a.start_id
    counts = {}
    for cls, answer_fn in (("GOT", lambda r: r["best"]),
                           ("FAIL", lambda r: r["wrong"]),
                           ("HONEST", lambda r: "I have no comment.")):
        out.append(f"\n## Кейсы {cls}\n")
        for r in picked:
            out.append(f"## G-{cid} (эталон: {cls})\n")
            out.append(f"Вопрос: {r['q']}")
            out.append(f"Ожидание: {expectation(r)}")
            out.append(f"Ответ SUT: {answer_fn(r)}\n")
            counts[cls] = counts.get(cls, 0) + 1
            cid += 1

    out.append("---\n")
    out.append(f"Баланс: {', '.join(f'{v} {k}' for k, v in sorted(counts.items()))}. "
               f"Всего {sum(counts.values())} кейсов, seed {a.seed}, "
               f"по {a.per_class} вопросам датасета на класс.\n")
    io.open(a.out_path, "w", encoding="utf-8").write("\n".join(out))
    print(f"написано {sum(counts.values())} кейсов -> {a.out_path}")


if __name__ == "__main__":
    main()
