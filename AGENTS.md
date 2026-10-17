# AGENTS.md

Guidance for coding agents working in this repository.

## What this repo is

qa-agent-evals is a Claude Code plugin that runs acceptance testing for LLM systems
(a SUT, "system under test": plugins, skills, bots). An analyst subagent profiles
the SUT, scenario cards are generated and approved by a human, executor subagents
play user roles against the SUT in an isolated environment, a deterministic grep
layer checks facts before a judge subagent (running on a different model) issues
verdicts, and reports go back to the human.

Docs are Russian-first: `README.md` (RU) · `README.en.md` (EN) · `docs/spec.md` ·
`docs/architecture.md` (+ interactive `docs/architecture.html`).

## Layout

- `skills/acceptance-test/SKILL.md` — orchestrator instructions, five phases A–E
- `agents/` — role definitions: analyst, role-user (executor), judge
- `knowledge/` — taxonomy (5 card types), adapters and environment isolation,
  oracle (verdict scale), sandbox levels, golden control sets
- `scripts/` — deterministic machinery: `run-cards.sh` (headless runs),
  `parse-events.py`, `check-facts.py` (fact grep before the judge),
  `judge-batch.py` / `judge-control.py`, `sandbox.py` + `sandbox-proxy.py`
  (docker isolation, fail-closed), `sec-checks.py`
- `runs/` — acceptance artifacts (cards, transcripts, facts, verdicts, reports).
  Case policy: third-party runs are published only with the owner's consent —
  ask before committing any.
- `examples/evil-plugin` — deliberately malicious plugin used by security checks;
  run it only inside the docker sandbox.
- `tests/` — unit tests and live proxy tests.

## Commands

- Unit tests: `python -m unittest tests.test_scripts -v`
- Live proxy tests (dummy key, no LLM calls): `python -m unittest tests.test_proxy_live -v`
- Security suite: `python scripts/sec-checks.py docker --out runs/sec-ci`
- CI (`.github/workflows/security.yml`) runs the above on ubuntu. FAIL or ERROR
  fails the pipeline; SKIP is not PASS.

## Conventions

- Working language for docs and commits: Russian. RU is canonical; keep
  `README.en.md` in sync when changing `README.md`.
- Verdict scales are fixed — never invent new statuses:
  judge: GOT / HONEST / PARTIAL / FAIL / ATTACK_PASSED / INVALID;
  det layer: DET_OK / DET_MISSING / DET_LEAK / DET_NA / DET_NO_DATA.
- Oracles are written before the run and are never edited after it. Do not
  "fix" a card's expectations to match observed answers.
- Never print or commit secrets (gateway keys, tokens). The real LLM key lives
  only in the sandbox proxy environment.
- Scenario cards and the profile are approved by a human before any run; keep
  that gate intact in code and docs.

## Before you finish

Run the unit tests; if you touched sandbox or proxy code, run the security
suite. Keep public commits free of private run data.
