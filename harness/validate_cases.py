"""Check the test set is clean before we run anything on it.

Run:  python -m harness.validate_cases            (owner columns may be blank)
      python -m harness.validate_cases --strict   (owner columns must be filled)
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from harness.models import OWNER_COLUMNS, TestCase

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "test_cases.csv"
SOURCES = ROOT / "data" / "sources.md"

COLUMNS = list(TestCase.model_fields)


def read_source_keys(sources_path: Path) -> set[str]:
    """Return the source keys listed in the first column of the sources.md table."""
    text = sources_path.read_text(encoding="utf-8")
    return set(re.findall(r"^\| ([A-Z][A-Z0-9_]*) \|", text, flags=re.MULTILINE))


def validate(cases_path: Path, sources_path: Path, strict: bool = False) -> tuple[list[TestCase], list[str]]:
    """Load every row as a TestCase. Return the valid cases and a list of problems found."""
    errors: list[str] = []
    with cases_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            return [], [f"Columns wrong: {reader.fieldnames}\n    expected: {COLUMNS}"]
        rows = list(reader)

    for cid, n in Counter(r["case_id"] for r in rows).items():
        if n > 1:
            errors.append(f"Duplicate case_id {cid}")

    known_sources = read_source_keys(sources_path)
    cases: list[TestCase] = []
    for line, row in enumerate(rows, start=2):
        cid = row["case_id"] or f"line {line}"
        try:
            case = TestCase(**row)
        except ValidationError as e:
            for err in e.errors():
                where = ".".join(str(p) for p in err["loc"]) or "row"
                errors.append(f"{cid}: {where}: {err['msg']}")
            continue
        for k in sorted(case.source_keys() - known_sources):
            errors.append(f"{cid}: unknown source {k}")
        if strict:
            for col in OWNER_COLUMNS:
                if getattr(case, col) is None:
                    errors.append(f"{cid}: {col} is blank")
        cases.append(case)
    return cases, errors


def print_summary(cases: list[TestCase]) -> None:
    """Print counts per column so the balance of the test set is easy to see."""
    print(f"Cases: {len(cases)}\n")
    for col in ["category", "risk_level", "expected_behaviour", "medicine", "workstream",
                "partition", "assistant_scope"]:
        counts = Counter(str(getattr(c, col) or "(blank)") for c in cases)
        print(f"{col}:")
        for k, v in counts.most_common():
            print(f"  {k:<22}{v}")
        print()
    traps = sum(1 for c in cases if c.trap != "None")
    print(f"Cases with a known trap: {traps}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="fail if owner columns are blank")
    args = parser.parse_args(argv)

    cases, errors = validate(CASES, SOURCES, strict=args.strict)
    print_summary(cases)
    if errors:
        print("PROBLEMS:")
        for e in errors:
            print("  -", e)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
