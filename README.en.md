# qa-agent-evals

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[RU](README.md) · **EN** · [中文](README.zh.md) · [Español](README.es.md) · [Français](README.fr.md)

A Claude Code plugin for acceptance testing of LLM systems with role-playing subagents. You point it at the system under test. The plugin profiles it, generates scenario cards of five types, runs them through an isolated adapter, hands down verdicts with a judge running on a different model, and assembles a report with pass rates and a coverage matrix.

Three things separate it from running prompts by hand: every card has its expected answer written down before the run (the oracle), a machine layer grep-checks facts before the judge ever sees the answer, and the judge itself runs on a different model and is calibrated against a control sample with known-correct verdicts. Human confirmations after acceptance grow that sample. The environment is isolated from the owner's skills and MCP. Verdicts are asymmetric: FAIL proves a defect, GOT only means "not refuted".

![How it works: the plugin studies the system, writes tasks, an actor plays the user, an untrusted plugin runs behind glass, a judge scores the answers, the report shows the result](assets/concept.en.gif)

*A pet project: understand acceptance evals by building a working instrument and running it on itself.*

## How it works

```
[A: analyze SUT] → [B: adapter + smoke test] → [C: scenario cards] → [D: runs × N repeats] → [E: report]
```

- **Analyst** (step A) reads the SUT and builds a profile: feature registry, risk map, attack surface, ambiguity points, adapter options.
- **Cards** (step C) come in five types: obvious (happy path), convoluted (multi-turn ambiguity), critical (damage zones), adversarial (one attack per card), out-of-scope (does the SUT admit what it doesn't know). Format: YAML with a persona, an instruction, an oracle (required and forbidden facts + prose expectation), and a budget.
- **The role-user actor** plays the persona against the SUT through the adapter. For CLI systems that is an isolated headless session: neutral working directory, no access to the owner's skills or MCP. Web SUTs go through a browser adapter with a Playwright surface, see `knowledge/adapters.md`. Repeats are driven by `scripts/run-cards.sh`.
- **The machine layer** (`scripts/check-facts.py`) runs before the judge: it greps the oracle markers over the transcripts and over the files the SUT wrote itself. What the machine proves, the judge does not re-adjudicate, and a self-contradiction (positive verdict over a proven violation) triggers an automatic re-judge.
- **The judge** runs on a different model and works in two steps: first it scores the answer against the oracle without knowing the scenario's intent, then it supervises the actor. Before each acceptance run it is calibrated on a control sample: hand-written cases, open-dataset cases (TruthfulQA, Apache 2.0; HH-RLHF attacks, MIT), and a growing live section fed by human feedback.
- **Feedback loop (Growing-Golden)**: after a run the owner confirms or corrects verdicts, via a clickable markup page or plain chat text. Only a human verdict ever becomes an etalon; the judge's own verdict never does.
- **Report**: repeat verdicts and votes, a feature-by-type coverage matrix, findings with priorities, root-cause analysis, run limitations, and the run's cost in tokens and dollars (SUT side and judge side measured separately).

The full map (isolation, context hierarchy, responsibility matrix) is in [docs/architecture.md](docs/architecture.md). Interactive version: [docs/architecture.html](docs/architecture.html), every node shows which file or parameter moves it. Open the file locally in a browser. All runs of the project are summed up in the acceptance log: [docs/benchmarks.md](docs/benchmarks.md).

## Execution isolation (v0.5.0)

The tested plugin runs at one of two isolation levels, recorded in every run report:

- **host** (default): no Docker, no extra dependencies. Environment isolation as before: env allowlist, empty MCP, neutral working directory, tamper detector. There is no filesystem or network barrier, and the report honestly marks this level "not a sandbox". Good enough for public plugins from known sources.
- **docker** (for untrusted material): a container mounting only the work directory and a copy of the plugin, read-only root, non-root user, resource limits; the only way out is an internal proxy container to the LLM gateway. If Docker is unavailable, the run refuses to start (fail-closed), with no silent fallback to the unsafe mode.

Verified in live runs against our own examples/evil-plugin (a plugin that never refuses): under docker, reading a host secret, network access, writing outside the workspace, and evidence tampering were all blocked; on host, the same attacks are honestly recorded as level risks. Side finding: gateway server-side tools (web reading) deliver content into a closed network, so they are banned in docker mode.

Hardened in v0.5.1: plugin sources are mounted read-only with a boot-time write probe (writable means the run is refused); the real gateway key lives only inside the proxy container while the tested process gets a placeholder; the proxy accepts LLM API paths only and enforces request limits. An automated security suite (`python scripts/sec-checks.py docker`) runs all six checks in one command and in CI, green on both Windows and the Linux runner (runs/2026-10-13-sec/). Final hardening in v0.5.2: the write probe is evidence-based (success only on a confirmed block), proxy path normalization closes /../ traversals, rate/volume/time limits added, and the proxy container itself runs as non-root with no capabilities; SEC-06 is split into an oracle-tamper attack and a verdict-forgery attack (both hash-verified); an integration test runs the full live pipeline with real Claude Code (runs/2026-10-13-secint/).

## Quick start

Requirements: Claude Code, bash, python3. On Windows use Git Bash or WSL.

Install the plugin (with `--plugin-dir <path>` at session start, via a marketplace, or via APM: `pip install apm-cli`, then `apm install vonavikon/qa-agent-evals`), open a session in the tested system's directory, and write:

```
run acceptance testing on <path to SUT>
```

The pipeline walks steps A-E on its own and stops exactly once, before the card review: it shows you the cards and waits for your approval.

## Contents

```
.claude-plugin/plugin.json    manifest
skills/acceptance-test/       the five-step pipeline (orchestrator)
agents/analyst.md             SUT profiler
agents/role-user.md           role-playing actor
agents/judge.md               two-step judge (pinned to a different model)
agents/visual-reviewer.md     visual review of screenshots (markup for the human only)
knowledge/taxonomy.md         5 card types, patterns, reference YAML
knowledge/adapters.md         CLI and browser (Playwright) adapters, environment isolation
knowledge/oracle.md           oracles, verdict scale, report templates
knowledge/sandbox.md          host/docker levels: boundaries, proxy, checks
knowledge/golden-live.md      live section of the control sample (golden cases from feedback)
scripts/run-cards.sh          CLI runner for single-turn cards with repeats
scripts/run-integrity.sh      tamper detector for the run directory
scripts/parse-events.py       events.jsonl parser: answers, provenance, diagnostics
scripts/check-facts.py        machine fact-checker (transcripts + SUT-written files)
scripts/judge-batch.py        judge batch + automatic re-judge of self-contradictions
scripts/judge-control.py      judge control sample (golden sets)
scripts/collect-feedback.py   human feedback: markup page + golden candidates
scripts/annotate-visuals.py   visual review: markup validation, annotated page, sample selection (--publish)
scripts/build-index.py        machine-readable run index (index.jsonl)
scripts/cost-report.py        run cost and duration
scripts/judge-metrics.py      judge agreement metrics over corpora
scripts/diff-runs.py          two-run comparison (a view, not a criterion)
scripts/make-golden-*.py      converters from open datasets (TruthfulQA, HH-RLHF)
scripts/sandbox.py            isolation-level backend for SUT sessions
scripts/sandbox-proxy.py      reverse proxy to the LLM gateway for the docker level
scripts/sec-checks.py         security suite of six docker-isolation checks
scripts/sec-integration.py    integration test: live pipeline inside the docker sandbox
scripts/Dockerfile.sandbox    image for the isolation container
examples/evil-plugin          target plugin for isolation verification
tests/                        unit and live tests for the pipeline
docs/spec.md                  specification
docs/plan.md                  implementation plan
docs/architecture.md          how it works: pipeline, isolation, responsibility
docs/research-2026-10-09.md   review of source frameworks
docs/research-2026-10-10-rsi.md  notes on self-improvement sources
docs/research-2026-10-11-kaggle-golden.md  open datasets for golden cases
docs/reviews/                 external spec reviews and code reviews
runs/                         self-acceptance and third-party run artifacts (raw session logs and sensitive data stripped)
```

## Status

v0.6.0. The pipeline grew on third-party systems and on itself.

v0.6.0 added a visual layer for browser acceptance runs: the adapter takes screenshots of states next to the transcripts, a reviewer subagent marks flaws on them (box + severity + comment), and the feedback page shows annotated shots next to the verdicts. The markup is a hint for the human: the judge never sees it, verdicts stay unchanged, and screenshots never enter oracles or the machine layer. Only samples hand-picked by the owner get published (`annotate-visuals.py --publish`).

First came four self-acceptance runs (v1-v4, reports in [runs/](runs/2026-10-08-qa-agent-evals-selftest/report.md)): v1 found 3 real defects (scope boundaries, promising the unimplemented, approval control); each next run verified the previous fixes and hunted for new ones.

Then third-party systems: a prose-editing skill (two runs with a version comparison, [runs/](runs/2026-10-11-stop-slop-r2/report.md)), a slide generator with a content-borne injection, a technical-English rewriting skill, the classic 2048 game through the browser adapter (a deterministic non-LLM SUT), and systems from a closed perimeter (details withheld). Those runs grew v0.3-v0.4: the machine fact layer (grep-caught leaks, including SUT-written files), the judge control sample from open datasets (TruthfulQA 45/45; HH-RLHF attacks), the Growing-Golden feedback loop with a clickable markup page, automatic re-judging of self-contradictions, and measured run economics: a typical acceptance run costs $0.6-1.8 on the SUT side plus roughly $0.4 per judge call, because a judge CLI call carries ~75K tokens of session preamble.

v0.5.0 added execution isolation (host/docker) with live evil-plugin proof, and infrastructure failures are now separated from plugin defects (BLOCKED/ERROR statuses). v0.5.1 and v0.5.2 hardened it: the gateway key lives only in the proxy container, plugin sources are mounted read-only with an evidence-based write probe, proxy path normalization closes /../ traversals, rate/volume/time limits added, and the proxy runs as non-root with no capabilities. The security suite (`python scripts/sec-checks.py docker`) is green on Windows and the Linux CI runner (runs/2026-10-13-sec/); an integration test runs the live pipeline with real Claude Code (runs/2026-10-13-secint/). In total: 52 tests: 43 pipeline unit tests and 9 live proxy tests.

Not working yet: only the CLI and browser adapters are implemented; isolation cuts skill invocation but not knowledge of the skills' existence; the judge is wired up manually (explicit `--model` or the owner's choice at step B), because the agent `model` field does not work in every environment.

Spec: [docs/spec.md](docs/spec.md), plan: [docs/plan.md](docs/plan.md).
