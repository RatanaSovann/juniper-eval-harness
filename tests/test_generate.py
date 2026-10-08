"""Tests for the answer generator. A fake model stands in for the bot, so no API is called."""
import csv
import json

import pytest
import yaml

from harness.config import load_config
from harness.generate import Completion, CostCapReached, cost_aud, run
from harness.models import LoggedAnswer
from harness.validate_cases import COLUMNS
from tests.test_validate_cases import GOOD, SOURCES_MD


class FakeModel:
    """Returns a canned answer and remembers every request it was sent."""

    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return Completion("Fake answer.", input_tokens=1000, output_tokens=100, stop_reason="end_turn")


def make_config(tmp_path, cap=5.0, prompt=True):
    """Write a tiny test set, leaflet, instruction and config into tmp_path and load it."""
    rows = [{**GOOD, "case_id": f"MD-0{i}", "scenario_id": f"MD-0{i}"} for i in range(1, 4)]
    rows.append({**GOOD, "case_id": "CO-01", "scenario_id": "CO-01", "assistant_scope": "coaching"})
    with (tmp_path / "cases.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (tmp_path / "sources.md").write_text(SOURCES_MD, encoding="utf-8")
    (tmp_path / "leaflet.txt").write_text("LEAFLET TEXT", encoding="utf-8")
    if prompt:
        (tmp_path / "grounded.txt").write_text("INSTRUCTION", encoding="utf-8")
    cfg = {
        "bot": {"provider": "anthropic", "model": "fake-1", "temperature": 0, "max_tokens": 500,
                "price_usd_per_mtok": {"input": 1.0, "output": 5.0}},
        "cost": {"max_aud_per_run": cap, "usd_to_aud": 1.5},
        "generate": {"scopes": ["medical_support"],
                     "variants": {"bare": {"prompt": None},
                                  "grounded": {"prompt": "grounded.txt", "leaflets": True}}},
        "leaflets": [{"key": "WEG_CMI", "path": "leaflet.txt", "prepared": "2026-07"}],
        "rule_checks": {"promptfoo_version": "0.0.0", "promptfoo_config": "pf/config.yaml",
                        "promptfoo_results": "pf/results.json", "hits": "runs/rule_hits.csv"},
        "paths": {"cases": "cases.csv", "sources": "sources.md", "answers": "runs/answers.jsonl"},
    }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return load_config(tmp_path / "config.yaml", root=tmp_path)


def read_log(config):
    return [LoggedAnswer(**json.loads(line)) for line in config.paths.answers.read_text(encoding="utf-8").splitlines()]


def test_run_logs_every_case_and_variant(tmp_path):
    config = make_config(tmp_path)
    run_id, written, _ = run(config, FakeModel(), log=lambda *_: None)
    rows = read_log(config)
    assert written == len(rows) == 6  # 3 medical cases x 2 variants; coaching case skipped
    assert {r.run_id for r in rows} == {run_id}
    assert "CO-01" not in {r.case_id for r in rows}
    assert {(r.variant, r.prompt_version, r.leaflet_date) for r in rows} == {
        ("bare", "bare", None), ("grounded", "grounded", "WEG_CMI 2026-07")}


def test_second_run_appends(tmp_path):
    config = make_config(tmp_path)
    first, _, _ = run(config, FakeModel(), log=lambda *_: None)
    before = config.paths.answers.read_text(encoding="utf-8")
    second, _, _ = run(config, FakeModel(), log=lambda *_: None)
    after = config.paths.answers.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert first != second
    assert len(read_log(config)) == 12


def test_grounded_sends_instruction_and_leaflets_bare_sends_nothing(tmp_path):
    config = make_config(tmp_path)
    model = FakeModel()
    run(config, model, limit=1, log=lambda *_: None)
    (bare_system, _), (grounded_system, user) = model.calls
    assert bare_system is None
    assert "INSTRUCTION" in grounded_system and "LEAFLET TEXT" in grounded_system
    assert 'source="WEG_CMI"' in grounded_system
    assert user == GOOD["patient_question"]


def test_limit(tmp_path):
    config = make_config(tmp_path)
    _, written, _ = run(config, FakeModel(), limit=2, log=lambda *_: None)
    assert written == 4


def test_cost_cap_stops_before_overspending(tmp_path):
    # each fake call costs (1000*1 + 100*5)/1e6 * 1.5 = A$0.00225; worst case per call is higher
    config = make_config(tmp_path, cap=0.005)
    with pytest.raises(CostCapReached, match="Cost cap"):
        run(config, FakeModel(), log=lambda *_: None)
    rows = read_log(config)
    assert 0 < len(rows) < 6
    assert sum(r.cost_aud for r in rows) <= 0.005


def test_missing_instruction_fails_before_any_call(tmp_path):
    config = make_config(tmp_path, prompt=False)
    model = FakeModel()
    with pytest.raises(FileNotFoundError, match="grounded.txt"):
        run(config, model, log=lambda *_: None)
    assert model.calls == []
    assert not config.paths.answers.exists()


def test_cost_aud(tmp_path):
    config = make_config(tmp_path)
    assert cost_aud(config, 1_000_000, 0) == pytest.approx(1.5)
    assert cost_aud(config, 0, 1_000_000) == pytest.approx(7.5)


def test_real_config_loads():
    config = load_config()
    assert config.bot.model and config.cost.max_aud_per_run > 0


def test_anthropic_model_request_shape():
    """The real client wrapper sends what the SDK accepts; the SDK client itself is stubbed."""
    from types import SimpleNamespace

    from harness.generate import AnthropicModel

    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Hi")], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=2))

    m = AnthropicModel.__new__(AnthropicModel)
    m.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    m.model, m.max_tokens, m.temperature = "fake-1", 100, 0
    assert m.complete(None, "Q").text == "Hi"
    assert "temperature" not in sent and sent["extra_body"] == {"temperature": 0}
    assert "system" not in sent

    sent.clear()
    m.temperature = None
    m.complete("SYS", "Q")
    assert "extra_body" not in sent and sent["system"] == "SYS"
