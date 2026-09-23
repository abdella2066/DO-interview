"""Business logic: flag CRUD, per-user overrides, cached evaluation, and the audit log.

Reads use cache-aside on a per-flag snapshot (global state, rollout percentage, overrides). Every
write commits to Postgres first and only then deletes that snapshot, so the next read rebuilds it
from the source of truth. The TTL is a safety net for anything invalidation misses.

Every write also adds its audit event to the same transaction before committing, so the change
and its record are saved or rolled back together.
"""

from typing import Any

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import Cache
from app.errors import FlagAlreadyExistsError, FlagNotFoundError, OverrideNotFoundError
from app.evaluation import Evaluation, FlagSnapshot, evaluate
from app.models import AuditAction, Flag, FlagAuditEvent, FlagOverride
from app.repository import FlagRepository
from app.schemas import FlagCreate, FlagUpdate


def snapshot_cache_key(flag_key: str) -> str:
    # Bump the version whenever FlagSnapshot's fields change. During a rolling deploy, old and new
    # instances share the cache, and neither may read a snapshot written by the other.
    return f"ff:flag:v2:{flag_key}"


def _override_map(user_id: str, override: bool | None) -> dict[str, bool]:
    return {} if override is None else {user_id: override}


class FlagService:
    def __init__(
        self, session: AsyncSession, cache: Cache, cache_ttl_seconds: int, actor: str | None
    ) -> None:
        self.session = session
        self.repo = FlagRepository(session)
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.actor = actor

    # --- Flags ---

    async def create_flag(self, data: FlagCreate) -> Flag:
        try:
            flag = await self.repo.add_flag(Flag(**data.model_dump()))
            self._audit(flag.key, AuditAction.FLAG_CREATED, data.model_dump(exclude={"key"}))
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if isinstance(exc.orig, UniqueViolation):
                raise FlagAlreadyExistsError(data.key) from exc
            raise
        await self._invalidate(flag.key)
        return flag

    async def get_flag(self, key: str) -> Flag:
        flag = await self.repo.get_flag(key)
        if flag is None:
            raise FlagNotFoundError(key)
        return flag

    async def list_flags(self, limit: int, offset: int) -> tuple[list[Flag], int]:
        return await self.repo.list_flags(limit, offset)

    async def update_flag(self, key: str, data: FlagUpdate) -> Flag:
        flag = await self.get_flag(key)
        changes = {
            field: value
            for field, value in data.model_dump(exclude_unset=True).items()
            if getattr(flag, field) != value
        }
        for field, value in changes.items():
            setattr(flag, field, value)
        if changes:
            self._audit(key, AuditAction.FLAG_UPDATED, changes)
        await self.session.commit()
        await self._invalidate(key)
        return flag

    async def delete_flag(self, key: str) -> None:
        if not await self.repo.delete_flag(key):
            raise FlagNotFoundError(key)
        self._audit(key, AuditAction.FLAG_DELETED, {})
        await self.session.commit()
        await self._invalidate(key)

    # --- Per-user overrides ---

    async def set_override(
        self, key: str, user_id: str, enabled: bool
    ) -> tuple[FlagOverride, bool]:
        """Create or replace a user's override. Returns (override, created)."""
        flag = await self.get_flag(key)
        created = await self.repo.get_override(flag.id, user_id) is None
        override = await self.repo.upsert_override(flag.id, user_id, enabled)
        self._audit(key, AuditAction.OVERRIDE_SET, {"user_id": user_id, "enabled": enabled})
        await self.session.commit()
        await self._invalidate(key)
        return override, created

    async def delete_override(self, key: str, user_id: str) -> None:
        flag = await self.get_flag(key)
        if not await self.repo.delete_override(flag.id, user_id):
            raise OverrideNotFoundError(key, user_id)
        self._audit(key, AuditAction.OVERRIDE_DELETED, {"user_id": user_id})
        await self.session.commit()
        await self._invalidate(key)

    async def list_overrides(
        self, key: str, limit: int, offset: int
    ) -> tuple[list[FlagOverride], int]:
        flag = await self.get_flag(key)
        return await self.repo.list_overrides(flag.id, limit, offset)

    # --- Audit log ---

    async def list_audit_events(
        self, key: str, limit: int, offset: int
    ) -> tuple[list[FlagAuditEvent], int]:
        """No 404 for unknown keys: a flag's history is kept after the flag is deleted."""
        return await self.repo.list_audit_events(key, limit, offset)

    def _audit(self, key: str, action: AuditAction, details: dict[str, Any]) -> None:
        self.repo.add_audit_event(key, action, self.actor, details)

    # --- Evaluation ---

    async def evaluate(self, key: str, user_id: str) -> tuple[Evaluation, bool]:
        """Returns (evaluation, cache_hit)."""
        snapshot, cache_hit = await self._get_snapshot(key)
        return evaluate(snapshot, user_id), cache_hit

    async def evaluate_all(self, user_id: str) -> list[tuple[str, Evaluation]]:
        """Every flag for one user, straight from Postgres in a single query (not cached)."""
        rows = await self.repo.list_flags_with_user_override(user_id)
        snapshots = [
            FlagSnapshot(key, enabled, rollout_percentage, _override_map(user_id, override))
            for key, enabled, rollout_percentage, override in rows
        ]
        return [(snapshot.key, evaluate(snapshot, user_id)) for snapshot in snapshots]

    async def _get_snapshot(self, key: str) -> tuple[FlagSnapshot, bool]:
        cached = await self.cache.get(snapshot_cache_key(key))
        if cached is not None:
            return FlagSnapshot.from_json(cached), True

        flag = await self.get_flag(key)
        snapshot = FlagSnapshot(
            key=flag.key,
            enabled=flag.enabled,
            rollout_percentage=flag.rollout_percentage,
            overrides=await self.repo.get_override_map(flag.id),
        )
        await self.cache.set(snapshot_cache_key(key), snapshot.to_json(), self.cache_ttl_seconds)
        return snapshot, False

    async def _invalidate(self, key: str) -> None:
        await self.cache.delete(snapshot_cache_key(key))
