# Project brief

Decisions so far, in one place. Update it when a decision changes, and note the date.

_Last updated: 07 Oct 2026_

## Goal

Show Eucalyptus a working, honest version of the job: a standardised evaluation layer for AI patient conversations.

## Why this angle

- Juniper's AI health companion **June** is built with an outside vendor and serves 200,000+ patients. Vendors report their own safety numbers.
- The role exists to give Euc **one independent way to check every AI tool** it uses.
- So the harness is **vendor-neutral**: it only sees questions and answers.

## Scope

**In**

- ~95 single-turn test cases: Wegovy and Mounjaro, Australian rules, English
- Two versions of the bot under test:
  - **bare**: no instruction
  - **grounded**: a support-assistant instruction plus the two CMI leaflets
- An `assistant_scope` setting: `medical_support` or `coaching` (June-style). The expected behaviour can differ by scope.
- Seven layers (L0–L6), see `CLAUDE.md`

**Out (named as future work)**

- Multi-turn conversations, agents and tool use
- Languages other than English; markets other than Australia
- Activation probes, calibrated judge fusion, conformal thresholds
- Testing June itself (members-only)

## Test set additions (Stage 1b)

| Addition | Count | Why | Status |
|---|---|---|---|
| Style variants of critical cases (dramatic, minimising, second-language) | ~9 | Same symptoms must get the same triage | Cut (07 Oct 2026) |
| Coaching-vs-medical boundary cases | 8 | The line a coaching bot like June must hold | Done |
| Over-safety cases | ~8 | A bot that sends everyone to Emergency is unsafe too | Cut (07 Oct 2026) |
| Adversarial variants | 10 | Buried red flags, fake policy citations, pushback | Done |
| Trial-results / promotional claims | 1 | Bot must not quote trial figures as promises | Cut (07 Oct 2026) |

Cut because synthetic rewordings don't reflect real customer chats, and they are beyond the scope of this demo. Named as future work.

## Experiments (written before running)

| # | Question | Measure |
|---|---|---|
| E1 | Does the full stack catch more severe misses than one judge? | Severe miss rate at similar review load |
| E2 | Do judges flip on wording that shouldn't matter? | Counterfactual flip rate, locked critical cases |
| E3 | Does allowing `unsure` reduce confident mistakes? | Error rate on cases the judge decided |

If E1 shows no gain, the simpler design wins. Say so.

**Watch for:** judges sharing the bot's US-rule blind spot (e.g. the 48-hour missed-dose rule).

## Tools

| Tool | Status | Why |
|---|---|---|
| Python service + pytest + Pydantic | Core | Ad: "reliable services, not just notebooks" |
| promptfoo | Core | Named in the ad; runs L1 rule checks |
| BigQuery + dbt | Core | Euc's analytics stack; GCP + SQL |
| Dagster | Core-lite | Euc's orchestrator; one scheduled job |
| GitHub Actions | Core | Regression alert when prompts or models change |
| Datadog LLM Observability | Optional | "Dashcam" demo; 14-day trial, so record it |
| Ragas | Stretch | Grounded bot only |
| Databricks | Skip | Competing platform to Euc's GCP stack |
| LangSmith | Skip | Not using LangChain; promptfoo covers it |

## Headline metrics

1. **Severe miss rate**, with a 95% bootstrap range
2. **Human review load** at that miss rate

No single overall safety percentage, anywhere.

## Open decisions

- [x] Bot under test: Claude Haiku 4.5 (Anthropic), cheapest first; compare other models later (07 Oct 2026)
- [x] Judge pair: OpenAI + Google Gemini, models chosen at Stage 5 (07 Oct 2026)
- [x] Budget cap: A$5 per run (07 Oct 2026)
- [ ] Clinician reviewer for the ~15 critical cases (pharmacist, nurse or GP)
- [ ] Datadog in or out

## Pitch lines

> HealthBench and MedHELM showed AI judges can match clinician agreement. I applied the same validation to Australian GLP-1 patient questions, and added one check they don't report: whether the judges miss the same local-rule errors as the chatbot.

> A 2% escalation rate is good news only if the other 98% didn't need escalating. My harness measures that second number.
