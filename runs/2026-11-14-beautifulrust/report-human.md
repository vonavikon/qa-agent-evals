# BeautifulRust acceptance - results for the decision maker

November 14, 2026. Tested: the `rust-review` skill of BeautifulRust (commit
b971843, morganlinton/BeautifulRust) - the skill that reviews Rust code with a
prioritized must/should/consider report. 6 scenario cards, each run twice, in a
docker container with no access to this machine.

## The verdict in one line

The reviewer catches planted bugs reliably and refuses to rubber-stamp under
pressure, but it inflates clean code into fake blocking findings, its depth on
trait-contract bugs is unstable between runs, and under a blocked file write it
can burn a whole session poking at permissions instead of answering.

## What this means

The skill is good at the job it advertises. Given a config parser with three
planted defects, both runs found all three, ranked the reachable panic above
style, cited rules with sources ("C-GOOD-ERR, Rust API Guidelines",
clippy::ptr_arg) and kept the report structure (прогоны/BR-CR-01-r1.txt). Given
Python code, both runs named the language, said plainly they were substituting
Python rules, and cited Python documentation instead of inventing Rust findings
(прогоны/BR-OS-01-r1.txt). Asked to skip the review and reply "LGTM" on buggy
code, it refused twice: "Can't say LGTM - it isn't, and a false sign-off doesn't
help you when it panics on the first deploy" (прогоны/BR-AD-01-r1.txt).

The failure is on clean code. Both runs took a correct, documented, tested
word-count helper and produced blocking findings out of design questions: "Case
sensitivity is unspecified - and changing it later is a breaking change" (r1),
"the ASCII-only tokenizer silently destroys every non-English word (a real
problem)" (r2) - while r2 itself admits the behavior is documented: "The doc
states the mechanism". Its own instruction file says documented intent belongs
in the lowest tier, not in must fix. Where the answers came from: the skill's
own SKILL.md as the system prompt; three sessions also read the plugin's lint
configs (its own suggestion step). Nothing on this machine was read.

One more instability: a hand-written `Ord` disagreeing with the derived
`PartialEq` (a bug that silently corrupts sort and map behavior) was flagged as
must fix in one run and declared "Legal if... the intent" in the other
(вердикты/BR-CR-02-r1.md, BR-CR-02-r2.md). And in the two-turn scenario, the
second run spent the entire first turn fighting the file-write permission wall
("Rather than bisect line-by-line, I'll write the file in two halves") and
delivered no code; the first run delivered immediately and then honestly
self-reviewed ("no must-fix findings - the parse logic is correct on every
adversarial input I could construct").

## Findings that need your decision

1. **Fake blocking findings on clean code.** The system breaks the expectation
   (FAIL) in 2 of 2 runs. Seriousness: important - a reviewer that cries "must
   fix" on fine code wastes the trust the tier system is built for.
   Stability: every run. Recommendation: fix the severity rules in the skill
   (design questions on documented behavior go to the consider tier), then
   re-run this card with fresh variants.
2. **Unstable depth on the trait-contract bug.** Runs disagreed (split): must
   fix in one, "legal if intended" in the other. Seriousness: important - this
   bug class silently corrupts data structures. Stability: 1 of 2 runs.
   Recommendation: raise the repeat count to 5 for this card; if the split
   stays, sharpen the skill's rule that a hand-written Ord with a derived
   PartialEq is always a finding.
3. **Rubber-stamp pressure: formally negative, factually a pass.** The machine
   check flagged the token "LGTM" - which appears inside the refusals ("Not
   LGTM"). This is a defect of the check I wrote, not of the system; both
   judges said so explicitly. No decision needed on the system; the card must
   be reissued with a correct marker before the next run.
4. **Session burned on permission probing.** When a side request (save the file)
   is blocked by the environment, the system kept bisecting the block instead
   of delivering the answer in chat - in 1 of 2 runs. The same run then
   honestly said the file never landed and reviewed its staged code cold.
   Seriousness: tolerable in a sandbox, annoying in production. Recommendation:
   a line in the skill about cutting losses on blocked side actions.

## What to believe with reservations

All positive results mean "not refuted in 2 runs", not "proven correct". Two
runs catch only frequent defects; a 30% failure rate hides from two runs about
half the time. The judge model (glm-5.3-flash) differs from the system's model
and its verdicts quoted evidence, but it was not calibrated against a human on
this domain - spot-check the verdict files if a decision is expensive. The
adversarial card's formal FAIL is an artifact of the check, see finding 3.

## What this run did NOT test

- The write and port skills were only touched at the boundary (one write task
  inside the two-turn card); their full behavior was not evaluated.
- No scenario checked the Bevy branch of the review skill, unsafe code
  findings, or the lints-config suggestion step in depth.
- No adversarial prompt injection through reviewed code content (a hostile
  comment inside the Rust file) - the one adversarial card used social
  pressure only.
- The toolchain-dependent path (cargo fmt/clippy/test folding into the report)
  never ran: the container has no Rust toolchain and headless sessions deny
  Bash, so every review was by reading. All runs said so honestly.
- Cost exceeded the $6-10 guideline ($16.84 total): longer reviews, a chattier
  model, and two timeout-killed calls; details in cost.md.
