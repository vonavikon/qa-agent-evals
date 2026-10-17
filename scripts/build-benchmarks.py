#!/usr/bin/env python3
"""Журнал приёмок: собирает docs/benchmarks.md из runs/*/.

Источник строки прогона - сайдкар runs/<дата>-<sut>/bench.yaml (то, что не выводится
машинно: имя SUT, тип, адаптер, среда, находки) плюс машинные артефакты того же прогона:
index.jsonl (число карточек, повторы, счёт результатов, модель судьи) и cost.md ($).

Страница генерируется целиком, руками её не правят: python scripts/build-benchmarks.py.
Приватные прогоны в журнал не попадают: он собирается только из каталога публичного
репо, и генератор отказывается записывать страницу, если защитный фильтр находит
приватные маркеры. Проверка фильтра позитив-контролем: --selftest.
"""

import argparse
import io
import json
import os
import re
import sys

# Защитный фильтр: генератор не выпускает страницу, если в собранном тексте
# есть приватные маркеры (корп-личность, личные пути, формы секретов).
GUARD_PATTERNS = [
    (r"kivanov", "корп-логин"),
    (r"naumen|nau\.im|itsm365", "корп-домены"),
    (r"\baon[- ]", "корп-аббревиатура"),
    (r"\bаон\b", "корп-аббревиатура"),
    (r"c:\\+users\\+[a-z]+|c:/+users/+[a-z]+", "личный путь"),
    (r"ghp_[A-Za-z0-9]{10}|github_pat_", "github-токен"),
    (r"sk-[A-Za-z0-9]{8}", "api-ключ"),
    (r"AKIA[0-9A-Z]{16}", "aws-ключ"),
    (r"Bearer\s+[A-Za-z0-9._-]{15}", "bearer-токен"),
    (r"t\.me/\+", "инвайт-ссылка"),
]


def guard(text):
    """Список (паттерн, объяснение) по срабатываниям; пустой = чисто."""
    hits = []
    for pat, why in GUARD_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            hits.append((m.group(0), why))
    return hits


def parse_bench(run_dir):
    """Сайдкар bench.yaml: плоские строки «ключ: значение»."""
    out = {}
    path = os.path.join(run_dir, "bench.yaml")
    if not os.path.exists(path):
        return out
    for line in io.open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key.strip()] = val.strip()
    return out


def parse_index(run_dir):
    """Машинный слой: карточки, повторы, счёт результатов, модель судьи."""
    path = os.path.join(run_dir, "index.jsonl")
    if not os.path.exists(path):
        return None
    cards, tally, judge, repeats = 0, {}, "", 0
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        cards += 1
        tally[row.get("result", "?")] = tally.get(row.get("result", "?"), 0) + 1
        reps = row.get("repeats") or []
        repeats = max(repeats, len(reps))
        judge = judge or (row.get("meta") or {}).get("judge_model", "")
    return {"cards": cards, "repeats": repeats, "tally": tally, "judge": judge}


def parse_cost(run_dir):
    """Итог прогона из cost.md: сначала «Прогон целиком», иначе SUT-строка."""
    path = os.path.join(run_dir, "cost.md")
    if not os.path.exists(path):
        return ""
    txt = io.open(path, encoding="utf-8").read()
    m = (re.search(r"Прогон целиком:\s*\$(\d+(?:\.\d+)?)", txt)
         or re.search(r"Стоимость:\s*\$(\d+(?:\.\d+)?)", txt))
    return "$" + m.group(1) if m else ""


def default_report(run_dir):
    if os.path.exists(os.path.join(run_dir, "report.md")):
        return "report.md"
    for name in sorted(os.listdir(run_dir)):
        if name.startswith("report") and name.endswith((".md",)):
            return name
    return ""


def fmt_tally(tally):
    order = ["GOT", "FAIL", "ATTACK_PASSED", "PARTIAL", "split", "HONEST",
             "BLOCKED", "ERROR", "NOT_TESTED"]
    keys = [k for k in order if k in tally] + \
           [k for k in tally if k not in order]
    return ", ".join(f"{k} {tally[k]}" for k in keys) if keys else ""


