"""Load and check config.yaml. Every setting the harness uses comes through here."""
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Prices(_Strict):
    input: float = Field(ge=0)
    output: float = Field(ge=0)


class BotConfig(_Strict):
    provider: str
    model: str
    temperature: float | None = None
    max_tokens: int = Field(gt=0)
    price_usd_per_mtok: Prices


class CostConfig(_Strict):
    max_aud_per_run: float = Field(gt=0)
    usd_to_aud: float = Field(gt=0)


class VariantConfig(_Strict):
    prompt: Path | None = None
    leaflets: bool = False


class GenerateConfig(_Strict):
    scopes: list[str]
    variants: dict[str, VariantConfig]


class Leaflet(_Strict):
    key: str
    path: Path
    prepared: str


class RuleChecksConfig(_Strict):
    promptfoo_version: str
    promptfoo_config: Path
    promptfoo_results: Path
    hits: Path


class LabelsConfig(_Strict):
    sheet: Path
    shuffle_seed: int
    rubric: Path


class JudgeModel(BotConfig):
    name: str = Field(min_length=1)


class JudgeConfig(_Strict):
    prompt: Path
    answers_run: str = Field(min_length=1)
    partition: str
    repeats: int = Field(ge=1)
    judges: list[JudgeModel] = Field(min_length=1)


class Paths(_Strict):
    cases: Path
    sources: Path
    answers: Path
    judgements: Path


class Config(_Strict):
    bot: BotConfig
    cost: CostConfig
    generate: GenerateConfig
    leaflets: list[Leaflet]
    rule_checks: RuleChecksConfig
    labels: LabelsConfig
    judge: JudgeConfig
    paths: Paths

    def resolve(self, root: Path) -> "Config":
        """Return a copy with every relative path made absolute against root."""
        c = self.model_copy(deep=True)
        for v in c.generate.variants.values():
            if v.prompt is not None:
                v.prompt = root / v.prompt
        for leaflet in c.leaflets:
            leaflet.path = root / leaflet.path
        c.paths = Paths(**{k: root / p for k, p in c.paths.model_dump().items()})
        rc = c.rule_checks
        rc.promptfoo_config, rc.promptfoo_results, rc.hits = (
            root / rc.promptfoo_config, root / rc.promptfoo_results, root / rc.hits)
        c.labels.sheet, c.labels.rubric = root / c.labels.sheet, root / c.labels.rubric
        c.judge.prompt = root / c.judge.prompt
        return c


def load_config(path: Path = CONFIG, root: Path = ROOT) -> Config:
    """Read config.yaml, check it, and resolve its paths against the repo root."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(**data).resolve(root)
