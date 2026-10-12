#!/usr/bin/env python3
"""Машиночитаемый индекс прогона (runs/<дата>-<sut>/index.jsonl).

По образцу .eval-лога Inspect AI: одна строка JSON на прогон - вердикты,
редьюсер-итог, пути артефактов. Открывает re-scoring (пересуд по протоколам
без новых прогонов), программные сводки и сравнение приёмок.

Usage: build-index.py <run-dir> [--reducer majority|unanimous|at_least_k]
  majority  - итог за большинством повторов, расхождение = "split"
  unanimous - итог только при единодушии, иначе "split" (дефолт N=2)
Читает: карточки/*.yaml, вердикты/*.md (строка «- Вердикт: X»), прогоны/ (наличие),
        facts/index-facts.jsonl (если есть - колонка det: детерминированный слой).
Пишет: index.jsonl. Выход 0.
"""

import argparse
import glob
import io
import json
import os
import re
import sys

NEG = {"FAIL", "ATTACK_PASSED"}
DET_NEG = {"DET_LEAK", "DET_MISSING"}


def det_judge_tag(det, judge):
    """Согласие слоёв по направлению (survey: комитеты показывают расхождение)."""
    if det == "-" or det in ("DET_NA", "DET_NO_DATA"):
        return "NA"
    dn, jn = det in DET_NEG, judge in NEG
    if dn and jn:
        return "CONFIRM_NEG"
    if dn and not jn:
        return "DET_NEG_JUDGE_POS"
    if not dn and jn:
        return "JUDGE_NEG_DET_OK"
    return "AGREE_POS"


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
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--reducer", default="majority")
    ap.add_argument("--sut", default="", help="SUT и версия")
    ap.add_argument("--judge-model", default="", dest="judge_model", help="модель судьи")
    ap.add_argument("--plugin-version", default="", dest="plugin_version",
                    help="версия qa-agent-evals; по умолчанию из plugin.json")
    a = ap.parse_args()
    run_dir = norm(a.run_dir)
    meta_path = os.path.join(run_dir, "meta.json")
    if os.path.exists(meta_path):
        m = json.load(io.open(meta_path, encoding="utf-8"))
        a.sut = a.sut or m.get("sut", "")
        a.judge_model = a.judge_model or m.get("judge_model", "")
        a.plugin_version = a.plugin_version or m.get("plugin_version", "")
    if not a.plugin_version:
        pj = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          ".claude-plugin", "plugin.json")
        if os.path.exists(pj):
            a.plugin_version = json.load(io.open(pj, encoding="utf-8")).get("version", "")
    reducer = a.reducer
    det_index = {}
    det_path = os.path.join(run_dir, "facts", "index-facts.jsonl")
    if os.path.exists(det_path):
        for line in io.open(det_path, encoding="utf-8"):
            r = json.loads(line)
            det_index[(r["id"], r["rep"])] = (r["det"], r["source"])
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
        tally = {}
        for v in verdicts:
            tally[v] = tally.get(v, 0) + 1
        row = {
            "id": cid, "type": ctype, "feature": feature,
            "repeats": sorted(reps), "verdicts": reps,
            "reducer": reducer,
            "result": reduce_verdicts(verdicts, reducer) if verdicts else "NO_VERDICT",
            "any_negative": any(v in NEG or v == "split" for v in verdicts),
            "meta": {"sut": a.sut, "judge_model": a.judge_model,
                     "plugin_version": a.plugin_version},
            "votes": ", ".join(f"{k}:{v}" for k, v in sorted(tally.items())),
            "judge_disagreement": len(tally) > 1,
        }
        arts = {}
        for rep, suffix in [(k, f"-r{k}") for k in sorted(reps)]:
            for ext, key in [(".txt", "transcript"), (".prov.txt", "provenance"),
                             (".diag.txt", "diag"), (".events.jsonl", "events")]:
                p = os.path.join(run_dir, "прогоны", cid + suffix + ext)
                if os.path.exists(p):
                    arts.setdefault(rep, {})[key] = os.path.relpath(p, run_dir)
        row["artifacts"] = arts
        if det_index:
            row["det"] = {rep: det_index[(cid, rep)][0] if (cid, rep) in det_index else "-"
                          for rep in sorted(reps)}
            row["det_source"] = {rep: det_index[(cid, rep)][1] if (cid, rep) in det_index else "-"
                                 for rep in sorted(reps)}
            row["det_judge"] = {rep: det_judge_tag(det_index[(cid, rep)][0], reps[rep])
                                if (cid, rep) in det_index else "NA" for rep in sorted(reps)}
        rows.append(json.dumps(row, ensure_ascii=False))
    out = os.path.join(run_dir, "index.jsonl")
    io.open(out, "w", encoding="utf-8").write("\n".join(rows) + "\n")
    neg = sum(1 for r in rows if json.loads(r)["any_negative"])
    print(f"index.jsonl: {len(rows)} карточек, редьюсер {reducer}, карточек с негативом/расхождением: {neg}")


if __name__ == "__main__":
    main()
