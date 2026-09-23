"""Evaluation rules as pure functions: no I/O, so they are easy to test and to reason about."""

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from hashlib import sha256


class Reason(StrEnum):
    USER_OVERRIDE = "USER_OVERRIDE"
    GLOBAL = "GLOBAL"
    ROLLOUT = "ROLLOUT"


@dataclass(frozen=True)
class FlagSnapshot:
    """Everything needed to evaluate one flag for any user. This is the unit that gets cached."""

    key: str
    enabled: bool
    rollout_percentage: int = 100
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


def rollout_bucket(flag_key: str, user_id: str) -> int:
    """The user's fixed slot (0-99) for this flag. Hashing in the flag key as well as the user ID
    places users independently per flag, so the same users aren't first into every rollout."""
    digest = sha256(f"{flag_key}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def evaluate(snapshot: FlagSnapshot, user_id: str) -> Evaluation:
    """In order: the user's override, the global off switch, then the percentage rollout."""
    if user_id in snapshot.overrides:
        return Evaluation(enabled=snapshot.overrides[user_id], reason=Reason.USER_OVERRIDE)
    if not snapshot.enabled:
        return Evaluation(enabled=False, reason=Reason.GLOBAL)
    if snapshot.rollout_percentage == 100:
        return Evaluation(enabled=True, reason=Reason.GLOBAL)
    in_rollout = rollout_bucket(snapshot.key, user_id) < snapshot.rollout_percentage
    return Evaluation(enabled=in_rollout, reason=Reason.ROLLOUT)
