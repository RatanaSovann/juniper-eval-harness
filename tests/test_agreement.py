"""Tests for the agreement report. Uses hand-made judgements; no API is called."""
import csv
import json
from datetime import datetime, timezone

import pytest

from harness.agreement import cohen_kappa, report
from harness.models import METRICS, Judgement, JudgeScores
from tests.test_judge import make_judge_config


def test_kappa_textbook_example():
    # Wikipedia's worked example: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> kappa 0.4
    a = [2] * 20 + [2] * 5 + [0] * 10 + [0] * 15
    b = [2] * 20 + [0] * 5 + [2] * 10 + [0] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    assert cohen_kappa(a, b, weighted=True) == pytest.approx(0.4)  # only 0s and 2s: weights don't change it


def test_kappa_perfect_chance_and_undefined():
    assert cohen_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == pytest.approx(1.0)
    assert cohen_kappa([2, 2, 2], [2, 2, 2]) is None  # everyone said 2: chance explains everything
    assert cohen_kappa([], []) is None


def test_weighted_kappa_punishes_big_misses_more():
    labels = [0, 1, 2, 2, 1, 0]
    near = [1, 1, 2, 2, 1, 0]   # one 0 scored as 1
    far = [2, 1, 2, 2, 1, 0]    # one 0 scored as 2
    assert cohen_kappa(labels, near) == pytest.approx(cohen_kappa(labels, far))
    assert cohen_kappa(labels, near, weighted=True) > cohen_kappa(labels, far, weighted=True)


def verdict(judge, case_id, repeat, safety):
    scores = JudgeScores(**{m: {"score": safety if m == "safety" else 2, "evidence": f"ev {case_id}"}
                            for m in METRICS})
    return Judgement(judge_run_id="J-1", answer_run_id="RUN-1", case_id=case_id, variant="grounded",
                     judge=judge, model=f"{judge}-fake", prompt_version="judge_v1", repeat=repeat, attempts=1,
                     status="valid", scores=scores, raw=None, timestamp=datetime.now(timezone.utc),
                     input_tokens=1, output_tokens=1, cost_aud=0)


def write_files(config, verdicts, labels):
    with config.paths.judgements.open("w", encoding="utf-8") as f:
        f.writelines(v.model_dump_json() + "\n" for v in verdicts)
    path = config.paths.cases.parent / "labels.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["run_id", "case_id", "variant", *METRICS, "label_confidence", "note"])
        w.writeheader()
        for case_id, safety, conf in labels:
            w.writerow({"run_id": "RUN-1", "case_id": case_id, "variant": "grounded", "safety": safety,
                        "grounding": 2, "scope": 2, "escalation": 2, "label_confidence": conf, "note": ""})
    return path


def test_report_counts_unsure_skips_clinician_and_locked_and_lists_disagreements(tmp_path):
    config = make_judge_config(tmp_path)
    verdicts = [verdict("openai", "MD-01", 1, 0), verdict("openai", "MD-01", 2, 2),
                verdict("openai", "MD-02", 1, "unsure"), verdict("openai", "MD-02", 2, "unsure"),
                verdict("openai", "MD-03", 1, 2)]  # MD-03 is locked: ignored
    labels = [("MD-01", 2, "sure"), ("MD-02", 2, "fairly_sure"), ("MD-03", 0, "sure"), ("CO-01", 0, "needs_clinician")]
    text = report(config, write_files(config, verdicts, labels))
    assert "3 labelled dev answers; 1 needs_clinician" in text  # MD-03 is locked
    assert "MD-03" not in text
    assert "MD-01      grounded        safety     label 2  openai 0" in text
    assert "safety 1/2" in text                        # MD-01 changed between repeats, MD-02 didn't
    unsure_line = next(l for l in text.splitlines() if l.startswith("unsure: judge"))
    assert unsure_line.split()[2] == "1"               # MD-02 safety


def test_report_says_so_when_labels_cover_another_run(tmp_path):
    config = make_judge_config(tmp_path)
    path = write_files(config, [verdict("openai", "MD-01", 1, 2)], [])
    assert "nothing to compare" in report(config, path)
