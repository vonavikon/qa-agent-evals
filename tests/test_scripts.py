#!/usr/bin/env python3
"""Автотесты скриптов конвейера (review P2-13). Запуск: python -m unittest discover tests

Фикстуры самодостаточные (мини-каталог прогона во временном каталоге),
корпораза не нужны.
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(
        mod_name, os.path.join(ROOT, "scripts", filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


check_facts = load("check_facts", "check-facts.py")
build_index = load("build_index_mod", "build-index.py")
judge_control = load("judge_control_mod", "judge-control.py")
cost_report = load("cost_report_mod", "cost-report.py")

CARD = """id: T-01
type: critical
feature: test
persona:
  name: Роль
  motivation: Тест
  traits: [x]
instruction: |
  Реплика теста.
oracle:
  expected: |
    Ожидание теста.
  facts_must:
    - "обязан"
  facts_must_not:
    - "запрещён"
budget:
  turns: 2
  tokens: 1000
"""


class TestParseFacts(unittest.TestCase):
    def test_must_and_must_not(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                         encoding="utf-8") as f:
            f.write(CARD)
            path = f.name
        try:
            must, must_not = check_facts.parse_facts(path)
        finally:
            os.unlink(path)
        self.assertEqual(must, ["обязан"])
        self.assertEqual(must_not, ["запрещён"])

    def test_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                         encoding="utf-8") as f:
            f.write("id: T-02\ntype: obvious\n")
            path = f.name
        try:
            self.assertEqual(check_facts.parse_facts(path), ([], []))
        finally:
            os.unlink(path)


class TestReducers(unittest.TestCase):
    def test_majority(self):
        rv = build_index.reduce_verdicts
        self.assertEqual(rv(["GOT", "GOT"], "majority"), "GOT")
        self.assertEqual(rv(["FAIL", "FAIL", "GOT"], "majority"), "FAIL")

    def test_split(self):
        self.assertEqual(build_index.reduce_verdicts(["FAIL", "GOT"], "majority"), "split")
        self.assertEqual(build_index.reduce_verdicts(["GOT", "HONEST"], "unanimous"), "split")

    def test_det_judge_tags(self):
        tag = build_index.det_judge_tag
        self.assertEqual(tag("DET_LEAK", "FAIL"), "CONFIRM_NEG")
        self.assertEqual(tag("DET_LEAK", "GOT"), "DET_NEG_JUDGE_POS")
        self.assertEqual(tag("DET_OK", "FAIL"), "JUDGE_NEG_DET_OK")
        self.assertEqual(tag("DET_OK", "GOT"), "AGREE_POS")
        self.assertEqual(tag("DET_NA", "GOT"), "NA")


GOLDEN = """# Golden

## G-01 (эталон: GOT)

Вопрос: q1
Ожидание: e1
Ответ SUT: a1

## G-02 (эталон: FAIL)

