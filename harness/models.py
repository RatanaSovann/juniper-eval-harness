"""Data models for the harness. One row of data/test_cases.csv is one TestCase;
one line of runs/answers.jsonl is one LoggedAnswer."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEVERITY_WEIGHT = {"low": 1, "medium": 3, "high": 10, "critical": 30}

# Columns the author fills by hand. Blank is allowed until Stage 1b is finished.
OWNER_COLUMNS = ("partition", "rule_checks", "assistant_scope")


def parse_rule_checks(text: str) -> dict[str, list[str]]:
    """Split 'require:a|b; forbid:x|y' into {'require': ['a', 'b'], 'forbid': ['x', 'y']}.

    Raises ValueError if the text doesn't follow that format.
    """
    rules: dict[str, list[str]] = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        kind, sep, terms = part.partition(":")
        kind = kind.strip()
        if not sep or kind not in ("require", "forbid"):
            raise ValueError(f"each part must start with 'require:' or 'forbid:', got {part!r}")
        if kind in rules:
            raise ValueError(f"'{kind}' appears more than once")
        words = [t.strip() for t in terms.split("|")]
        if not all(words):
            raise ValueError(f"empty term in {part!r}")
        rules[kind] = words
    if not rules:
        raise ValueError("no rules found")
    return rules


class TestCase(BaseModel):
    """One patient question, with what a good answer must and must not do."""

    __test__ = False  # stop pytest treating this as a test class

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    workstream: Literal["ai_assistant", "px_support"]
    category: str = Field(min_length=1)
    medicine: str = Field(min_length=1)
    patient_question: str = Field(min_length=1)
    risk_level: Literal["low", "medium", "high", "critical"]
    expected_behaviour: Literal[
        "answer", "answer_with_caveat", "escalate_clinician", "escalate_urgent", "handoff_human"
    ]
    must_include: str = Field(min_length=1)
    must_not_include: str = Field(min_length=1)
    trap: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    partition: Literal["dev", "locked"] | None = None
    severity_weight: int
    rule_checks: str | None = None
    assistant_scope: Literal["medical_support", "coaching"] | None = None

    @field_validator(*OWNER_COLUMNS, mode="before")
    @classmethod
    def blank_is_none(cls, v):
        """Treat an empty CSV cell as 'not filled in yet'."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("rule_checks")
    @classmethod
    def rule_checks_format(cls, v):
        if v is not None:
            parse_rule_checks(v)
        return v

    @model_validator(mode="after")
    def cross_field_rules(self):
        if self.risk_level == "critical" and self.expected_behaviour != "escalate_urgent":
            raise ValueError("critical case must be escalate_urgent")
        if self.severity_weight != SEVERITY_WEIGHT[self.risk_level]:
            raise ValueError(
                f"severity_weight {self.severity_weight} does not match "
                f"risk_level {self.risk_level} (expected {SEVERITY_WEIGHT[self.risk_level]})"
            )
        return self

    def source_keys(self) -> set[str]:
        """Source keys cited in source_ref, e.g. 'WEG_CMI s4; MJ_CMI s2' -> {'WEG_CMI', 'MJ_CMI'}."""
        return {part.strip().split()[0] for part in self.source_ref.split(";") if part.strip()}


class LoggedAnswer(BaseModel):
    """One bot answer to one test case, as written to runs/answers.jsonl."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float | None
    prompt_version: str = Field(min_length=1)
    leaflet_date: str | None
    timestamp: datetime
    answer: str
    stop_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_aud: float = Field(ge=0)
