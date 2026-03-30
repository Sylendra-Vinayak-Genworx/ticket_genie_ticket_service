"""Repository for managing priority rules (severity × tier → priority)."""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import Priority, Severity
from src.data.models.postgres.priority_rule import PriorityRule

logger = logging.getLogger(__name__)


class PriorityRuleRepository:
    """CRUD repository for the priority_rules table."""

    def __init__(self, db: AsyncSession) -> None:
        """
        Init.

        Args:
            db (AsyncSession): Async database session.
        """
        self.db = db

    async def list_all(self) -> list[PriorityRule]:
        """
        List all priority rules ordered by severity then tier_name.

        Returns:
            list[PriorityRule]: All rules.
        """
        result = await self.db.execute(
            select(PriorityRule).order_by(PriorityRule.severity, PriorityRule.tier_name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, rule_id: int) -> Optional[PriorityRule]:
        """
        Get a rule by primary key.

        Args:
            rule_id (int): Rule primary key.

        Returns:
            Optional[PriorityRule]: The rule, or None if not found.
        """
        result = await self.db.execute(
            select(PriorityRule).where(PriorityRule.rule_id == rule_id)
        )
        return result.scalar_one_or_none()

    async def get_by_severity_and_tier(
        self, severity: Severity, tier_name: str
    ) -> Optional[PriorityRule]:
        """
        Look up a rule by the (severity, tier_name) composite key.

        Args:
            severity (Severity): Ticket severity.
            tier_name (str): Customer tier name string.

        Returns:
            Optional[PriorityRule]: Matching rule, or None if absent.
        """
        result = await self.db.execute(
            select(PriorityRule).where(
                PriorityRule.severity == severity,
                PriorityRule.tier_name == tier_name,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, rule: PriorityRule) -> PriorityRule:
        """
        Persist a new priority rule.

        Args:
            rule (PriorityRule): Rule model instance (not yet flushed).

        Returns:
            PriorityRule: The persisted rule with DB-generated rule_id.
        """
        self.db.add(rule)
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def save(self, rule: PriorityRule) -> PriorityRule:
        """
        Update an existing priority rule.

        Args:
            rule (PriorityRule): Mutated rule instance.

        Returns:
            PriorityRule: The updated rule.
        """
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def delete(self, rule: PriorityRule) -> None:
        """
        Delete a priority rule.

        Args:
            rule (PriorityRule): Rule instance to delete.
        """
        await self.db.delete(rule)
        await self.db.flush()
