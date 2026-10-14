#!/usr/bin/env python3
"""Визуальный ревью скриншотов прогона (фаза E, только для человека).

Браузерный адаптер снимает состояния SUT рядом с транскриптами:
прогоны/<id>-r<N>.png (финал карточки) и <id>-r<N>-k<K>.png (по действиям,
когда карточка помечена visual: true). Субагент agents/visual-reviewer.md
смотрит снимки и пишет визуальный-ревью.json: находки с рамками (bbox в
процентах от размеров снимка) и комментариями. Этот скрипт - детерминированный
хвост: проверяет схему, собирает страницу визуальный-ревью.html (снимок +
рамки + комментарии) и по запросу отбирает образцы для публикации.

Границы модуля:
  - находки ревьюера - подсказки человеку на этапе обратной связи; вердикты
    они не меняют;
  - судье скриншоты и находки не передаются, в оракул и машинный слой не
    попадают;
  - пачкой снимки не публикуются: --publish переносит в docs/visual-samples/
    только названные владельцем карточки (политика - knowledge/adapters.md).

Usage:
  annotate-visuals.py <run-dir>                      # проверить + собрать страницу
  annotate-visuals.py <run-dir> --publish GA-01,CR-02  # образцы в docs/visual-samples/
Нет ни скриншотов, ни ревью - тихий выход 0 (шаг необязательный).
"""

import argparse
import io
import json
import os
import re
import shutil
import sys

SEVERITIES = ("defect", "risk", "note")
SHOT_RE = re.compile(r"^([\w-]+)-r\d+(?:-k\d+)?\.png$")
REVIEW_NAME = "визуальный-ревью.json"
PAGE_NAME = "визуальный-ревью.html"

CSS = """body{margin:0;background:#f4f6f9;color:#1f2d3a;
font:15px/1.55 system-ui,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:21px;margin:0 0 4px}
.sub{color:#5f7186;margin:0 0 18px}
.shot{background:#fff;border:1px solid #d9e1e8;border-radius:10px;
padding:14px 16px;margin:14px 0}
.fname{font-weight:700;margin-bottom:8px}
.fig{position:relative;display:inline-block;max-width:100%}
.fig img{max-width:100%;display:block;border:1px solid #d9e1e8;border-radius:8px}
.box{position:absolute;border:2px solid;border-radius:4px;pointer-events:none}
.box i{position:absolute;top:-11px;left:-2px;font-style:normal;font-size:12px;
line-height:1;color:#fff;border-radius:3px;padding:2px 5px}
.s-defect{border-color:#b3261e;background:rgba(179,38,30,.12)}
.s-defect i{background:#b3261e}
.s-risk{border-color:#b26a00;background:rgba(178,106,0,.12)}
.s-risk i{background:#b26a00}
.s-note{border-color:#1f6fb2;background:rgba(31,111,178,.12)}
.s-note i{background:#1f6fb2}
ul{margin:8px 0 0;padding-left:20px}
li{margin:3px 0}
.sev{font-weight:700;font-size:13px}
.t-defect{color:#b3261e}.t-risk{color:#b26a00}.t-note{color:#1f6fb2}
.empty{color:#5f7186}"""


def shot_card(fname):
    m = SHOT_RE.match(fname)
    return m.group(1) if m else None


def load_review(run_dir):
    path = os.path.join(run_dir, REVIEW_NAME)
    if not os.path.exists(path):
        return None
    try:
        return json.loads(io.open(path, encoding="utf-8").read())
    except ValueError as e:
        print(f"  ! {REVIEW_NAME} не разбирается: {e}", file=sys.stderr)
        return None


