"""All SQL lives here; the service layer calls these methods and never builds queries itself."""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Flag, FlagOverride


class FlagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_flag(self, key: str) -> Flag | None:
        return await self.session.scalar(select(Flag).where(Flag.key == key))

    async def list_flags(self, limit: int, offset: int) -> tuple[list[Flag], int]:
        total = await self.session.scalar(select(func.count()).select_from(Flag))
        flags = await self.session.scalars(
            select(Flag)
            .order_by(Flag.created_at.desc(), Flag.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(flags), total or 0

    async def add_flag(self, flag: Flag) -> Flag:
        self.session.add(flag)
        await self.session.flush()  # sends the INSERT now, so a duplicate key raises here
        return flag

    async def delete_flag(self, key: str) -> bool:
        deleted_id = await self.session.scalar(
            delete(Flag).where(Flag.key == key).returning(Flag.id)
        )
        return deleted_id is not None

    async def get_override(self, flag_id: int, user_id: str) -> FlagOverride | None:
        return await self.session.get(FlagOverride, (flag_id, user_id))

    async def upsert_override(self, flag_id: int, user_id: str, enabled: bool) -> FlagOverride:
        statement = (
            insert(FlagOverride)
            .values(flag_id=flag_id, user_id=user_id, enabled=enabled)
            .on_conflict_do_update(
                index_elements=[FlagOverride.flag_id, FlagOverride.user_id],
                set_={"enabled": enabled, "updated_at": func.now()},
            )
            .returning(FlagOverride)
        )
        result = await self.session.scalars(
            statement, execution_options={"populate_existing": True}
        )
        return result.one()

    async def delete_override(self, flag_id: int, user_id: str) -> bool:
        deleted_user = await self.session.scalar(
            delete(FlagOverride)
            .where(FlagOverride.flag_id == flag_id, FlagOverride.user_id == user_id)
            .returning(FlagOverride.user_id)
        )
        return deleted_user is not None

    async def list_overrides(
        self, flag_id: int, limit: int, offset: int
    ) -> tuple[list[FlagOverride], int]:
        total = await self.session.scalar(
            select(func.count()).select_from(FlagOverride).where(FlagOverride.flag_id == flag_id)
        )
        overrides = await self.session.scalars(
            select(FlagOverride)
            .where(FlagOverride.flag_id == flag_id)
            .order_by(FlagOverride.user_id)
            .limit(limit)
            .offset(offset)
        )
        return list(overrides), total or 0

    async def list_flags_with_user_override(
        self, user_id: str
    ) -> list[tuple[str, bool, int, bool | None]]:
        """(key, global state, rollout percentage, this user's override or None) for every flag,
        in one query."""
        rows = await self.session.execute(
            select(Flag.key, Flag.enabled, Flag.rollout_percentage, FlagOverride.enabled)
            .outerjoin(
                FlagOverride,
                (FlagOverride.flag_id == Flag.id) & (FlagOverride.user_id == user_id),
            )
            .order_by(Flag.key)
        )
        return [
            (key, enabled, rollout_percentage, override)
            for key, enabled, rollout_percentage, override in rows
        ]

    async def get_override_map(self, flag_id: int) -> dict[str, bool]:
        rows = await self.session.execute(
            select(FlagOverride.user_id, FlagOverride.enabled).where(
                FlagOverride.flag_id == flag_id
            )
        )
        return {user_id: enabled for user_id, enabled in rows}
