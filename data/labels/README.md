# Labels

Reference labels for run `20261007T061343Z-71f54e` (130 answers: 65 medical-support cases × bare + grounded, dev and locked). Scores follow `rubric/rubric.md`: safety, grounding, scope, escalation as 0 / 1 / 2 / `unsure`.

| File | Who labelled | How |
|---|---|---|
| `label_sheet.csv` | The project author, by hand | Blind (no rule or judge results), in the Streamlit app with the leaflet section on screen. A subset of priority (critical / high-risk dev) answers. Not a clinician. |
| `claude_labels.csv` | Claude (`claude-opus-5-5`), every row marked in `labeller` | All 130 answers. **Not blind:** Claude had seen `must_include`, `must_not_include` and the Stage 3 rule results. Same model family as the bot under test (Claude Haiku 4.5), so it may share the bot's blind spots. |

### Locked set (run `20261008T141049Z-88741d`)

| File | Who labelled | How |
|---|---|---|
| `claude_labels_locked.csv` | Claude (`claude-opus-5-5`) | The 24 locked high/critical answers, labelled 09 Oct 2026 because the author ran out of time before applying. **Not blind and not human:** Claude had seen `must_include`/`must_not_include`, the leaflet text, and the judges' audit verdicts on some of these answers. Reported only as "AI reference labels". 3 hard fails, all from the v1 bot (PC-04, RF-01-ADV, RF-04-ADV). |

The scorecard keeps hand and AI labels apart (`label_kind`), never pooled.

## How to use them

- Treat `claude_labels.csv` as **AI reference labels**, never as human gold. Report judge agreement against it under that name.
- Where both files label the same answer, the human label wins and the disagreement is itself a result worth reporting.
- `needs_clinician` marks answers neither labeller could settle; a clinician review is the next step for those.
- Corrections are logged in `notes/criteria_drift.md` with the reason, never made silently.
