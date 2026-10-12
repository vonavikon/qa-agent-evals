#!/usr/bin/env python3
"""Обратная связь человека по итогам прогона (необязательный шаг фазы E).

Человек подтверждает или исправляет вердикты файлом runs/<дата>-<sut>/feedback.yaml
(строка на карточку: «id: ок» - согласен с итогом судьи, «id: FAIL» - вердикт
человека). Скрипт:

  1. считает согласие судьи с человеком по живым кейсам (главная рабочая метрика
     судьи: боевые кейсы, в отличие от контрольной выборки);
  2. готовит golden-кандидаты: на каждый кейс с ответом человека - готовый кейс
     контрольной выборки, эталон = вердикт ЧЕЛОВЕКА (вердикт судьи эталоном не
     становится никогда - принцип Growing-Golden).

Кандидаты (runs/<run>/golden-candidates.md) владелец просматривает и переносит
в knowledge/golden-live.md - так контрольная выборка растёт из живых приёмок.

Usage:
  collect-feedback.py <run-dir> [--feedback <path>] [--start-id N] [--html]
Файла обратной связи нет - тихий выход 0 (шаг необязателен).
--html - собрать страницу разметки feedback.html (клики вместо yaml руками):
отметил вердикты -> «Скачать feedback.yaml» -> файл в папку прогона.
"""

import argparse
import glob
import io
import json
import os
import re
import sys

VERDICTS = {"GOT", "HONEST", "PARTIAL", "FAIL", "ATTACK_PASSED"}
OK_WORDS = {"ок", "ok"}
MAX_ANSWER = 1200


def one_line(s):
    return " ".join(s.split())


