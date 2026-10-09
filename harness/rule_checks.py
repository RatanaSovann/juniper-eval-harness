"""Layer 1: grade saved answers against each case's rule_checks, using promptfoo.

Run:  python -m harness.rule_checks                 (latest run in runs/answers.jsonl)
      python -m harness.rule_checks --run-id <id>

The bot is not called again. promptfoo's `echo` provider hands each saved answer straight
to the assertions. Results are appended to runs/rule_hits.csv.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import yaml

from harness.config import Config, load_config
from harness.models import LoggedAnswer, TestCase, parse_rule_checks
from harness.validate_cases import validate

HIT_COLUMNS = ["checked_at", "run_id", "case_id", "variant", "rule", "passed", "matched_text"]


def strip_markdown(text: str) -> str:
    """Remove markdown symbols so '**5 days**' matches '5 days'. Words are left untouched."""
    text = re.sub(r"[*`]|__", "", text)  # bold, italics, code
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)  # headings
    return re.sub(r"[ \t]+", " ", text)


def first_match(text: str, terms: list[str]) -> str:
    """Return the first term found in text, ignoring capitals, or '' if none is."""
    low = text.lower()
    return next((t for t in terms if t.lower() in low), "")


def load_answers(path, run_id: str | None) -> tuple[str, list[LoggedAnswer]]:
    """Read one run from the answer log. With no run_id, use the most recent run."""
    rows = [LoggedAnswer(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        raise ValueError(f"No answers in {path}")
    run_id = run_id or rows[-1].run_id
    picked = [r for r in rows if r.run_id == run_id]
    if not picked:
        raise ValueError(f"No answers for run_id {run_id}")
    return run_id, picked


def build_promptfoo_config(cases: list[TestCase], answers: list[LoggedAnswer]) -> dict:
    """One promptfoo test per answer whose case has rule_checks; one assertion per rule."""
    by_id = {c.case_id: c for c in cases}
    tests = []
    for a in answers:
        case = by_id.get(a.case_id)
        if case is None or case.rule_checks is None:
            continue
        rules = parse_rule_checks(case.rule_checks)
        asserts = []
        if "require" in rules:
            asserts.append({"type": "icontains-any", "value": rules["require"]})
        for term in rules.get("forbid", []):
            asserts.append({"type": "not-icontains", "value": term})
        tests.append({
            "description": f"{a.case_id} {a.variant}",
            "vars": {"answer": strip_markdown(a.answer), "run_id": a.run_id,
                     "case_id": a.case_id, "variant": a.variant},
            "assert": asserts,
        })
    return {
        "description": "GLP-1 eval harness: L1 rule checks on saved answers (generated, do not edit)",
        "prompts": ["{{answer}}"],
        "providers": ["echo"],
        "tests": tests,
    }


def run_promptfoo(config: Config) -> None:
    """Run promptfoo on the generated config and write its JSON results."""
    npx = shutil.which("npx")
    if npx is None:
        raise FileNotFoundError("npx not found: install Node.js to run promptfoo")
    rc = config.rule_checks
    rc.promptfoo_results.unlink(missing_ok=True)
    env = {**os.environ, "PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1"}
    proc = subprocess.run(
        [npx, "-y", f"promptfoo@{rc.promptfoo_version}", "eval", "-c", str(rc.promptfoo_config),
         "-o", str(rc.promptfoo_results), "--no-cache", "--no-progress-bar"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # promptfoo exits non-zero when assertions fail; that is a result, not an error
    if not rc.promptfoo_results.exists():
        raise RuntimeError(f"promptfoo did not produce results (exit {proc.returncode}):\n{proc.stderr[-2000:]}")


def hits_from_results(results: dict, checked_at: str) -> list[dict]:
    """Turn promptfoo's JSON output into one row per rule per answer, stamped with when the check ran."""
    rows = []
    for r in results["results"]["results"]:
        v = r["vars"]
        for comp in r["gradingResult"]["componentResults"]:
            a = comp["assertion"]
            if a["type"] == "icontains-any":
                rule, terms = "require:" + "|".join(a["value"]), a["value"]
            else:
                rule, terms = "forbid:" + a["value"], [a["value"]]
            rows.append({"checked_at": checked_at, "run_id": v["run_id"], "case_id": v["case_id"], "variant": v["variant"],
                         "rule": rule, "passed": comp["pass"], "matched_text": first_match(v["answer"], terms)})
    return rows


def append_hits(path, rows: list[dict]) -> None:
    """Append rows to rule_hits.csv, writing the header only when the file is new.

    Raises ValueError if the existing file has different columns, rather than mixing layouts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    if not new:
        with path.open(newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), [])
        if header != HIT_COLUMNS:
            raise ValueError(f"{path} has columns {header}, expected {HIT_COLUMNS}. "
                             "Rename the old file so a new one is started.")
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, HIT_COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", help="run to grade (default: latest)")
    args = parser.parse_args(argv)

    config = load_config()
    cases, errors = validate(config.paths.cases, config.paths.sources)
    if errors:
        print("Test set has problems; run python -m harness.validate_cases")
        return 1
    try:
        run_id, answers = load_answers(config.paths.answers, args.run_id)
    except ValueError as e:
        print(e)
        return 1
    pf = build_promptfoo_config(cases, answers)
    if not pf["tests"]:
        print(f"Nothing to check: no answered case in run {run_id} has rule_checks filled in.")
        return 1

    config.rule_checks.promptfoo_config.parent.mkdir(parents=True, exist_ok=True)
    config.rule_checks.promptfoo_config.write_text(
        yaml.safe_dump(pf, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8")
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"run_id {run_id}: {len(pf['tests'])} answers to check, promptfoo {config.rule_checks.promptfoo_version}")
    try:
        run_promptfoo(config)
    except (FileNotFoundError, RuntimeError) as e:
        print(e)
        return 1
    rows = hits_from_results(json.loads(config.rule_checks.promptfoo_results.read_text(encoding="utf-8")), checked_at)
    try:
        append_hits(config.rule_checks.hits, rows)
    except ValueError as e:
        print(e)
        return 1
    failed = [r for r in rows if not r["passed"]]
    print(f"{len(rows)} rule results, {len(failed)} failed; appended to {config.rule_checks.hits}")
    for r in failed:
        print(f"  FAIL {r['case_id']:<10} {r['variant']:<9} {r['rule']}  matched: {r['matched_text']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
