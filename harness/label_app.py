"""Stage 4: a local page for labelling the blind label sheet one answer at a time.

Run:  streamlit run harness/label_app.py

Reads and writes data/labels/label_sheet.csv (path from config.yaml). It shows only what is
on the sheet plus the leaflet section its source_ref names, so no rule-check or judge results
can leak in. The sidebar can narrow the rows to dev cases at chosen risk levels; the partition
and risk level are used to filter, never shown. Nothing leaves your machine.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # streamlit runs this as a script

from harness.config import load_config  # noqa: E402
from harness.label_sheet import (CONFIDENCE_VALUES, SCORE_COLUMNS, SCORE_VALUES, is_labelled,  # noqa: E402
                                 read_sheet, save_sheet, set_labels, source_excerpts)
from harness.validate_cases import validate  # noqa: E402

RISK_LEVELS = ["critical", "high", "medium", "low"]


def next_unlabelled(rows: list[dict], order: list[int], after: int) -> int | None:
    """Position in `order` of the first unlabelled row after position `after`, wrapping; None if all done."""
    n = len(order)
    return next((p % n for p in range(after + 1, after + 1 + n) if not is_labelled(rows[order[p % n]])), None)


def go(pos: int) -> None:
    st.session_state.pos = pos
    st.rerun()


config = load_config()
path = config.labels.sheet
st.set_page_config(page_title="Label sheet", layout="wide")

if not path.exists():
    st.error(f"No sheet at {path}. Run: python -m harness.label_sheet")
    st.stop()
rows = read_sheet(path)  # read fresh every time, so the page always matches the file
cases = {c.case_id: c for c in validate(config.paths.cases, config.paths.sources)[0]}
leaflets = {l.key: l.path.read_text(encoding="utf-8") for l in config.leaflets}

with st.sidebar:
    st.header("Which answers")
    show_all = st.toggle("All answers", value=False)
    risks = st.multiselect("Dev cases at risk level", RISK_LEVELS, default=["critical", "high"], disabled=show_all)
order = [i for i, r in enumerate(rows)
         if show_all or (cases[r["case_id"]].partition == "dev" and cases[r["case_id"]].risk_level in risks)]
if not order:
    st.info("No answers match the sidebar filter.")
    st.stop()
if st.session_state.get("filter") != (show_all, tuple(risks)):  # filter changed: restart at first unlabelled
    st.session_state.filter = (show_all, tuple(risks))
    st.session_state.pos = next_unlabelled(rows, order, -1) or 0
pos = min(st.session_state.pos, len(order) - 1)
row = rows[order[pos]]
done = sum(is_labelled(rows[i]) for i in order)

st.progress(done / len(order), text=f"{done} / {len(order)} labelled in this set "
                                    f"({sum(map(is_labelled, rows))} / {len(rows)} overall)")
nav = st.columns(4)
if nav[0].button("◀ Prev", disabled=pos == 0, use_container_width=True):
    go(pos - 1)
if nav[1].button("Next ▶", disabled=pos == len(order) - 1, use_container_width=True):
    go(pos + 1)
nxt = next_unlabelled(rows, order, pos)
if nav[2].button("Next unlabelled", disabled=nxt is None, use_container_width=True):
    go(nxt)
jump = nav[3].number_input("Row", 1, len(order), pos + 1, label_visibility="collapsed")
if jump - 1 != pos:
    go(jump - 1)

left, right = st.columns([3, 2])
with left:
    st.caption(f"{pos + 1} of {len(order)} · {row['case_id']} · "
               f"{'labelled ✓' if is_labelled(row) else 'not labelled'}")
    st.markdown(f"**Question:** {row['patient_question']}")
    st.markdown(f"**Expected:** `{row['expected_behaviour']}` · **Source:** {row['source_ref']}")
    with st.container(border=True):
        st.markdown(row["answer"])

    with st.form(f"labels-{order[pos]}"):
        picks = {}
        for c in SCORE_COLUMNS:
            current = SCORE_VALUES.index(row[c]) if row[c] in SCORE_VALUES else None
            picks[c] = st.radio(c.capitalize(), SCORE_VALUES, index=current, horizontal=True, key=f"{c}-{order[pos]}")
        conf = row["label_confidence"]
        picks["label_confidence"] = st.radio(
            "Confidence", CONFIDENCE_VALUES, horizontal=True, key=f"conf-{order[pos]}",
            index=CONFIDENCE_VALUES.index(conf) if conf in CONFIDENCE_VALUES else None)
        picks["note"] = st.text_input("Note", row["note"], key=f"note-{order[pos]}")
        if st.form_submit_button("Save & next", type="primary"):
            try:
                set_labels(row, picks)
                save_sheet(path, rows)
            except ValueError as e:
                st.error(f"Not saved: {e}")
            except PermissionError:
                st.error("Not saved: the sheet is open in another program (Excel?). Close it and try again.")
            else:
                nxt = next_unlabelled(rows, order, pos)
                go(nxt if nxt is not None else pos)

with right:
    st.subheader("Source")
    for title, text in source_excerpts(row["source_ref"], leaflets):
        with st.expander(title, expanded=True):
            with st.container(height=420):
                st.markdown(text)
    with st.expander("Rubric"):
        st.markdown(config.labels.rubric.read_text(encoding="utf-8"))
