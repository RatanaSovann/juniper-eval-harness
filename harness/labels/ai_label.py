"""Blind AI reference labels: an AI labels one run's answers from a blind label sheet.

Run:  python -m harness ai_label --sheet data/labels/ai_blind_sheet_88741d.csv --out data/labels/claude_blind_88741d.csv
      python -m harness ai_label --sheet ... --out ... --limit 3          (first 3 rows: a cheap trial)
      python -m harness ai_label --sheet ... --out ... --partition all    (dev and locked)

Make the sheet first with python -m harness label_sheet --run-id <answer run ID>.

The labeller sees only what you see in the label app: the question, the expected behaviour,
the leaflet section(s) for the case, the rubric and the answer. It is never shown the case ID,
the bot version (variant), must_include, rule results or judge scores.

The output has the same columns as data/labels/claude_labels.csv, so agreement.py and load.py
read it as they are. Rows are appended one at a time; running again with the same --out skips
rows already labelled, so a stopped run can simply be run again. A reply that still breaks the
rules after one retry is left unlabelled (never guessed) and listed at the end. The run stops
before any call that could push its estimated cost past cost.max_aud_per_run (per run of this
command).

These are AI reference labels, never human gold: list the output file under
warehouse.ai_labels in config.yaml, never under hand_labels.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from harness.core.config import ROOT, AiLabellerConfig, Config, JudgeModel, load_config
from harness.answers.generate import AnthropicModel, ChatModel, CostCapReached, cost_aud, worst_case_aud
from harness.labels.label_sheet import SCORE_COLUMNS, read_sheet, set_labels, source_excerpts
from harness.testset.validate_cases import validate

OUT_COLUMNS = ["run_id", "case_id", "variant", *SCORE_COLUMNS, "label_confidence", "note", "labeller"]
RETRY_NOTE = "\n\nYour last reply could not be read. Reply with JSON only, in exactly the shape given."
KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
            "xai": "XAI_API_KEY"}


def build_system(config: Config) -> str:
    """Labeller instruction + rubric. The same for every row."""
    cfg = config.ai_labeller
    return "\n\n".join([cfg.prompt.read_text(encoding="utf-8").strip(),
                        f"<rubric>\n{config.labels.rubric.read_text(encoding='utf-8').strip()}\n</rubric>"])


def build_user(row: dict, leaflets: dict[str, str]) -> str:
    """What the labeller sees for one row: no case ID, no variant, no run ID, no answer key."""
    parts = [f"Patient question: {row['patient_question']}",
             f"Expected behaviour: {row['expected_behaviour']}"]
    for title, text in source_excerpts(row["source_ref"], leaflets):
        parts.append(f'<source title="{title}">\n{text}\n</source>')
    parts.append(f"<answer>\n{row['answer']}\n</answer>")
    return "\n\n".join(parts)


def parse_labels(text: str) -> dict | None:
    """Read a reply into label values, or None if it isn't JSON that follows the label rules.

    Accepts scores written as numbers (2) or text ("2"), and stray words or a ```json fence
    around the JSON. The value checks are the label app's (label_sheet.set_labels).
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    labels = {c: str(data.get(c, "")).strip() for c in [*SCORE_COLUMNS, "label_confidence"]}
    labels["note"] = str(data.get("note") or "").strip()
    try:
        set_labels({}, labels)   # raises ValueError on a missing or not-allowed value
    except ValueError:
        return None
    return labels


def read_done(path: Path) -> set[tuple[str, str, str]]:
    """(run_id, case_id, variant) already labelled in an existing output file.

    Raises ValueError if the file has other columns, rather than mixing layouts.
    """
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != OUT_COLUMNS:
            raise ValueError(f"{path} has columns {reader.fieldnames}, expected {OUT_COLUMNS}. "
                             "Use a new --out file.")
        return {(r["run_id"], r["case_id"], r["variant"]) for r in reader}


def select_rows(config: Config, sheet_rows: list[dict], partition: str, limit: int | None) -> list[dict]:
    """Sheet rows whose case is in the partition ('dev', 'locked' or 'all'), in sheet order."""
    cases, errors = validate(config.paths.cases, config.paths.sources)
    if errors:
        raise ValueError("Test set has problems; run python -m harness validate_cases")
    by_id = {c.case_id: c for c in cases}
    if missing := sorted({r["case_id"] for r in sheet_rows} - by_id.keys()):
        raise ValueError(f"Sheet rows for cases not in the test set: {', '.join(missing)}")
    rows = [r for r in sheet_rows if partition == "all" or by_id[r["case_id"]].partition == partition]
    return rows[:limit] if limit else rows


def label_once(config: Config, model: ChatModel, system: str, user: str, spent: float) -> tuple[dict | None, float, int]:
    """Ask for one row's labels, with one retry if the reply breaks the rules.

    Returns (labels or None, AUD spent on this row, attempts). Raises CostCapReached before any
    call that could push the run past the cap.
    """
    cfg, cap = config.ai_labeller, config.cost.max_aud_per_run
    labels, cost, attempts = None, 0.0, 0
    while labels is None and attempts < 2:
        prompt = user if attempts == 0 else user + RETRY_NOTE
        next_max = worst_case_aud(config, system, prompt, cfg)
        if spent + cost + next_max > cap:
            raise CostCapReached(f"Cost cap: spent A${spent + cost:.2f} of A${cap:.2f}; "
                                 f"next call could cost up to A${next_max:.2f}.")
        c = model.complete(system, prompt)
        attempts += 1
        cost += cost_aud(config, c.input_tokens, c.output_tokens, cfg)
        labels = parse_labels(c.text)
    return labels, cost, attempts


def run(config: Config, model: ChatModel, sheet: Path, out: Path, partition: str = "dev",
        limit: int | None = None, log=print) -> tuple[int, list[str], float]:
    """Label each selected sheet row and append it to out.

    Returns (rows written now, rows left unlabelled, AUD spent). Raises CostCapReached if the
    next call could exceed the cap; rows already written stay.
    """
    done = read_done(out)
    rows = [r for r in select_rows(config, read_sheet(sheet), partition, limit)
            if (r["run_id"], r["case_id"], r["variant"]) not in done]
    leaflets = {l.key: l.path.read_text(encoding="utf-8") for l in config.leaflets}
    system = build_system(config)
    labeller = f"{config.ai_labeller.model} (blind, {config.ai_labeller.prompt.stem})"
    spent, written, failed = 0.0, 0, []

    log(f"{len(rows)} rows to label from {sheet.name} ({partition}), {len(done)} already in {out.name}, "
        f"model {config.ai_labeller.model}, cap A${config.cost.max_aud_per_run:.2f}")
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    with out.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
        w = csv.DictWriter(f, OUT_COLUMNS)
        if new:
            w.writeheader()
        for row in rows:
            try:
                labels, cost, attempts = label_once(config, model, system, build_user(row, leaflets), spent)
            except CostCapReached as e:
                raise CostCapReached(f"{e} Stopped after {written} rows; run again to continue.") from None
            spent += cost
            key = f"{row['case_id']} {row['variant']}"
            if labels is None:
                failed.append(key)
                log(f"  {key:<28} not labelled (unreadable reply twice)  A${spent:.3f}")
                continue
            w.writerow({"run_id": row["run_id"], "case_id": row["case_id"], "variant": row["variant"],
                        **labels, "labeller": labeller})
            f.flush()
            written += 1
            log(f"  {key:<28} S{labels['safety']} G{labels['grounding']} Sc{labels['scope']} "
                f"E{labels['escalation']} {labels['label_confidence']:<15} A${spent:.3f}")
    log(f"Done: {written} rows labelled, {len(failed)} left unlabelled, A${spent:.2f} spent, appended to {out}")
    if failed:
        log("Unlabelled (run again to retry): " + ", ".join(failed))
    return written, failed, spent


def setup_problems(config: Config, out: Path) -> list[str]:
    """Everything that must be fixed before a paid run."""
    cfg = config.ai_labeller
    if cfg is None:
        return ["Add an ai_labeller block to config.yaml (see the README)"]
    problems = []
    if not cfg.prompt.exists():
        problems.append(f"Labeller instruction missing: {cfg.prompt}")
    if not config.labels.rubric.exists():
        problems.append(f"Rubric missing: {config.labels.rubric}")
    if cfg.provider not in KEY_VARS:
        problems.append(f"ai_labeller.provider {cfg.provider!r} is not supported ({', '.join(KEY_VARS)})")
    elif not os.environ.get(KEY_VARS[cfg.provider]):
        problems.append(f"No {KEY_VARS[cfg.provider]} in .env or this terminal")
    if not cfg.model:
        problems.append("Fill in ai_labeller.model in config.yaml")
    if cfg.price_usd_per_mtok.input <= 0 or cfg.price_usd_per_mtok.output <= 0:
        problems.append("Fill in ai_labeller list prices in config.yaml so the cost cap works")
    protected = [config.labels.sheet, *config.warehouse.hand_labels]
    if any(out.resolve() == p.resolve() for p in protected):
        problems.append(f"{out} is a hand-label file; AI labels must go in a file of their own")
    return problems


def make_model(cfg: AiLabellerConfig) -> ChatModel:
    """The labeller's API client. Anthropic via generate.py; others via the judges' clients."""
    if cfg.provider == "anthropic":
        return AnthropicModel(cfg.model, cfg.max_tokens, cfg.temperature)
    from harness.judges.judge import PROVIDERS  # imported here so an Anthropic run never needs other SDKs
    return PROVIDERS[cfg.provider](JudgeModel(name="ai_labeller", **cfg.model_dump(exclude={"prompt"})))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", type=Path, required=True, help="blind label sheet from harness.labels.label_sheet")
    parser.add_argument("--out", type=Path, required=True, help="AI label file to write (or continue)")
    parser.add_argument("--partition", choices=["dev", "locked", "all"], default="dev")
    parser.add_argument("--limit", type=int, help="only the first N rows")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    config = load_config()
    sheet, out = (p if p.is_absolute() else ROOT / p for p in (args.sheet, args.out))
    if not sheet.exists():
        print(f"No sheet at {sheet}. Make one with python -m harness label_sheet --run-id <id>. Nothing was sent.")
        return 1
    problems = setup_problems(config, out)
    if problems:
        print("Not ready, nothing was sent:\n  " + "\n  ".join(problems))
        return 1
    try:
        run(config, make_model(config.ai_labeller), sheet, out, args.partition, args.limit)
    except (ValueError, CostCapReached) as e:
        print(e)
        return 1
    except Exception as e:  # API errors: rows so far are already saved
        print(f"Stopped on {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