def validate_review(review, run_dir):
    """Ошибки схемы. Пустой список - валидно; пустой ревью (нет снимков) валиден."""
    errs = []
    if not isinstance(review, dict) or not isinstance(review.get("screenshots"), list):
        return [f"{REVIEW_NAME}: ожидается объект с массивом screenshots"]
    shots_dir = os.path.join(run_dir, "прогоны")
    files = [s.get("file") if isinstance(s, dict) else None
             for s in review["screenshots"]]
    for n, (s, fname) in enumerate(zip(review["screenshots"], files), 1):
        if not isinstance(s, dict) or not isinstance(fname, str) or not SHOT_RE.match(fname):
            errs.append(f"screenshots[{n}]: file «{fname}» не вида <id>-r<N>[-k<K>].png")
            continue
        if not os.path.exists(os.path.join(shots_dir, fname)):
            errs.append(f"screenshots[{n}]: файла нет - прогоны/{fname}")
        finds = s.get("findings", [])
        if not isinstance(finds, list):
            errs.append(f"screenshots[{n}] ({fname}): findings не массив")
            continue
        for k, f in enumerate(finds, 1):
            tag = f"screenshots[{n}] ({fname}) finding {k}: "
            bbox = f.get("bbox") if isinstance(f, dict) else None
            if (not isinstance(bbox, list) or len(bbox) != 4
                    or not all(isinstance(v, (int, float)) and 0 <= v <= 100 for v in bbox)
                    or bbox[2] <= 0 or bbox[3] <= 0):
                errs.append(tag + f"bbox {bbox!r} - нужны [x, y, w, h], "
                                 "числа 0..100, w и h больше нуля")
            sev = f.get("severity") if isinstance(f, dict) else None
            if sev not in SEVERITIES:
                errs.append(tag + f"severity «{sev}» - только {'/'.join(SEVERITIES)}")
            comment = f.get("comment") if isinstance(f, dict) else None
            if not isinstance(comment, str) or not comment.strip():
                errs.append(tag + "пустой комментарий")
    dupes = sorted({f for f in files if files.count(f) > 1})
    for d in dupes:
        errs.append(f"снимок {d} указан больше одного раза")
    return errs


def totals(review):
    c = {"defect": 0, "risk": 0, "note": 0}
    for s in review.get("screenshots", []):
        for f in s.get("findings", []):
            c[f.get("severity")] = c.get(f.get("severity"), 0) + 1
    return c


def render_html(run_dir, review):
    """Страница: снимок + рамки + комментарии. Работает и без feedback.html."""
    t = totals(review)
    head = (f"<h1>Визуальный ревью</h1>"
            f"<p class=\"sub\">{os.path.basename(os.path.normpath(run_dir))} - "
            f"находок: {sum(t.values())} (defect {t['defect']}, risk {t['risk']}, "
            f"note {t['note']}). Разметка ассистента для человека на этапе "
            "обратной связи; судья её не видит и вердикты не меняет.</p>")
    parts = [head]
    for s in review.get("screenshots", []):
        finds = s.get("findings", [])
        parts.append(f"<div class=\"shot\"><div class=\"fname\">{s['file']}</div>")
        parts.append("<div class=\"fig\"><img loading=\"lazy\" "
                     f"src=\"прогоны/{s['file']}\">")
        for k, f in enumerate(finds, 1):
            x, y, w, h = f["bbox"]
            parts.append(f"<div class=\"box s-{f['severity']}\" "
                         f"style=\"left:{x}%;top:{y}%;width:{w}%;height:{h}%\">"
                         f"<i>{k}</i></div>")
        parts.append("</div>")
        if finds:
            parts.append("<ul>")
            for k, f in enumerate(finds, 1):
                parts.append(f"<li><span class=\"sev t-{f['severity']}\">"
                             f"{k}. {f['severity']}</span> - {f['comment']}</li>")
            parts.append("</ul>")
        else:
            parts.append("<p class=\"empty\">Находок нет.</p>")
        parts.append("</div>")
    page = ("<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<title>Визуальный ревью</title><style>" + CSS + "</style></head>"
            "<body><div class=\"wrap\">" + "".join(parts) + "</div></body></html>")
    out = os.path.join(run_dir, PAGE_NAME)
    io.open(out, "w", encoding="utf-8").write(page)
    print(f"страница визуального ревью: {out}")
    return out