HEADER = """# Журнал приёмок

Каждая строка - один прогон конвейера: приёмка сторонней или собственной системы,
самоприёмка самого плагина, контрольная выборка судьи или security-прогон изоляции.
Это журнал находок, а не рейтинг: вердикт GOT означает «не опровергнуто», дефект
доказывается только негативным вердиктом (FAIL, ATTACK_PASSED). Формулировка
«система прошла приёмку» здесь не используется - асимметрия вердиктов в [oracle](../knowledge/oracle.md).

Страница собирается скриптом `scripts/build-benchmarks.py` из каталога `runs/`
(сайдкар bench.yaml + index.jsonl + cost.md каждого прогона) и руками не правится.
Приватные прогоны в журнал не попадают: он собирается из публичного каталога репо,
а генератор отказывается записывать страницу при срабатывании защитного фильтра
(проверка фильтра позитив-контролем: `python scripts/build-benchmarks.py --selftest`).

| Дата | SUT | Тип | Адаптер | Среда | Карточки | Итог | Судья | $ | Находки | Отчёт |
|---|---|---|---|---|---|---|---|---|---|---|
"""


def build_row(name, run_dir):
    b = parse_bench(run_dir)
    idx = parse_index(run_dir)
    date = name[:10] if re.match(r"\d{4}-\d{2}-\d{2}", name) else name
    cards = (f"{idx['cards']} × {idx['repeats']}" if idx
             and idx["cards"] else b.get("cards", "-"))
    score = fmt_tally(idx["tally"]) if idx and idx["tally"] else b.get("score", "-")
    judge = b.get("judge") or (idx["judge"] if idx else "") or "-"
    cost = b.get("cost") or parse_cost(run_dir) or "-"
    report = b.get("report") or default_report(run_dir)
    link = f"[report](../runs/{name}/{report})" if report else "-"
    cells = [
        date, b.get("sut", name), b.get("type", "-"), b.get("adapter", "-"),
        b.get("env", "-"), cards, score, judge, cost,
        b.get("findings", "-"), link,
    ]
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def build(runs_root):
    names = sorted((n for n in os.listdir(runs_root)
                    if os.path.isdir(os.path.join(runs_root, n))), reverse=True)
    lines = [HEADER.rstrip("\n")]
    missing = []
    for n in names:
        run_dir = os.path.join(runs_root, n)
        if not os.path.exists(os.path.join(run_dir, "bench.yaml")):
            missing.append(n)
            continue
        lines.append(build_row(n, run_dir))
    if missing:
        lines.append(f"\n*Без сайдкара bench.yaml в журнал не попали: "
                     f"{', '.join(missing)}*")
    return "\n".join(lines) + "\n"


def selftest():
    """Позитив-контроль фильтра: канарейка обязана ловиться, чистый текст - нет."""
    dirty = "kivanov@naumen.example и C:\\Users\\sample, плюс ghp_abcdefghij и Bearer abcdef1234567890"
    hits = guard(dirty)
    if len(hits) < 4:
        print(f"selftest FAIL: канарейка поймала только {len(hits)} срабатываний", file=sys.stderr)
        return False
    if guard("чистый текст журнала, ste100 и stop-slop, $1.38, docker"):
        print("selftest FAIL: ложное срабатывание на чистом тексте", file=sys.stderr)
        return False
    print(f"selftest OK: фильтр поймал {len(hits)} канарейки, на чистом тексте тишина")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default=os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), "runs"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), "docs", "benchmarks.md"))
    ap.add_argument("--selftest", action="store_true",
                    help="проверить защитный фильтр позитив-контролем и выйти")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    page = build(args.runs)
    hits = guard(page)
    if hits:
        print("ОТКАЗ: в журнале приватные маркеры, страница не записана:", file=sys.stderr)
        for fragment, why in hits:
            print(f"  ! [{why}] {fragment}", file=sys.stderr)
        sys.exit(1)

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    print(f"журнал собран: {args.out} ({len(page.splitlines())} строк)")


if __name__ == "__main__":
    main()
