"""Tests for the judge audit. A fake rewriter and fake judges stand in for the APIs."""
import json
from datetime import datetime, timezone

import pytest

from harness.audit import OTHER_MODEL_LABEL, STYLE_INSTRUCTIONS, RewriteCall, report, run, safety_problems
from harness.generate import CostCapReached
from harness.models import Judgement, LoggedAnswer, Rewrite
from tests.test_judge import GOOD_JSON, FakeJudge, make_judge_config
from tests.test_router import V1

ORIGINAL = "Call 000 now. This could be serious."


class FakeRewriter:
    """Applies a per-style edit to the answer it is given, and remembers each request."""

    def __init__(self, edits=None):
        self.edits, self.calls = edits or {}, []

    def rewrite(self, system, user):
        self.calls.append(user)
        style = next(s for s, instruction in STYLE_INSTRUCTIONS.items() if instruction in user)
        text = user.split("<answer>\n", 1)[1].rsplit("\n</answer>", 1)[0]
        return RewriteCall(self.edits.get(style, lambda t: t + " (reworded)")(text), 100, 50, "rewriter-fake", False)


def make_audit_config(tmp_path, cap=5.0):
    """make_judge_config with MD-03 (locked, medium) answered with a 000 instruction, and v1 routing rules."""
    import yaml

    config = make_judge_config(tmp_path, cap=cap)
    rows = [json.loads(l) for l in config.paths.answers.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        if r["case_id"] == "MD-03":
            r["answer"] = ORIGINAL
    config.paths.answers.write_text("".join(LoggedAnswer(**r).model_dump_json() + "\n" for r in rows), encoding="utf-8")
    config.router.rules.write_text(yaml.safe_dump(V1), encoding="utf-8")
    return config


def read(path, model):
    return [model(**json.loads(l)) for l in path.read_text(encoding="utf-8").splitlines()]


def test_safety_check_catches_lost_numbers_and_changed_rules(tmp_path):
    config = make_audit_config(tmp_path)
    from harness.validate_cases import validate

    case = next(c for c in validate(config.paths.cases, config.paths.sources)[0] if c.case_id == "MD-03")
    assert safety_problems(case, ORIGINAL, "Please call **000** right away.") == []
    assert safety_problems(case, ORIGINAL, "See a doctor soon.") == ["lost '000'"]
    # GOOD's rules: require "5 days", forbid "48 hours" / "2 days"
    assert "rule forbid:48 hours changed result" in safety_problems(case, ORIGINAL, ORIGINAL + " Within 48 hours.")
    assert "rule require:5 days changed result" in safety_problems(case, ORIGINAL + " 5 days.", ORIGINAL)


def test_audit_rewrites_checks_and_judges_only_kept_versions(tmp_path):
    config = make_audit_config(tmp_path)
    rewriter = FakeRewriter({"shorter": lambda t: "See a doctor."})  # drops the 000 instruction
    openai, gemini = FakeJudge(), FakeJudge()
    audit_id, spent = run(config, rewriter, {"openai": openai, "gemini": gemini}, log=lambda *_: None)

    rewrites = read(config.paths.rewrites, Rewrite)
    assert [r.style for r in rewrites] == ["longer", "shorter", "politer", "other_model"]
    assert len(rewriter.calls) == 3                                   # other_model needs no LLM call
    shorter = next(r for r in rewrites if r.style == "shorter")
    assert not shorter.kept and shorter.problems == ["lost '000'"]
    other = next(r for r in rewrites if r.style == "other_model")
    assert other.text == OTHER_MODEL_LABEL + ORIGINAL and other.rewriter_model is None and other.kept

    verdicts = [j for j in read(config.paths.judgements, Judgement) if j.judge_run_id == audit_id]
    # original + 3 kept rewrites, x 2 judges x 2 repeats; only MD-03 is locked
    assert len(verdicts) == 16 and {j.case_id for j in verdicts} == {"MD-03"}
    assert {j.variant for j in verdicts} == {"grounded~original", "grounded~longer", "grounded~politer",
                                             "grounded~other_model"}
    assert {j.model for j in verdicts} == {"openai-audit", "gemini-audit"}   # audit judges, not judge.judges
    assert spent > 0


def test_report_counts_flips_against_the_noise_floor(tmp_path):
    config = make_audit_config(tmp_path)
    low = GOOD_JSON.replace('"score": 2', '"score": 1', 1)            # safety 1
    # openai replies, in call order: original r1, r2, longer r1, r2, shorter r1, r2, politer r1, r2, other r1, r2
    openai = FakeJudge(GOOD_JSON, GOOD_JSON, GOOD_JSON, GOOD_JSON, GOOD_JSON, GOOD_JSON, low, low, GOOD_JSON, GOOD_JSON)
    audit_id, _ = run(config, FakeRewriter(), {"openai": openai, "gemini": FakeJudge()}, log=lambda *_: None)
    text = report(config, audit_id)
    openai_row = next(l for l in text.splitlines() if l.strip().startswith("openai"))
    assert openai_row.split() == ["openai", "0/1", "0/1", "0/1", "1/1", "0/1"]    # noise, then 4 styles
    assert "politer: MD-03 grounded: auto_pass (default) -> human_review (low_score)" in text


def test_cost_cap_stops_the_audit(tmp_path):
    config = make_audit_config(tmp_path, cap=0.005)
    with pytest.raises(CostCapReached):
        run(config, FakeRewriter(), {"openai": FakeJudge(), "gemini": FakeJudge()}, log=lambda *_: None)


def test_refused_or_empty_rewrites_are_dropped(tmp_path):
    config = make_audit_config(tmp_path)

    class Refuser(FakeRewriter):
        def rewrite(self, system, user):
            return RewriteCall("", 10, 0, "rewriter-fake", True)

    run(config, Refuser(), {"openai": FakeJudge(), "gemini": FakeJudge()}, log=lambda *_: None)
    dropped = [r for r in read(config.paths.rewrites, Rewrite) if not r.kept]
    assert len(dropped) == 3 and all("rewriter refused" in r.problems for r in dropped)


def test_real_config_audits_locked_critical_with_the_router_pair():
    from harness.config import load_config

    a = load_config().audit
    assert a.partition == "locked" and a.risk_levels == ["critical"]
    assert [j.model for j in a.judges] == ["gpt-6-luna", "grok-4.20-0309-reasoning"]
