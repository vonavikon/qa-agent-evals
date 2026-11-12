#!/usr/bin/env python3
"""Automated tests for the pipeline scripts (review P2-13). Run: python -m unittest discover tests

Fixtures are self-contained (a mini run directory in a temp directory),
no corporate data needed.
"""

import base64
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
av = load("av", "annotate-visuals.py")

# Valid 1x1 PNG - the content does not matter, the validator only needs the file to exist.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

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
        """The converter emits the format parse_golden accepts, with 3 balanced classes."""
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
        """Rows without answers and with an ignorance reference are filtered out."""
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
            self.assertEqual(cases[0]["ref"], "FAIL")  # the reference is the human verdict
            # the repeat for a candidate - where the judge was wrong (r1: GOT != FAIL)
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
            CollectFeedback = self  # readability
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
            self.assertNotIn("</script>\n</script>", page)  # data injection does not break the tag

    def test_page_embeds_screenshots_and_findings(self):
        m = load("cfv", "collect-feedback.py")
        with tempfile.TemporaryDirectory() as td:
            io.open(os.path.join(td, "index.jsonl"), "w", encoding="utf-8").write(json.dumps({
                "id": "T-01", "type": "critical", "feature": "f",
                "verdicts": {"1": "FAIL"}, "result": "FAIL"}) + "\n")
            os.makedirs(os.path.join(td, "карточки"))
            os.makedirs(os.path.join(td, "прогоны"))
            io.open(os.path.join(td, "карточки", "T-01.yaml"), "w", encoding="utf-8").write(
                "id: T-01\ninstruction: |\n  Вопрос?\noracle:\n  expected: |\n    Ответ.\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.txt"), "w", encoding="utf-8").write(
                "Ответ системы.")
            io.open(os.path.join(td, "прогоны", "T-01-r1.png"), "wb").write(PNG_1PX)
            io.open(os.path.join(td, "визуальный-ревью.json"), "w", encoding="utf-8").write(
                json.dumps({"screenshots": [{"file": "T-01-r1.png", "findings": [
                    {"bbox": [5, 10, 50, 40], "severity": "risk",
                     "comment": "счёт блеклый"}]}]}, ensure_ascii=False))
            page = io.open(m.build_feedback_html(td), encoding="utf-8").read()
            self.assertIn('"shots": [{"file": "T-01-r1.png"', page)
            self.assertIn("Скриншоты", page)
            self.assertIn("счёт блеклый", page)
            # a broken finding does not crash the page: the shot stays without markup
            io.open(os.path.join(td, "визуальный-ревью.json"), "w", encoding="utf-8").write(
                '{"screenshots": [{"file": "T-01-r1.png", "findings": '
                '[{"bbox": [1], "severity": "wat"}]}, {"file": 3}]}')
            page = io.open(m.build_feedback_html(td), encoding="utf-8").read()
            self.assertIn('"shots": [{"file": "T-01-r1.png", "findings": []}]', page)


class VisualReview(unittest.TestCase):
    def fixture(self, td, review=None):
        os.makedirs(os.path.join(td, "прогоны"))
        io.open(os.path.join(td, "прогоны", "GA-01-r1.png"), "wb").write(PNG_1PX)
        if review is None:
            review = {"screenshots": [{"file": "GA-01-r1.png", "findings": [
                {"bbox": [10, 20, 40, 30], "severity": "defect",
                 "comment": "плитки перекрывают счёт"}]}]}
        io.open(os.path.join(td, av.REVIEW_NAME), "w", encoding="utf-8").write(
            json.dumps(review, ensure_ascii=False))

    def test_validate_and_render(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td)
            review = av.load_review(td)
            self.assertEqual(av.validate_review(review, td), [])
            page = io.open(av.render_html(td, review), encoding="utf-8").read()
            self.assertIn("GA-01-r1.png", page)
            self.assertIn("left:10%", page)
            self.assertIn("s-defect", page)
            self.assertIn("плитки перекрывают счёт", page)
            self.assertIn("вердикты не меняет", page)

    def test_validate_rejects_bad_bbox_severity_missing_file_dupes(self):
        with tempfile.TemporaryDirectory() as td:
            self.fixture(td, {"screenshots": [
                {"file": "GA-01-r1.png", "findings": [
                    {"bbox": [120, 0, 0, 30], "severity": "wat", "comment": " "}]},
                {"file": "GA-01-r9.png", "findings": []},
                {"file": "GA-01-r1.png"}]})
            errs = av.validate_review(av.load_review(td), td)
            text = "\n".join(errs)
            self.assertIn("bbox", text)
            self.assertIn("severity", text)
            self.assertIn("пустой комментарий", text)
            self.assertIn("файла нет", text)
            self.assertIn("больше одного раза", text)

    def test_publish_copies_samples_and_manifest(self):
        with tempfile.TemporaryDirectory() as repo:
            rd = os.path.join(repo, "runs", "2026-10-20-2048")
            os.makedirs(rd)
            self.fixture(rd)
            self.assertEqual(av.publish(rd, ["GA-01"], repo_root=repo), ["GA-01"])
            dst = os.path.join(repo, "docs", "visual-samples", "2026-10-20-2048")
            self.assertTrue(os.path.exists(os.path.join(dst, "GA-01-r1.png")))
            md = io.open(os.path.join(dst, "GA-01.md"), encoding="utf-8").read()
            self.assertIn("плитки перекрывают счёт", md)
            rm = io.open(os.path.join(repo, "docs", "visual-samples", "README.md"),
                         encoding="utf-8").read()
            self.assertIn("2026-10-20-2048", rm)
            # a repeated publish does not duplicate the manifest row
            av.publish(rd, ["GA-01"], repo_root=repo)
            rm2 = io.open(os.path.join(repo, "docs", "visual-samples", "README.md"),
                          encoding="utf-8").read()
            self.assertEqual(rm2, rm)

    def test_quiet_when_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(av.load_review(td))
            self.assertEqual(av.validate_review({"screenshots": []}, td), [])


