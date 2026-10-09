"""Tests for the BigQuery loader. A fake client stands in for BigQuery; nothing leaves the machine."""
import csv
from datetime import datetime, timezone

import pytest

pytest.importorskip("google.cloud.bigquery")  # part of the [warehouse] extra

from harness.load import build_tables, infer_schema, load, to_json_ready
from harness.models import METRICS
from tests.test_router import setup_run


class FakeJob:
    def result(self):
        return None


class FakeClient:
    """Records datasets created and tables loaded."""

    def __init__(self):
        self.datasets, self.loads = [], {}

    def create_dataset(self, dataset, exists_ok):
        self.datasets.append((dataset.dataset_id, dataset.location, exists_ok))

    def load_table_from_json(self, rows, table_id, job_config):
        self.loads[table_id] = (rows, job_config)
        return FakeJob()


def test_schema_is_decided_from_every_row():
    rows = [{"score": "2", "n": 1, "x": 1, "ok": True, "at": datetime.now(timezone.utc), "tags": [], "gone": None},
            {"score": "unsure", "n": 2, "x": 1.5, "ok": False, "at": None, "tags": ["a"], "gone": None}]
    assert infer_schema(rows) == [("score", "STRING", "NULLABLE"), ("n", "INT64", "NULLABLE"),
                                  ("x", "FLOAT64", "NULLABLE"), ("ok", "BOOL", "NULLABLE"),
                                  ("at", "TIMESTAMP", "NULLABLE"), ("tags", "STRING", "REPEATED"),
                                  ("gone", "STRING", "NULLABLE")]
    assert isinstance(to_json_ready(rows)[0]["at"], str)


def test_tables_flatten_judgements_and_tag_labels(tmp_path):
    config = setup_run(tmp_path)  # 2 dev answers judged by 2 judges x 2 repeats; MD-02 labelled a hard fail
    with config.warehouse.ai_labels[0].open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "case_id", "variant", *METRICS, "label_confidence", "note", "labeller"])
        w.writerow(["RUN-1", "MD-01", "grounded", 2, 2, 2, 2, "sure", "", "some-model"])
    tables = build_tables(config)
    j = tables["judgements"][0]
    assert "scores" not in j and j["safety_score"] == "2" and j["safety_evidence"] == "e"
    md02 = [r for r in tables["judgements"] if r["case_id"] == "MD-02" and r["judge"] == "gemini"]
    assert {r["safety_score"] for r in md02} == {"0"}
    kinds = sorted((r["label_kind"], r["labeller"], r["case_id"]) for r in tables["labels"])
    assert kinds == [("ai", "some-model", "MD-01"), ("hand", "hand", "MD-01"), ("hand", "hand", "MD-02")]
    assert len(tables["cases"]) == 4 and len(tables["answers"]) == 4 and tables["routes"] == []


def test_load_replaces_tables_and_skips_empty_ones(tmp_path):
    config = setup_run(tmp_path)
    client = FakeClient()
    loaded = load(config, client, log=lambda *_: None)
    assert client.datasets == [("raw", "australia-southeast1", True)]
    assert "routes" not in loaded and "rewrites" not in loaded           # nothing logged yet
    assert loaded["judgements"] == 8 and "proj.raw.judgements" in client.loads
    rows, job_config = client.loads["proj.raw.judgements"]
    assert job_config.write_disposition == "WRITE_TRUNCATE"
    assert {f.name: f.field_type for f in job_config.schema}["safety_score"] == "STRING"
    assert isinstance(rows[0]["timestamp"], str)
