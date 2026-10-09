"""How far each judge agrees with a set of labels, and with itself. Reads saved files only.

Run:  python -m harness.agreement                                        (latest judge run vs your hand labels)
      python -m harness.agreement --labels data/labels/claude_labels.csv  (vs the AI reference labels)
      python -m harness.agreement --judge-run <judge_run_id>

Kappa uses each judge's first repeat, on dev cases only, and only where both the label and
the judge gave a number: "unsure" and invalid verdicts are counted, never turned into
numbers. Labels marked needs_clinician are left out of kappa. Judges are never averaged.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from harness.config import Config, load_config
from harness.models import METRICS, Judgement
from harness.validate_cases import validate

LEVELS = (0, 1, 2)


def cohen_kappa(a: list[int], b: list[int], weighted: bool = False) -> float | None:
    """Agreement between two raters' 0/1/2 scores, with chance agreement removed.

    1 = perfect, 0 = no better than chance. weighted=True uses quadratic weights, so a 2-vs-0
    disagreement costs four times a 2-vs-1. Returns None when kappa is undefined (no pairs,
    or both raters gave one identical score to everything).
    """
    n = len(a)
    if n == 0 or n != len(b):
        return None
    weight = (lambda i, j: (i - j) ** 2 / 4) if weighted else (lambda i, j: float(i != j))
    count_a = {k: a.count(k) / n for k in LEVELS}
    count_b = {k: b.count(k) / n for k in LEVELS}
    observed = sum(weight(x, y) for x, y in zip(a, b)) / n
    expected = sum(weight(i, j) * count_a[i] * count_b[j] for i in LEVELS for j in LEVELS)
    if expected == 0:
        return None
    return 1 - observed / expected


def read_label(value: str):
    return int(value) if value in ("0", "1", "2") else value


def load_labels(path: Path, answer_run_id: str, dev_ids: set[str]) -> dict[tuple[str, str], dict]:
    """Fully labelled dev rows for one answer run, keyed by (case_id, variant)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        (r["case_id"], r["variant"]): {**{m: read_label(r[m]) for m in METRICS},
                                       "confidence": r["label_confidence"]}
        for r in rows
        if r["run_id"] == answer_run_id and r["case_id"] in dev_ids and all(r[m] for m in METRICS)
    }


