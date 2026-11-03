"""One entry point for every harness command: python -m harness <command> [options].

Run:  python -m harness                          (list the commands)
      python -m harness generate --limit 5
      python -m harness judge --resume <judge_run_id>
      python -m harness <command> --help         (that command's own options)

Commands stay the same however the files inside harness/ are arranged. The label app is a
Streamlit page, not a command: streamlit run harness/labels/label_app.py
"""
import importlib
import sys

# command -> (module, what it does); listed in the order a run goes
COMMANDS = {
    "validate_cases": ("harness.testset.validate_cases", "check data/test_cases.csv"),
    "generate": ("harness.answers.generate", "L0: the bot answers every question (paid)"),
    "rule_checks": ("harness.rules.rule_checks", "L1: exact-text rules on saved answers"),
    "label_sheet": ("harness.labels.label_sheet", "L3: export a blind label sheet for one run"),
    "ai_label": ("harness.labels.ai_label", "L3: blind AI reference labels from a sheet (paid)"),
    "judge": ("harness.judges.judge", "L2: AI judges score the answers (paid)"),
    "agreement": ("harness.judges.agreement", "L3: judges vs labels"),
    "router": ("harness.routing.router", "L4: route answers, or backtest two policies"),
    "audit": ("harness.judges.audit", "L5: judge audit on reworded answers (paid)"),
    "load": ("harness.scorecard.load", "L6: copy the logs into BigQuery"),
}


def usage() -> str:
    lines = ["Usage: python -m harness <command> [options]", "", "Commands:"]
    lines += [f"  {name:<15} {what}" for name, (_, what) in COMMANDS.items()]
    lines += ["", "python -m harness <command> --help shows that command's options."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run one command's main() with the remaining arguments; return its exit code."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(usage())
        return 0 if argv else 1
    name = argv[0].replace("-", "_")       # rule-checks works as well as rule_checks
    if name not in COMMANDS:
        print(f"Unknown command {argv[0]!r}.\n\n{usage()}")
        return 1
    module = importlib.import_module(COMMANDS[name][0])   # import only what this command needs
    sys.argv[0] = f"python -m harness {name}"             # so --help shows the right usage line
    return module.main(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