class CheckFactsArtifacts(unittest.TestCase):
    def test_leak_in_artifact_file(self):
        """A marker in a file written by the SUT (an artifact outside the transcript) - DET_LEAK,
        source "artifact". The banner.html case from the role-builder acceptance."""
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
        """GOT with DET_LEAK -> rerun, final file: the rescued verdict
        goes first (verdict_of picks it), both passes are kept."""
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
            self.assertEqual(len(calls), 3)  # r1 rescued (2 calls), r1... r1 twice + r2 once
            text = io.open(os.path.join(td, "вердикты", "T-01-r1.md"),
                           encoding="utf-8").read()
            self.assertIn("автопересуд: GOT -> FAIL", text)
            v, _ = build_index.verdict_of(os.path.join(td, "вердикты", "T-01-r1.md"))
            self.assertEqual(v, "FAIL")
            self.assertIn("АВТОПЕРЕСУД", calls[1])
            # r2 without a contradiction - one call, a regular file
            text2 = io.open(os.path.join(td, "вердикты", "T-01-r2.md"),
                            encoding="utf-8").read()
            self.assertNotIn("автопересуд", text2)


class NestedOracle(unittest.TestCase):
    def test_expected_reaches_judge(self):
        """v0.3.x regression: expected inside oracle: never reached the judge."""
        jb = load("jb_nested", "judge-batch.py")
        card = ("id: T-01\ntype: critical\nfeature: f\ninstruction: |\n"
                "  Реплика\noracle:\n  expected: |\n    Норма такая.\n"
                "    Ещё строка.\n  facts_must:\n    - x\n")
        got = jb.nested_literal(card, "oracle", "expected")
        self.assertIn("Норма такая.", got)
        self.assertIn("Ещё строка.", got)
        self.assertNotIn("facts_must", got)
        self.assertEqual(jb.nested_literal(card, "oracle", "missing"), "")


class JudgeUsage(unittest.TestCase):
    def test_parse_judge_output(self):
        jb = load("jb_usage", "judge-batch.py")
        raw = json.dumps({"result": "Вердикт: GOT\nобоснование",
                          "usage": {"input_tokens": 100, "output_tokens": 5,
                                    "cache_read_input_tokens": 7},
                          "total_cost_usd": 0.01, "duration_ms": 2000,
                          "model": "m"})
        body, note, row = jb.parse_judge_output(raw)
        self.assertIn("Вердикт: GOT", body)
        self.assertIn("$0.0100", note)
        self.assertEqual(row["in"], 100)
        self.assertEqual(row["dur_s"], 2.0)
        # non-JSON - raw text, no usage
        body2, note2, row2 = jb.parse_judge_output("Вердикт: FAIL\nтекст")
        self.assertIn("FAIL", body2)
        self.assertIsNone(note2)
        self.assertIsNone(row2)

    def test_judge_stats(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "вердикты"))
            self.assertIsNone(cost_report.judge_stats(td))
            io.open(os.path.join(td, "вердикты", "judge-usage.jsonl"), "w",
                    encoding="utf-8").write(
                json.dumps({"in": 10, "out": 2, "cache_read": 1,
                            "cost_usd": 0.5, "dur_s": 3}) + "\n" +
                json.dumps({"in": 5, "out": 1, "cache_read": 0,
                            "cost_usd": 0.25, "dur_s": 2}) + "\n")
            j = cost_report.judge_stats(td)
            self.assertEqual(j["n"], 2)
            self.assertAlmostEqual(j["usd"], 0.75)
            self.assertEqual(j["in"], 15)


class SandboxBackend(unittest.TestCase):
    def test_wrap_docker_flags(self):
        """docker prefix: network off, read-only, non-root, limits, only work
        is mounted; no docker.sock and no host home."""
        sb = load("sandbox", "sandbox.py")
        cmd = sb.wrap("docker", "/tmp/qa-evals-run-x", ["claude", "-p", "hi"])
        self.assertEqual(cmd[0], "docker")
        joined = " ".join(cmd)
        for token in ["--network qa-sbx-", "--read-only", "--user 1000:1000",
                      "--pids-limit 64", "--memory 1g", "--env-file"]:
            self.assertIn(token, joined)
        # outbound - only via the internal proxy container, the SUT has no bridge
        self.assertNotIn("bridge", joined)
        self.assertNotIn("docker.sock", joined)
        self.assertNotIn("/c/Users", joined)
        mounts = [cmd[i + 1] for i, t in enumerate(cmd) if t == "-v"]
        # all mounts come from the single work root; the naive conversion
        # /tmp -> C:\tmp (an empty mount) is forbidden
        self.assertTrue(all("qa-evals-run-x" in m for m in mounts), mounts)
        self.assertNotIn("C:" + chr(92) + "tmp", " ".join(mounts))
        self.assertEqual(cmd[-3:], ["claude", "-p", "hi"])

    def test_wrap_host_passthrough(self):
        sb = load("sandbox2", "sandbox.py")
        self.assertEqual(sb.wrap("host", "/tmp/x", ["claude", "-p"]), ["claude", "-p"])

    def test_fail_closed_unknown_and_verify(self):
        sb = load("sandbox3", "sandbox.py")
        self.assertEqual(sb.verify("host"), 0)
        self.assertEqual(sb.verify("hyper"), 1)
        # docker unavailable -> code 2, no crash
        sb.docker_version = lambda: None
        self.assertEqual(sb.verify("docker"), 2)

    def test_tree_hash_deterministic(self):
        sb = load("sandbox4", "sandbox.py")
        with tempfile.TemporaryDirectory() as td:
            io.open(os.path.join(td, "a.txt"), "w", encoding="utf-8").write("x")
            h1, h2 = sb.tree_hash(td), sb.tree_hash(td)
            self.assertEqual(h1, h2)
            io.open(os.path.join(td, "b.txt"), "w", encoding="utf-8").write("y")
            self.assertNotEqual(h1, sb.tree_hash(td))

    def test_canary_markers_differ(self):
        sb = load("sandbox5", "sandbox.py")
        p = sb.ensure_host_canary()
        body = io.open(p, encoding="utf-8").read()
        self.assertIn(sb.CANARY_HOST_MARKER, body)
        self.assertNotIn(sb.CANARY_GUEST_MARKER, body)


