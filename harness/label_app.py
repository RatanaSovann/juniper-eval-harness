"""Stage 4: a local page for labelling the blind label sheet one answer at a time.

Run:  streamlit run harness/label_app.py

Reads and writes data/labels/label_sheet.csv (path from config.yaml). It shows only what is
on the sheet, so no rule-check or judge results can leak in. Nothing leaves your machine.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # streamlit runs this as a script

from harness.config import load_config  # noqa: E402
from harness.label_sheet import (CONFIDENCE_VALUES, SCORE_COLUMNS, SCORE_VALUES, is_labelled,  # noqa: E402
                                 read_sheet, save_sheet, set_labels)


def next_unlabelled(rows: list[dict], after: int) -> int | None:
    """Index of the first unlabelled row after `after`, wrapping round; None if all are done."""
    n = len(rows)
    return next((i % n for i in range(after + 1, after + 1 + n) if not is_labelled(rows[i % n])), None)


def go(i: int) -> None:
    st.session_state.idx = i
    st.rerun()


config = load_config()
path = config.labels.sheet
st.set_page_config(page_title="Label sheet", layout="centered")

if not path.exists():
    st.error(f"No sheet at {path}. Run: python -m harness.label_sheet")
    st.stop()
rows = read_sheet(path)  # read fresh every time, so the page always matches the file
done = sum(is_labelled(r) for r in rows)

if "idx" not in st.session_state:
    st.session_state.idx = next_unlabelled(rows, -1) or 0
idx = st.session_state.idx
row = rows[idx]

st.progress(done / len(rows), text=f"{done} / {len(rows)} labelled")
nav = st.columns(4)
if nav[0].button("◀ Prev", disabled=idx == 0, use_container_width=True):
    go(idx - 1)
if nav[1].button("Next ▶", disabled=idx == len(rows) - 1, use_container_width=True):
    go(idx + 1)
nxt = next_unlabelled(rows, idx)
if nav[2].button("Next unlabelled", disabled=nxt is None, use_container_width=True):
    go(nxt)
jump = nav[3].number_input("Row", 1, len(rows), idx + 1, label_visibility="collapsed")
if jump - 1 != idx:
    go(jump - 1)

st.caption(f"Row {idx + 1} · {row['case_id']} · {'labelled ✓' if is_labelled(row) else 'not labelled'}")
st.markdown(f"**Question:** {row['patient_question']}")
st.markdown(f"**Expected:** `{row['expected_behaviour']}` · **Source:** {row['source_ref']}")
with st.container(border=True):
    st.markdown(row["answer"])

with st.form(f"labels-{idx}"):
    picks = {}
    for c in SCORE_COLUMNS:
        current = SCORE_VALUES.index(row[c]) if row[c] in SCORE_VALUES else None
        picks[c] = st.radio(c.capitalize(), SCORE_VALUES, index=current, horizontal=True, key=f"{c}-{idx}")
    conf = row["label_confidence"]
    picks["label_confidence"] = st.radio("Confidence", CONFIDENCE_VALUES, horizontal=True, key=f"conf-{idx}",
                                         index=CONFIDENCE_VALUES.index(conf) if conf in CONFIDENCE_VALUES else None)
    picks["note"] = st.text_input("Note", row["note"], key=f"note-{idx}")
    if st.form_submit_button("Save & next", type="primary"):
        try:
            set_labels(row, picks)
            save_sheet(path, rows)
        except ValueError as e:
            st.error(f"Not saved: {e}")
        except PermissionError:
            st.error("Not saved: the sheet is open in another program (Excel?). Close it and try again.")
        else:
            go(next_unlabelled(rows, idx) if next_unlabelled(rows, idx) is not None else idx)

with st.expander("Rubric"):
    st.markdown(config.labels.rubric.read_text(encoding="utf-8"))
