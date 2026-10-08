"""Stage 4: export one run's answers to a blind label sheet for hand labelling.

Run:  python -m harness.label_sheet                 (latest run in runs/answers.jsonl)
      python -m harness.label_sheet --run-id <id>

The sheet has no rule-check results, no judge output, no must_include and no partition, so
nothing nudges the labels. Rows are shuffled with the seed in config.yaml. The script never
overwrites an existing sheet, because that file holds your labels.
"""
import argparse
import csv
import os
import random
import re
import sys

from harness.config import load_config
from harness.models import LoggedAnswer, TestCase
from harness.rule_checks import load_answers
from harness.validate_cases import validate

GIVEN_COLUMNS = ["run_id", "case_id", "variant", "patient_question", "answer", "expected_behaviour", "source_ref"]
LABEL_COLUMNS = ["safety", "grounding", "scope", "escalation", "label_confidence", "note"]
SHEET_COLUMNS = GIVEN_COLUMNS + LABEL_COLUMNS
SCORE_VALUES = ["0", "1", "2", "unsure"]
SCORE_COLUMNS = ["safety", "grounding", "scope", "escalation"]
CONFIDENCE_VALUES = ["sure", "fairly_sure", "needs_clinician"]


def build_rows(cases: list[TestCase], answers: list[LoggedAnswer], seed: int) -> list[dict]:
    """One sheet row per answer, label columns empty, in a shuffled but repeatable order.

    Raises ValueError if an answer's case is no longer in the test set.
    """
    by_id = {c.case_id: c for c in cases}
    missing = sorted({a.case_id for a in answers} - by_id.keys())
    if missing:
        raise ValueError(f"Answers for cases not in the test set: {', '.join(missing)}")
    rows = []
    for a in answers:
        case = by_id[a.case_id]
        rows.append({"run_id": a.run_id, "case_id": a.case_id, "variant": a.variant,
                     "patient_question": case.patient_question, "answer": a.answer,
                     "expected_behaviour": case.expected_behaviour, "source_ref": case.source_ref,
                     **{c: "" for c in LABEL_COLUMNS}})
    random.Random(seed).shuffle(rows)
    return rows


def write_sheet(path, rows: list[dict]) -> None:
    """Write the sheet as UTF-8 with a BOM so Excel shows curly quotes correctly.

    Raises FileExistsError if the sheet is already there, so labels are never lost.
    """
    if path.exists():
        raise FileExistsError(f"{path} already exists and may hold your labels. "
                              "Rename or move it first if you really want a new sheet.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def read_sheet(path) -> list[dict]:
    """Read the label sheet back as a list of rows.

    Raises ValueError if its columns are not the sheet's columns.
    """
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SHEET_COLUMNS:
            raise ValueError(f"{path} has columns {reader.fieldnames}, expected {SHEET_COLUMNS}")
        return list(reader)


def save_sheet(path, rows: list[dict]) -> None:
    """Save the label sheet in place, safely: write a temp file, then swap it in.

    A crash part-way leaves the old sheet intact. Raises PermissionError if another
    program (e.g. Excel) has the sheet open.
    """
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def leaflet_sections(text: str) -> dict[int, str]:
    """Split a CMI leaflet into its numbered sections, e.g. {4: '### 4. How do I use...'}.

    Each leaflet has a short summary followed by the full CMI with the same headings;
    the full version (the later one) is kept.
    """
    sections = {}
    for m in re.finditer(r"^### (\d+)\. .*?(?=^#{1,3} |\Z)", text, flags=re.MULTILINE | re.DOTALL):
        sections[int(m.group(1))] = m.group(0).strip()
    return sections


def source_excerpts(source_ref: str, leaflets: dict[str, str]) -> list[tuple[str, str]]:
    """Turn a source_ref like 'MJ_CMI s6; WEG_CMI s2 s6' into (title, text) pairs to show.

    Sources that aren't leaflets (e.g. JUNIPER_FAQ), or sections that can't be found,
    come back with a pointer to data/sources.md instead of text.
    """
    out = []
    for part in source_ref.split(";"):
        key, *secs = part.split()
        if key not in leaflets or not secs:
            out.append((part.strip(), "No text in the app: see data/sources.md"))
            continue
        sections = leaflet_sections(leaflets[key])
        for s in secs:
            n = int(s.lstrip("s")) if s.lstrip("s").isdigit() else None
            out.append((f"{key} {s}", sections.get(n, "Section not found: see data/sources.md")))
    return out


def is_labelled(row: dict) -> bool:
    """True when every score and the confidence are filled in (the note is optional)."""
    return all(row[c] for c in SCORE_COLUMNS + ["label_confidence"])


def set_labels(row: dict, labels: dict) -> None:
    """Put one answer's labels into its row.

    Raises ValueError if a score or the confidence is missing or not an allowed value.
    """
    for c in SCORE_COLUMNS:
        if labels.get(c) not in SCORE_VALUES:
            raise ValueError(f"{c} must be one of {SCORE_VALUES}, got {labels.get(c)!r}")
    if labels.get("label_confidence") not in CONFIDENCE_VALUES:
        raise ValueError(f"label_confidence must be one of {CONFIDENCE_VALUES}, got {labels.get('label_confidence')!r}")
    for c in LABEL_COLUMNS:
        row[c] = (labels.get(c) or "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", help="run to export (default: latest)")
    args = parser.parse_args(argv)

    config = load_config()
    cases, errors = validate(config.paths.cases, config.paths.sources)
    if errors:
        print("Test set has problems; run python -m harness.validate_cases")
        return 1
    try:
        run_id, answers = load_answers(config.paths.answers, args.run_id)
        rows = build_rows(cases, answers, config.labels.shuffle_seed)
        write_sheet(config.labels.sheet, rows)
    except (ValueError, FileExistsError) as e:
        print(e)
        return 1
    print(f"run_id {run_id}: {len(rows)} answers written to {config.labels.sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
