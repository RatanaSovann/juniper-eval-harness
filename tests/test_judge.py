"""Tests for the judges. Fake judges stand in for OpenAI and Gemini, so no API is called."""
import csv
import json
from datetime import datetime, timezone

import pytest

from harness.generate import Completion, CostCapReached
from harness.judge import parse_scores, run, setup_problems
from harness.models import Judgement, LoggedAnswer
from harness.validate_cases import COLUMNS
from tests.test_generate import make_config

GOOD_JSON = json.dumps({m: {"score": 2, "evidence": "Take it now."}
                        for m in ("safety", "grounding", "scope", "escalation")})


class FakeJudge:
    """Returns the queued replies in order (the last one repeats) and remembers each request."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies or [GOOD_JSON]), []

    def complete(self, system, user):
        self.calls.append((system, user))
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return Completion(text, input_tokens=1000, output_tokens=100, stop_reason="stop")


def make_judge_config(tmp_path, cap=5.0):
    """make_config plus a locked case, a judge instruction, a rubric and three logged answers."""
    config = make_config(tmp_path, cap=cap)
    with config.paths.cases.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[2]["partition"] = "locked"  # MD-03
    with config.paths.cases.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (tmp_path / "judge.txt").write_text("JUDGE INSTRUCTION", encoding="utf-8")
    (tmp_path / "rubric.md").write_text("RUBRIC TEXT", encoding="utf-8")
    config.paths.answers.parent.mkdir(parents=True)
    answers = [("RUN-1", "MD-01"), ("RUN-1", "MD-02"), ("RUN-1", "MD-03"), ("RUN-0", "MD-01")]
    with config.paths.answers.open("w", encoding="utf-8") as f:
        for run_id, case_id in answers:
            a = LoggedAnswer(run_id=run_id, case_id=case_id, variant="grounded", model="bot", temperature=0,
                             prompt_version="grounded_v2", leaflet_date=None,
                             timestamp=datetime.now(timezone.utc), answer=f"Answer to {case_id}.",
                             stop_reason="end_turn", input_tokens=1, output_tokens=1, cost_aud=0)
            f.write(a.model_dump_json() + "\n")
    return config


def read_judgements(config):
    return [Judgement(**json.loads(l)) for l in config.paths.judgements.read_text(encoding="utf-8").splitlines()]


def test_scores_dev_answers_of_target_run_with_each_judge_and_repeat(tmp_path):
    config = make_judge_config(tmp_path)
    models = {"openai": FakeJudge(), "gemini": FakeJudge()}
    _, written, spent = run(config, models, log=lambda *_: None)
    rows = read_judgements(config)
    # MD-01 and MD-02 from RUN-1 (MD-03 is locked, RUN-0 is another run) x 2 judges x 2 repeats
    assert written == len(rows) == 8
    assert {r.case_id for r in rows} == {"MD-01", "MD-02"}
    assert {(r.judge, r.repeat) for r in rows} == {(j, n) for j in ("openai", "gemini") for n in (1, 2)}
    assert all(r.status == "valid" and r.attempts == 1 and r.scores.safety.score == 2 for r in rows)
    assert spent > 0


def test_judge_sees_leaflet_and_expected_behaviour_but_not_must_include(tmp_path):
    config = make_judge_config(tmp_path)
    judge = FakeJudge()
    run(config, {"openai": judge, "gemini": FakeJudge()}, limit=1, log=lambda *_: None)
    system, user = judge.calls[0]
    assert "JUDGE INSTRUCTION" in system and "RUBRIC TEXT" in system and "LEAFLET TEXT" in system
    assert "Expected behaviour: answer" in user and "Answer to MD-01." in user
    assert "Take it within 5 days" not in system + user  # must_include
    assert "48-hour rule" not in system + user            # must_not_include


def test_bad_json_is_retried_once_then_kept(tmp_path):
    config = make_judge_config(tmp_path)
    judge = FakeJudge("not json", GOOD_JSON)
    run(config, {"openai": judge, "gemini": FakeJudge()}, limit=1, log=lambda *_: None)
    first = [r for r in read_judgements(config) if r.judge == "openai"][0]
    assert first.status == "valid" and first.attempts == 2
    assert first.input_tokens == 2000  # both attempts are paid for
    assert "JSON only" in judge.calls[1][1]


def test_bad_json_twice_is_logged_invalid_with_raw_text(tmp_path):
    config = make_judge_config(tmp_path)
    run(config, {"openai": FakeJudge('{"safety": 5}'), "gemini": FakeJudge()}, limit=1, log=lambda *_: None)
    bad = [r for r in read_judgements(config) if r.judge == "openai"]
    assert all(r.status == "invalid" and r.scores is None and r.raw == '{"safety": 5}' for r in bad)
    assert all(r.attempts == 2 for r in bad)


def test_parse_scores_accepts_fences_unsure_and_digit_strings():
    text = "```json\n" + GOOD_JSON.replace('"score": 2', '"score": "unsure"', 1).replace('"score": 2', '"score": "1"', 1) + "\n```"
    scores = parse_scores(text)
    assert scores.safety.score == "unsure" and scores.grounding.score == 1
    assert parse_scores('{"safety": {"score": 3, "evidence": "x"}}') is None
    assert parse_scores("no json here") is None


def test_cost_cap_stops_before_overspending(tmp_path):
    config = make_judge_config(tmp_path, cap=0.01)
    with pytest.raises(CostCapReached):
        run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, log=lambda *_: None)
    rows = read_judgements(config) if config.paths.judgements.exists() else []
    assert sum(r.cost_aud for r in rows) <= 0.01


def test_runs_append_and_get_their_own_id(tmp_path):
    config = make_judge_config(tmp_path)
    models = {"openai": FakeJudge(), "gemini": FakeJudge()}
    first, _, _ = run(config, models, limit=1, log=lambda *_: None)
    second, _, _ = run(config, models, limit=1, log=lambda *_: None)
    rows = read_judgements(config)
    assert first != second and len(rows) == 8


def test_setup_problems_flags_unfilled_models_and_missing_keys(tmp_path, monkeypatch):
    config = make_judge_config(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    config.judge.judges[1].model = ""
    problems = "\n".join(setup_problems(config))
    assert "OPENAI_API_KEY" in problems and "gemini: fill in" in problems


def test_real_config_has_judge_settings():
    from harness.config import load_config

    config = load_config()
    assert config.judge.partition == "dev"
    assert {j.provider for j in config.judge.judges} == {"openai", "xai"}


def test_resume_skips_saved_verdicts_and_keeps_the_run_id(tmp_path):
    config = make_judge_config(tmp_path)
    first, _, _ = run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, limit=1, log=lambda *_: None)
    openai, gemini = FakeJudge(), FakeJudge()
    run_id, written, spent = run(config, {"openai": openai, "gemini": gemini}, resume=first, log=lambda *_: None)
    rows = read_judgements(config)
    assert run_id == first and written == 4  # only MD-02 was left
    assert len(openai.calls) == len(gemini.calls) == 2
    assert len(rows) == 8 and {r.judge_run_id for r in rows} == {first}
    assert len({(r.case_id, r.judge, r.repeat) for r in rows}) == 8  # no duplicates
    assert spent == pytest.approx(sum(r.cost_aud for r in rows))


def test_resume_counts_earlier_spend_toward_the_cap(tmp_path):
    config = make_judge_config(tmp_path)
    first, _, spent = run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, limit=1, log=lambda *_: None)
    config.cost.max_aud_per_run = spent + 0.001  # less than one more call's worst case
    with pytest.raises(CostCapReached):
        run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, resume=first, log=lambda *_: None)


def test_resume_refuses_unknown_run_or_changed_config(tmp_path):
    config = make_judge_config(tmp_path)
    with pytest.raises(ValueError, match="nothing to resume"):
        run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, resume="NOPE", log=lambda *_: None)
    first, _, _ = run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, limit=1, log=lambda *_: None)
    config.judge.judges[0].model = "openai-other"
    with pytest.raises(ValueError, match="has changed"):
        run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, resume=first, log=lambda *_: None)


def test_labelled_keeps_only_hand_labelled_answers(tmp_path):
    config = make_judge_config(tmp_path)
    config.labels.sheet.parent.mkdir(parents=True, exist_ok=True)
    with config.labels.sheet.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "case_id", "variant", "safety", "grounding", "scope", "escalation", "label_confidence"])
        w.writerow(["RUN-1", "MD-02", "grounded", 2, 2, 2, 2, "sure"])
        w.writerow(["RUN-1", "MD-01", "grounded", "", "", "", "", ""])  # not labelled yet
    run(config, {"openai": FakeJudge(), "gemini": FakeJudge()}, labelled=True, log=lambda *_: None)
    assert {r.case_id for r in read_judgements(config)} == {"MD-02"}


def test_grok_judge_uses_the_openai_sdk_pointed_at_xai(monkeypatch):
    from harness.judge import PROVIDERS
    from harness.config import load_config

    monkeypatch.setenv("XAI_API_KEY", "test-key")
    grok = next(j for j in load_config().judge.judges if j.provider == "xai")
    model = PROVIDERS["xai"](grok)
    assert str(model.client.base_url).startswith("https://api.x.ai/v1") and model.client.api_key == "test-key"


def test_every_real_judge_class_can_score(monkeypatch):
    """Guards against a class losing its complete() method (the bug that broke OpenAI after adding Grok)."""
    from harness.judge import PROVIDERS, OpenAIModel

    for cls in PROVIDERS.values():
        assert callable(getattr(cls, "complete", None)), cls.__name__
    assert "complete" in OpenAIModel.__dict__  # defined on OpenAIModel itself, which XAIModel inherits
