"""
KeywordRule repository — manages the ``keyword_rules`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.keyword_rule import KeywordRule


class KeywordRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── READ ─────────────────────────────────────────────────────────────────

    async def get_active_rules(self) -> list[KeywordRule]:
        result = await self.db.execute(
            select(KeywordRule)
            .where(KeywordRule.is_active == True)
            .order_by(KeywordRule.keyword_rule_id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, rule_id: int) -> Optional[KeywordRule]:
        result = await self.db.execute(
            select(KeywordRule).where(KeywordRule.keyword_rule_id == rule_id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        is_active: Optional[bool] = None,
        target_severity: Optional[str] = None,
        match_field: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[KeywordRule]]:
        stmt = select(KeywordRule)
        if is_active is not None:
            stmt = stmt.where(KeywordRule.is_active == is_active)
        if target_severity is not None:
            stmt = stmt.where(KeywordRule.target_severity == target_severity)
        if match_field is not None:
            stmt = stmt.where(KeywordRule.match_field == match_field)

        count_result = await self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = count_result.scalar_one()

        stmt = stmt.order_by(KeywordRule.keyword_rule_id)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return total, list(result.scalars().all())

    # ── WRITE ────────────────────────────────────────────────────────────────

    async def create(self, rule: KeywordRule) -> KeywordRule:
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def save(self, rule: KeywordRule) -> KeywordRule:
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def delete(self, rule: KeywordRule) -> None:
        await self.db.delete(rule)
        await self.db.flush()