def parse_feedback(path):
    """Строки «id: ок» или «id: ВЕРДИКТ». Возвращает {id: (value, is_ok)}."""
    if not os.path.exists(path):
        return None
    fb, bad = {}, []
    for n, raw in enumerate(io.open(path, encoding="utf-8"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([\w-]+):\s*(\S+)", line)
        if not m:
            bad.append(f"строка {n}: «{line}» не разобрана"); continue
        cid, val = m.group(1), m.group(2)
        v = val.strip(",;.").lower()
        if v in OK_WORDS:
            fb[cid] = (None, True)
        elif val.upper() in VERDICTS:
            fb[cid] = (val.upper(), False)
        else:
            bad.append(f"строка {n}: «{val}» - не вердикт и не «ок»")
    for b in bad:
        print("  !", b, file=sys.stderr)
    return fb


def yaml_fields(card_path):
    """Поля карточки: instruction (реплика) и oracle.expected (мини-парсер regex'ом)."""
    txt = io.open(card_path, encoding="utf-8").read()
    out = {"instruction": "", "expected": ""}
    m = re.search(r"^instruction:\s*\|\n((?:[ \t]+.*\n?)*)", txt, flags=re.M)
    if not m:
        m = re.search(r"^instruction:\s*(.+)$", txt, flags=re.M)
    if m:
        out["instruction"] = m.group(1)
    m = re.search(r"^oracle:\n(?:[ \t]+.*\n?)*?^\s+expected:\s*\|\n((?:[ ]{4,}.*\n?)*)",
                  txt, flags=re.M)
    if not m:
        m = re.search(r"^\s+expected:\s*(.+)$", txt, flags=re.M)
    if m:
        out["expected"] = m.group(1)
    return out


def dedup_transcript(s):
    """Транскрипт собирает текст из промежуточных блоков и result - итоговое
    сообщение может повториться дословно. Отсекаем повтор по второму вхождению
    начального фрагмента (до 100 символов, но не более трети текста)."""
    probe = s[:min(100, max(20, len(s) // 3))]
    second = s.find(probe, 1)
    return s[:second].rstrip() if second > 0 else s


def choose_rep(index_row, human_verdict):
    """Повтор для golden-кандидата: где судья ошибся (самый поучительный),
    иначе r1."""
    verdicts = index_row.get("verdicts", {})
    if human_verdict:
        for rep in sorted(verdicts):
            if verdicts[rep] != human_verdict:
                return rep
    return sorted(verdicts)[0] if verdicts else None


def next_id(repo_root):
    """Свободный G-ID: максимум из golden-live.md и всех файлов кандидатов + 1.
    Живые кейсы нумеруются с G-201 (TruthfulQA занял 101-145, ручные - 1-8)."""
    mx = 200
    for path in ([os.path.join(repo_root, "knowledge", "golden-live.md")] +
                 glob.glob(os.path.join(repo_root, "runs", "*", "golden-candidates.md"))):
        if not os.path.exists(path):
            continue
        for m in re.finditer(r"^## G-(\d+)", io.open(path, encoding="utf-8").read(), re.M):
            mx = max(mx, int(m.group(1)))
    return mx + 1


def load_entries(run_dir):
    """Данные прогона для страницы разметки: карточка + итог судьи + ответ."""
    entries = []
    index_path = os.path.join(run_dir, "index.jsonl")
    for line in io.open(index_path, encoding="utf-8"):
        r = json.loads(line)
        cid = r["id"]
        f = yaml_fields(os.path.join(run_dir, "карточки", f"{cid}.yaml"))
        answer = ""
        reps = r.get("verdicts", {})
        rep = sorted(reps)[0] if reps else "1"
        tpath = os.path.join(run_dir, "прогоны", f"{cid}-r{rep}.txt")
        if os.path.exists(tpath):
            answer = dedup_transcript(one_line(io.open(tpath, encoding="utf-8").read()))
        det = r.get("det", {})
        det_s = r.get("det_source", {})
        det_str = "; ".join(f"r{k}: {det[k]} ({det_s.get(k, '')})"
                            for k in sorted(det) if det.get(k) and det[k] != "DET_OK")
        entries.append({
            "id": cid, "type": r.get("type", ""), "feature": r.get("feature", ""),
            "question": one_line(f["instruction"]),
            "expected": one_line(f["expected"]),
            "answer": answer,
            "verdicts": "; ".join(f"r{k}: {v}" for k, v in sorted(reps.items())),
            "result": r.get("result", ""),
            "det": det_str,
        })
    return entries


HTML = u"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Обратная связь — {{RUN}}</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--line:#d9e1e8;--ink:#1f2d3a;--mut:#5f7186;--ok:#2e7d32;--sel:#1f2d3a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:21px;margin:0 0 4px}
.sub{color:var(--mut);margin:0 0 18px}
.bar{position:sticky;top:0;background:var(--bg);padding:10px 0 12px;border-bottom:1px solid var(--line);z-index:2;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.bar .grow{flex:1}
button{font:inherit;border:1px solid var(--line);background:var(--card);border-radius:8px;padding:7px 14px;cursor:pointer}
button:hover{border-color:var(--mut)}
button.primary{background:var(--sel);color:#fff;border-color:var(--sel)}
#prog{font-size:14px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
.head{display:flex;gap:8px;flex-wrap:wrap;align-items:baseline}
.idb{font-weight:700;font-size:16px}
.meta{color:var(--mut);font-size:13px}
.res{margin-left:auto;font-weight:600;font-size:14px}
.neg{color:#b3261e}
.det{color:var(--mut);font-size:13px;margin:2px 0 0}
details{margin:8px 0}
summary{cursor:pointer;color:var(--mut);font-size:14px;user-select:none}
details div{white-space:pre-wrap;background:#f4f6f9;border-radius:8px;padding:10px 12px;margin-top:6px;font-size:14px;max-height:280px;overflow:auto}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.chip{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:5px 13px;font-size:14px;cursor:pointer}
.chip.ok{color:var(--ok);border-color:var(--ok)}
.chip.on{background:var(--sel);color:#fff;border-color:var(--sel)}
.chip.ok.on{background:var(--ok);border-color:var(--ok)}
.sep{width:1px;height:22px;background:var(--line);margin:2px 4px}
input[type=text]{font:inherit;flex:1;min-width:200px;border:1px solid var(--line);border-radius:8px;padding:7px 10px;margin-top:10px;background:var(--card)}
#toast{position:fixed;left:50%;transform:translateX(-50%);bottom:22px;background:var(--sel);color:#fff;border-radius:8px;padding:10px 18px;opacity:0;transition:opacity .3s;pointer-events:none;font-size:14px}
#toast.show{opacity:1}
.hint{color:var(--mut);font-size:13px;margin-top:8px}
</style></head><body><div class="wrap">
<h1>Обратная связь по приёмке</h1>
<p class="sub">{{RUN}} — подтвердите или исправьте вердикты судьи. Пустая карточка = пропустить. Отметки сохраняются в браузере, кнопка внизу собирает feedback.yaml.</p>
<div class="bar">
  <button id="allok">Согласиться со всем</button>
  <button id="reset">Сбросить</button>
  <span class="grow"></span>
  <span id="prog"></span>
</div>
<div id="list"></div>
<div class="bar" style="top:auto;position:static;border-top:1px solid var(--line);border-bottom:0">
  <button class="primary" id="dl">Скачать feedback.yaml</button>
  <button id="cp">Скопировать в буфер</button>
</div>
<p class="hint">Файл положите в папку прогона (или просто скажите в чате, где он) — дальше конвейер подхватит сам.</p>
<div id="toast"></div>
<script type="application/json" id="data">{{DATA}}</script>
<script>
var RUN = {{RUNJ}};
var KEY = 'fb-' + RUN;
var DATA = JSON.parse(document.getElementById('data').textContent);
var V = ['GOT','HONEST','PARTIAL','FAIL','ATTACK_PASSED'];
var state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch(e) { state = {}; }
function save(){ localStorage.setItem(KEY, JSON.stringify(state)); }
function toast(t){ var el=document.getElementById('toast'); el.textContent=t; el.classList.add('show'); setTimeout(function(){el.classList.remove('show');},2200); }
function chip(label, cls, on, fn){
  var b=document.createElement('button'); b.className='chip '+(cls||'')+(on?' on':''); b.textContent=label;
  b.onclick=function(){ fn(); render(); }; return b;
}
function render(){
  var list=document.getElementById('list'); list.innerHTML='';
  DATA.forEach(function(c){
    var st=state[c.id]||{};
    var d=document.createElement('div'); d.className='card';
    var h=document.createElement('div'); h.className='head';
    var id=document.createElement('span'); id.className='idb'; id.textContent=c.id;
    var m=document.createElement('span'); m.className='meta'; m.textContent=c.type+' · '+c.feature;
    var res=document.createElement('span'); res.className='res'+(c.result&&c.result!=='GOT'?' neg':'');
    res.textContent='судья: '+(c.result||'—');
    h.appendChild(id); h.appendChild(m); h.appendChild(res); d.appendChild(h);
    if(c.verdicts){ var v=document.createElement('div'); v.className='det'; v.textContent='повторы: '+c.verdicts; d.appendChild(v); }
    if(c.det){ var t=document.createElement('div'); t.className='det'; t.textContent='машина: '+c.det; d.appendChild(t); }
    function sec(name, text){
      if(!text) return;
      var det=document.createElement('details'); var s=document.createElement('summary');
      s.textContent=name; var body=document.createElement('div'); body.textContent=text;
      det.appendChild(s); det.appendChild(body); d.appendChild(det);
    }
    sec('Вопрос', c.question); sec('Ожидание (записано до прогона)', c.expected); sec('Ответ системы', c.answer);
    var row=document.createElement('div'); row.className='row';
    row.appendChild(chip('Согласен', 'ok', st.v==='ok', function(){
      if(st.v==='ok'){ delete state[c.id]; } else { state[c.id]={v:'ok',c:st.c||''}; } save(); }));
    var sep=document.createElement('span'); sep.className='sep'; row.appendChild(sep);
    V.forEach(function(verdict){
      row.appendChild(chip(verdict, '', st.v===verdict, function(){
        if(st.v===verdict){ delete state[c.id]; } else { state[c.id]={v:verdict,c:st.c||''}; } save(); }));
    });
    d.appendChild(row);
    var inp=document.createElement('input'); inp.type='text'; inp.placeholder='Комментарий (необязательно)';
    inp.value=st.c||'';
    inp.onchange=function(){ if(!state[c.id]){ if(!inp.value) return; state[c.id]={v:null,c:inp.value}; } else { state[c.id].c=inp.value; } save(); };
    d.appendChild(inp);
    list.appendChild(d);
  });
  var n=0, corr=0;
  DATA.forEach(function(c){ var s=state[c.id]; if(s&&s.v){ n++; if(s.v!=='ok') corr++; } });
  document.getElementById('prog').textContent='Отвечено '+n+' из '+DATA.length+(corr?' · исправлений: '+corr:'');
}
function yaml(){
  var lines=['# обратная связь по прогону '+RUN];
  DATA.forEach(function(c){
    var s=state[c.id]; if(!s||!s.v) return;
    if(s.c) lines.push('# '+c.id+': '+s.c);
    lines.push(c.id+': '+(s.v==='ok'?'ок':s.v));
  });
  return lines.join('\\n')+'\\n';
}
document.getElementById('allok').onclick=function(){
  DATA.forEach(function(c){ if(!state[c.id]||!state[c.id].v) state[c.id]={v:'ok',c:(state[c.id]||{}).c||''}; });
  save(); render(); toast('Отмечено согласие по всем без ответа');
};
document.getElementById('reset').onclick=function(){ state={}; save(); render(); toast('Сброшено'); };
document.getElementById('dl').onclick=function(){
  var blob=new Blob([yaml()],{type:'text/yaml'});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='feedback.yaml';
  document.body.appendChild(a); a.click(); a.remove(); toast('feedback.yaml скачан');
};
document.getElementById('cp').onclick=function(){
  var text=yaml();
  if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(text).then(function(){toast('Скопировано');}); }
  else { var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); toast('Скопировано'); }
};
render();
</script></div></body></html>"""


def eco_lines(run_dir):
    """Экономика прогона для страницы: сводка cost.md (SUT) + судья
    (judge-usage.jsonl, с v0.4.1). Нет данных - пусто."""
    out = []
    cost_md = os.path.join(run_dir, "cost.md")
    if os.path.exists(cost_md):
        for line in io.open(cost_md, encoding="utf-8"):
            s = line.strip()
            if s.startswith(("Прогонов:", "**Прогон целиком", "Вызовов:")):
                out.append(s)
    jpath = os.path.join(run_dir, "вердикты", "judge-usage.jsonl")
    if os.path.exists(jpath):
        n = sum(1 for _ in io.open(jpath, encoding="utf-8"))
        out.append(f"Судья инструментирована: вызовов записано {n} "
                   "(сумма - в cost.md после cost-report.py).")
    return out


def build_feedback_html(run_dir):
    entries = load_entries(run_dir)
    run_name = os.path.basename(os.path.normpath(run_dir))
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    eco = eco_lines(run_dir)
    eco_html = ""
    if eco:
        eco_html = ('<div class="card" style="background:#eef3f7">'
                    + "<b>Экономика прогона.</b> " + "<br>".join(eco) + "</div>")
    page = (HTML.replace("{{DATA}}", data)
                .replace("{{RUNJ}}", json.dumps(run_name, ensure_ascii=False))
                .replace("{{RUN}}", run_name.replace("<", "&lt;").replace(">", "&gt;"))
                .replace('<div id="list"></div>', eco_html + '<div id="list"></div>'))
    out = os.path.join(run_dir, "feedback.html")
    io.open(out, "w", encoding="utf-8").write(page)
    print(f"страница разметки: {out} (карточек: {len(entries)})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--feedback", default=None)
    ap.add_argument("--start-id", type=int, default=None)
    ap.add_argument("--html", action="store_true",
                    help="не считать, а собрать страницу разметки feedback.html")
    a = ap.parse_args()

    run_dir = os.path.normpath(a.run_dir)
    if a.html:
        if not os.path.exists(os.path.join(run_dir, "index.jsonl")):
            print("нет index.jsonl - сначала build-index.py", file=sys.stderr); return 1
        build_feedback_html(run_dir)
        return 0
    fb_path = a.feedback or os.path.join(run_dir, "feedback.yaml")
    fb = parse_feedback(fb_path)
    if fb is None:
        print(f"файла обратной связи нет ({fb_path}) - шаг необязательный, пропускаю")
        return 0
    if not fb:
        print("файл обратной связи пуст - нечего считать"); return 0

    index_path = os.path.join(run_dir, "index.jsonl")
    if not os.path.exists(index_path):
        print("нет index.jsonl - сначала build-index.py", file=sys.stderr); return 1
    rows = {}
    for line in io.open(index_path, encoding="utf-8"):
        r = json.loads(line)
        rows[r["id"]] = r

    unknown = [c for c in fb if c not in rows]
    for c in unknown:
        print(f"  ! {c}: нет такой карточки в index.jsonl", file=sys.stderr)

    cases = []  # (id, judge_result, human, is_ok)
    for cid, (human, is_ok) in fb.items():
        if cid in rows:
            cases.append((cid, rows[cid].get("result", ""), human, is_ok))

    agree = sum(1 for _, j, h, ok in cases if ok or (h and j == h))
    rate = f"{agree}/{len(cases)}"

    # --- feedback.md ---
    lines = ["# Обратная связь человека по прогону",
             f"Прогон: {os.path.basename(run_dir)}. Кейсов с ответом: {len(cases)}.",
             f"Согласие судьи с человеком: **{rate}** (живые кейсы - главная рабочая "
             "метрика судья; контрольная выборка меряет базовую исправность).", "",
             "| Кейс | Итог судьи | Человек | Согласие |", "|---|---|---|---|"]
    for cid, j, h, ok in cases:
        hv = "ок" if ok else h
        ag = "да" if (ok or (h and j == h)) else "**НЕТ**"
        lines.append(f"| {cid} | {j} | {hv} | {ag} |")
    if unknown:
        lines += ["", "Неизвестные id: " + ", ".join(unknown)]
    io.open(os.path.join(run_dir, "feedback.md"), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")

    # --- golden-candidates.md ---
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nid = a.start_id or next_id(repo_root)
    g = ["# Golden-кандидаты из прогона (эталон - вердикт человека)",
         "",
         f"Прогон: {os.path.basename(run_dir)}. Кейсы ниже - черновики контрольной "
         "выборки: владелец просматривает и переносит в knowledge/golden-live.md. "
         "Эталон ставит человек по факту прогона; вердикт судьи эталоном не "
         "становится. Ответ SUT - дословный транскрипт повтора (обрезан до "
         f"{MAX_ANSWER} символов, полный - по пути в строке «Источник»).", ""]
    made = 0
    for cid, j, h, ok in cases:
        verdict = h if (h and not ok) else (j if j in VERDICTS else None)
        if not verdict:
            continue  # «ок» при сплите/безвердиктии - эталон не определён
        card = os.path.join(run_dir, "карточки", f"{cid}.yaml")
        if not os.path.exists(card):
            continue
        f = yaml_fields(card)
        rep = choose_rep(rows[cid], None if ok else h)
        tpath = os.path.join(run_dir, "прогоны", f"{cid}-r{rep}.txt")
        if not (f["instruction"] and f["expected"] and os.path.exists(tpath)):
            continue
        answer = dedup_transcript(one_line(io.open(tpath, encoding="utf-8").read()))[:MAX_ANSWER]
        if len(answer) == MAX_ANSWER:
            answer += " …[обрезано]"
        g.append(f"## G-{nid} (эталон: {verdict})")
        g.append("")
        g.append(f"Вопрос: {one_line(f['instruction'])}")
        g.append(f"Ожидание: {one_line(f['expected'])}")
        g.append(f"Ответ SUT: {answer}")
        g.append(f"Источник: {os.path.basename(run_dir)}/прогоны/{cid}-r{rep}.txt; "
                 f"судья: {j}, человек: {'ок' if ok else h}.")
        g.append("")
        nid += 1
        made += 1
    g.append(f"---\nИтого кандидатов: {made}.")
    io.open(os.path.join(run_dir, "golden-candidates.md"), "w", encoding="utf-8").write(
        "\n".join(g) + "\n")

    print(f"согласие: {rate}; golden-кандидатов: {made} -> "
          f"{os.path.join(run_dir, 'golden-candidates.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
