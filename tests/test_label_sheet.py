"""Tests for the Stage 4 label sheet. Answers are faked; no API is called."""
import csv

import pytest

from harness.label_sheet import (LABEL_COLUMNS, SHEET_COLUMNS, build_rows, is_labelled, read_sheet, save_sheet,
                                 leaflet_sections, set_labels, source_excerpts, write_sheet)
from harness.models import TestCase
from tests.test_rule_checks import answer
from tests.test_validate_cases import GOOD

CASES = [TestCase(**{**GOOD, "case_id": f"MD-0{i}", "scenario_id": f"MD-0{i}"}) for i in range(1, 6)]
ANSWERS = [answer(c.case_id, v, text=f"answer {c.case_id} {v}") for c in CASES for v in ("bare", "grounded")]


def test_rows_are_blind_and_unlabelled():
    rows = build_rows(CASES, ANSWERS, seed=1)
    assert len(rows) == 10
    for r in rows:
        assert list(r) == SHEET_COLUMNS
        assert all(r[c] == "" for c in LABEL_COLUMNS)
    # nothing that hints at the right answer or the partition
    for leak in ("must_include", "must_not_include", "rule_checks", "trap", "partition", "risk_level"):
        assert leak not in SHEET_COLUMNS


def test_rows_join_case_fields():
    row = next(r for r in build_rows(CASES, ANSWERS, seed=1) if r["case_id"] == "MD-02" and r["variant"] == "bare")
    assert row["answer"] == "answer MD-02 bare"
    assert row["patient_question"] == CASES[1].patient_question
    assert row["expected_behaviour"] == CASES[1].expected_behaviour
    assert row["source_ref"] == CASES[1].source_ref and row["run_id"] == "R1"


def test_shuffle_is_repeatable_and_changes_order():
    order = lambda seed: [(r["case_id"], r["variant"]) for r in build_rows(CASES, ANSWERS, seed)]
    assert order(1) == order(1)
    assert order(1) != [(a.case_id, a.variant) for a in ANSWERS]


def test_answer_for_unknown_case_is_an_error():
    with pytest.raises(ValueError, match="MD-09"):
        build_rows(CASES, ANSWERS + [answer("MD-09")], seed=1)


def test_write_sheet_has_bom_and_never_overwrites(tmp_path):
    path = tmp_path / "labels" / "label_sheet.csv"
    rows = build_rows(CASES, [answer(text="Don’t stop")], seed=1)
    write_sheet(path, rows)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM tells Excel it's UTF-8
    with path.open(newline="", encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f))["answer"] == "Don’t stop"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_sheet(path, rows)
    assert path.read_bytes() == before


LABELS = {"safety": "2", "grounding": "1", "scope": "2", "escalation": "unsure",
          "label_confidence": "fairly_sure", "note": " check s4 "}


def test_read_then_save_is_byte_identical(tmp_path):
    path = tmp_path / "label_sheet.csv"
    write_sheet(path, build_rows(CASES, ANSWERS + [answer("MD-01", text="line 1\nline 2, \"quoted\"")], seed=1))
    before = path.read_bytes()
    save_sheet(path, read_sheet(path))
    assert path.read_bytes() == before
    assert not (tmp_path / "label_sheet.csv.tmp").exists()


def test_saving_one_label_changes_only_that_row(tmp_path):
    path = tmp_path / "label_sheet.csv"
    write_sheet(path, build_rows(CASES, ANSWERS, seed=1))
    rows = read_sheet(path)
    set_labels(rows[3], LABELS)
    save_sheet(path, rows)
    after = read_sheet(path)
    assert after[3]["escalation"] == "unsure" and after[3]["note"] == "check s4" and is_labelled(after[3])
    original = build_rows(CASES, ANSWERS, seed=1)
    assert [r for i, r in enumerate(after) if i != 3] == [r for i, r in enumerate(original) if i != 3]


@pytest.mark.parametrize("bad", [{"safety": ""}, {"scope": "3"}, {"label_confidence": "unsure"}])
def test_incomplete_or_invalid_labels_are_refused(bad):
    row = build_rows(CASES, ANSWERS, seed=1)[0]
    before = dict(row)
    with pytest.raises(ValueError):
        set_labels(row, {**LABELS, **bad})
    assert row == before and not is_labelled(row)


def test_read_sheet_rejects_wrong_columns(tmp_path):
    path = tmp_path / "label_sheet.csv"
    path.write_text("case_id,answer\nMD-01,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_sheet(path)


LEAFLET = """# Wegovy
### 1. Why?
summary one
### 4. How?
summary four
# Wegovy full CMI
### 1. Why?
full one
### 4. How?
full four
#### Missed dose
skip it after 5 days
### 5. While using?
full five
"""


def test_leaflet_sections_keep_the_full_version_with_subsections():
    s = leaflet_sections(LEAFLET)
    assert s[1] == "### 1. Why?\nfull one"
    assert s[4] == "### 4. How?\nfull four\n#### Missed dose\nskip it after 5 days"
    assert s[5] == "### 5. While using?\nfull five"


def test_source_excerpts_handles_several_sources_and_missing_ones():
    out = source_excerpts("WEG_CMI s4 s9; JUNIPER_FAQ", {"WEG_CMI": LEAFLET})
    assert [t for t, _ in out] == ["WEG_CMI s4", "WEG_CMI s9", "JUNIPER_FAQ"]
    assert out[0][1].startswith("### 4. How?")
    assert "sources.md" in out[1][1] and "sources.md" in out[2][1]
