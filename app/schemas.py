"""Request/response models and parameter rules. Validation failures become 422 responses."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import Header, Path, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.evaluation import Reason
from app.models import AuditAction

FLAG_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
USER_ID_PATTERN = r"^[A-Za-z0-9._:@+-]{1,128}$"
# Plain-English messages for pattern failures, by field name, returned instead of the raw regex.
PATTERN_HINTS = {
    "key": "Use 1-64 letters, digits, '-' or '_', starting with a letter or digit "
    "(for example 'new-checkout')",
    "user_id": "Use 1-128 letters, digits, or the characters . _ : @ + -",
}
# Printable ASCII only: header bytes are decoded as Latin-1, so UTF-8 names would be stored garbled.
ACTOR_PATTERN = r"^[ -~]+$"

FlagKey = Annotated[str, StringConstraints(pattern=FLAG_KEY_PATTERN)]
FlagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
FlagDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
# Strict: "50", 50.5, 50.0, and true are rejected rather than coerced.
RolloutPercentage = Annotated[StrictInt, Field(ge=0, le=100)]

FlagKeyPath = Annotated[str, Path(pattern=FLAG_KEY_PATTERN, description="Flag key")]
UserIdPath = Annotated[str, Path(pattern=USER_ID_PATTERN, description="Your system's user ID")]
UserIdQuery = Annotated[str, Query(pattern=USER_ID_PATTERN, description="User to evaluate for")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
ActorHeader = Annotated[
    str | None,
    Header(
        alias="X-Actor",
        max_length=100,
        pattern=ACTOR_PATTERN,
        description="Who is making the change. Writes record it in the audit log; reads only "
        "validate it. Self-reported: the service can't verify it.",
    ),
]


class RequestModel(BaseModel):
    # Unknown fields are rejected, so a typo like {"enable": true} fails loudly instead of no-op.
    model_config = ConfigDict(extra="forbid")


class FlagCreate(RequestModel):
    key: FlagKey = Field(
        examples=["new-checkout"],
        description="Immutable. Letters, digits, '-' and '_'. Lookups are exact, but keys "
        "that differ only in case count as duplicates.",
    )
    name: FlagName = Field(examples=["New checkout flow"])
    description: FlagDescription | None = None
    enabled: StrictBool = Field(
        default=False, description="Global state: what every user gets unless overridden"
    )
    rollout_percentage: RolloutPercentage = Field(
        default=100, description="Share of users (0-100) who get the flag while it's enabled"
    )


class FlagUpdate(RequestModel):
    name: FlagName | None = None
    description: FlagDescription | None = None
    enabled: StrictBool | None = Field(
        default=None, description="true/false enables/disables the flag globally"
    )
    rollout_percentage: RolloutPercentage | None = Field(
        default=None, description="Share of users (0-100) who get the flag while it's enabled"
    )

    @model_validator(mode="after")
    def reject_empty_or_null(self) -> "FlagUpdate":
        if not self.model_fields_set:
            raise ValueError(
                "Provide at least one of: name, description, enabled, rollout_percentage"
            )
        for field in ("name", "enabled", "rollout_percentage"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"'{field}' cannot be null")
        return self


class OverrideSet(RequestModel):
    enabled: StrictBool


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str | None
    enabled: bool
    rollout_percentage: int
    created_at: datetime
    updated_at: datetime


class FlagList(BaseModel):
    items: list[FlagOut]
    total: int
    limit: int
    offset: int


class OverrideOut(BaseModel):
    flag_key: str
    user_id: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class OverrideList(BaseModel):
    items: list[OverrideOut]
    total: int
    limit: int
    offset: int


class EvaluationOut(BaseModel):
    flag_key: str
    user_id: str
    enabled: bool
    reason: Reason


class UserFlag(BaseModel):
    flag_key: str
    enabled: bool
    reason: Reason


class UserFlagsOut(BaseModel):
    user_id: str
    flags: list[UserFlag]


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: AuditAction
    actor: str | None
    details: dict[str, Any]
    created_at: datetime


class AuditEventList(BaseModel):
    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int
