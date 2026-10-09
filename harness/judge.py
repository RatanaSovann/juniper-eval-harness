"""Have two AI judges score the bot's answers and append their verdicts to runs/judgements.jsonl.

Run:  python -m harness.judge --limit 2      (first 2 answers, every judge, every repeat)
      python -m harness.judge                (every answer in judge.answers_run and judge.partition)
      python -m harness.judge --resume <judge_run_id>   (finish a run that stopped part-way)
      python -m harness.judge --only gemini             (one judge only, e.g. after changing its model)
      python -m harness.judge --labelled                (only answers you have hand-labelled)
      python -m harness.judge --partition locked        (the locked set, once, at the end)

Each judge scores each answer judge.repeats times, so you can see whether it agrees with
itself. Busy-server errors (429/5xx) are retried by the SDKs with growing waits. Unusable JSON gets one retry, then the verdict is logged as "invalid". Scores are
never averaged. The run stops before any call that could push its estimated cost past
cost.max_aud_per_run in config.yaml.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from pydantic import ValidationError

from harness.agreement import load_labels
from harness.config import ROOT, Config, JudgeModel, load_config
from harness.generate import ChatModel, Completion, CostCapReached, cost_aud, worst_case_aud
from harness.models import Judgement, JudgeScores, LoggedAnswer, TestCase
from harness.validate_cases import validate

BUSY_CODES = [429, 500, 502, 503, 504]
RETRY_NOTE = "\n\nYour last reply could not be read. Reply with JSON only, in exactly the shape given."
KEY_VARS = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "xai": "XAI_API_KEY"}


class OpenAIModel:
    """An OpenAI judge, called through the official OpenAI SDK in JSON mode."""

    def __init__(self, cfg: JudgeModel, **client_args):
        import openai  # imported here so tests never need the SDK or a key

        # key from OPENAI_API_KEY unless client_args say otherwise; SDK backs off between tries
        self.client = openai.OpenAI(max_retries=5, **client_args)
        self.cfg = cfg


    def complete(self, system: str | None, user: str) -> Completion:
        kwargs = {} if self.cfg.temperature is None else {"temperature": self.cfg.temperature}
        response = self.client.chat.completions.create(
            model=self.cfg.model,
            max_completion_tokens=self.cfg.max_tokens,  # includes any reasoning tokens
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system or ""}, {"role": "user", "content": user}],
            **kwargs,
        )
        choice = response.choices[0]
        return Completion(choice.message.content or "", response.usage.prompt_tokens,
                          response.usage.completion_tokens, choice.finish_reason)


class XAIModel(OpenAIModel):
    """An xAI Grok judge. xAI's API is OpenAI-compatible, so it is the OpenAI SDK pointed at api.x.ai."""

    def __init__(self, cfg: JudgeModel):
        super().__init__(cfg, base_url="https://api.x.ai/v1", api_key=os.environ.get("XAI_API_KEY"))


class GeminiModel:
    """A Google Gemini judge, called through the google-genai SDK in JSON mode."""

    def __init__(self, cfg: JudgeModel):
        from google import genai
        from google.genai import types

        retry = types.HttpRetryOptions(attempts=6, initial_delay=2, max_delay=60, http_status_codes=BUSY_CODES)
        self.client = genai.Client(http_options=types.HttpOptions(retry_options=retry))  # key from GEMINI_API_KEY
        self.cfg = cfg

    def complete(self, system: str | None, user: str) -> Completion:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.cfg.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=self.cfg.temperature,
                max_output_tokens=self.cfg.max_tokens, response_mime_type="application/json",
            ),
        )
        usage = response.usage_metadata
        # thinking tokens are billed as output, so count them
        output = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        finish = response.candidates[0].finish_reason if response.candidates else None
        return Completion(response.text or "", usage.prompt_token_count or 0, output,
                          str(finish) if finish else None)


PROVIDERS = {"openai": OpenAIModel, "gemini": GeminiModel, "xai": XAIModel}


def build_system(config: Config, case: TestCase) -> str:
    """Judge instruction + rubric + the leaflet text for every leaflet the case cites.

    Cases citing only sources without saved text (e.g. JUNIPER_FAQ) get no leaflet; the
    user message names those sources so the judge knows it hasn't seen them.
    """
    parts = [config.judge.prompt.read_text(encoding="utf-8").strip(),
             f"<rubric>\n{config.labels.rubric.read_text(encoding='utf-8').strip()}\n</rubric>"]
    keys = case.source_keys()
    for leaflet in config.leaflets:
        if leaflet.key in keys:
            body = leaflet.path.read_text(encoding="utf-8").strip()
            parts.append(f'<leaflet source="{leaflet.key}" prepared="{leaflet.prepared}">\n{body}\n</leaflet>')
    return "\n\n".join(parts)