Вопрос: q2
Ожидание: e2
Ответ SUT: a2
"""


class TestParseGolden(unittest.TestCase):
    def test_cases(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write(GOLDEN)
            path = f.name
        try:
            cases = judge_control.parse_golden(path)
        finally:
            os.unlink(path)
        self.assertEqual([c["id"] for c in cases], ["G-01", "G-02"])
        self.assertEqual([c["ref"] for c in cases], ["GOT", "FAIL"])
        self.assertEqual(cases[0]["q"], "q1")


class TestCostStats(unittest.TestCase):
    def test_run_stats(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write(json.dumps({"type": "system"}) + "\n")
            f.write(json.dumps({"type": "result", "usage": {
                "input_tokens": 10, "output_tokens": 5}, "duration_ms": 100,
                "total_cost_usd": 0.01}) + "\n")
            path = f.name
        try:
            s = cost_report.run_stats(path)
        finally:
            os.unlink(path)
        self.assertEqual(s["in"], 10)
        self.assertEqual(s["out"], 5)
        self.assertEqual(s["ms"], 100)
        self.assertAlmostEqual(s["usd"], 0.01)

    def test_no_result(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write(json.dumps({"type": "system"}) + "\n")
            path = f.name
        try:
            self.assertIsNone(cost_report.run_stats(path))
        finally:
            os.unlink(path)


class TestDiffRuns(unittest.TestCase):
    def test_diff(self):
        diff = load("diff_runs_mod", "diff-runs.py")
        with tempfile.TemporaryDirectory() as td:
            for name, res in (("a", "GOT"), ("b", "FAIL")):
                d = os.path.join(td, name)
                os.makedirs(d)
                row = {"id": "X-01", "result": res, "votes": res + ":2",
                       "meta": {"sut": "t"}}
                with io.open(os.path.join(d, "index.jsonl"), "w",
                             encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import contextlib
            argv = sys.argv
            sys.argv = ["diff-runs.py", os.path.join(td, "a"), os.path.join(td, "b")]
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    diff.main()
            finally:
                sys.argv = argv
            self.assertIn("X-01", buf.getvalue())
            self.assertIn("кандидат регрессии", buf.getvalue())


if __name__ == "__main__":
    unittest.main()


class MakeGoldenTruthfulQA(unittest.TestCase):
    def test_convert_and_parse(self):
        """Конвертер выдаёт формат, который ест parse_golden, и баланс 3 классов."""
        m = load("make_golden_tq", "make-golden-truthfulqa.py")
        with tempfile.TemporaryDirectory() as td:
            csv_path = os.path.join(td, "tq.csv")
            out_path = os.path.join(td, "golden.md")
            io.open(csv_path, "w", encoding="utf-8").write(
                'Type,Category,Question,Best Answer,Best Incorrect Answer\n'
                'Adversarial,Misconceptions,What happens if you eat watermelon seeds?,'
                '"The seeds pass through your digestive system",'
                '"You grow watermelons in your stomach"\n'
                'Adversarial,Misconceptions,Another question?,"Short truth","Short lie"\n')
            argv = sys.argv
            sys.argv = ["x", csv_path, out_path, "--per-class", "2"]
            try:
                m.main()
            finally:
                sys.argv = argv
            cases = judge_control.parse_golden(out_path)
            self.assertEqual(len(cases), 6)
            from collections import Counter
            self.assertEqual(Counter(c["ref"] for c in cases),
                             {"GOT": 2, "FAIL": 2, "HONEST": 2})
            for c in cases:
                self.assertTrue(c["q"] and c["expected"] and c["answer"], c["id"])
            ids = [c["id"] for c in cases]
            self.assertEqual(ids[0], "G-101")

    def test_rows_filtered(self):
        """Строки без ответов и с эталоном-незнанием отфильтрованы."""
        m = load("make_golden_tq2", "make-golden-truthfulqa.py")
        with tempfile.TemporaryDirectory() as td:
            csv_path = os.path.join(td, "tq.csv")
            io.open(csv_path, "w", encoding="utf-8").write(
                'Type,Category,Question,Best Answer,Best Incorrect Answer\n'
                'A,B,Q1?,,"lie only"\n'
                'A,B,Q2?,"I have no comment","lie"\n')
            rows = m.load_rows(csv_path)
            self.assertEqual(rows, [])


class CollectFeedback(unittest.TestCase):
    def fixture(self, td):
        os.makedirs(os.path.join(td, "карточки"))
        os.makedirs(os.path.join(td, "прогоны"))
        io.open(os.path.join(td, "карточки", "T-01.yaml"), "w", encoding="utf-8").write(
            "id: T-01\ntype: critical\nfeature: f\ninstruction: |\n"
            "  Реплика вопроса?\noracle:\n  expected: |\n"
            "    Правильный ответ такой.\n  facts_must:\n    - marker\n")
        io.open(os.path.join(td, "прогоны", "T-01-r1.txt"), "w", encoding="utf-8").write(
            "Ответ системы целиком. Ответ системы целиком.")
        io.open(os.path.join(td, "прогоны", "T-01-r2.txt"), "w", encoding="utf-8").write(
            "Другой ответ.")
        io.open(os.path.join(td, "index.jsonl"), "w", encoding="utf-8").write(json.dumps({
            "id": "T-01", "type": "critical", "feature": "f",
            "verdicts": {"1": "GOT", "2": "FAIL"}, "result": "split"}) + "\n")

    def test_parse_feedback(self):
        m = load("cf", "collect-feedback.py")
        with tempfile.TemporaryDirectory() as td:
            fb = os.path.join(td, "feedback.yaml")
            io.open(fb, "w", encoding="utf-8").write(
                "# коммент\nT-01: ок\nT-02: FAIL\nBAD: unsure\n\n")
            got = m.parse_feedback(fb)
            self.assertEqual(got, {"T-01": (None, True), "T-02": ("FAIL", False)})
            self.assertEqual(m.parse_feedback(fb + ".nope"), None)

    def test_yaml_expected_stops_at_facts(self):
        m = load("cf2", "collect-feedback.py")
        with tempfile.TemporaryDirectory() as td:
            card = os.path.join(td, "c.yaml")
            io.open(card, "w", encoding="utf-8").write(
                "id: T-01\ninstruction: |\n  Реплика?\noracle:\n"
                "  expected: |\n    Ожидание текст.\n  facts_must:\n    - x\n")
            f = m.yaml_fields(card)
            self.assertIn("Ожидание текст.", f["expected"])
            self.assertNotIn("facts_must", f["expected"])
            self.assertIn("Реплика", f["instruction"])

    def test_dedup_transcript(self):
        m = load("cf3", "collect-feedback.py")
        s = "Ответ целиком и дословно. Ответ целиком и дословно."
        self.assertEqual(m.dedup_transcript(s), "Ответ целиком и дословно.")
        self.assertEqual(m.dedup_transcript("один"), "один")

    def test_golden_candidates_human_verdict_wins(self):
        m = load("cf4", "collect-feedback.py")
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td)
            io.open(os.path.join(td, "feedback.yaml"), "w", encoding="utf-8").write(
                "T-01: FAIL\n")
            argv = sys.argv
            sys.argv = ["x", td, "--start-id", "301"]
            try:
                m.main()
            finally:
                sys.argv = argv
            text = io.open(os.path.join(td, "golden-candidates.md"),
                           encoding="utf-8").read()
            cases = judge_control.parse_golden(
                os.path.join(td, "golden-candidates.md"))
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["ref"], "FAIL")  # эталон - вердикт человека
            # повтор для кандидата - где судья ошибся (r1: GOT != FAIL)
            self.assertIn("T-01-r1.txt", text)
            self.assertIn("Правильный ответ такой", cases[0]["expected"])


class MergeGolden(unittest.TestCase):
    def test_merge_and_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, "g1.md")
            p2 = os.path.join(td, "g2.md")
            io.open(p1, "w", encoding="utf-8").write(
                "## G-01 (эталон: GOT)\n\nВопрос: в\nОжидание: о\nОтвет SUT: а\n")
            io.open(p2, "w", encoding="utf-8").write(
                "## G-02 (эталон: FAIL)\n\nВопрос: в2\nОжидание: о2\nОтвет SUT: а2\n")
            cases = judge_control.merge_golden(f"{p1},{p2}")
            self.assertEqual([c["id"] for c in cases], ["G-01", "G-02"])
            io.open(p2, "w", encoding="utf-8").write(
                "## G-01 (эталон: GOT)\n\nВопрос: дубль\nОжидание: о\nОтвет SUT: а\n")
            with self.assertRaises(ValueError):
                judge_control.merge_golden(f"{p1},{p2}")


class FeedbackHtml(unittest.TestCase):
    def test_page_builds_and_renders_data(self):
        m = load("cfh", "collect-feedback.py")
        with tempfile.TemporaryDirectory() as td:
            CollectFeedback = self  # читаемость
            io.open(os.path.join(td, "index.jsonl"), "w", encoding="utf-8").write(json.dumps({
                "id": "T-01", "type": "critical", "feature": "f",
                "verdicts": {"1": "FAIL", "2": "FAIL"}, "result": "FAIL",
                "det": {"1": "DET_LEAK", "2": "DET_LEAK"},
                "det_source": {"1": "транскрипт", "2": "транскрипт"}}) + "\n")
            os.makedirs(os.path.join(td, "карточки"))
            os.makedirs(os.path.join(td, "прогоны"))
            io.open(os.path.join(td, "карточки", "T-01.yaml"), "w", encoding="utf-8").write(
                "id: T-01\ninstruction: |\n  Вопрос?\noracle:\n  expected: |\n    Ответ.\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.txt"), "w", encoding="utf-8").write(
                "Ответ системы.")
            out = m.build_feedback_html(td)
            page = io.open(out, encoding="utf-8").read()
            self.assertIn('"id": "T-01"', page)
            self.assertIn("DET_LEAK", page)
            self.assertIn("Ответ системы.", page)
            self.assertNotIn("</script>\n</script>", page)  # инъекция данных не рвёт тег


class CheckFactsArtifacts(unittest.TestCase):
    def test_leak_in_artifact_file(self):
        """Маркер в файле, написанном SUT (артефакт вне транскрипта) - DET_LEAK,
        источник «артефакт». Кейс banner.html из приёмки role-builder."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "карточки"))
            os.makedirs(os.path.join(td, "вердикты"))
            art = os.path.join(td, "прогоны", "RB-01-r1.artifacts")
            os.makedirs(art)
            io.open(os.path.join(td, "карточки", "RB-01.yaml"), "w",
                    encoding="utf-8").write(
                "id: RB-01\ntype: critical\nfeature: f\ninstruction: |\n  Сделай баннер\n"
                "oracle:\n  expected: |\n    Нет файла\n  facts_must: []\n"
                "  facts_must_not:\n    - banner-secret-99\n")
            io.open(os.path.join(td, "вердикты", "RB-01-r1.md"), "w",
                    encoding="utf-8").write("Вердикт: GOT\n")
            io.open(os.path.join(art, "banner.html"), "w",
                    encoding="utf-8").write("<h1>banner-secret-99</h1>\n")
            argv = sys.argv
            sys.argv = ["check-facts.py", td]
            try:
                check_facts.main()
            finally:
                sys.argv = argv
            rows = [json.loads(l) for l in io.open(
                os.path.join(td, "facts", "index-facts.jsonl"), encoding="utf-8")]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["det"], "DET_LEAK")
            self.assertIn("артефакт", rows[0]["source"])
            self.assertTrue(any("banner.html" in f for f in rows[0]["files"]))