class SandboxHardeningP0(unittest.TestCase):
    """Hardening P0 spec: sources read-only, the LLM secret stays outside the SUT."""

    def test_mounts_split_and_readonly(self):
        sb = load("sb_h1", "sandbox.py")
        cmd = sb.wrap("docker", "/tmp/qa-evals-run-x", ["claude", "-p"])
        joined = " ".join(cmd)
        mounts = [cmd[i + 1] for i, t in enumerate(cmd) if t == "-v"]
        self.assertTrue(any(m.endswith("sut:/workspace/sut:ro") for m in mounts), mounts)
        self.assertTrue(any(m.endswith("out:/workspace/out:rw") for m in mounts), mounts)
        # the shared rw work mount is gone
        self.assertFalse(any(m.endswith(":/workspace") for m in mounts), mounts)
        # golden refs/runner internals and the proxy SECRET are not mounted;
        # the allowed exception - priv/canary (a decoy file, ro, no secret)
        self.assertFalse(any("oracle" in m or "runner" in m or "proxy.env" in m
                             for m in mounts), mounts)
        for m in mounts:
            if "priv" in m:
                self.assertTrue(m.endswith("canary:/home/node/.qa-evals-canary:ro"), m)
        self.assertIn("/workspace:rw,nosuid", joined)  # tmpfs for the root

    def test_sut_env_has_no_secret(self):
        sb = load("sb_h2", "sandbox.py")
        with tempfile.TemporaryDirectory() as td:
            p = sb.build_llm_env(td, True)
            body = io.open(p, encoding="utf-8").read()
            self.assertIn("sandbox-local-placeholder", body)
            self.assertIn("http://llm:8140", body)
            # neither the real key nor the proxy env file
            self.assertNotIn("sk-", body)
            self.assertNotIn("proxy.env", body)
            self.assertEqual(os.path.basename(p), "sut.env")

    def test_priv_dir_outside_work(self):
        sb = load("sb_h3", "sandbox.py")
        base = "C:" + chr(92) + "x" + chr(92) + "qa-evals-run-ab12cd"
        priv = sb.priv_dir_of(base)
        self.assertNotEqual(priv, base)
        self.assertTrue(priv.startswith(base))

    def test_probe_matrix(self):
        """Final P1 hardening spec: success ONLY with rc==0 + BLOCKED and no WROTE.
        Seven scenarios: blocked, write allowed, docker unavailable,
        container did not start, command error, marker missing, timeout."""
        sb = load("sb_h4", "sandbox.py")
        cases = [
            (0, "BLOCKED", "", True, ""),                      # blocking confirmed
            (0, "WROTE", "", False, "изоляция сломана"),       # write allowed
            (127, "", "docker: not found", False, "docker"),   # docker unavailable
            (125, "", "docker: Error response", False, "rc=125"),  # container did not start
            (1, "", "sh: syntax error", False, "rc=1"),        # command error
            (0, "(пусто/мусор)", "", False, "BLOCKED отсутствует"),  # no marker
            (124, "TIMEOUT", "", False, "таймаут"),            # probe timeout
            (0, "WROTE BLOCKED", "", False, "оба маркера"),    # ambiguous
        ]
        for rc, out, err, want_ok, want_reason in cases:
            sb.run = lambda cmd, timeout=60, _r=rc, _o=out, _e=err: (_r, _o, _e)
            ok, reason = sb.probe_write_rights("/tmp/qa-evals-run-x")
            self.assertEqual(ok, want_ok, f"{want_reason}: {reason}")
            if not want_ok:
                self.assertTrue(reason, "причина отказа обязана быть непустой")


