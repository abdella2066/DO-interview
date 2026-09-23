"""Evaluation rules as pure functions: no I/O, so they are easy to test and to reason about."""

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Reason(StrEnum):
    USER_OVERRIDE = "USER_OVERRIDE"
    GLOBAL = "GLOBAL"


@dataclass(frozen=True)
class FlagSnapshot:
    """Everything needed to evaluate one flag for any user. This is the unit that gets cached."""

    key: str
    enabled: bool
    overrides: dict[str, bool] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "FlagSnapshot":
        return cls(**json.loads(raw))


@dataclass(frozen=True)
class Evaluation:
    enabled: bool
    reason: Reason


def evaluate(snapshot: FlagSnapshot, user_id: str) -> Evaluation:
    """A per-user override wins; everyone else gets the flag's global state."""
    if user_id in snapshot.overrides:
        return Evaluation(enabled=snapshot.overrides[user_id], reason=Reason.USER_OVERRIDE)
    return Evaluation(enabled=snapshot.enabled, reason=Reason.GLOBAL)
