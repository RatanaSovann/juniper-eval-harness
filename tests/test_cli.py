"""Tests for the single entry point (python -m harness <command>). Nothing is run for real."""
import importlib

import pytest

from harness.__main__ import COMMANDS, main


@pytest.mark.parametrize("name", list(COMMANDS))
def test_every_command_points_at_a_module_with_main(name):
    module = importlib.import_module(COMMANDS[name][0])
    assert callable(module.main)


def test_hands_the_remaining_arguments_to_the_command(monkeypatch):
    seen = {}
    module = importlib.import_module("harness.answers.generate")
    monkeypatch.setattr(module, "main", lambda argv: seen.setdefault("argv", argv) and 7)
    assert main(["generate", "--limit", "5"]) == 7
    assert seen["argv"] == ["--limit", "5"]


def test_hyphens_work_as_underscores(monkeypatch):
    module = importlib.import_module("harness.rules.rule_checks")
    monkeypatch.setattr(module, "main", lambda argv: 0)
    assert main(["rule-checks"]) == 0


def test_no_command_lists_them_and_fails(capsys):
    assert main([]) == 1
    out = capsys.readouterr().out
    assert all(name in out for name in COMMANDS)


def test_help_lists_them_and_succeeds(capsys):
    assert main(["--help"]) == 0
    assert "generate" in capsys.readouterr().out


def test_unknown_command_is_refused(capsys):
    assert main(["generat"]) == 1
    assert "Unknown command 'generat'" in capsys.readouterr().out
