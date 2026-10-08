# CLAUDE.md — Juniper AI Answer Eval Harness

Read this first, every session. It sets how we work in this repo.

## What this project is

A small, independent harness that checks whether an AI assistant gives safe, accurate, properly escalated answers to Australian GLP-1 patients (Wegovy, Mounjaro), and measures when the AI judges marking those answers can't be trusted.

Portfolio artefact for a Data Scientist (AI evaluations) application at Eucalyptus / Juniper. Full context: `docs/PROJECT_BRIEF.md`.

## How we work

- **Build in stages.** Stop after each stage. Tell me exactly how to test it, then wait for me.
- **Plan before code.** Show a short plan (files to touch, what each does) and wait for my OK.
- **Small diffs.** One concern per change. Don't refactor files I didn't ask about.
- **Explain new things.** The first time a tool, library or term appears, explain it in one plain sentence.
- **Commit messages** start with the stage, e.g. `Stage 2: ...`.

## What I own — never write these for me

Review them if I ask, but the content is mine:

- Gold labels (`data/labels/`) and `label_confidence`
- `expected_behaviour`, `must_include`, `must_not_include` for every test case
- Style variants and coaching-vs-medical boundary cases
- The `partition` (dev / locked) split
- `rule_checks` wording
- Routing rules (what auto-passes, what goes to review)
- The grounded bot's instruction (`prompts/grounded_*.txt`)
- All SQL and dbt models
- `notes/` (build log, criteria drift log)

You may **draft** adversarial variants when I ask. Mark each one `DRAFT` so I review it.

## Hard rules

- **No patient data, ever.** Every test case cites a source key in `data/sources.md`.
- **Never edit rows where `partition = locked`.** If one looks wrong, tell me; I log the change in `notes/criteria_drift.md`.
- **Never tune judge prompts or rules on locked cases.** Dev only.
- **Never average judge scores.** Keep every score separate; the router decides.
- **Runs are append-only.** Never overwrite `runs/*.jsonl`. Every run gets a `run_id`.
- **Respect the cost cap** in `config.yaml`. Stop with a clear message if it would be exceeded.
- **No secrets in the repo.** API keys come from environment variables; `.env` stays in `.gitignore`.
- **Don't claim we tested June** or any real Juniper system. The bot under test is a stand-in.

## Engineering standards

- Python 3.11+, as a package: `harness/`. No notebooks.
- Settings in `config.yaml`, not hard-coded.
- Pydantic models for test cases, logged answers and judge outputs.
- pytest for everything; tests use a fake model and never call a paid API.
- Plain-English docstrings on public functions.
- Windows + PowerShell is my environment. Give commands that work there.

## Layers (for orientation)

| Layer | What | Stage |
|---|---|---|
| L0 | Generate and log answers (bare + grounded bot) | 2 |
| L1 | Rule checks (promptfoo assertions) | 3 |
| L2 | Two judges, different model families, may say `unsure` | 5 |
| L3 | Compare judges with my blind labels | 4–5 |
| L4 | Router: auto-pass / human review / auto-fail | 6 |
| L5 | Judge audit: reworded copies, count flips | 6 |
| L6 | Scorecard: severe miss rate + review load (BigQuery + dbt) | 7 |

## Current stage

Update this line at the end of every session.

- **Done:** Stage 1 (test set, rubric, validator); Stage 1b (73 cases, 50 dev / 23 locked; coaching + adversarial added; style variants, over-safety, trial claims cut)
- **Done:** Stage 2 (generator, Claude Haiku 4.5 bot, grounded_v2 prompt, first full run A$1.87)
- **Done:** Stage 3 (rule checks via promptfoo 0.124.0; require-only rules on 25 dev cases; run 20261007T061343Z-71f54e: 15 fails, all bare, grounded all pass)
- **Done:** Stage 4 tooling (blind label sheet from run 20261007T061343Z-71f54e, 130 answers, both partitions; Streamlit app `streamlit run harness/label_app.py`). Stage 6 plan now includes a `--compare` routing backtest
- **Next:** finish labelling (2 / 130 at commit), then Stage 5 (two judges + kappa on dev). Still open: check DIET_GUIDE content in `data/sources.md`; the 8 coaching-scope cases (incl. MD-01-CO, CO-06) have no answers until a coaching prompt exists (`generate.scopes`); PC-01 forbid has a garbled apostrophe (`don�t stop`)
