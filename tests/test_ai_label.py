"""Tests for the blind AI labeller. A fake model stands in for the API, so nothing is sent."""
import csv
import json

import pytest
import yaml

from harness.agreement import load_labels
from harness.ai_label import (OUT_COLUMNS, build_system, build_user, parse_labels, read_done, run,
                              setup_problems)
from harness.config import load_config
from harness.generate import Completion, CostCapReached
from harness.label_sheet import build_rows, write_sheet
from harness.validate_cases import COLUMNS, validate
from tests.test_generate import make_config
from tests.test_rule_checks import answer

GOOD_REPLY = json.dumps({"safety": "2", "grounding": "2", "scope": "2", "escalation": "1",
                         "label_confidence": "fairly_sure", "note": "Slightly under-escalates."})
LEAFLET = "### 4. How do I use it?\nIf you forget a dose, take it within 5 days.\n### 5. Other\nMore text."


class FakeLabeller:
    """Returns the queued replies in order (the last one repeats) and remembers each request."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies or [GOOD_REPLY]), []

    def complete(self, system, user):
        self.calls.append((system, user))
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return Completion(text, input_tokens=2000, output_tokens=100, stop_reason="end_turn")


def make_ai_config(tmp_path, cap=5.0, model="labeller-fake", prices=(1.0, 5.0)):
    """make_config + an ai_labeller block, a rubric, a sectioned leaflet and MD-03 made locked."""
    make_config(tmp_path, cap=cap)
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    cfg["ai_labeller"] = {"provider": "anthropic", "model": model, "temperature": None, "max_tokens": 400,
                          "price_usd_per_mtok": {"input": prices[0], "output": prices[1]},
                          "prompt": "ai_labeller.txt"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "ai_labeller.txt").write_text("LABELLER INSTRUCTION", encoding="utf-8")
    (tmp_path / "rubric.md").write_text("RUBRIC TEXT", encoding="utf-8")
    (tmp_path / "leaflet.txt").write_text(LEAFLET, encoding="utf-8")
    with (tmp_path / "cases.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[2]["partition"] = "locked"  # MD-03
    with (tmp_path / "cases.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return load_config(tmp_path / "config.yaml", root=tmp_path)


def make_sheet(config, tmp_path):
    """A blind sheet for 3 medical cases x 2 variants of run R1, as harness.label_sheet makes it."""
    cases = [c for c in validate(config.paths.cases, config.paths.sources)[0] if c.assistant_scope == "medical_support"]
    answers = [answer(c.case_id, v, text=f"Fake answer number {i}.")
               for i, (c, v) in enumerate((c, v) for c in cases for v in ("bare", "grounded"))]
    sheet = tmp_path / "labels" / "blind_sheet.csv"
    write_sheet(sheet, build_rows(cases, answers, seed=1))
    return sheet


def read_out(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def quiet(*_):
    pass


def test_labels_dev_rows_only_by_default(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    written, failed, spent = run(config, FakeLabeller(), sheet, out, log=quiet)
    rows = read_out(out)
    assert written == len(rows) == 4 and failed == []          # MD-01, MD-02 x 2 variants; MD-03 is locked
    assert {r["case_id"] for r in rows} == {"MD-01", "MD-02"}
    assert spent > 0


def test_partition_all_includes_locked(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    written, _, _ = run(config, FakeLabeller(), sheet, out, partition="all", log=quiet)
    assert written == 6


def test_labeller_never_sees_case_id_variant_or_answer_key(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    model = FakeLabeller()
    run(config, model, sheet, out, log=quiet)
    case = validate(config.paths.cases, config.paths.sources)[0][0]
    for system, user in model.calls:
        sent = system + user
        for leak in ("MD-0", "R1", case.must_include, case.must_not_include, case.trap, case.rule_checks):
            assert leak not in sent
        assert "variant" not in sent.lower() and "case_id" not in sent
        assert "LABELLER INSTRUCTION" in system and "RUBRIC TEXT" in system
        assert case.patient_question in user and "take it within 5 days" in user  # leaflet section s4


def test_build_user_shows_only_the_cited_section():
    row = {"patient_question": "Q?", "expected_behaviour": "answer", "source_ref": "WEG_CMI s4", "answer": "A."}
    user = build_user(row, {"WEG_CMI": LEAFLET})
    assert "take it within 5 days" in user and "More text." not in user
    assert user.index("Patient question") < user.index("<source") < user.index("<answer>")


def test_output_matches_claude_labels_format_and_agreement_can_read_it(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    run(config, FakeLabeller(), sheet, out, log=quiet)
    with out.open(newline="", encoding="utf-8-sig") as f:
        assert csv.DictReader(f).fieldnames == OUT_COLUMNS
    row = read_out(out)[0]
    assert (row["safety"], row["escalation"], row["label_confidence"]) == ("2", "1", "fairly_sure")
    assert row["labeller"] == "labeller-fake (blind, ai_labeller)"
    labels = load_labels(out, "R1", {"MD-01", "MD-02"})        # the same reader agreement.py uses
    assert len(labels) == 4 and labels[("MD-01", "bare")]["escalation"] == 1


def test_unreadable_reply_gets_one_retry_then_is_left_unlabelled(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    model = FakeLabeller("not json", GOOD_REPLY)           # first row: bad, then good; the rest good
    written, failed, _ = run(config, model, sheet, out, log=quiet)
    assert written == 4 and failed == [] and len(model.calls) == 5
    assert "could not be read" in model.calls[1][1]

    out2 = tmp_path / "labels" / "ai2.csv"
    written, failed, _ = run(config, FakeLabeller('{"safety": "5"}'), sheet, out2, log=quiet)
    assert written == 0 and len(failed) == 4                 # never guessed
    assert read_out(out2) == []


def test_running_again_skips_rows_already_labelled(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    run(config, FakeLabeller(), sheet, out, limit=2, log=quiet)
    assert len(read_out(out)) == 2
    model = FakeLabeller()
    written, _, _ = run(config, model, sheet, out, log=quiet)
    assert written == 2 and len(model.calls) == 2
    rows = read_out(out)
    assert len(rows) == 4 and len({(r["case_id"], r["variant"]) for r in rows}) == 4
    assert len(read_done(out)) == 4


def test_cost_cap_stops_before_the_call_and_keeps_rows(tmp_path):
    config = make_ai_config(tmp_path, cap=0.008)             # room for two rows, not three
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    with pytest.raises(CostCapReached, match="run again to continue"):
        run(config, FakeLabeller(), sheet, out, log=quiet)
    assert 0 < len(read_out(out)) < 4


def test_existing_file_with_other_columns_is_refused(tmp_path):
    config = make_ai_config(tmp_path)
    sheet, out = make_sheet(config, tmp_path), tmp_path / "labels" / "ai.csv"
    out.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected"):
        run(config, FakeLabeller(), sheet, out, log=quiet)


@pytest.mark.parametrize("reply, ok", [
    (GOOD_REPLY, True),
    ("```json\n" + GOOD_REPLY + "\n```", True),
    (json.dumps({"safety": 2, "grounding": 1, "scope": 0, "escalation": "unsure",
                 "label_confidence": "sure", "note": ""}), True),       # numbers are fine
    (json.dumps({"safety": "2", "grounding": "2", "scope": "2", "escalation": "2"}), False),  # no confidence
    (json.dumps({"safety": "3", "grounding": "2", "scope": "2", "escalation": "2",
                 "label_confidence": "sure"}), False),
    ("[1, 2]", False),
    ("no json here", False),
])
def test_parse_labels(reply, ok):
    labels = parse_labels(reply)
    assert (labels is not None) == ok
    if ok:
        assert all(labels[m] in ("0", "1", "2", "unsure") for m in ("safety", "grounding", "scope", "escalation"))


def test_setup_problems(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    config = make_ai_config(tmp_path)
    assert setup_problems(config, tmp_path / "labels" / "ai.csv") == []
    # never into a hand-label file
    assert any("hand-label" in p for p in setup_problems(config, config.labels.sheet))
    # unfilled model and prices are refused
    config = make_ai_config(tmp_path, model="", prices=(0, 0))
    problems = setup_problems(config, tmp_path / "labels" / "ai.csv")
    assert any("model" in p for p in problems) and any("prices" in p for p in problems)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert any("ANTHROPIC_API_KEY" in p for p in setup_problems(config, tmp_path / "x.csv"))


def test_build_system_has_instruction_and_rubric(tmp_path):
    config = make_ai_config(tmp_path)
    system = build_system(config)
    assert system.startswith("LABELLER INSTRUCTION") and "<rubric>\nRUBRIC TEXT\n</rubric>" in system
