# Research: recursive self-improvement and our pipeline (2026-10-10)

Three sources, each studied by a separate analyst subagent:

1. The Anthropic Institute, "When AI builds itself" (Marina Favaro, Jack Clark, October 2026), a position paper on recursive self-improvement.
2. arXiv:2609.26457, "Recursive self-improvement of AI research agents" (AIDE², Weco AI, 22.09.2026). Empirics: an agent rewrites its harness for 8 days, 0.703 → 0.778 on a private selection.
3. arXiv:2607.07663, the survey "Recursive Self-Improvement in AI: From Bounded Self-Refinement to Autonomous Research Loops" (Chen, Wang, Qu, v2 06.09.2026, 44 pages, 1250 sources). Corpus repository: deepgrounding/recursive-self-improvement.

Link to the previous review (`research-2026-10-09.md`): HALO (context-labs) and AIDE² sit in one class, harness evolution driven by an external signal. The survey gives this class a vocabulary and limits.

## 1. Anthropic Institute: When AI builds itself

**What it is.** An essay arguing that recursive self-improvement is already underway in embryo form. More than 80% of the code merged to production at Anthropic is written by Claude (May 2026). Engineers merge 8 times more lines per day than in 2024 (the authors discount this themselves: LOC measures quantity, not quality). Code optimization speed grew from ~3× to ~52× in a year. At "pivotal moments" of research sessions the model picks a better step than the human in 64% of cases (51% a year before). Half of the document is policy: a verifiable pause program, an analogy with the INF Treaty.

**Methodological micro-techniques we take:**

- **A control sample for the judge** (footnote 8): they measured the model win rate on 129 moments where the human left the course (64%). In parallel, on 127 moments where the human move was known to be strong, the model wins only ~20%. This is a cheap detector of judge bias: a fixed card set with known verdicts, run at every judge model change.
- **The "clearly succeeded" criterion**: a session counts only on an unambiguous success, with no interpretation in favor. Hence a judge rule: FAIL only on an explicit oracle violation, gray cases pull neither FAIL nor GOT.
- **A retrospective recall metric**: their reviewer would retroactively have caught ~a third of the bugs of past incidents. Our analog: seed known defects into the SUT and measure the share caught. Today we measure precision, not recall.
- **The double quality criterion** ("works" + "written so another engineer can build on it"). It is a second oracle axis for critical cards: not only "gave the fact" but "gave enough to continue".
- **Amdahl's law as a frame**: speeding up one part of a process shifts the bottleneck. For reports, an axis "at which scenario horizon the SUT fails".
- **Verifiability > detectability**: an oracle written in advance is a checkable obligation. A judge opinion without an oracle is only detection. A ready frame for the docs.

**Conflict with us.** Their judge is single-step, from the Claude model family, with a bias admitted in footnotes. Our design (two steps, a different model) closes these weaknesses. Their throughput metrics are orthogonal to our correctness metrics. For fast SUTs their scenario exposes our gap: the version N oracle goes stale at N+1. We need SUT version pinning in the report and a diff run at a version change.

## 2. AIDE² (arXiv:2609.26457): harness self-rewriting

**Method.** A two-level loop. The inner agent solves tasks, watching the public signal r_pub. The outer agent rewrites the inner agent's code, and a rewrite is accepted only when g grows. g is the mean score on a private held-out, averaged over several runs. Key design decisions: "the inner loop signal is decoupled from the selection signal of the outer loop, to prevent gaming. Fixed budgets guarantee that the gain reflects the algorithm, not the compute."

**Results.** 8 days of autonomous work: 100 trajectory nodes, 7 rewrites accepted, 92 rejected. g: 0.703 → 0.778 against 0.749 for a production agent built by humans over ~2 years. The largest gain came on an OOD benchmark (WeatherBench 2: 0.262 → 0.793). Reward hacking on KernelBench dropped emergently: 55% → 32% on a metric nobody optimized. Rigor is moderate: one trajectory (a case study), replications gave 2 and 4 accepted rewrites, no ablations, no public AIDE² code.

**What we take:**

- **Decoupling of public and private signal** is the theoretical name for our trick "the oracle is hidden from the SUT". The evaluation criterion stays invisible to the system under test. It also argues against coaching the SUT on repeated runs.
- **Fixed budgets** are the same argument as our isolation: max-turns and the card budget, so SUT differences are not confounded by resources.
- **Averaging g over runs** gives our reducers literature support: noise is the main threat to validity, a falsely accepted rewrite pulls the search aside.
- **A two-level reward-hacking oracle**: a cheap proxy test (isolated gain > threshold) + an expensive integration one (does the gain survive downstream). The pair is a pattern for adversarial cards: a local SUT success must not survive the transfer into context.
- **Dead code of the evolved artifact** (the median penalty "never changed the outcome") is a reason to count the fireability of facts_must / facts_must_not items. An oracle item that never fired is a deletion candidate.
- **"Fixed the broken evaluation instead of exploiting it"** is close to our diagnostics: first test the measuring instrument, then blame the SUT.
- **The incumbent rule** (accept a new version only when g grows on the private selection) is a conservative acceptance rule for SUT iterations.