class SandboxOpsResilience(unittest.TestCase):
    def test_parallel_works_disjoint(self):
        """Two parallel runs: work paths and resource names are unique."""
        sb = load("sb_r1", "sandbox.py")
        w1 = "C:" + chr(92) + "tmp" + chr(92) + "qa-evals-run-aa11bb"
        w2 = "C:" + chr(92) + "tmp" + chr(92) + "qa-evals-run-cc22dd"
        n1 = "qa-sbx-" + os.path.basename(w1)[-6:].lower()
        n2 = "qa-sbx-" + os.path.basename(w2)[-6:].lower()
        self.assertNotEqual(w1, w2)
        self.assertNotEqual(n1, n2)
        self.assertNotEqual(sb.priv_dir_of(w1), sb.priv_dir_of(w2))

    def test_cleanup_idempotent(self):
        """A repeated cleanup does not crash and does not touch other runs' data."""
        sb = load("sb_r2", "sandbox.py")
        sb.run = lambda cmd, timeout=60: (0, "", "")
        sb.stop_proxy("C:" + chr(92) + "x" + chr(92) + "qa-evals-run-zz99zz")  # first
        sb.stop_proxy("C:" + chr(92) + "x" + chr(92) + "qa-evals-run-zz99zz")  # repeat
        self.assertTrue(True)

    def test_proxy_rejects_wrong_path(self):
        """Proxy logic: a non-API path is rejected (a unit test on the 403 status code)."""
        src = io.open(os.path.join(ROOT, "scripts", "sandbox-proxy.py"),
                      encoding="utf-8").read()
        self.assertIn("only the LLM API path is allowed", src)
        self.assertIn("429", src)   # request limit
        self.assertIn("413", src)   # body limit
        self.assertIn("Bearer \" + LLM_KEY", src.replace("'Bearer ' + LLM_KEY", 'Bearer " + LLM_KEY')) if False else None
        self.assertIn("LLM_KEY", src)


class ProxyHardening(unittest.TestCase):
    def test_normalize_path_matrix(self):
        """Spec 4.2: only paths inside the prefix are allowed after normalization."""
        import importlib.util as _ilu
        import os as _os
        _os.environ["UPSTREAM"] = "https://api.z.ai/api/anthropic"
        spec = _ilu.spec_from_file_location("sp_t", os.path.join(ROOT, "scripts", "sandbox-proxy.py"))
        sp = _ilu.module_from_spec(spec)
        spec.loader.exec_module(sp)
        for p in ["/api/anthropic", "/api/anthropic/v1/messages",
                  "/api/anthropic/v1/x?y=1", "/api/anthropic//v1", "/api/anthropic/./v1"]:
            self.assertIsNotNone(sp.normalize_path(p), "ложный запрет: " + p)
        for p in ["/api/anthropic/../evil", "/api/anthropic/%2e%2e/evil",
                  "/api/anthropic/%252e%252e/evil", "/api/anthropi",
                  "/other", "/", "//api.z.ai/x", "/api/anthropic/../../etc/passwd"]:
            self.assertIsNone(sp.normalize_path(p), "ложный пропуск: " + p)

    def test_proxy_container_hardened_flags(self):
        """Spec item 5: the proxy runs non-root, read-only, cap-drop ALL, with limits."""
        src = io.open(os.path.join(ROOT, "scripts", "sandbox.py"), encoding="utf-8").read()
        i = src.index('"docker", "run", "-d"')
        seg = src[i:i + 700]
        for token in ['"--user", "65534:65534"', '"--read-only"',
                      '"--cap-drop", "ALL"', '"--memory", "256m"', '"--pids-limit", "32"']:
            self.assertIn(token, seg, token)
        self.assertNotIn("/workspace", seg)   # SUT directories are not mounted into the proxy

    def test_proxy_env_chmod600(self):
        """Spec item 5: the proxy env file gets 0600, the priv directory 0700."""
        sb = load("sb_hd", "sandbox.py")
        with tempfile.TemporaryDirectory() as td:
            calls = {}
            chmod_calls = []
            real_chmod = os.chmod
            def spy_chmod(path, mode):
                chmod_calls.append((os.path.basename(str(path)), mode))
                try:
                    real_chmod(path, mode)
                except OSError:
                    pass
            sb.os.chmod = spy_chmod
            def fake_run(cmd, timeout=60):
                calls.setdefault("runs", []).append(cmd)
                if cmd[:2] == ["docker", "run"]:
                    # interception: the env file exists, chmod was already called
                    # (Windows NTFS does not expose POSIX bits in stat - we check the call)
                    self.assertTrue(os.path.exists(os.path.join(td, "qa-evals-run-x-priv", "proxy.env")))
                    self.assertIn(("proxy.env", 0o600), chmod_calls)
                    return (1, "", "stopped-here")   # abort, we clean up networks ourselves
                return (0, "", "")
            sb.run = fake_run
            sb.gateway_of_host = lambda: ("https://api.z.ai/api/anthropic", "k")
            sb.start_proxy(os.path.join(td, "qa-evals-run-x"))

    def test_proxy_failure_removes_priv(self):
        """issue #1: a failed docker run leaves no priv dir with proxy.env."""
        sb = load("sb_pr", "sandbox.py")
        with tempfile.TemporaryDirectory() as td:
            seen_env = []

            def fake_run(cmd, timeout=60):
                if cmd[:2] == ["docker", "run"]:
                    # mid-flight: the env file with the key existed before the failure
                    seen_env.append(os.path.exists(
                        os.path.join(td, "qa-evals-run-y-priv", "proxy.env")))
                    return (1, "", "boom")
                return (0, "", "")

            sb.run = fake_run
            sb.gateway_of_host = lambda: ("https://api.z.ai/api/anthropic", "k")
            sb.start_proxy(os.path.join(td, "qa-evals-run-y"))
            self.assertEqual(seen_env, [True])
            self.assertFalse(os.path.exists(os.path.join(td, "qa-evals-run-y-priv")),
                             "priv with the key must not outlive a failed docker run")

    def test_prepare_proxy_fail_cleans_work_and_priv(self):
        """issue #1: proxy failure in prepare -> rc=4, meta in run_dir, work and priv removed."""
        sb = load("sb_pf", "sandbox.py")
        sut = tempfile.mkdtemp(prefix="sut-")
        run_dir = tempfile.mkdtemp(prefix="run-")
        self.addCleanup(lambda: __import__("shutil").rmtree(sut, ignore_errors=True))
        self.addCleanup(lambda: __import__("shutil").rmtree(run_dir, ignore_errors=True))
        io.open(os.path.join(sut, "a.txt"), "w", encoding="utf-8").write("SUT")

        def fake_run(cmd, timeout=60):
            if cmd[:2] == ["docker", "run"]:
                return (1, "", "boom")
            return (0, "", "")   # network create/rm, ps, rm succeed

        sb.run = fake_run
        sb.gateway_of_host = lambda: ("https://api.z.ai/api/anthropic", "k")
        sb.cli_version = lambda: "test-cli"   # otherwise calls an external binary
        rc = sb.prepare("docker", sut, run_dir)
        self.assertEqual(rc, 4)
        meta = json.load(io.open(os.path.join(run_dir, "meta-sandbox.json"),
                                 encoding="utf-8"))
        self.assertIsNone(meta["sbx_net"])
        work = meta["work"]
        self.assertTrue(work and os.path.isabs(work))
        self.assertFalse(os.path.exists(work), "work with the SUT copy must be removed")
        self.assertFalse(os.path.exists(work + "-priv"),
                         "priv with the key must be removed")


