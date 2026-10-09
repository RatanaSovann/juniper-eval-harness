# Build log

Five lines per session. Newest at the top.

Template:

```
## YYYY-MM-DD · Stage X
- Built:
- Surprise:
- Finding so far:
- Open question:
- First task next session:
```

---

## 2026-10-09 · Stage 5  — DRAFT (Claude), edit or delete
- Built: two judges (gpt-6-luna, gemini-3.5-flash-lite) scoring 88 dev answers of the v1 vs v2 run twice each; agreement report vs my 42 hand labels; SDK retries + --resume after a Gemini 503.
- Surprise: Gemini called 97% of answers safe and missed every hard fail, including MD-01's US 48-hour rule, the blind spot the brief warned about. OpenAI caught them but changed its own safety score on 12/88 answers.
- Finding so far: kappa ~0 for both judges is mostly a prevalence artefact (almost all labels are 2); hard-fail catches tell the real story. Judges also exposed at least one wrong label of mine (SC-07 v1: Wegovy is approved from age 12).
- Open question: is a cheap second judge worth anything, or should Gemini be upgraded / used only as a tiebreaker? Note v1 vs v2 changes prompt and leaflets at once.
- First task next session: review the 64 disagreements, fix + log labels, then write routing_rules.md.

## 2026-10-04 · Stage 1
- Built: 55 test cases from the Australian Wegovy and Mounjaro CMI, 4-metric rubric, validator script.
- Surprise: the Australian and US missed-dose rules differ (5 days vs 48 hours), a ready-made trap.
- Finding so far: 33 of 55 cases carry a known trap.
- Open question: who could clinically review the ~15 critical cases?
- First task next session: Stage 1b, upgrade the test set.
