# Juniper AI Answer Eval Harness

**Can you trust an AI to check another AI's medical answers?** This project tests that, on questions an Australian patient taking Wegovy or Mounjaro might ask.

**What I found so far:**

- The bot told someone with possible anaphylaxis they could drive themselves.
- **Two of the three AI judges I tried marked that answer as safe.** Only one caught every dangerous answer.
- With a single, poorly chosen judge, the scorecard would have looked perfect.

> **Not medical advice.** Expected answers come from public consumer medicine leaflets, written by a data scientist, not a clinician.
>
> **No patient data.** Every test case cites a public source in `data/sources.md`.
>


## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/harness-flow-dark.svg">
  <img src="docs/harness-flow-light.svg" width="100%" alt="Flow: 73 test cases go to the bot, then rule checks and two AI judges. Blind labels and a judge audit measure the judges and backtest the router. The router sends 33 of 88 answers to auto-pass, 55 to human review and 0 to auto-fail. The scorecard shows 0 of 4 hard fails missed (range 0 to 49 percent), and an alert fails the build if a hard fail is auto-passed.">
</picture>

Read it top to bottom:

1. **The bot answers** every test question.
2. **Rules** check exact facts, such as Australia's 5-day missed-dose rule.
3. **Two AI judges** score every answer for safety, grounding, scope and escalation.
4. **The router** decides: auto-pass, send to a person, or auto-fail.
5. **The scorecard** shows two numbers side by side: dangerous answers missed, and how much human review it took.

**On the right:** my blind labels and a judge audit check whether the judges themselves can be trusted.

**At the bottom:** if a dangerous answer is ever auto-passed, the build fails.

## Where it fits in production

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/production-fit-dark.svg">
  <img src="docs/production-fit-light.svg" width="100%" alt="Production fit: patients chat with an AI assistant and chats are logged to a data warehouse. The harness takes a daily sample, runs rules and two judges, and a router sends cases to a scorecard with alerts and to clinician review. Labelled cases feed a kappa check back to the judges, and a regression set that gates model updates before they reach patients.">
</picture>

- **The harness only needs questions and answers,** so it works on any vendor's bot.
- **People review what the router sends them,** plus a small random slice of "safe" chats to catch what the system misses.
- **Left loop:** clinician labels re-check the judges (kappa), so a judge that drifts gets caught.
- **Right loop:** every real failure becomes a test that each model update must pass before going live.

This repo is the offline half: a fixed test set and a release gate. Daily monitoring of live chats is the next step.

## Results (dev set, 9 Oct 2026)

Two versions of the bot: **v1** (instructions only) and **v2** (instructions + the two Australian leaflets).

**The bot**
- v1 produced 3 of the 4 hand-labelled hard fails, including the anaphylaxis answer, and gave the **US 48-hour missed-dose rule** instead of Australia's 5 days.
- v2 still under-escalated one critical case. Grounding helps; it doesn't fix everything.

**The judges** (vs 42 hand-labelled high/critical answers, 4 hard fails)
- **gemini-3.5-flash-lite** called 97% of answers safe and missed all 4 hard fails and the US-rule error.
- **grok-4.20-0309-reasoning** (a dated snapshot) caught the US-rule error and flagged 2 of 4 hard fails, but called the anaphylaxis answer fully safe, twice.
- **gpt-6-luna** caught or flagged all 4, but is noisy: it changed its own safety score on 12 of 88 answers between identical calls.
- **Kappa is close to 0 for every judge, and here it misleads:** 39 of 42 labels are "safe", so chance agreement is already high. Hard-fail catches tell the real story.
- The judges also **found errors in my labels** (e.g. Wegovy is approved from age 12, not 18). One label was revised after an OpenAI flag, which moved OpenAI's safety kappa from 0.17 to 0.28; both numbers are reported.
- **So far the second judge adds almost nothing to routing:** luna + Grok and luna alone route the same way with 0 misses. A second judge earns its place only if it is independent *and* at least as sensitive.

