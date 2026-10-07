# Juniper AI Answer Eval Harness

A small, independent harness that checks whether an AI assistant gives **safe, accurate, properly escalated** answers to the questions an Australian patient on GLP-1 weight-management medicine might ask. It also measures **when the AI judges marking those answers can't be trusted**.

> **Not medical advice.** This is an evaluation project. The expected answers are written from public consumer medicine leaflets by a data scientist, not a clinician. If you have questions about your medicine, talk to your doctor or pharmacist.
>
> **No patient data is used.** Every test case comes from public sources, listed in `data/sources.md`.
>
> **Not affiliated with Eucalyptus or Juniper.** The chatbot under test is a stand-in, not any real Juniper system.

## Why

AI now touches most patient conversations in digital weight-management care. The hard question isn't "can the bot answer?" but "would we be comfortable if a clinician read every answer?". This harness turns that question into numbers, and checks the AI judges as well as the bot.

## How it works

| Layer | What happens |
|---|---|
| L0 Generate and log | Bot answers every question; every answer saved with model, prompt version and date |
| L1 Rule checks | Exact facts checked by text rules, e.g. the Australian 5-day missed-dose rule |
| L2 Two judges | AIs from different model families score safety, grounding, scope and escalation; either may say `unsure` |
| L3 Human labels | Every answer labelled blind by a person before the judges are compared |
| L4 Router | Auto-pass, human review or auto-fail; critical cases never auto-pass |
| L5 Judge audit | Reworded copies of critical answers: does a judge flip on style alone? |
| L6 Scorecard | Severe miss rate (with a range) and human review load; no single safety percentage |

## Status

| Stage | What | Status |
|---|---|---|
| 1 | Test set, rubric, validator | Done |
| 1b | Test set v2: variants, boundary cases, locked split | Done |
| 2 | Generate and log (bare + grounded bot) | In progress |
| 3 | Rule checks in promptfoo | |
| 4 | Blind human labels | |
| 5 | Two judges + agreement | |
| 6 | Router + judge audit | |
| 7 | Scorecard on BigQuery + dbt, scheduled with Dagster | |

## Repo map

```
data/            test cases, sources, leaflets, labels
rubric/          scoring rubric
harness/         Python package (validator now; generator, judges, router later)
prompts/         instructions for the bot under test
runs/            append-only run logs
docs/            project brief, stage prompts, routing rules
notes/           build log and criteria drift log
```

## Run it

```
pip install -e ".[dev]"
python -m harness.validate_cases
pytest
```

## Limits

- Labels and expected behaviours by one non-clinician; critical cases pending clinical review.
- Pilot size (~95 cases). Results are signals, not proof; ranges are reported.
- Single-turn questions, English only, two medicines, Australian rules.
- Sources checked 04 Oct 2026. Medicine information and models change.
- AI tools helped draft code and some test cases; every case was checked against its source by the author.
