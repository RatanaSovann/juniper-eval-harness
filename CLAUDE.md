# CLAUDE.md — GLP-1 AI Answer Eval Harness

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
- **Done:** labels. `data/labels/claude_labels.csv` = AI reference labels for all 130 (not blind, not human gold); `label_sheet.csv` = my hand labels on a priority subset (wins on overlap). See `data/labels/README.md`
- **Done:** v1 vs v2 run 20261008T141049Z-88741d (v1 = grounded_v1, no leaflets, logged as `v1_no_leaflets`; v2 = grounded_v2 + leaflets, logged as `grounded`). My hand labels: 42 high/critical dev answers in `label_sheet_v1_v2.csv` (3 hard fails: PC-01 v1, RF-05-ADV v1, RF-06 v2)
- **Done:** Stage 5 (`harness/judge.py` + `harness/agreement.py`; judges gpt-6-luna + gemini-3.5-flash-lite, prompt judge_v2, 2 repeats, SDK retries + `--resume`; judge run 20261009T001243Z-ff6b22 on 88 dev answers, 352 verdicts, 0 invalid, A$1.05). Kappa ~0 for both (prevalence: labels almost all 2). Gemini scored 97% safe and missed all 3 hard fails + MD-01 US rule; OpenAI caught/flagged all 3 but noisy (safety changed 12/88 between repeats). Judges found likely label errors (SC-07 v1 grounding)
- **Done:** Stage 5 follow-ups: Grok judge (grok-4.20-0309-reasoning, run 20261009T030812Z-16238e) replaces Gemini; router pair is now luna + Grok. Dev safety: luna 61% called safe, kappa 0.28, 12 flips; Grok 89%, kappa -0.02, 7 flips; Gemini 97%, kappa 0.00. RF-02-ADV v1 label revised (logged)
- **Done:** Stage 6 (`harness/router.py`, `rules/routing_v1.yaml` + `routing_v2.yaml`, `docs/routing_rules.md`, `--compare` backtest; judge audit audit-20261009T050742Z-24dfda). Dev, routing_v2, luna + Grok (route run 20261009T050627Z-4b48c5): review load 62.5%, 0 of 4 hand-labelled hard fails auto-passed
- **Done:** locked check (judge run 20261009T062155Z-ac2718, route run 20261009T071439Z-3a1624, 42 answers, AI reference labels on 24 high/critical): review load 54.8%, 1 of 3 hard fails auto-passed (RF-04-ADV v1_no_leaflets). These two runs are in `runs/judgements.jsonl` + `runs/routes.jsonl`, not yet committed
- **Done:** Stage 7 (BigQuery loader, dbt staging + scorecard marts, alerts, Dagster pipeline, README rewrite + diagrams). Project renamed to glp1-eval-harness (text only; GCP project and BigQuery datasets keep `juniper`). Live dashboard linked in README: https://claude.ai/artifact/XXNzQEJBLDMAQMcLgmMxFS. The promptfoo share link in README needs a promptfoo login
- **Next:** commit the locked runs; look at why RF-04-ADV v1 was auto-passed on locked (don't tune on it, but log it); add the locked result to README (it still says the locked check is future work); write the technical report. Still open: RF-07-ADV question has no hypo symptoms though `must_include` expects them (fix + log in criteria_drift, regenerate); check DIET_GUIDE content in `data/sources.md`; the 8 coaching-scope cases (incl. MD-01-CO, CO-06) have no answers until a coaching prompt exists (`generate.scopes`); replace the promptfoo link with a public one or remove it