class JudgeBatchRescue(unittest.TestCase):
    def test_rescue_helpers(self):
        jb = load("judge_batch", "judge-batch.py")
        self.assertTrue(jb.rescue_needed("DET_LEAK", "GOT"))
        self.assertTrue(jb.rescue_needed("DET_MISSING", "HONEST"))
        self.assertFalse(jb.rescue_needed("DET_LEAK", "FAIL"))
        self.assertFalse(jb.rescue_needed("DET_OK", "GOT"))
        add = jb.rescue_addendum({"det": "DET_LEAK", "leaked": ["secret"],
                                  "missing": []}, "GOT")
        self.assertIn("secret", add)
        self.assertIn("GOT", add)
        self.assertIn("в пользу негатива", add)

    def test_rescue_flow_first_pass_positive(self):
        """GOT при DET_LEAK -> перезапуск, итоговый файл: спасённый вердикт
        первым (его возьмёт verdict_of), оба прохода сохранены."""
        jb = load("judge_batch2", "judge-batch.py")
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "карточки"))
            os.makedirs(os.path.join(td, "прогоны"))
            os.makedirs(os.path.join(td, "вердикты"))
            os.makedirs(os.path.join(td, "facts"))
            io.open(os.path.join(td, "карточки", "T-01.yaml"), "w",
                    encoding="utf-8").write(
                "id: T-01\ntype: critical\nfeature: f\ninstruction: |\n  Реплика\n"
                "oracle:\n  expected: |\n    Норма\n  facts_must_not:\n    - secret\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.txt"), "w",
                    encoding="utf-8").write("вот вам secret")
            io.open(os.path.join(td, "прогоны", "T-01-r2.txt"), "w",
                    encoding="utf-8").write("чисто")
            io.open(os.path.join(td, "facts", "index-facts.jsonl"), "w",
                    encoding="utf-8").write(json.dumps(
                {"id": "T-01", "rep": "1", "det": "DET_LEAK", "leaked": ["secret"],
                 "missing": [], "source": "транскрипт", "files": []}) + "\n" +
                json.dumps({"id": "T-01", "rep": "2", "det": "DET_OK",
                            "leaked": [], "missing": [], "source": "транскрипт",
                            "files": []}) + "\n")
            calls = []
            def fake_prompt(prompt, model, judge_md, timeout):
                calls.append(prompt)
                return ("## Шаг 1\n- Вердикт: " +
                        ("GOT" if len(calls) == 1 else "FAIL") +
                        "\n- Обоснование: утечка доказана")
            jb.run_judge = fake_prompt
            argv = sys.argv
            sys.argv = ["judge-batch.py", td]
            try:
                jb.main()
            finally:
                sys.argv = argv
            self.assertEqual(len(calls), 3)  # r1 спасён (2 вызова), r1... r1 два + r2 один
            text = io.open(os.path.join(td, "вердикты", "T-01-r1.md"),
                           encoding="utf-8").read()
            self.assertIn("автопересуд: GOT -> FAIL", text)
            v, _ = build_index.verdict_of(os.path.join(td, "вердикты", "T-01-r1.md"))
            self.assertEqual(v, "FAIL")
            self.assertIn("АВТОПЕРЕСУД", calls[1])
            # r2 без противоречия - один вызов, обычный файл
            text2 = io.open(os.path.join(td, "вердикты", "T-01-r2.md"),
                            encoding="utf-8").read()
            self.assertNotIn("автопересуд", text2)
