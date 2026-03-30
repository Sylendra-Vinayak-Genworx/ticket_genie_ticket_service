"""Service for Priority Rule CRUD — admin-controlled configuration of priority lookup."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import UserRole
from src.core.exceptions.base import (
    InsufficientPermissionsError,
    PriorityRuleConflictError,
    PriorityRuleNotFoundError,
)
from src.data.models.postgres.priority_rule import PriorityRule
from src.data.repositories.priority_rule_repository import PriorityRuleRepository
from src.schemas.priority_rule_schema import (
    PriorityRuleCreateRequest,
    PriorityRuleUpdateRequest,
)

logger = logging.getLogger(__name__)

# STRICT: only ADMIN can write.  TEAM_LEAD is explicitly excluded.
_WRITE_ROLES = {UserRole.ADMIN}


class PriorityRuleService:
    """CRUD service for priority_rules table — write operations are ADMIN-only."""

    def __init__(self, db: AsyncSession) -> None:
        """
        Init.

        Args:
            db (AsyncSession): Async database session.
        """
        self.db = db
        self._repo = PriorityRuleRepository(db)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_write_access(role: str) -> None:
        """
        Enforce admin-only write access.

        Args:
            role (str): Current user role string.

        Raises:
            InsufficientPermissionsError: If role is not ADMIN.
        """
        if UserRole(role) not in _WRITE_ROLES:
            raise InsufficientPermissionsError(
                "Only administrators can manage priority rules."
            )

    async def _get_or_404(self, rule_id: int) -> PriorityRule:
        """
        Fetch a rule by ID or raise PriorityRuleNotFoundError.

        Args:
            rule_id (int): Rule primary key.

        Returns:
            PriorityRule: The found rule.

        Raises:
            PriorityRuleNotFoundError: If rule does not exist.
        """
        rule = await self._repo.get_by_id(rule_id)
        if not rule:
            raise PriorityRuleNotFoundError(f"PriorityRule {rule_id} not found.")
        return rule

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def list_rules(self) -> list[PriorityRule]:
        """
        List all priority rules.

        Returns:
            list[PriorityRule]: All rules ordered by severity, tier.
        """
        return await self._repo.list_all()

    async def get_rule(self, rule_id: int) -> PriorityRule:
        """
        Get a priority rule by ID.

        Args:
            rule_id (int): Rule primary key.

        Returns:
            PriorityRule: The rule.

        Raises:
            PriorityRuleNotFoundError: If rule does not exist.
        """
        return await self._get_or_404(rule_id)

    async def create_rule(
        self,
        payload: PriorityRuleCreateRequest,
        current_user_role: str,
    ) -> PriorityRule:
        """
        Create a new priority rule.  ADMIN only.

        Args:
            payload (PriorityRuleCreateRequest): Rule data.
            current_user_role (str): Caller's role.

        Returns:
            PriorityRule: The created rule.

        Raises:
            InsufficientPermissionsError: Non-admin caller.
            PriorityRuleConflictError: Duplicate (severity, tier_name).
        """
        self._check_write_access(current_user_role)

        existing = await self._repo.get_by_severity_and_tier(payload.severity, payload.tier_name)
        if existing:
            raise PriorityRuleConflictError(
                f"Rule for ({payload.severity}, {payload.tier_name!r}) already exists."
            )

        rule = PriorityRule(
            severity=payload.severity,
            tier_name=payload.tier_name,
            priority=payload.priority,
        )
        rule = await self._repo.create(rule)
        await self.db.commit()
        logger.info(
            "priority_rule_created: id=%s severity=%s tier=%r priority=%s",
            rule.rule_id, rule.severity, rule.tier_name, rule.priority,
        )
        return rule

    async def update_rule(
        self,
        rule_id: int,
        payload: PriorityRuleUpdateRequest,
        current_user_role: str,
    ) -> PriorityRule:
        """
        Update the priority of an existing rule.  ADMIN only.

        Args:
            rule_id (int): Rule primary key.
            payload (PriorityRuleUpdateRequest): Updated priority.
            current_user_role (str): Caller's role.

        Returns:
            PriorityRule: The updated rule.

        Raises:
            InsufficientPermissionsError: Non-admin caller.
            PriorityRuleNotFoundError: Rule does not exist.
        """
        self._check_write_access(current_user_role)
        rule = await self._get_or_404(rule_id)
        rule.priority = payload.priority
        rule = await self._repo.save(rule)
        await self.db.commit()
        logger.info("priority_rule_updated: id=%s new_priority=%s", rule_id, payload.priority)
        return rule

    async def delete_rule(
        self,
        rule_id: int,
        current_user_role: str,
    ) -> None:
        """
        Delete a priority rule.  ADMIN only.

        Args:
            rule_id (int): Rule primary key.
            current_user_role (str): Caller's role.

        Raises:
            InsufficientPermissionsError: Non-admin caller.
            PriorityRuleNotFoundError: Rule does not exist.
        """
        self._check_write_access(current_user_role)
        rule = await self._get_or_404(rule_id)
        await self._repo.delete(rule)
        await self.db.commit()
        logger.info("priority_rule_deleted: id=%s", rule_id)