def build_user(config: Config, case: TestCase, answer: str) -> str:
    """The case facts the rubric needs (not must_include / must_not_include) plus the answer."""
    have_text = {l.key for l in config.leaflets}
    missing = sorted(case.source_keys() - have_text)
    lines = [
        f"Patient question: {case.patient_question}",
        f"Medicine: {case.medicine}",
        f"Risk level: {case.risk_level}",
        f"Expected behaviour: {case.expected_behaviour}",
        f"Source cited for this case: {case.source_ref}",
    ]
    if missing:
        lines.append(f"Not provided to you (no saved text): {', '.join(missing)}")
    lines.append(f"\n<answer>\n{answer}\n</answer>")
    return "\n".join(lines)


def parse_scores(text: str) -> JudgeScores | None:
    """Read a judge reply into JudgeScores, or None if it isn't valid JSON in the right shape.

    Tolerates a ```json fence or stray words around the JSON object.
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return JudgeScores(**json.loads(text[start:end + 1]))
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None


def select_answers(config: Config, limit: int | None, labelled: bool = False) -> list[tuple[LoggedAnswer, TestCase]]:
    """Answers from judge.answers_run whose case is in judge.partition, in log order.

    labelled=True keeps only answers fully hand-labelled in labels.sheet, the ones the
    agreement report compares against.
    """
    cases, errors = validate(config.paths.cases, config.paths.sources)
    if errors:
        raise ValueError("Test set has problems; run python -m harness.validate_cases")
    by_id = {c.case_id: c for c in cases if c.partition == config.judge.partition}
    keep = load_labels(config.labels.sheet, config.judge.answers_run, set(by_id)) if labelled else None
    picked = []
    for line in config.paths.answers.read_text(encoding="utf-8").splitlines():
        a = LoggedAnswer(**json.loads(line))
        if a.run_id == config.judge.answers_run and a.case_id in by_id and (
                keep is None or (a.case_id, a.variant) in keep):
            picked.append((a, by_id[a.case_id]))
    if not picked:
        raise ValueError(f"No {'labelled ' if labelled else ''}{config.judge.partition} answers "
                         f"found for run {config.judge.answers_run}")
    return picked[:limit] if limit else picked


def load_resume(config: Config, judge_run_id: str) -> tuple[set[tuple], float]:
    """Verdicts already saved for judge_run_id, as (case_id, variant, judge, repeat) keys, and their cost.

    Raises ValueError if the run doesn't exist or config.yaml has changed since it started
    (answer run, judge prompt or a judge's model), so one run never mixes two setups.
    """
    path = config.paths.judgements
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    rows = [j for j in (Judgement(**json.loads(l)) for l in lines) if j.judge_run_id == judge_run_id]
    if not rows:
        raise ValueError(f"No saved verdicts for judge_run_id {judge_run_id}; nothing to resume")
    models = {j.name: j.model for j in config.judge.judges}
    for r in rows:
        if (r.answer_run_id != config.judge.answers_run or r.prompt_version != config.judge.prompt.stem
                or models.get(r.judge) != r.model):
            raise ValueError(f"config.yaml has changed since {judge_run_id} started "
                             f"(it used answers {r.answer_run_id}, prompt {r.prompt_version}, "
                             f"{r.judge} = {r.model}); start a new run instead")
    return {(r.case_id, r.variant, r.judge, r.repeat) for r in rows}, sum(r.cost_aud for r in rows)


def judge_once(config: Config, model: ChatModel, jcfg: JudgeModel, system: str, user: str, spent: float,
               **ids) -> Judgement:
    """One verdict from one judge: unusable JSON gets one retry, then the verdict is "invalid".

    spent is what the run has already spent; raises CostCapReached before any call that could
    push it past cost.max_aud_per_run. ids fills the Judgement's run, case, variant and repeat fields.
    """
    cap = config.cost.max_aud_per_run
    scores, text, attempts, tokens_in, tokens_out, cost = None, "", 0, 0, 0, 0.0
    while scores is None and attempts < 2:
        prompt = user if attempts == 0 else user + RETRY_NOTE
        next_max = worst_case_aud(config, system, prompt, jcfg)
        if spent + cost + next_max > cap:
            raise CostCapReached(f"Cost cap: spent A${spent + cost:.2f} of A${cap:.2f}; "
                                 f"next call could cost up to A${next_max:.2f}.")
        c = model.complete(system, prompt)
        attempts += 1
        tokens_in, tokens_out = tokens_in + c.input_tokens, tokens_out + c.output_tokens
        cost += cost_aud(config, c.input_tokens, c.output_tokens, jcfg)
        text, scores = c.text, parse_scores(c.text)
    return Judgement(
        **ids, judge=jcfg.name, model=jcfg.model, prompt_version=config.judge.prompt.stem,
        attempts=attempts, status="valid" if scores else "invalid", scores=scores,
        raw=None if scores else text, timestamp=datetime.now(timezone.utc),
        input_tokens=tokens_in, output_tokens=tokens_out, cost_aud=round(cost, 6),
    )


def run(config: Config, models: dict[str, ChatModel], limit: int | None = None, log=print,
        resume: str | None = None, labelled: bool = False) -> tuple[str, int, float]:
    """Score each selected answer with each judge, judge.repeats times, appending one line per verdict.

    models maps judge name -> model. resume is a judge_run_id to finish: its saved verdicts are
    skipped and its spend counts toward the cap. Returns (judge_run_id, verdicts written now,
    AUD spent by the run in total). Raises CostCapReached if the next call could exceed the
    cap; verdicts already written stay.
    """
    answers = select_answers(config, limit, labelled)
    if resume:
        judge_run_id = resume
        done, spent = load_resume(config, resume)
    else:
        judge_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        done, spent = set(), 0.0
    cap, repeats = config.cost.max_aud_per_run, config.judge.repeats
    written = 0

    config.paths.judgements.parent.mkdir(parents=True, exist_ok=True)
    log(f"judge_run_id {judge_run_id}: {len(answers)} answers from {config.judge.answers_run} x "
        f"{len(config.judge.judges)} judges x {repeats} repeats, cap A${cap:.2f}"
        + (f"; resuming: {len(done)} verdicts already saved, A${spent:.2f} spent" if resume else ""))
    with config.paths.judgements.open("a", encoding="utf-8") as out:
        for answer, case in answers:
            system, user = build_system(config, case), build_user(config, case, answer.answer)
            for jcfg in config.judge.judges:
                for repeat in range(1, repeats + 1):
                    if (answer.case_id, answer.variant, jcfg.name, repeat) in done:
                        continue
                    try:
                        row = judge_once(config, models[jcfg.name], jcfg, system, user, spent,
                                         judge_run_id=judge_run_id, answer_run_id=answer.run_id,
                                         case_id=answer.case_id, variant=answer.variant, repeat=repeat)
                    except CostCapReached as e:
                        raise CostCapReached(f"{e} Stopped after {written} verdicts (judge_run_id {judge_run_id}).") from None
                    out.write(row.model_dump_json() + "\n")
                    out.flush()
                    spent += row.cost_aud
                    written += 1
                    log(f"  {answer.case_id:<10} {answer.variant:<15} {jcfg.name:<7} r{repeat} "
                        f"{row.status:<7} A${spent:.3f}")
    log(f"Done: {written} new verdicts, A${spent:.2f} spent by this run, appended to {config.paths.judgements}")
    return judge_run_id, written, spent


def setup_problems(config: Config) -> list[str]:
    """Everything that must be fixed before a paid run: unfilled models, zero prices, missing keys."""
    problems = []
    if not config.judge.prompt.exists():
        problems.append(f"Judge instruction missing: {config.judge.prompt}")
    for j in config.judge.judges:
        if j.provider not in PROVIDERS:
            problems.append(f"Judge {j.name}: provider {j.provider!r} is not supported")
            continue
        if not j.model:
            problems.append(f"Judge {j.name}: fill in judge.judges[].model in config.yaml")
        if j.price_usd_per_mtok.input <= 0 or j.price_usd_per_mtok.output <= 0:
            problems.append(f"Judge {j.name}: fill in list prices in config.yaml so the cost cap works")
        if not os.environ.get(KEY_VARS[j.provider]):
            problems.append(f"Judge {j.name}: no {KEY_VARS[j.provider]} in .env or this terminal")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only the first N answers")
    parser.add_argument("--resume", metavar="JUDGE_RUN_ID", help="finish a run that stopped part-way")
    parser.add_argument("--labelled", action="store_true", help="only answers with a full hand label")
    parser.add_argument("--partition", choices=["dev", "locked"],
                        help="which cases to judge (default: judge.partition). Locked is for measuring only, never tuning")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="run only these judges, e.g. --only gemini")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    config = load_config()
    if args.partition:
        config.judge.partition = args.partition
    if args.only:
        names = {j.name for j in config.judge.judges}
        if unknown := set(args.only) - names:
            print(f"Unknown judge(s) {sorted(unknown)}; config.yaml has {sorted(names)}. Nothing was sent.")
            return 1
        config.judge.judges = [j for j in config.judge.judges if j.name in args.only]
    problems = setup_problems(config)
    if problems:
        print("Not ready, nothing was sent:\n  " + "\n  ".join(problems))
        return 1
    try:
        models = {j.name: PROVIDERS[j.provider](j) for j in config.judge.judges}
        run(config, models, args.limit, resume=args.resume, labelled=args.labelled)
    except (ValueError, CostCapReached) as e:
        print(e)
        return 1
    except Exception as e:  # API errors: verdicts so far are already saved
        print(f"Stopped on {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
