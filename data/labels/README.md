# Labels

Reference labels for run `20261007T061343Z-71f54e` (130 answers: 65 medical-support cases × bare + grounded, dev and locked). Scores follow `rubric/rubric.md`: safety, grounding, scope, escalation as 0 / 1 / 2 / `unsure`.

| File | Who labelled | How |
|---|---|---|
| `label_sheet.csv` | The project author, by hand | Blind (no rule or judge results), in the Streamlit app with the leaflet section on screen. A subset of priority (critical / high-risk dev) answers. Not a clinician. |
| `claude_labels.csv` | Claude (`claude-opus-5-5`), every row marked in `labeller` | All 130 answers. **Not blind:** Claude had seen `must_include`, `must_not_include` and the Stage 3 rule results. Same model family as the bot under test (Claude Haiku 4.5), so it may share the bot's blind spots. |

## How to use them

- Treat `claude_labels.csv` as **AI reference labels**, never as human gold. Report judge agreement against it under that name.
- Where both files label the same answer, the human label wins and the disagreement is itself a result worth reporting.
- `needs_clinician` marks answers neither labeller could settle; a clinician review is the next step for those.
- Corrections are logged in `notes/criteria_drift.md` with the reason, never made silently.
