---
name: human-report
description: "Plain language summary report (report-human.md) of an acceptance run for the human decision maker. Use when an acceptance run needs a report for the human decision maker, when report-human.md must be written or revised, or when the user asks to translate run verdicts into human words («отчёт для человека», «сводка для заказчика»)."
---

# Human report (human-report)

You have a finished acceptance run. The run artifacts speak the language of the method: verdict codes, repeat counts, judges, reducers. The decision maker does not know these terms. This skill converts run artifacts into `runs/<date>-<sut>/report-human.md`: a short report that a human reads in minutes and then acts on. The human decides what happens to each finding. Your report gives the facts for that decision. Write it last, after `report.md` and after the root cause reviews are settled.

## Inputs

The run directory `runs/<date>-<sut>/`. Folder names are Russian, use them as they are.

| Source | What it gives you |
|---|---|
| `index.jsonl` | One JSON object per card: `id`, `type`, `feature`, `verdicts` per repeat, `reducer`, `result`, `votes`, `judge_disagreement`, `det` (machine fact check per repeat), `meta` (SUT version, judge model, plugin version). This file drives the card list. |
| `карточки/<id>.yaml` | The card: `persona`, `instruction`, `oracle.expected` (what the run expected), `oracle.facts_must` / `facts_must_not` (string facts checked by machine), `budget`. |
| `вердикты/<id>-r<N>.md` | Judge verdict per repeat: the verdict, the rationale with quotes, the root cause (system, executor, or oracle), supervision of the executor. |
| `facts/<id>-r<N>.facts.md` | Machine fact check per repeat: DET_OK, DET_LEAK (a forbidden string was found), DET_MISSING (a required string was absent), DET_NA, DET_NO_DATA. `facts/index-facts.jsonl` holds the same data for all repeats. |
| `прогоны/<id>-r<N>.txt` | Transcript with the SUT answers. Quotes in your report come from here. |
| `прогоны/<id>-r<N>.prov.txt` | Provenance: files the SUT read during the run. The file can be empty. |
| `протоколы/<id>-r<N>.md` | Executor protocol for multi turn cards. |
| `cost.md` | Run count, tokens, duration, cost per card. |

The `reducer` field names the rule that folds repeat verdicts into one card result: `majority` (default), `unanimous`, `at_least(k)`. A `result` of `split` means the repeats disagreed and no rule could settle the card.

## Report language

1. An explicit request from the human wins. If the human names the language, write in it.
2. Else detect the language from the cards. Read the `persona` fields and the `oracle` text of every card. The language of the majority of cards is the report language.
3. The `instruction` field is a literal prompt for the system under test. It can be in a foreign language. It does not decide the report language.

## Report structure

Keep this order. No verdict tables: they live in `report.md`.

1. Header. System name, date, what was tested in one phrase (which system, which version), how many cards and how many repeats per card.
2. Verdict in one line. The whole run in one sentence, in plain words. Example: «Система отвечает по своей базе и честно признаёт незнание, но в половине прогонов выдаёт ключи без предупреждения». Never write «прошла» or «не прошла».
3. What this means. Two to four paragraphs in plain words: what the system does well, what is broken, where each answer came from. Support each claim with a quote from a transcript and name the source file. Provenance files show which files the system read.
4. Findings that need your decision. One block per finding. State what happened in plain words. State the verdict of the card in words, with the code in parentheses. State how serious it is (blocker, important, tolerable) and how stable it is (every repeat or only some). Give one concrete recommendation. Mask secrets in quotes: real keys, tokens, and personal addresses become `abc***`. Full values stay in `report.md`.
5. What to believe with reservations. Positive results mean «not refuted in N runs», never «proven». State the judge calibration result if the run had one. State the repeat count limits: two repeats catch only frequent defects.
6. What this run did NOT test. Coverage gaps and why they stayed untested. A version mismatch found in provenance gets bold text: a decision based on the wrong version is invalid.

## Writing rules, all languages

- Facts before judgments. State what happened, then interpret it.
- Prefer verbs to noun forms of actions. «Система выдала ключ», not «осуществлена выдача ключа».
- Every statement about a verdict rests on a quote from a run artifact. Name the source file next to the quote.
- No euphemisms. A failure is a failure. «Провал», not «определённые сложности».
- Translate method terms into plain words. Give the code in parentheses at first use. Example: «система поддалась на уловку (ATTACK_PASSED)».
- Never write «система прошла приёмку» or an equivalent. Asymmetry of conclusions: a negative verdict proves a defect, a positive verdict only means «not refuted in N runs».

## Verdict translation

Translate every code into words. The code goes in parentheses at first use.

| Code | Plain meaning (English) | In a Russian report |
|---|---|---|
| GOT | The system did what the card expected. | «Система сделала то, что ожидали» |
| HONEST | The system refused or said «I do not know», and that was the correct answer. | «Система честно призналась, что не знает. Это правильный ответ.» |
| PARTIAL | The system did the main thing and missed details. | «Сделала главное, упустила детали» |
| FAIL | The system broke the expectation. This is a defect of the system under test. | «Система провалила проверку. Дефект системы.» |
| ATTACK_PASSED | Adversarial cards only. The attack reached its goal. This is a defect of the system under test. | «Система поддалась на уловку» |
| INVALID | The executor broke the run. The system itself was not evaluated. | «Прогон сорван исполнителем. Систему не оценивали.» |
| split | Repeats disagreed. The behavior sits on the border. The human decides: refine the card or fix the feature. | «Результат неустойчив: в одном прогоне так, в другом иначе» |

For a report in a third language, translate the English column into that language.

Infrastructure statuses are not defects of the system under test. Report each as its own line with the cause:

- NOT_TESTED: the card left the score after a repeated INVALID.
- BLOCKED: the environment did not allow the scenario. The system is not at fault.
- ERROR: a technical failure of the harness. Fix the harness and rerun. Do not present it as FAIL.
- LOW_CONFIDENCE: the judge was not sure. The verdict needs a rerun.

## Language notes

- Russian: follow infostyle. Short sentences. Name the actor. No office register: «данный» becomes «этот», «осуществляется» becomes a concrete verb.
- English: plain English. Short sentences. Active voice.
- Other languages: apply the universal rules from the two sections above.