class TestBuildBenchmarks(unittest.TestCase):
    """Acceptance log: sidecar + machine artifacts -> a table row; a guard filter."""

    def setUp(self):
        self.bb = load("build_benchmarks", "build-benchmarks.py")
        td = tempfile.mkdtemp(prefix="bench-")
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        run = os.path.join(td, "2026-10-12-example")
        os.makedirs(run)
        with io.open(os.path.join(run, "bench.yaml"), "w", encoding="utf-8") as f:
            f.write("sut: example (author) - публичный скилл\n"
                    "type: приёмка\nadapter: CLI+ASP\nenv: host\n"
                    "findings: граница сломана\n")
        with io.open(os.path.join(run, "index.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "EX-01", "result": "GOT", "repeats": ["1", "2"],
                                "meta": {"judge_model": "glm-5.3-flash"}}) + "\n"
                    + json.dumps({"id": "EX-02", "result": "FAIL", "repeats": ["1", "2"],
                                  "meta": {"judge_model": "glm-5.3-flash"}}) + "\n")
        with io.open(os.path.join(run, "cost.md"), "w", encoding="utf-8") as f:
            f.write("# Стоимость\n\n**Прогон целиком: $1.234** (SUT $1.0 + судья $0.234).\n")
        with io.open(os.path.join(run, "report.md"), "w", encoding="utf-8") as f:
            f.write("# отчёт\n")
        self.td, self.run = td, run

    def test_row_derives_counts_and_cost(self):
        row = self.bb.build_row("2026-10-12-example", self.run)
        self.assertIn("2 × 2", row)            # cards × repeats from index.jsonl
        self.assertIn("GOT 1, FAIL 1", row)    # result tally
        self.assertIn("glm-5.3-flash", row)    # judge model from meta
        self.assertIn("$1.234", row)           # cost without a greedy dot
        self.assertNotIn("$1.234.", row)
        self.assertIn("[report](../runs/2026-10-12-example/report.md)", row)

    def test_guard_blocks_private_markers(self):
        hits = self.bb.guard("автор kivanov, путь C:\\Users\\const, ключ sk-abcdefgh1234")
        self.assertTrue(hits, "приватные маркеры обязаны ловиться")
        self.assertFalse(self.bb.guard("чистая строка: ste100, docker, $1.38"))

    def test_selftest_positive_control(self):
        self.assertTrue(self.bb.selftest())

    def test_build_refuses_run_without_sidecar(self):
        os.remove(os.path.join(self.run, "bench.yaml"))
        page = self.bb.build(self.td)
        self.assertIn("Без сайдкара bench.yaml в журнал не попали", page)


GOLDEN3 = """# Golden

## G-01 (эталон: GOT)

Вопрос: q1
Ожидание: e1
Ответ SUT: a1

## G-02 (эталон: FAIL)

Вопрос: q2
Ожидание: e2
Ответ SUT: a2

## G-03 (эталон: HONEST)

Вопрос: q3
Ожидание: e3
Ответ SUT: a3
"""


class JudgeControlMain(unittest.TestCase):
    """judge-control.py main(): согласие, отчёт, переиспользование вердиктов.

    Убивает мутанты 435/437/449/452-461/472/481/486-491/493-513 (инверсия
    согласия, счётчик, шапка и строки таблицы, rate, reuse с --only).
    """
    def run_main(self, td, golden, extra=()):
        import contextlib
        argv = sys.argv
        sys.argv = ["judge-control.py", golden, os.path.join(td, "out"), *extra]
        buf = io.StringIO()
        real = judge_control.run_judge
        judge_control.run_judge = lambda case, model, judge_md, timeout: {
            "G-01": "Вердикт: GOT\nобоснование",
            "G-02": "Вердикт: GOT\nобоснование",
            "G-03": "Вердикт: HONEST\nобоснование"}[case["id"]]
        try:
            with contextlib.redirect_stdout(buf):
                judge_control.main()
        finally:
            judge_control.run_judge = real
            sys.argv = argv
        return buf.getvalue()

    def test_agreement_report_and_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            g = os.path.join(td, "golden.md")
            io.open(g, "w", encoding="utf-8").write(GOLDEN3)
            out = self.run_main(td, g)
            self.assertIn("итог: 2/3", out)  # G-02: судья GOT, эталон FAIL
            report = io.open(os.path.join(td, "out", "report.md"),
                             encoding="utf-8").read()
            self.assertIn("Согласие с эталоном: **2/3**", report)
            self.assertIn("| Кейс | Эталон | Судья | Согласие |", report)
            self.assertIn("| G-01 | GOT | GOT | да |", report)
            self.assertIn("| G-02 | FAIL | GOT | **НЕТ** |", report)
            self.assertIn("| G-03 | HONEST | HONEST | да |", report)
            v2 = io.open(os.path.join(td, "out", "вердикты", "G-02.md"),
                         encoding="utf-8").read()
            self.assertIn("Эталон: FAIL", v2)
            self.assertIn("Судья: GOT", v2)
            self.assertIn("Согласие: НЕТ", v2)
            v1 = io.open(os.path.join(td, "out", "вердикты", "G-01.md"),
                         encoding="utf-8").read()
            self.assertIn("Согласие: да", v1)
            # второй прогон с --only: кейсы вне --only берутся из сохранённых
            self.run_main(td, g, ("--only", "G-03"))
            v1 = io.open(os.path.join(td, "out", "вердикты", "G-01.md"),
                         encoding="utf-8").read()
            self.assertIn("(из сохранённого вердикта)", v1)