def load_judgements(path: Path, judge_run_id: str | None) -> list[Judgement]:
    """Every verdict from one judge run; the most recent run if judge_run_id is None."""
    if not path.exists():
        raise ValueError(f"No judgements yet ({path}); run python -m harness.judge first")
    rows = [Judgement(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]
    if not rows:
        raise ValueError(f"No judgements in {path}")
    judge_run_id = judge_run_id or rows[-1].judge_run_id
    picked = [r for r in rows if r.judge_run_id == judge_run_id]
    if not picked:
        raise ValueError(f"No judgements for judge_run_id {judge_run_id}")
    return picked


def judge_score(j: Judgement | None, metric: str):
    """A verdict's score on one metric, or 'invalid' if there is no usable verdict."""
    return getattr(j.scores, metric).score if j and j.scores else "invalid"


def fmt(k: float | None) -> str:
    return "  n/a" if k is None else f"{k:5.2f}"


def report(config: Config, labels_path: Path, judge_run_id: str | None = None) -> str:
    """Build the agreement report as text."""
    cases, _ = validate(config.paths.cases, config.paths.sources)
    category = {c.case_id: c.category for c in cases if c.partition == "dev"}
    judgements = [j for j in load_judgements(config.paths.judgements, judge_run_id) if j.case_id in category]
    if not judgements:
        raise ValueError("This judge run has no dev verdicts")
    run_id, answer_run = judgements[0].judge_run_id, judgements[0].answer_run_id
    labels = load_labels(labels_path, answer_run, set(category))
    by_key = {(j.judge, j.case_id, j.variant, j.repeat): j for j in judgements}
    judges = sorted({j.judge for j in judgements})

    out = [f"Judge run {run_id} on answers {answer_run}, labels {labels_path.name}",
           f"{len(labels)} labelled dev answers; "
           f"{sum(l['confidence'] == 'needs_clinician' for l in labels.values())} needs_clinician (left out of kappa)",
           "Kappa: plain / quadratic-weighted, (n) = answers where both gave a number. Repeat 1 only.", ""]
    if not labels:
        out.append("No labelled answers overlap this judge run; nothing to compare.")
        return "\n".join(out)

    disagreements = []
    for judge in judges:
        model = next(j.model for j in judgements if j.judge == judge)
        out.append(f"== {judge} ({model})")
        groups = defaultdict(lambda: defaultdict(lambda: ([], [])))  # group -> metric -> (labels, judge)
        counts = defaultdict(lambda: defaultdict(int))                # metric -> label_unsure / judge_unsure / invalid
        for (case_id, variant), lab in sorted(labels.items()):
            if lab["confidence"] == "needs_clinician":
                continue
            v = by_key.get((judge, case_id, variant, 1))
            for m in METRICS:
                ls, js = lab[m], judge_score(v, m)
                if js == "invalid":
                    counts[m]["invalid"] += 1
                    continue
                if ls == "unsure" or js == "unsure":
                    counts[m]["label_unsure"] += ls == "unsure"
                    counts[m]["judge_unsure"] += js == "unsure"
                    continue
                for g in ("ALL", category[case_id]) + (("sure only",) if lab["confidence"] == "sure" else ()):
                    groups[g][m][0].append(ls)
                    groups[g][m][1].append(js)
                if ls != js:
                    disagreements.append((judge, case_id, variant, m, ls, js, getattr(v.scores, m).evidence))
        out.append(f"{'':<16}" + "".join(f"{m:<22}" for m in METRICS))
        order = ["ALL", "sure only"] + sorted(g for g in groups if g not in ("ALL", "sure only"))
        for g in order:
            cells = []
            for m in METRICS:
                ls, js = groups[g][m]
                cells.append(f"{fmt(cohen_kappa(ls, js))} /{fmt(cohen_kappa(ls, js, True))} ({len(ls):>2})".ljust(22))
            out.append(f"{g:<16}" + "".join(cells))
        out.append(f"{'unsure: judge':<16}" + "".join(f"{counts[m]['judge_unsure']:<22}" for m in METRICS))
        out.append(f"{'unsure: label':<16}" + "".join(f"{counts[m]['label_unsure']:<22}" for m in METRICS))
        out.append(f"{'invalid':<16}" + "".join(f"{counts[m]['invalid']:<22}" for m in METRICS))
        out.append("")

    out.append("== Consistency: how often a judge changed its own score between repeat 1 and 2 (all dev answers)")
    for judge in judges:
        cells = []
        for m in METRICS:
            pairs = [(judge_score(j, m), judge_score(by_key.get((judge, j.case_id, j.variant, 2)), m))
                     for j in judgements if j.judge == judge and j.repeat == 1
                     and (judge, j.case_id, j.variant, 2) in by_key]
            pairs = [(x, y) for x, y in pairs if "invalid" not in (x, y)]
            changed = sum(x != y for x, y in pairs)
            cells.append(f"{m} {changed}/{len(pairs)}")
        out.append(f"  {judge:<10} " + "   ".join(cells))
    out.append("")

    out.append(f"== Disagreements with labels ({len(disagreements)}), repeat 1")
    for judge, case_id, variant, m, ls, js, evidence in sorted(disagreements, key=lambda d: (d[1], d[2], d[3], d[0])):
        out.append(f"  {case_id:<10} {variant:<15} {m:<10} label {ls}  {judge} {js}  | {evidence[:90]}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", type=Path, help="label CSV (default: labels.sheet in config.yaml)")
    parser.add_argument("--judge-run", help="judge_run_id (default: the latest)")
    args = parser.parse_args(argv)
    config = load_config()
    try:
        print(report(config, args.labels or config.labels.sheet, args.judge_run))
    except (ValueError, FileNotFoundError) as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
