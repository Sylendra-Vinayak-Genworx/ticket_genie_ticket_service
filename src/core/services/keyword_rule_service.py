"""Service for Keyword Rule CRUD — admin/lead management of classification rules."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import UserRole
from src.core.exceptions.base import InsufficientPermissionsError, KeywordRuleNotFoundError
from src.data.models.postgres.keyword_rule import KeywordRule
from src.data.repositories.keyword_repository import KeywordRepository
from src.schemas.keyword_rule_schema import (
    KeywordRuleCreateRequest,
    KeywordRuleListFilters,
    KeywordRuleUpdateRequest,
)

logger = logging.getLogger(__name__)

_WRITE_ROLES = {UserRole.LEAD, UserRole.ADMIN}


class KeywordRuleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = KeywordRepository(db)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_write_access(role: str) -> None:
        if UserRole(role) not in _WRITE_ROLES:
            raise InsufficientPermissionsError(
                "Only team leads and admins can manage keyword rules."
            )

    async def _get_or_404(self, rule_id: int) -> KeywordRule:
        rule = await self._repo.get_by_id(rule_id)
        if not rule:
            raise KeywordRuleNotFoundError(f"KeywordRule {rule_id} not found.")
        return rule

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def list_rules(
        self, filters: KeywordRuleListFilters
    ) -> tuple[int, list[KeywordRule]]:
        return await self._repo.list_all(
            is_active=filters.is_active,
            target_severity=filters.target_severity,
            match_field=filters.match_field,
            page=filters.page,
            page_size=filters.page_size,
        )

    async def get_rule(self, rule_id: int) -> KeywordRule:
        return await self._get_or_404(rule_id)

    async def create_rule(
        self,
        payload: KeywordRuleCreateRequest,
        current_user_role: str,
    ) -> KeywordRule:
        self._check_write_access(current_user_role)
        rule = KeywordRule(
            keyword=payload.keyword,
            match_field=payload.match_field,
            target_severity=payload.target_severity,
            is_active=payload.is_active,
        )
        rule = await self._repo.create(rule)
        await self.db.commit()
        logger.info("keyword_rule_created: id=%s keyword=%r", rule.keyword_rule_id, rule.keyword)
        return rule

    async def update_rule(
        self,
        rule_id: int,
        payload: KeywordRuleUpdateRequest,
        current_user_role: str,
    ) -> KeywordRule:
        self._check_write_access(current_user_role)
        rule = await self._get_or_404(rule_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
        rule = await self._repo.save(rule)
        await self.db.commit()
        logger.info("keyword_rule_updated: id=%s", rule_id)
        return rule

    async def delete_rule(
        self,
        rule_id: int,
        current_user_role: str,
    ) -> None:
        self._check_write_access(current_user_role)
        rule = await self._get_or_404(rule_id)
        await self._repo.delete(rule)
        await self.db.commit()
        logger.info("keyword_rule_deleted: id=%s", rule_id)
