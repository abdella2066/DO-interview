"""Request/response models and parameter rules. Validation failures become 422 responses."""

from datetime import datetime
from typing import Annotated

from fastapi import Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.evaluation import Reason

FLAG_KEY_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
USER_ID_PATTERN = r"^[A-Za-z0-9._:@+-]{1,128}$"

FlagKey = Annotated[str, StringConstraints(pattern=FLAG_KEY_PATTERN)]
FlagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
FlagDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

FlagKeyPath = Annotated[str, Path(pattern=FLAG_KEY_PATTERN, description="Flag key")]
UserIdPath = Annotated[str, Path(pattern=USER_ID_PATTERN, description="Your system's user ID")]
UserIdQuery = Annotated[str, Query(pattern=USER_ID_PATTERN, description="User to evaluate for")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


class RequestModel(BaseModel):
    # Unknown fields are rejected, so a typo like {"enable": true} fails loudly instead of no-op.
    model_config = ConfigDict(extra="forbid")


class FlagCreate(RequestModel):
    key: FlagKey = Field(
        examples=["new-checkout"],
        description="Unique and immutable. Lowercase letters, digits, '-' and '_'.",
    )
    name: FlagName = Field(examples=["New checkout flow"])
    description: FlagDescription | None = None
    enabled: StrictBool = Field(
        default=False, description="Global state: what every user gets unless overridden"
    )


class FlagUpdate(RequestModel):
    name: FlagName | None = None
    description: FlagDescription | None = None
    enabled: StrictBool | None = Field(
        default=None, description="true/false enables/disables the flag globally"
    )

    @model_validator(mode="after")
    def reject_empty_or_null(self) -> "FlagUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: name, description, enabled")
        for field in ("name", "enabled"):
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
