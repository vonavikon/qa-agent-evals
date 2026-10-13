# qa-agent-evals

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[RU](README.md) · **EN**

A Claude Code plugin for acceptance testing of LLM systems with role-playing subagents. You point it at the system under test. The plugin profiles it, generates scenario cards of five types, runs them through an isolated adapter, hands down verdicts with a judge running on a different model, and assembles a report with pass rates and a coverage matrix.

Three things separate it from running prompts by hand: every card has its expected answer written down before the run (the oracle), a machine layer grep-checks facts before the judge ever sees the answer, and the judge itself runs on a different model and is calibrated against a control sample with known-correct verdicts. Verdicts are asymmetric: FAIL proves a defect, GOT only means "not refuted".

![How it works: the plugin studies the system, writes tasks, an actor plays the user, an untrusted plugin runs behind glass, a judge scores the answers, the report shows the result](assets/concept.en.gif)

*A pet project: understand acceptance evals by building a working instrument and running it on itself.*

## How it works

```
[A: analyze SUT] → [B: adapter + smoke test] → [C: scenario cards] → [D: runs × N repeats] → [E: report]
```

- **Analyst** (step A) reads the SUT and builds a profile: feature registry, risk map, attack surface, ambiguity points, adapter options.
- **Cards** (step C) come in five types: obvious (happy path), convoluted (multi-turn ambiguity), critical (damage zones), adversarial (one attack per card), out-of-scope (does the SUT admit what it doesn't know). Format: YAML with a persona, an instruction, an oracle (required and forbidden facts + prose expectation), and a budget.
- **The role-user actor** plays the persona against the SUT through the adapter. For CLI systems that is an isolated headless session: neutral working directory, no access to the owner's skills or MCP. A browser adapter (Playwright surface) exists for web SUTs — see `knowledge/adapters.md`.
- **The machine layer** (`scripts/check-facts.py`) runs before the judge: it greps the oracle markers over the transcripts and over the files the SUT wrote itself. What the machine proves, the judge does not re-adjudicate — and a self-contradiction (positive verdict over a proven violation) triggers an automatic re-judge.
- **The judge** runs on a different model and works in two steps: first it scores the answer against the oracle without knowing the scenario's intent, then it supervises the actor. Before each acceptance run it is calibrated on a control sample: hand-written cases, open-dataset cases (TruthfulQA, Apache 2.0; HH-RLHF attacks, MIT), and a growing live section fed by human feedback.
- **Feedback loop (Growing-Golden)**: after a run the owner confirms or corrects verdicts — via a clickable markup page or plain chat text. Only a human verdict ever becomes an etalon; the judge's own verdict never does.
- **Report**: repeat verdicts and votes, a feature-by-type coverage matrix, findings with priorities, root-cause analysis, run limitations, and the run's cost in tokens and dollars (SUT side and judge side measured separately).

The full map — isolation, context hierarchy, responsibility matrix, and an interactive version where every node shows which file or parameter moves it — is in [docs/architecture.md](docs/architecture.md). Interactive: [docs/architecture.html](docs/architecture.html), open it locally in a browser.

## Execution isolation (v0.5.0)

The tested plugin runs at one of two isolation levels, recorded in every run report:

- **host** (default): no Docker, no extra dependencies. Environment isolation as before: env allowlist, empty MCP, neutral working directory, tamper detector. There is no filesystem or network barrier — the report honestly marks this level "not a sandbox". Good enough for public plugins from known sources.
- **docker** (for untrusted material): a container mounting only the work directory and a copy of the plugin, read-only root, non-root user, resource limits; the only way out is an internal proxy container to the LLM gateway. If Docker is unavailable, the run refuses to start (fail-closed) — no silent fallback to the unsafe mode.

Verified in live runs against our own examples/evil-plugin (a plugin that never refuses): under docker, reading a host secret, network access, writing outside the workspace, and evidence tampering were all blocked; on host, the same attacks are honestly recorded as level risks. Side finding: gateway server-side tools (web reading) deliver content into a closed network — banned in docker mode.

Hardened in v0.5.1: plugin sources are mounted read-only with a boot-time write probe (writable means the run is refused); the real gateway key lives only inside the proxy container while the tested process gets a placeholder; the proxy accepts LLM API paths only and enforces request limits. An automated security suite (`python scripts/sec-checks.py docker`) runs all six checks in one command and in CI — green on both Windows and the Linux runner (runs/2026-10-13-sec/).

## Quick start

Requirements: Claude Code, bash, python3. On Windows use Git Bash or WSL.

Install the plugin (with `--plugin-dir <path>` at session start or via a marketplace), open a session in the tested system's directory, and write:

```
run acceptance testing on <path to SUT>
```

The pipeline walks steps A–E on its own and stops exactly once, before the card review: it shows you the cards and waits for your approval.

## Contents

```
.claude-plugin/plugin.json    manifest
skills/acceptance-test/       the five-step pipeline (orchestrator)
agents/analyst.md             SUT profiler
agents/role-user.md           role-playing actor
agents/judge.md               two-step judge (pinned to a different model)
knowledge/taxonomy.md         5 card types, patterns, reference YAML
knowledge/adapters.md         CLI adapter, isolation, browser adapter (Playwright)
knowledge/oracle.md           oracles, verdict scale, report templates
scripts/run-cards.sh          CLI runner for single-turn cards with repeats
scripts/run-integrity.sh      tamper detector for the run directory
scripts/parse-events.py       events.jsonl parser: answers, provenance, diagnostics
scripts/check-facts.py        machine fact-checker (transcripts + SUT-written files)
scripts/judge-batch.py        judge batch + automatic re-judge of self-contradictions
scripts/judge-control.py      judge control sample (golden sets)
scripts/collect-feedback.py   human feedback: markup page + golden candidates
scripts/build-index.py        machine-readable run index (index.jsonl)
scripts/cost-report.py        run cost in tokens/time/dollars (SUT + judge)
scripts/judge-metrics.py      judge agreement metrics over corpora
scripts/diff-runs.py          two-run comparison (a view, not a criterion)
scripts/make-golden-*.py      converters from open datasets (TruthfulQA, HH-RLHF)
tests/                        unit tests for the pipeline scripts
runs/                         self-acceptance and third-party run artifacts
```

## Status

v0.5.0. Execution isolation (host/docker) landed with live evil-plugin proof; infra failures are now separated from plugin defects (BLOCKED/ERROR statuses).

v0.4.1. The pipeline ran on itself four times (self-acceptance v1–v4, reports in [runs/](runs/2026-10-08-qa-agent-evals-selftest/report.md)): v1 found 3 real defects (scope boundaries, promising the unimplemented, approval control); each next run verified the previous fixes and hunted for new ones.

Then third-party systems: a public prose-editing skill (two runs with a version comparison, [runs/](runs/2026-10-11-stop-slop-r2/report.md)), a slide generator with a content-borne injection, a technical-English rewriting skill, the classic 2048 game through the browser adapter (a deterministic non-LLM SUT), and systems from a closed perimeter (details withheld). Those runs grew v0.3–v0.4: the machine fact layer (grep-caught leaks, including SUT-written files), the judge control sample from open datasets (TruthfulQA 45/45; HH-RLHF attacks), the Growing-Golden feedback loop with a clickable markup page, automatic re-judging of self-contradictions, and measured run economics — a typical acceptance run costs $0.6–1.8 on the SUT side plus roughly $0.4 per judge call, because a judge CLI call carries ~75K tokens of session preamble.

Not working yet: only the CLI and browser adapters are implemented; isolation cuts skill invocation but not knowledge of the skills' existence; the judge is wired up manually (explicit `--model` or the owner's choice at step B), because the agent `model` field does not work in every environment.

Spec: [docs/spec.md](docs/spec.md), plan: [docs/plan.md](docs/plan.md).
