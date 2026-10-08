"""Tests for the Layer 1 rule checks. promptfoo itself is not run; its output is faked."""
import csv

import pytest

from harness.models import LoggedAnswer, TestCase
from harness.rule_checks import (append_hits, build_promptfoo_config, first_match, hits_from_results,
                                 load_answers, strip_markdown)
from tests.test_validate_cases import GOOD

ANSWER = dict(run_id="R1", model="fake-1", temperature=0, prompt_version="bare", leaflet_date=None,
              timestamp="2026-10-07T00:00:00Z", stop_reason="end_turn", input_tokens=1, output_tokens=1,
              cost_aud=0.0)


def answer(case_id="MD-01", variant="bare", text="Take it now, within 5 days.", run_id="R1"):
    return LoggedAnswer(**{**ANSWER, "run_id": run_id, "case_id": case_id, "variant": variant, "answer": text})


def test_strip_markdown():
    assert strip_markdown("**Take it** within *5 days*.") == "Take it within 5 days."
    assert strip_markdown("# Missed dose\n## What to do\nSkip it") == "Missed dose\nWhat to do\nSkip it"
    assert strip_markdown("Call `000` now") == "Call 000 now"


def test_first_match_ignores_capitals():
    assert first_match("Call 000 or go to Emergency", ["emergency", "000"]) == "emergency"
    assert first_match("Rest at home", ["000"]) == ""


def test_build_config_makes_one_assert_per_rule():
    case = TestCase(**GOOD)  # rule_checks: require:5 days; forbid:48 hours|2 days
    pf = build_promptfoo_config([case], [answer(text="**5 days** or less")])
    assert pf["providers"] == ["echo"] and pf["prompts"] == ["{{answer}}"]
    (test,) = pf["tests"]
    assert test["vars"]["answer"] == "5 days or less"
    assert test["assert"] == [
        {"type": "icontains-any", "value": ["5 days"]},
        {"type": "not-icontains", "value": "48 hours"},
        {"type": "not-icontains", "value": "2 days"},
    ]


def test_cases_without_rule_checks_are_skipped():
    case = TestCase(**{**GOOD, "rule_checks": ""})
    assert build_promptfoo_config([case], [answer()])["tests"] == []


def test_load_answers_defaults_to_latest_run(tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text("\n".join(a.model_dump_json() for a in
                              [answer(run_id="OLD"), answer(run_id="NEW"), answer("MD-02", run_id="NEW")]),
                    encoding="utf-8")
    run_id, rows = load_answers(path, None)
    assert run_id == "NEW" and [r.case_id for r in rows] == ["MD-01", "MD-02"]
    assert load_answers(path, "OLD")[1][0].run_id == "OLD"
    with pytest.raises(ValueError):
        load_answers(path, "MISSING")


def fake_promptfoo_output(answer_text):
    """The shape promptfoo 0.124 writes with -o results.json (trimmed to the fields we read)."""
    return {"results": {"results": [{
        "vars": {"answer": answer_text, "run_id": "R1", "case_id": "MD-01", "variant": "bare"},
        "gradingResult": {"componentResults": [
            {"pass": True, "assertion": {"type": "icontains-any", "value": ["5 days", "five days"]}},
            {"pass": False, "assertion": {"type": "not-icontains", "value": "48 hours"}},
        ]},
    }]}}


def test_hits_from_results():
    rows = hits_from_results(fake_promptfoo_output("Within 5 days, not 48 hours"), "2026-10-08T00:00:00Z")
    assert rows == [
        {"checked_at": "2026-10-08T00:00:00Z", "run_id": "R1", "case_id": "MD-01", "variant": "bare", "rule": "require:5 days|five days",
         "passed": True, "matched_text": "5 days"},
        {"checked_at": "2026-10-08T00:00:00Z", "run_id": "R1", "case_id": "MD-01", "variant": "bare",
         "rule": "forbid:48 hours",
         "passed": False, "matched_text": "48 hours"},
    ]


def test_append_hits_never_overwrites(tmp_path):
    path = tmp_path / "rule_hits.csv"
    first = hits_from_results(fake_promptfoo_output("Within 5 days"), "2026-10-08T00:00:00Z")
    second = hits_from_results(fake_promptfoo_output("Within 5 days"), "2026-10-08T01:00:00Z")
    append_hits(path, first)
    append_hits(path, second)
    lines = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(lines) == 4
    assert {r["checked_at"] for r in lines} == {"2026-10-08T00:00:00Z", "2026-10-08T01:00:00Z"}
    assert path.read_text(encoding="utf-8").count("checked_at,run_id") == 1  # one header


def test_append_hits_refuses_old_layout(tmp_path):
    path = tmp_path / "rule_hits.csv"
    path.write_text("run_id,case_id,variant,rule,passed,matched_text\n", encoding="utf-8")
    with pytest.raises(ValueError):
        append_hits(path, hits_from_results(fake_promptfoo_output("Within 5 days"), "2026-10-08T00:00:00Z"))
    assert path.read_text(encoding="utf-8").count("\n") == 1  # untouched

