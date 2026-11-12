# Golden Set From Live Acceptance Runs (Growing)

Cases land here from `runs/<дата>-<sut>/golden-candidates.md` after the owner reviews them. The script `scripts/collect-feedback.py` prepares a candidate from a run fact plus human feedback (feedback.yaml). The owner moves it here by hand. A human look at a case before it enters the references is mandatory.

Rules:

- The reference is the verdict of a human on the run fact (an approval or a correction of the judge result). The verdict of the judge itself never becomes the reference.
- IDs of live cases start at G-201 (the manual set is G-01..G-08, TruthfulQA is G-101..G-145).
- Agreement between the judge and the human on live cases is the main working metric of the judge. The material is real, unlike dataset material (the dataset cases are simpler).

A control run over all sets at once:

```
python scripts/judge-control.py "runs/2026-10-09-judge-calibration-aon/golden.md,runs/2026-10-11-judge-control-tq/golden-truthfulqa.md,knowledge/golden-live.md" <out-dir>
```

---

Cases: 0. The first ones will appear after the first acceptance run with feedback.yaml.