## 3. Survey (arXiv:2607.07663): the RSI taxonomy

**What it is.** A systematic review of 1250 papers (2024-2026): 45% deployment behavior improvement, 30% training policies, 15% self-evaluation, 5% + 5% research automation and closed loops. The key frame is a hierarchy of verification: formal verifiers > feedback from execution > learned judges > internal self-evaluation signals. Each level is "a versioned, serializable artifact that can be checked independently". The central thesis: "when the generator and the evaluator become one entity, its biases are not eliminated but replicated".

**The controlled falsification experiment** (§3.3): Self-Rep-Agent "improved" by +24.4 points after the environment implicitly encoded the desired behavior and added a placebo prompt "please, self-improve". With the key information hidden, the effect fell to +0.4 points. Conclusion: the observed improvement followed the instruction, not the evidence. Hence an epistemology isomorphic to ours: "a test failure is an executable counterexample. A pass does not prove correctness, it only bounds risk", plus "a claimed success must be backed by a minimum of independent evidence".

**What we take:**

- **Executable checking beats a judge.** Where a fact can be matched against a trace or an artifact, move it from the judge to the deterministic layer. A universal LLM judge as the only mechanism is a revision candidate: our judge is level 3, not the top.
- **Binary oracle questions** (BinEval: "ask, do not judge") are an argument that facts_must/facts_must_not stay binary, not graded.
- **Committees soften but do not remove bias**: the unanimous reducer protects from noise, not from correlated bias. Do not sell unanimous as proof of absence of defects.
- **Rewarding rightness** (LLM-generated tests are too predictable): vary probe wording across runs. And the main rule: after a harness optimization (HALO class), test only with fresh probes. Old cards work only as a regression smoke test.
- **Translation drops judge performance**: no machine translation of cards for multilingual SUTs without manual revision.
- **MAST cascades** (a failure of one component cascades) are a vocabulary for our diagnostics "environment vs SUT".
- **Positioning**: our pair "probe tests + external judge" in their terms is human-on-the-loop harness evolution with external falsification of the improvement. HALO without external probes is vulnerable to the placebo effect from §3.3.
- **The Self-Teacher paradox**: iterating the evaluator and the generator together is unstable. Do not change the harness and the cards or judge at once. One cycle changes one thing.

## Reuse plan

**P1, now and cheap (edits to knowledge and the judge):**

1. Placebo discipline for the HALO loop: a harness optimization is tested only with fresh cards. The old set is a regression smoke test (survey §3.3).
2. The judge control sample: extend the golden calibration with a fixed set of known verdicts (strong/weak executor, clean/defective SUT). Measure the bias at every judge model change (Anthropic, footnote 8).
3. Lowering facts into the deterministic layer (survey, hierarchy): a facts_must item matchable by trace or provenance moves from the LLM judge to the grep verifier.
4. Report wording: a positive verdict = "risk bounding", not "evidence of correctness". Judge vote divergence across repeats goes into a separate column over the reducers (survey + Anthropic).
5. The dev/test rule: a plugin fix found by self-acceptance closes only after a control run on an external SUT (AIDE² + HALO).

**P2, next milestone:**

6. Two-level adversarial oracles: a proxy threshold + an integration check of downstream survival (AIDE²).
7. An oracle-item fireability counter in build-index.py. Items that never fire raise a flag in the report (AIDE², dead code).
8. A harness recall metric: seed known defects into an SUT version, measure the share caught (Anthropic, retrospective).
9. A second axis of critical oracles: "enough for another agent to continue" (Anthropic, double criterion).
10. SUT version pinning in the report + a regression card diff run at a version change (Anthropic, the fast-SUT conflict).

**P3, conceptual:**

11. The plugin role in the RSI stack: an external private grader g(a) for harness optimizers (the HALO/AIDE² class). Our report with reducers is a candidate for the outer-loop evaluation function.
12. Probe wording variation across runs against "rewarding rightness".
13. The one-change rule: do not iterate the harness and the measuring instrument at the same time (the Self-Teacher paradox).

## Sources

- https://www.anthropic.com/institute/recursive-self-improvement
- https://arxiv.org/abs/2609.26457 (HTML: https://arxiv.org/html/2609.26457)
- https://arxiv.org/abs/2607.07663 (HTML: https://arxiv.org/html/2607.07663v2, corpus: https://github.com/deepgrounding/recursive-self-improvement)
