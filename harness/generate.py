"""Ask the bot under test every medical question and append its answers to runs/answers.jsonl.

Run:  python -m harness.generate --limit 3     (first 3 cases, both variants)
      python -m harness.generate               (every case in scope)

Each run gets a new run_id and only ever appends. The run stops before any call that
could push its estimated cost past cost.max_aud_per_run in config.yaml.
"""
import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from dotenv import load_dotenv

from harness.config import ROOT, BotConfig, Config, load_config
from harness.models import LoggedAnswer, TestCase
from harness.validate_cases import validate

CHARS_PER_TOKEN = 3  # cautious: real English text is closer to 4, so this over-estimates input cost


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None


class ChatModel(Protocol):
    """Anything that can answer one question. The real bot and the test fake both fit."""

    def complete(self, system: str | None, user: str) -> Completion: ...


class AnthropicModel:
    """The bot under test, called through the official Anthropic SDK."""

    def __init__(self, model: str, max_tokens: int, temperature: float | None):
        import anthropic  # imported here so tests never need the SDK or a key

        self.client = anthropic.Anthropic()  # key from ANTHROPIC_API_KEY
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature

    def complete(self, system: str | None, user: str) -> Completion:
        kwargs = {}
        if system is not None:
            kwargs["system"] = system
        if self.temperature is not None:
            # SDK 1.x dropped the temperature argument; models that still accept it take it in the body
            kwargs["extra_body"] = {"temperature": self.temperature}
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return Completion(text, response.usage.input_tokens, response.usage.output_tokens, response.stop_reason)


class CostCapReached(Exception):
    pass


@dataclass
class Variant:
    name: str
    system: str | None
    prompt_version: str
    leaflet_date: str | None


def build_variants(config: Config) -> list[Variant]:
    """Turn the variants in config.yaml into ready-to-send system prompts.

    Raises FileNotFoundError naming the missing file, before any paid call is made.
    """
    variants = []
    for name, v in config.generate.variants.items():
        if v.prompt is None:
            variants.append(Variant(name, None, name, None))
            continue
        if not v.prompt.exists():
            raise FileNotFoundError(f"Instruction file missing: {v.prompt}")
        parts = [v.prompt.read_text(encoding="utf-8").strip()]
        leaflet_date = None
        if v.leaflets:
            for leaflet in config.leaflets:
                body = leaflet.path.read_text(encoding="utf-8").strip()
                parts.append(f'<leaflet source="{leaflet.key}" prepared="{leaflet.prepared}">\n{body}\n</leaflet>')
            leaflet_date = "; ".join(f"{l.key} {l.prepared}" for l in config.leaflets)
        variants.append(Variant(name, "\n\n".join(parts), v.prompt.stem, leaflet_date))
    return variants


def cost_aud(config: Config, input_tokens: int, output_tokens: int, model: BotConfig | None = None) -> float:
    """Price a call in AUD from token counts and the list prices in config.yaml.

    model is the bot or judge that made the call; it defaults to the bot under test.
    """
    p = (model or config.bot).price_usd_per_mtok
    usd = (input_tokens * p.input + output_tokens * p.output) / 1_000_000
    return usd * config.cost.usd_to_aud


def worst_case_aud(config: Config, system: str | None, user: str, model: BotConfig | None = None) -> float:
    """Upper estimate for one call: generous input token guess plus a full max_tokens reply."""
    model = model or config.bot
    est_input = (len(system or "") + len(user)) // CHARS_PER_TOKEN + 50
    return cost_aud(config, est_input, model.max_tokens, model)


def select_cases(config: Config, limit: int | None) -> list[TestCase]:
    """Load the test set (refusing a broken one) and keep only cases in the configured scopes."""
    cases, errors = validate(config.paths.cases, config.paths.sources)
    if errors:
        raise ValueError("Test set has problems; run python -m harness.validate_cases")
    cases = [c for c in cases if c.assistant_scope in config.generate.scopes]
    return cases[:limit] if limit else cases


def run(config: Config, model: ChatModel, limit: int | None = None, log=print) -> tuple[str, int, float]:
    """Answer each case with each variant and append one line per answer.

    Returns (run_id, answers written, AUD spent). Raises CostCapReached if the next
    call could exceed the cap; answers already written stay in the log.
    """
    variants = build_variants(config)
    cases = select_cases(config, limit)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    cap = config.cost.max_aud_per_run
    spent, written = 0.0, 0

    config.paths.answers.parent.mkdir(parents=True, exist_ok=True)
    log(f"run_id {run_id}: {len(cases)} cases x {len(variants)} variants, model {config.bot.model}, cap A${cap:.2f}")
    with config.paths.answers.open("a", encoding="utf-8") as out:
        for case in cases:
            for v in variants:
                next_max = worst_case_aud(config, v.system, case.patient_question)
                if spent + next_max > cap:
                    raise CostCapReached(
                        f"Cost cap: spent A${spent:.2f} of A${cap:.2f}; next call could cost up to "
                        f"A${next_max:.2f}. Stopped after {written} answers (run_id {run_id})."
                    )
                c = model.complete(v.system, case.patient_question)
                cost = cost_aud(config, c.input_tokens, c.output_tokens)
                row = LoggedAnswer(
                    run_id=run_id, case_id=case.case_id, variant=v.name, model=config.bot.model,
                    temperature=config.bot.temperature, prompt_version=v.prompt_version,
                    leaflet_date=v.leaflet_date, timestamp=datetime.now(timezone.utc), answer=c.text,
                    stop_reason=c.stop_reason, input_tokens=c.input_tokens,
                    output_tokens=c.output_tokens, cost_aud=round(cost, 6),
                )
                out.write(row.model_dump_json() + "\n")
                out.flush()
                spent += cost
                written += 1
                log(f"  {case.case_id:<10} {v.name:<9} {c.input_tokens:>6} in {c.output_tokens:>5} out  A${spent:.3f}")
    log(f"Done: {written} answers, A${spent:.2f} spent, appended to {config.paths.answers}")
    return run_id, written, spent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only the first N cases")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")  # fills in keys from .env; a key already set in the terminal wins
    config = load_config()
    if config.bot.provider != "anthropic":
        print(f"Provider {config.bot.provider!r} is not supported yet.")
        return 1
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("No API key found. Add ANTHROPIC_API_KEY to .env or set it in this terminal. Nothing was sent.")
        return 1
    try:
        build_variants(config)
        model = AnthropicModel(config.bot.model, config.bot.max_tokens, config.bot.temperature)
        run(config, model, args.limit)
    except (FileNotFoundError, ValueError, CostCapReached) as e:
        print(e)
        return 1
    except Exception as e:  # API errors: answers so far are already saved
        print(f"Stopped on {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
