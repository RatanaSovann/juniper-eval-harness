"""Copy the harness's logs into BigQuery so dbt can build the scorecard.

Run:  python -m harness.load --dry-run   (build every table locally and print row counts; no cloud calls)
      python -m harness.load             (replace the raw tables in BigQuery)

The files on disk stay the source of truth: they are append-only and never changed here.
Each load replaces the raw tables in full, so the warehouse is always a rebuildable copy.
Login comes from gcloud (gcloud auth application-default login); there are no key files.
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from harness.config import Config, load_config
from harness.models import METRICS, Judgement, LoggedAnswer, Rewrite, RouteDecision
from harness.validate_cases import validate

LABEL_COLUMNS = ("run_id", "case_id", "variant", *METRICS, "label_confidence", "note")


def read_jsonl(path: Path, model) -> list:
    if not path.exists():
        return []
    return [model(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def judgement_row(j: Judgement) -> dict:
    """One verdict, flattened: a score and an evidence column per metric. Scores are text ('unsure')."""
    row = j.model_dump(exclude={"scores"})
    for m in METRICS:
        s = getattr(j.scores, m) if j.scores else None
        row[f"{m}_score"] = None if s is None else str(s.score)
        row[f"{m}_evidence"] = None if s is None else s.evidence
    return row


def build_tables(config: Config) -> dict[str, list[dict]]:
    """Every raw table as a list of rows, from the files on disk."""
    cases, errors = validate(config.paths.cases, config.paths.sources)
    if errors:
        raise ValueError("Test set has problems; run python -m harness.validate_cases")

    labels = []
    for kind, paths in (("hand", config.warehouse.hand_labels), ("ai", config.warehouse.ai_labels)):
        for path in paths:
            for r in read_csv(path):
                if all(r.get(m) for m in METRICS):  # only fully labelled answers
                    labels.append({**{c: r.get(c) or None for c in LABEL_COLUMNS},
                                   "labeller": r.get("labeller") or kind, "label_kind": kind, "source_file": path.name})

    rule_hits = [{**r, "passed": r["passed"] == "True", "matched_text": r["matched_text"] or None}
                 for r in read_csv(config.rule_checks.hits)]
    routes = [{**d.model_dump(), "judge_runs": json.dumps(d.judge_runs, sort_keys=True)}
              for d in read_jsonl(config.paths.routes, RouteDecision)]
    return {
        "cases": [c.model_dump() for c in cases],
        "answers": [a.model_dump() for a in read_jsonl(config.paths.answers, LoggedAnswer)],
        "rule_hits": rule_hits,
        "judgements": [judgement_row(j) for j in read_jsonl(config.paths.judgements, Judgement)],
        "routes": routes,
        "rewrites": [r.model_dump() for r in read_jsonl(config.paths.rewrites, Rewrite)],
        "labels": labels,
    }


def infer_schema(rows: list[dict]) -> list[tuple[str, str, str]]:
    """(column, BigQuery type, mode) for every column, decided from ALL rows, not a sample.

    Anything that is ever text stays text, so '2' and 'unsure' land in the same STRING column.
    """
    columns: dict[str, set] = {}
    for row in rows:
        for k, v in row.items():
            columns.setdefault(k, set()).add(type(v))
    schema = []
    for name, types in columns.items():
        types.discard(type(None))
        if types == {list}:
            schema.append((name, "STRING", "REPEATED"))
        elif types == {bool}:
            schema.append((name, "BOOL", "NULLABLE"))
        elif types and types <= {int}:
            schema.append((name, "INT64", "NULLABLE"))
        elif types and types <= {int, float}:
            schema.append((name, "FLOAT64", "NULLABLE"))
        elif types == {datetime}:
            schema.append((name, "TIMESTAMP", "NULLABLE"))
        else:
            schema.append((name, "STRING", "NULLABLE"))
    return schema


def to_json_ready(rows: list[dict]) -> list[dict]:
    """Timestamps as ISO text, which is what BigQuery's JSON loader expects."""
    return [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in r.items()} for r in rows]


def load(config: Config, client=None, log=print) -> dict[str, int]:
    """Replace every raw table in BigQuery. Returns rows loaded per table. Empty tables are skipped."""
    from google.cloud import bigquery  # imported here so tests and --dry-run never need it

    w = config.warehouse
    client = client or bigquery.Client(project=w.project, location=w.location)
    dataset = bigquery.Dataset(f"{w.project}.{w.raw_dataset}")
    dataset.location = w.location
    client.create_dataset(dataset, exists_ok=True)

    loaded = {}
    for name, rows in build_tables(config).items():
        if not rows:
            log(f"  {name:<11} skipped (no rows yet)")
            continue
        schema = [bigquery.SchemaField(c, t, mode=m) for c, t, m in infer_schema(rows)]
        job = client.load_table_from_json(
            to_json_ready(rows), f"{w.project}.{w.raw_dataset}.{name}",
            job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE"),
        )
        job.result()  # waits; raises if BigQuery rejected the load
        loaded[name] = len(rows)
        log(f"  {name:<11} {len(rows):>6} rows")
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="build the tables locally; send nothing")
    args = parser.parse_args(argv)
    config = load_config()
    w = config.warehouse
    try:
        if args.dry_run:
            print(f"Dry run: would replace tables in {w.project}.{w.raw_dataset} ({w.location})")
            for name, rows in build_tables(config).items():
                print(f"  {name:<11} {len(rows):>6} rows, {len(infer_schema(rows))} columns")
            return 0
        print(f"Loading into {w.project}.{w.raw_dataset} ({w.location})")
        load(config)
    except ValueError as e:
        print(e)
        return 1
    except Exception as e:  # cloud errors: nothing on disk is affected
        print(f"Stopped on {type(e).__name__}: {e}")
        print("If this is a login problem, run: gcloud auth application-default login")
        return 1
    print("Done. Look at the tables in console.cloud.google.com/bigquery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
