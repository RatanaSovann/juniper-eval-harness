"""Dagster pipeline: the harness's steps in order, with each run ID handed to the next step.

Run:  dagster dev -m harness.pipeline      (opens the Dagster UI at http://localhost:3000)

Two jobs:
- refresh_scorecard  (free)  load the files into BigQuery, then dbt build.
- full_eval          (PAID, about A$5)  generate answers -> rule checks -> judges -> router -> load -> dbt build.
  Each paid step keeps its own cost cap from config.yaml. Its weekly schedule is defined but OFF
  until you switch it on in the UI.

Run IDs pass between steps in memory (the judge reads the answers just generated, the router reads
those verdicts), so config.yaml is never edited. Dagster: a tool that runs steps in order, shows
each run's logs, and can schedule jobs.
"""
from dagster import (DefaultScheduleStatus, Definitions, Failure, In, Nothing, OpExecutionContext,
                     ScheduleDefinition, job, op)
from dotenv import load_dotenv

from harness import generate, judge, load, router, rule_checks
from harness.config import ROOT, load_config

DBT_DIR = ROOT / "dbt"


@op
def generate_answers(context: OpExecutionContext) -> str:
    """Ask the bot every in-scope question with every variant. Returns the new answer run ID."""
    load_dotenv(ROOT / ".env")
    config = load_config()
    model = generate.AnthropicModel(config.bot.model, config.bot.max_tokens, config.bot.temperature)
    run_id, written, spent = generate.run(config, model, log=context.log.info)
    context.add_output_metadata({"answers": written, "spent_aud": round(spent, 2)})
    return run_id


@op
def check_rules(context: OpExecutionContext, answers_run: str) -> str:
    """Stage 3 rule checks (promptfoo) on that answer run. Passes the run ID on."""
    if rule_checks.main(["--run-id", answers_run]) != 0:
        raise Failure(f"Rule checks failed for {answers_run}; see the log above")
    return answers_run


@op
def judge_answers(context: OpExecutionContext, answers_run: str) -> dict:
    """Every judge in config.yaml scores the dev answers of that run. Returns both run IDs."""
    load_dotenv(ROOT / ".env")
    config = load_config()
    config.judge.answers_run = answers_run
    problems = judge.setup_problems(config)
    if problems:
        raise Failure("Judges not ready: " + "; ".join(problems))
    models = {j.name: judge.PROVIDERS[j.provider](j) for j in config.judge.judges}
    judge_run, written, spent = judge.run(config, models, log=context.log.info)
    context.add_output_metadata({"verdicts": written, "spent_aud": round(spent, 2)})
    return {"answers_run": answers_run, "judge_run": judge_run}


@op
def route_answers(context: OpExecutionContext, runs: dict) -> str:
    """Route the answers with the active policy, using the verdicts just made. Returns the route run ID."""
    config = load_config()
    config.judge.answers_run = runs["answers_run"]
    config.router.judge_runs = {j.name: runs["judge_run"] for j in config.judge.judges}
    route_run, decisions = router.route(config, log=context.log.info)
    context.add_output_metadata({"answers": len(decisions),
                                 "human_review": sum(d.route == "human_review" for d in decisions)})
    return route_run


@op(ins={"after": In(Nothing)})
def load_warehouse(context: OpExecutionContext) -> None:
    """Replace the raw BigQuery tables with the current files."""
    loaded = load.load(load_config(), log=context.log.info)
    context.add_output_metadata({table: rows for table, rows in loaded.items()})


@op(ins={"after": In(Nothing)})
def build_scorecard(context: OpExecutionContext) -> None:
    """dbt build: rebuild the staging views and scorecard tables, and run every data test."""
    from dbt.cli.main import dbtRunner  # dbt's official way to run it from Python

    result = dbtRunner().invoke(["build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)])
    if not result.success:
        raise Failure(f"dbt build failed: {result.exception or 'a model or test failed; see the log above'}")


@job(description="Free: copy the files into BigQuery, then rebuild the scorecard.")
def refresh_scorecard():
    build_scorecard(after=load_warehouse())


@job(description="PAID (about A$5): new answers, rule checks, judges, routing, then the scorecard.")
def full_eval():
    routed = route_answers(judge_answers(check_rules(generate_answers())))
    build_scorecard(after=load_warehouse(after=routed))


weekly_full_eval = ScheduleDefinition(
    job=full_eval,
    cron_schedule="0 9 * * 1",                    # Mondays 09:00
    execution_timezone="Australia/Sydney",
    default_status=DefaultScheduleStatus.STOPPED,  # costs money: off until switched on in the UI
)

defs = Definitions(jobs=[refresh_scorecard, full_eval], schedules=[weekly_full_eval])