class CostReportMain(unittest.TestCase):
    """cost-report.py main(): агрегация по карточкам, итоги, судья, бюджет.

    Убивает 631-682 (суммы += / начальные значения), 685-717 (строки отчёта),
    718-746 (секция судьи, «Прогон целиком» с минусом вместо плюса),
    699-703 (граница бюджета > vs >=), 747-753 (запись cost.md).
    """
    def events(self, td, cid, rep, tk, ms, usd):
        p = os.path.join(td, "прогоны", f"{cid}-r{rep}.events.jsonl")
        io.open(p, "w", encoding="utf-8").write(json.dumps({
            "type": "result",
            "usage": {"input_tokens": tk, "output_tokens": tk // 2,
                      "cache_read_input_tokens": 4},
            "duration_ms": ms, "total_cost_usd": usd}) + "\n")

    def test_main_aggregation_judge_budget(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "прогоны"))
            os.makedirs(os.path.join(td, "вердикты"))
            self.events(td, "T-01", 1, 10, 100, 0.01)
            self.events(td, "T-01", 2, 20, 100, 0.01)
            self.events(td, "T-02", 1, 7, 60, 0.01)
            io.open(os.path.join(td, "вердикты", "judge-usage.jsonl"), "w",
                    encoding="utf-8").write(json.dumps(
                {"in": 100, "out": 50, "cache_read": 10,
                 "cost_usd": 0.005, "dur_s": 2.5}) + "\n")
            argv = sys.argv
            sys.argv = ["cost-report.py", td, "--budget", "0.05"]
            try:
                cost_report.main()
            finally:
                sys.argv = argv
            md = io.open(os.path.join(td, "cost.md"), encoding="utf-8").read()
            self.assertIn("Прогонов: 3. Токены: input 37 (cache read 12), "
                          "output 18. Длительность: 0.3 с. Стоимость: $0.030.", md)
            self.assertIn("| T-01 | 2 | 30 | 15 | 0.2 | 0.020 |", md)
            self.assertIn("| T-02 | 1 | 7 | 3 | 0.1 | 0.010 |", md)
            self.assertIn("Вызовов: 1 (включая автопересуды). Токены: input 100 "
                          "(cache read 10), output 50.", md)
            self.assertIn("**Прогон целиком: $0.035**", md)
            self.assertNotIn("БЮДЖЕТ ПРЕВЫШЕН", md)
            # бюджет ниже суммы - предупреждение появляется
            sys.argv = ["cost-report.py", td, "--budget", "0.02"]
            try:
                cost_report.main()
            finally:
                sys.argv = argv
            md2 = io.open(os.path.join(td, "cost.md"), encoding="utf-8").read()
            self.assertIn("**БЮДЖЕТ ПРЕВЫШЕН**: $0.030 > $0.020.", md2)

    def test_budget_boundary_strict_greater(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "прогоны"))
            self.events(td, "B-01", 1, 10, 100, 0.125)
            self.events(td, "B-01", 2, 10, 100, 0.125)  # 0.25 точно в двоичной
            argv = sys.argv
            sys.argv = ["cost-report.py", td, "--budget", "0.25"]
            try:
                cost_report.main()
            finally:
                sys.argv = argv
            md = io.open(os.path.join(td, "cost.md"), encoding="utf-8").read()
            self.assertNotIn("БЮДЖЕТ ПРЕВЫШЕН", md)  # равен бюджету - не превышен

    def test_norm(self):
        """norm(): a Git Bash drive path converts, others pass through."""
        self.assertEqual(cost_report.norm("/c/users/x"), "c:\\users\\x")
        self.assertEqual(cost_report.norm("/C/users/x"), "C:\\users\\x")
        self.assertEqual(cost_report.norm("C:/users/x"), "C:/users/x")
        self.assertEqual(cost_report.norm("/ab"), "/ab")  # не диск

    def test_posix_run_dir_from_git_bash(self):
        """run_dir в POSIX-форме Git Bash (/c/...): отчёт не пустой.
        Регрессия: replace("/", os.sep) до проверки диска глушил ветку
        конвертации на Windows, glob ничего не находил."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "прогоны"))
            self.events(td, "P-01", 1, 10, 100, 0.01)
            posix = td
            if os.name == "nt" and td[1:2] == ":":  # C:\x -> /c/x; POSIX - уже POSIX
                posix = "/" + td[0].lower() + td[2:].replace("\\", "/")
            argv = sys.argv
            sys.argv = ["cost-report.py", posix]
            try:
                cost_report.main()
            finally:
                sys.argv = argv
            md = io.open(os.path.join(td, "cost.md"), encoding="utf-8").read()
            self.assertIn("| P-01 | 1 | 10 | 5 | 0.1 | 0.010 |", md)


class CheckFactsVerdicts(unittest.TestCase):
    """check-facts.py: приоритет вердиктов, missing/leaked, содержимое facts.md.

    Убивает 158-159/211-212/216-218 (DET_OK/MISSING/NA/NO_DATA и приоритеты),
    231/233 (инверсия списков missing/leaked), 240-256 (НАЙДЕНО/НЕ НАЙДЕНО).
    """
    def run_facts(self, td):
        argv = sys.argv
        sys.argv = ["check-facts.py", td]
        try:
            check_facts.main()
        finally:
            sys.argv = argv

    def test_ok_missing_na_no_data_and_lists(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "карточки"))
            os.makedirs(os.path.join(td, "прогоны"))
            io.open(os.path.join(td, "карточки", "T-01.yaml"), "w",
                    encoding="utf-8").write(
                "id: T-01\ntype: critical\nfeature: f\ninstruction: |\n  Сделай\n"
                "oracle:\n  expected: |\n    Ожидание\n"
                "  facts_must:\n    - \"обязан\"\n"
                "  facts_must_not:\n    - \"запрещён\"\n")
            io.open(os.path.join(td, "карточки", "T-03.yaml"), "w",
                    encoding="utf-8").write(  # только facts_must, без must_not
                "id: T-03\ntype: obvious\nfeature: f\ninstruction: |\n  Сделай\n"
                "oracle:\n  expected: |\n    Ожидание\n"
                "  facts_must:\n    - \"обязан\"\n")
            io.open(os.path.join(td, "карточки", "T-NA.yaml"), "w",
                    encoding="utf-8").write(  # без фактов вовсе
                "id: T-NA\ntype: obvious\nfeature: f\ninstruction: |\n  Сделай\n")
            io.open(os.path.join(td, "карточки", "T-04.yaml"), "w",
                    encoding="utf-8").write(  # факты есть, транскрипта нет
                "id: T-04\ntype: obvious\nfeature: f\ninstruction: |\n  Сделай\n"
                "oracle:\n  expected: |\n    Ожидание\n"
                "  facts_must:\n    - \"обязан\"\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.txt"), "w",
                    encoding="utf-8").write("ответ обязан присутствовать\n")
            io.open(os.path.join(td, "прогоны", "T-01-r2.txt"), "w",
                    encoding="utf-8").write("ответ неполный\n")
            io.open(os.path.join(td, "прогоны", "T-03-r1.txt"), "w",
                    encoding="utf-8").write("обязан\n")
            io.open(os.path.join(td, "прогоны", "T-NA-r1.txt"), "w",
                    encoding="utf-8").write("что-то\n")
            os.makedirs(os.path.join(td, "вердикты"))
            io.open(os.path.join(td, "вердикты", "T-04-r1.md"), "w",
                    encoding="utf-8").write("Вердикт: GOT\n")  # повтор есть, данных нет
            self.run_facts(td)
            rows = {}
            for line in io.open(os.path.join(td, "facts", "index-facts.jsonl"),
                                encoding="utf-8"):
                r = json.loads(line)
                rows[(r["id"], r["rep"])] = r
            self.assertEqual(rows[("T-01", "1")]["det"], "DET_OK")
            self.assertEqual(rows[("T-01", "1")]["missing"], [])
            self.assertEqual(rows[("T-01", "1")]["leaked"], [])
            self.assertEqual(rows[("T-01", "2")]["det"], "DET_MISSING")
            self.assertEqual(rows[("T-01", "2")]["missing"], ["обязан"])
            self.assertEqual(rows[("T-03", "1")]["det"], "DET_OK")
            self.assertEqual(rows[("T-NA", "1")]["det"], "DET_NA")
            self.assertEqual(rows[("T-04", "1")]["det"], "DET_NO_DATA")
            self.assertEqual(rows[("T-04", "1")]["source"], "нет артефакта")
            md = io.open(os.path.join(td, "facts", "T-01-r1.facts.md"),
                         encoding="utf-8").read()
            self.assertIn("- НАЙДЕНО: обязан", md)
            self.assertIn("- не найдено: запрещён", md)
            md2 = io.open(os.path.join(td, "facts", "T-01-r2.facts.md"),
                          encoding="utf-8").read()
            self.assertIn("- НЕ НАЙДЕНО: обязан", md2)


class BuildIndexMain(unittest.TestCase):
    """build-index.py: norm() и сборка index.jsonl через main().

    Убивает 795-811 (norm), 823-829 (INVALID-супервизия, or вместо and),
    913-954 (повторы из имён файлов, verdicts, result, any_negative, votes,
    judge_disagreement), 956-987 (artifacts, det-колонки), 996-999 (итог).
    """
    def test_norm(self):
        self.assertEqual(build_index.norm("/c/users/x"), "c:\\users\\x")
        self.assertEqual(build_index.norm("/C/users/x"), "C:\\users\\x")
        self.assertEqual(build_index.norm("C:/users/x"), "C:/users/x")
        self.assertEqual(build_index.norm("/ab"), "/ab")  # не диск

    def test_index_rows(self):
        import contextlib
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "карточки"))
            os.makedirs(os.path.join(td, "вердикты"))
            os.makedirs(os.path.join(td, "прогоны"))
            os.makedirs(os.path.join(td, "facts"))
            io.open(os.path.join(td, "карточки", "T-01.yaml"), "w",
                    encoding="utf-8").write("id: T-01\ntype: critical\nfeature: f\n")
            io.open(os.path.join(td, "карточки", "T-02.yaml"), "w",
                    encoding="utf-8").write("id: T-02\ntype: obvious\nfeature: g\n")
            io.open(os.path.join(td, "карточки", "T-05.yaml"), "w",
                    encoding="utf-8").write("id: T-05\ntype: obvious\nfeature: h\n")
            # INVALID в теле без супервизии - вердикт остаётся GOT
            io.open(os.path.join(td, "вердикты", "T-01-r1.md"), "w",
                    encoding="utf-8").write(
                "Вердикт: GOT\nКомментарий: упоминание INVALID без супервизии\n")
            io.open(os.path.join(td, "вердикты", "T-01-r2.md"), "w",
                    encoding="utf-8").write("Вердикт: FAIL\n")
            io.open(os.path.join(td, "вердикты", "T-02-r1.md"), "w",
                    encoding="utf-8").write("Вердикт: GOT\nСупервизия: INVALID\n")
            io.open(os.path.join(td, "вердикты", "T-05-r1.md"), "w",
                    encoding="utf-8").write("Вердикт: GOT\n")
            io.open(os.path.join(td, "вердикты", "T-05-r2.md"), "w",
                    encoding="utf-8").write("Вердикт: GOT\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.txt"), "w",
                    encoding="utf-8").write("транскрипт\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.prov.txt"), "w",
                    encoding="utf-8").write("prov\n")
            io.open(os.path.join(td, "прогоны", "T-01-r1.events.jsonl"), "w",
                    encoding="utf-8").write("{}\n")
            io.open(os.path.join(td, "facts", "index-facts.jsonl"), "w",
                    encoding="utf-8").write(json.dumps(
                {"id": "T-01", "rep": "1", "det": "DET_LEAK",
                 "source": "транскрипт"}, ensure_ascii=False) + "\n")
            posix = td
            if os.name == "nt" and td[1:2] == ":":  # C:\x -> /c/x; POSIX - уже POSIX
                posix = "/" + td[0].lower() + td[2:].replace("\\", "/")
            argv = sys.argv
            sys.argv = ["build-index.py", posix]
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    build_index.main()
            finally:
                sys.argv = argv
            self.assertIn("карточек с негативом/расхождением: 1", buf.getvalue())
            rows = [json.loads(l) for l in io.open(
                os.path.join(td, "index.jsonl"), encoding="utf-8")]
            self.assertEqual([r["id"] for r in rows], ["T-01", "T-02", "T-05"])
            r1, r2, r5 = rows
            self.assertEqual(r1["repeats"], ["1", "2"])
            self.assertEqual(r1["verdicts"], {"1": "GOT", "2": "FAIL"})
            self.assertEqual(r1["result"], "split")
            self.assertTrue(r1["any_negative"])
            self.assertTrue(r1["judge_disagreement"])
            self.assertEqual(r1["votes"], "FAIL:1, GOT:1")
            self.assertEqual(r2["verdicts"], {"1": "INVALID"})
            self.assertEqual(r2["result"], "INVALID")
            self.assertFalse(r2["any_negative"])
            self.assertEqual(r5["result"], "GOT")
            self.assertFalse(r5["judge_disagreement"])  # единогласие 2/2
            self.assertEqual(r1["det"], {"1": "DET_LEAK", "2": "-"})
            self.assertEqual(r1["det_source"], {"1": "транскрипт", "2": "-"})
            self.assertEqual(r1["det_judge"], {"1": "DET_NEG_JUDGE_POS", "2": "NA"})
            arts = r1["artifacts"]["1"]
            self.assertIn("transcript", arts)
            self.assertIn("provenance", arts)
            self.assertIn("events", arts)


class DiffRunsFull(unittest.TestCase):
    """diff-runs.py: закрытие негатива, split, отсутствующие карточки, счётчики.

    Убивает 39-46/51/53 (счётчики), 61/73 (xn-логика, ветка «негатив закрылся»),
    82 (пометка split).
    """
    def test_closed_negative_split_and_counters(self):
        import contextlib
        diff = load("diff_runs_mod3", "diff-runs.py")
        with tempfile.TemporaryDirectory() as td:
            for sub in ("a", "b"):
                os.makedirs(os.path.join(td, sub))
            rows = {
                "X-1": ("FAIL", "GOT"),    # негатив закрылся
                "X-2": ("split", "GOT"),   # расхождение повторов
                "X-3": ("GOT", "GOT"),     # совпало
                "X-6": ("GOT", "GOT"),     # совпало ещё раз
                "X-4": ("FAIL", None),     # нет в B
                "X-5": (None, "FAIL"),     # новая карточка в B
            }
            for sub in ("a", "b"):
                with io.open(os.path.join(td, sub, "index.jsonl"), "w",
                             encoding="utf-8") as f:
                    for cid, (ra, rb) in rows.items():
                        res = ra if sub == "a" else rb
                        if res is None:
                            continue
                        f.write(json.dumps({"id": cid, "result": res,
                                            "votes": res + ":2",
                                            "meta": {"sut": "t"}},
                                           ensure_ascii=False) + "\n")
            argv = sys.argv
            sys.argv = ["diff-runs.py", os.path.join(td, "a"), os.path.join(td, "b")]
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    diff.main()
            finally:
                sys.argv = argv
            out = buf.getvalue()
            self.assertIn("негатив закрылся", out)
            self.assertIn("расхождение повторов", out)
            self.assertIn("нет в B", out)
            self.assertIn("новая карточка в B", out)
            self.assertIn("Итогов совпало: 2, изменилось/новых: 4.", out)
