# Kaggle as a source of golden material (review P0-2)

Date: 2026-10-11. Owner question: can the judge golden set look for material at
https://www.kaggle.com/docs/mcp.

## What Kaggle MCP is

The official Kaggle remote MCP server (`https://www.kaggle.com/mcp`), built on
top of the kagglehub library. Tools: search, metadata, and file reading over
five entities (datasets, competitions, notebooks, models, benchmarks). The docs
page renders only in a browser (JS), so the tool list comes from the
announcement and from third-party mirrors of the server. Connection is OAuth
through a Kaggle account.

## Channel check (experiment, 2026-10-11)

The Kaggle channel sits entirely behind authorization, nothing works
anonymously:

| Path | Result without an account |
|---|---|
| docs/mcp page | the body is not served (a JS application) |
| curl on a dataset page | 404 (a non-browser UA is blocked), with a browser UA 200 |
| kagglehub 1.0.2, a public dataset | 403 on api.kaggle.com |
| direct endpoint `/api/v1/datasets/download/...` | HTTP 200, but the body is an HTML login page instead of the archive |

For the channel to work, the owner needs a free Kaggle account. A token from
kaggle.com/settings (Create New API Token) goes to `~/.kaggle/kaggle.json`
or the KAGGLE_USERNAME/KAGGLE_KEY variables. The MCP client authorizes over
OAuth.

No need to work around this: the same data sits in the primary sources without
a token (GitHub/Hugging Face). Kaggle is unique only in the official
lmsys/chatbot-arena-conversations dataset (33K dialogs).

## Candidates and mapping to our case format

Our case: `## G-NN (эталон: VERDICT)` + Question / Expectation / SUT Answer.
Review requirement: the reference verdict is set by a human expert, not by the
plugin judge.

| Dataset | Labels | Mapping | Status |
|---|---|---|---|
| TruthfulQA (Lin et al. 2021, Apache 2.0, canonical: github.com/sylinrl/TruthfulQA) | author labels, manual: a truthful answer + a typical misconception per question | Best Answer → GOT, Best Incorrect Answer → FAIL, "I have no comment." → HONEST, deterministic, no judgment | done: `scripts/make-golden-truthfulqa.py`, a draft of 45 cases |
| LMSYS chatbot-arena-conversations (Kaggle, official) | pairwise human votes (a better than b / tie / both bad) | a direct mapping is impossible: a pairwise signal is not an absolute verdict. Every pair needs manual relabeling | a volume candidate, after manual relabeling |
| Anthropic HH-RLHF (canonical: HF/GitHub anthropics/hh-rlhf. On Kaggle only unofficial mirrors) | chosen/rejected pairs from paid annotators | harmless split: a refusal (chosen) → the attack is repelled, a harmful concession (rejected) → ATTACK_PASSED. It closes the attack class missing from the manual set and TruthfulQA | next step |

## What the reconnaissance produced

- `scripts/make-golden-truthfulqa.py` is a deterministic converter (seed 42):
  15 dataset questions × 3 answer classes = 45 cases, IDs G-101..G-145,
  no overlap with the manual set G-01..G-08.
- Draft: `runs/2026-10-11-judge-control-tq/golden-truthfulqa.md`
  (15 GOT / 15 FAIL / 15 HONEST. The manual set never had a single FAIL).
- Set total: 8 + 45 = 53 cases. The review lower bound (50-100) is reached.
- The judge control run (glm-5.3-flash) over the draft: **45/45**. GOT, FAIL,
  and HONEST separate cleanly with zero errors,
  `runs/2026-10-11-judge-control-tq/report.md`.
  Caveat: TruthfulQA cases are easier than live ones. The expectation names
  the right answer verbatim, the answers are one-liners, and the HONEST answer
  repeats an allowed oracle wording literally. 45/45 shows basic class
  separability but does not replace the manual set (7/8 on live retellings).
  Live cases stay the source of hard ones.

## Decisions for the owner

1. Whether a Kaggle account is needed. For golden material, no: GitHub and HF
   give the same data without a token. MCP helps differently, interactive
   dataset search right in an acceptance session (for example, looking for SUT
   candidates or fresh benchmarks). If needed, create a free token, the recipe
   is above.
2. A look at the golden-truthfulqa.md draft before the extended set enters
   acceptance reports. Dataset author labels are expert ones, but the owner
   must see the material firsthand: it is the owner's control sample.
