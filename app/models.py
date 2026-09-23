"""Database tables: a flag, per-user overrides of that flag's global state, and the audit log."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Flag(Base):
    __tablename__ = "flags"
    __table_args__ = (
        CheckConstraint(
            "rollout_percentage >= 0 AND rollout_percentage <= 100",
            name="flags_rollout_percentage_check",
        ),
    )
    # Fetch server-set timestamps with RETURNING after UPDATEs too (the "auto" default only covers
    # INSERTs); reading an expired attribute would need a lazy load, which async sessions can't do.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=false())
    rollout_percentage: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FlagOverride(Base):
    __tablename__ = "flag_overrides"
    __mapper_args__ = {"eager_defaults": True}

    flag_id: Mapped[int] = mapped_column(
        ForeignKey("flags.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditAction(StrEnum):
    FLAG_CREATED = "flag.created"
    FLAG_UPDATED = "flag.updated"
    FLAG_DELETED = "flag.deleted"
    OVERRIDE_SET = "override.set"
    OVERRIDE_DELETED = "override.deleted"


class FlagAuditEvent(Base):
    __tablename__ = "flag_audit_events"
    __table_args__ = (
        Index("ix_flag_audit_events_flag_key_created_at_id", "flag_key", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Deliberately not a foreign key to flags, so a flag's history outlives the flag.
    flag_key: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