**The router** (`routing_v2`)
- 88 dev answers: 33 auto-pass, 55 human review (incl. a 10% random audit of auto-passes), 0 auto-fail.
- **0 of 4 hard fails auto-passed.** With only 4, the honest 95% range is **0% to 49%** (Wilson; a bootstrap would wrongly say 0–0%).
- A backtest showed what each rule buys: dropping the judge rules would have let 2 hard fails through.

**The rules** caught 2 of the 4 hard fails on their own, with 2 false alarms: useful, but not enough alone.

**Alerting** was fire-drilled: replaying a policy known to miss 2 hard fails made `dbt build` fail, as designed.

**The judge audit:** full run in progress.

These are pilot numbers from 4 hard fails and one labeller. They show where the system breaks, not how often.

## Design choices

- **No single safety percentage, anywhere.** An average hides the one answer that matters.
- **Judge scores are never averaged.** The router decides what disagreement means.
- **`unsure` is a valid score,** for judges and labellers.
- **Every judge scores every answer twice,** so self-disagreement is measured too.
- **Dev / locked split:** 50 dev cases for building; 23 locked cases are only measured, never tuned on.
- **Append-only runs with a hard cost cap** (A$5 per run).
- **Versioned policy:** routing rules in `rules/routing_v*.yaml`; every label or rule change is logged in `notes/criteria_drift.md`.

## Run it

Windows / PowerShell, Python 3.11+.

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,label,warehouse]"
python -m pytest -q          # fake models only, no API calls
```

API keys go in a git-ignored `.env`: `ANTHROPIC_API_KEY` (bot, rewriter), `OPENAI_API_KEY` and `XAI_API_KEY` (judges). Settings, models and prices live in `config.yaml`.

| Step | Command |
|---|---|
| Check the test set | `python -m harness.validate_cases` |
| Generate answers | `python -m harness.generate` |
| Rule checks | `python -m harness.rule_checks` |
| Label answers | `streamlit run harness/label_app.py` |
| Judge answers | `python -m harness.judge` (`--labelled`, `--only <judge>`, `--resume <id>`) |
| Agreement report | `python -m harness.agreement` |
| Route answers | `python -m harness.router` |
| Backtest two policies | `python -m harness.router --compare rules/routing_v1.yaml rules/routing_v2.yaml` |
| Judge audit | `python -m harness.audit`, then `python -m harness.audit --report` |
| Load into BigQuery | `python -m harness.load` (`--dry-run` to preview); needs `gcloud auth application-default login` |
| Build the scorecard | `cd dbt; dbt build` |
| Pipeline UI | `dagster dev -m harness.pipeline`: `refresh_scorecard` (free) and `full_eval` (paid, about A$5) |
| Redraw README diagrams | `python docs/make_readme_diagrams.py` |

## Repo map

```
data/      test cases, sources, leaflets, labels
rubric/    scoring rubric
harness/   generate, rule checks, label app, judges, agreement, router, audit, load, pipeline
prompts/   bot and judge instructions
rules/     routing policies (versioned YAML)
runs/      append-only run logs
dbt/       scorecard models, alerts and data tests
docs/      brief, routing rules, diagrams
notes/     build log and criteria drift log
tests/     pytest, fake models only
```

## Status

| Stage | What | Status |
|---|---|---|
| 1 / 1b | Test set (73 cases, 50 dev / 23 locked), rubric, validator | Done |
| 2 | Generate and log (v1 vs v2 bot) | Done |
| 3 | Rule checks in promptfoo | Done |
| 4 | Blind human labels + labelling app | Done (42 high/critical answers) |
| 5 | Two judges + agreement | Done (second judge: Gemini, then Grok) |
| 6 | Router + judge audit | Router done; full audit running |
| 7 | Scorecard on BigQuery + dbt, Dagster pipeline, alerts | Done except CI |

## Limits

- One non-clinician labeller; critical cases are pending clinical review.
- Pilot size: 73 cases, 42 hand-labelled answers, 4 hard fails. Signals, not proof.
- Misses can only be measured where there are labels (high and critical answers).
- The routing policy was chosen on dev results, so dev numbers are optimistic; it gets one check on the locked set at the end.
- Single-turn, English only, two medicines, Australian rules.
- Sources checked 4 Oct 2026. Medicine information and models change.
- AI tools helped draft code and some test cases; every case was checked against its source by me.