def publish(run_dir, ids, repo_root=None):
    """Образцы в docs/visual-samples/<прогон>/: снимок + находки разметки."""
    repo_root = repo_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_name = os.path.basename(os.path.normpath(run_dir))
    review = load_review(run_dir) or {}
    by_file = {s["file"]: s for s in review.get("screenshots", [])
               if isinstance(s, dict)}
    dst = os.path.join(repo_root, "docs", "visual-samples", run_name)
    os.makedirs(dst, exist_ok=True)
    made = []
    for cid in ids:
        shots = sorted(f for f in os.listdir(os.path.join(run_dir, "прогоны"))
                       if shot_card(f) == cid)
        if not shots:
            print(f"  ! {cid}: скриншотов в прогонах нет", file=sys.stderr)
            continue
        lines = [f"# {cid} (прогон {run_name})", "",
                 "Образец визуального ревью: снимок + разметка ассистента. "
                 "Разметка - подсказка человеку, не вердикт.", ""]
        for fname in shots:
            # copyfile, не copy2: метаданные снимка не нужны, а chmod-обёртки
            # из тестового окружения ломают copystat.
            shutil.copyfile(os.path.join(run_dir, "прогоны", fname),
                            os.path.join(dst, fname))
            lines += [f"## {fname}", f"![{fname}]({fname})", ""]
            s = by_file.get(fname)
            finds = (s or {}).get("findings", [])
            if finds:
                lines += ["| # | severity | comment |", "|---|---|---|"]
                for k, f in enumerate(finds, 1):
                    c = f["comment"].replace("|", "\\|")
                    lines.append(f"| {k} | {f['severity']} | {c} |")
            else:
                lines.append("Разметки нет.")
            lines.append("")
        io.open(os.path.join(dst, f"{cid}.md"), "w", encoding="utf-8").write(
            "\n".join(lines) + "\n")
        made.append(cid)
    if made:
        rdm = os.path.join(repo_root, "docs", "visual-samples", "README.md")
        row = f"- [{run_name}]({run_name}/): " + ", ".join(made) + "\n"
        if os.path.exists(rdm):
            old = io.open(rdm, encoding="utf-8").read()
            io.open(rdm, "w", encoding="utf-8").write(
                old if row in old else old.rstrip("\n") + "\n" + row)
        else:
            io.open(rdm, "w", encoding="utf-8").write(
                "# Образцы визуального ревью\n\n"
                "Отобранные владельцем снимки с разметкой "
                "(политика - knowledge/adapters.md).\n\n" + row)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--publish", default=None,
                    help="id карточек через запятую: образцы в docs/visual-samples/")
    a = ap.parse_args()
    run_dir = os.path.normpath(a.run_dir)

    if a.publish is not None:
        ids = [x.strip() for x in a.publish.split(",") if x.strip()]
        made = publish(run_dir, ids)
        print(f"образцы: {made or 'нет'} -> docs/visual-samples/")
        return 0 if made else 1

    shots_dir = os.path.join(run_dir, "прогоны")
    has_shots = os.path.isdir(shots_dir) and any(
        f.endswith(".png") for f in os.listdir(shots_dir))
    review = load_review(run_dir)
    if review is None:
        if has_shots:
            print("скриншоты есть, разметки нет - запусти визуального ревьюера "
                  "(agents/visual-reviewer.md) или собери страницу позже")
        return 0
    errs = validate_review(review, run_dir)
    if errs:
        for e in errs:
            print("  !", e, file=sys.stderr)
        print(f"{REVIEW_NAME}: ошибок {len(errs)} - исправь и перезапусти",
              file=sys.stderr)
        return 1
    t = totals(review)
    print(f"схема ок: снимков {len(review['screenshots'])}, находок "
          f"{sum(t.values())} (defect {t['defect']}, risk {t['risk']}, note {t['note']})")
    render_html(run_dir, review)
    return 0


if __name__ == "__main__":
    sys.exit(main())
