"""Tests for the Dagster pipeline. Every step is replaced by a fake; nothing is called or paid for."""
import pytest

pytest.importorskip("dagster")  # part of the [warehouse] extra

from dagster import DefaultScheduleStatus

from harness import pipeline


@pytest.fixture
def fakes(monkeypatch):
    """Replace each step with a fake that records what config it was given."""
    seen = {}

    class FakeModel:
        def __init__(self, *args):
            pass

    def fake_generate(config, model, log):
        return "ANS-1", 10, 1.0

    def fake_rules(argv):
        seen["rules"] = argv
        return 0

    def fake_judge(config, models, log):
        seen["judge_answers_run"] = config.judge.answers_run
        seen["judges"] = sorted(models)
        return "JUD-1", 20, 2.0

    def fake_route(config, log):
        seen["route"] = (config.judge.answers_run, config.router.judge_runs)
        return "RTE-1", []

    def fake_load(config, log):
        seen["loaded"] = True
        return {"answers": 10}

    class FakeDbt:
        def invoke(self, args):
            seen["dbt"] = args
            return type("Result", (), {"success": True, "exception": None})()

    monkeypatch.setattr(pipeline.generate, "AnthropicModel", FakeModel)
    monkeypatch.setattr(pipeline.generate, "run", fake_generate)
    monkeypatch.setattr(pipeline.rule_checks, "main", fake_rules)
    monkeypatch.setattr(pipeline.judge, "setup_problems", lambda config: [])
    monkeypatch.setattr(pipeline.judge, "PROVIDERS", {"openai": FakeModel, "xai": FakeModel})
    monkeypatch.setattr(pipeline.judge, "run", fake_judge)
    monkeypatch.setattr(pipeline.router, "route", fake_route)
    monkeypatch.setattr(pipeline.load, "load", fake_load)
    import dbt.cli.main
    monkeypatch.setattr(dbt.cli.main, "dbtRunner", FakeDbt)
    return seen


def test_full_eval_passes_each_run_id_to_the_next_step(fakes):
    result = pipeline.full_eval.execute_in_process()
    assert result.success
    assert fakes["rules"] == ["--run-id", "ANS-1"]
    assert fakes["judge_answers_run"] == "ANS-1" and fakes["judges"] == ["grok", "openai"]
    assert fakes["route"] == ("ANS-1", {"openai": "JUD-1", "grok": "JUD-1"})
    assert fakes["loaded"] and fakes["dbt"][0] == "build"


def test_refresh_scorecard_only_loads_and_builds(fakes):
    assert pipeline.refresh_scorecard.execute_in_process().success
    assert fakes["loaded"] and fakes["dbt"][0] == "build"
    assert "judge_answers_run" not in fakes and "rules" not in fakes


def test_pipeline_stops_when_a_step_fails(fakes, monkeypatch):
    monkeypatch.setattr(pipeline.rule_checks, "main", lambda argv: 1)
    result = pipeline.full_eval.execute_in_process(raise_on_error=False)
    assert not result.success and "judge_answers_run" not in fakes


def test_paid_schedule_is_off_by_default():
    assert pipeline.weekly_full_eval.default_status == DefaultScheduleStatus.STOPPED
    assert pipeline.weekly_full_eval.job_name == "full_eval"
