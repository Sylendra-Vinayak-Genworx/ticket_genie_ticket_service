"""Service for SLA + SLA Rule CRUD — admin/lead management of SLA contracts."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import UserRole
from src.core.exceptions.base import (
    InsufficientPermissionsError,
    SLANotFoundError,
    SLARuleNotFoundError,
)
from src.data.models.postgres.sla import SLA, SLARule
from src.data.repositories.sla_repository import SLARepository
from src.data.repositories.sla_rule_repository import SLARuleRepository
from src.schemas.sla_rule_schema import (
    SLACreateRequest,
    SLAListFilters,
    SLARuleCreateRequest,
    SLARuleUpdateRequest,
    SLAUpdateRequest,
)

logger = logging.getLogger(__name__)

_WRITE_ROLES = {UserRole.LEAD, UserRole.ADMIN}


class SLARuleManagementService:
    def __init__(self, db: AsyncSession) -> None:
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
        """
        self.db = db
        self._sla_repo = SLARepository(db)
        self._rule_repo = SLARuleRepository(db)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_write_access(role: str) -> None:
        if UserRole(role) not in _WRITE_ROLES:
            raise InsufficientPermissionsError(
                "Only team leads and admins can manage SLA configurations."
            )

    async def _get_sla_or_404(self, sla_id: int) -> SLA:
        sla = await self._sla_repo.get_sla_by_id(sla_id)
        if not sla:
            raise SLANotFoundError(f"SLA {sla_id} not found.")
        return sla

    async def _get_rule_or_404(self, rule_id: int) -> SLARule:
        rule = await self._rule_repo.get_by_id(rule_id)
        if not rule:
            raise SLARuleNotFoundError(f"SLARule {rule_id} not found.")
        return rule

    # ── SLA CRUD ──────────────────────────────────────────────────────────────

    async def list_slas(self, filters: SLAListFilters) -> tuple[int, list[SLA]]:
        """
        List slas.
        
        Args:
            filters (SLAListFilters): Input parameter.
        
        Returns:
            tuple[int, list[SLA]]: The expected output.
        """
        return await self._sla_repo.list_all(
            is_active=filters.is_active,
            customer_tier_id=filters.customer_tier_id,
            page=filters.page,
            page_size=filters.page_size,
        )

    async def get_sla(self, sla_id: int) -> SLA:
        """
        Get sla.
        
        Args:
            sla_id (int): Input parameter.
        
        Returns:
            SLA: The expected output.
        """
        return await self._get_sla_or_404(sla_id)

    async def create_sla(
        self,
        payload: SLACreateRequest,
        current_user_role: str,
    ) -> SLA:
        """
        Create sla.
        
        Args:
            payload (SLACreateRequest): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            SLA: The expected output.
        """
        self._check_write_access(current_user_role)
        sla = SLA(
            name=payload.name,
            customer_tier_id=payload.customer_tier_id,
            is_active=payload.is_active,
        )
        sla = await self._sla_repo.create(sla)
        await self.db.commit()
        # re-fetch to load rules relationship
        sla = await self._sla_repo.get_sla_by_id(sla.sla_id)
        logger.info("sla_created: id=%s name=%r tier=%s", sla.sla_id, sla.name, sla.customer_tier_id)
        return sla

    async def update_sla(
        self,
        sla_id: int,
        payload: SLAUpdateRequest,
        current_user_role: str,
    ) -> SLA:
        """
        Update sla.
        
        Args:
            sla_id (int): Input parameter.
            payload (SLAUpdateRequest): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            SLA: The expected output.
        """
        self._check_write_access(current_user_role)
        sla = await self._get_sla_or_404(sla_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(sla, field, value)
        await self._sla_repo.save(sla)
        await self.db.commit()
        sla = await self._sla_repo.get_sla_by_id(sla_id)
        logger.info("sla_updated: id=%s", sla_id)
        return sla

    async def delete_sla(
        self,
        sla_id: int,
        current_user_role: str,
    ) -> None:
        """
        Delete sla.
        
        Args:
            sla_id (int): Input parameter.
            current_user_role (str): Input parameter.
        """
        self._check_write_access(current_user_role)
        sla = await self._get_sla_or_404(sla_id)
        await self._sla_repo.delete(sla)
        await self.db.commit()
        logger.info("sla_deleted: id=%s", sla_id)

    # ── SLA Rule CRUD ─────────────────────────────────────────────────────────

    async def list_rules(self, sla_id: int) -> list[SLARule]:
        """
        List rules.
        
        Args:
            sla_id (int): Input parameter.
        
        Returns:
            list[SLARule]: The expected output.
        """
        await self._get_sla_or_404(sla_id)  # ensure parent exists
        return await self._rule_repo.list_by_sla(sla_id)

    async def get_rule(self, rule_id: int) -> SLARule:
        """
        Get rule.
        
        Args:
            rule_id (int): Input parameter.
        
        Returns:
            SLARule: The expected output.
        """
        return await self._get_rule_or_404(rule_id)

    async def create_rule(
        self,
        sla_id: int,
        payload: SLARuleCreateRequest,
        current_user_role: str,
    ) -> SLARule:
        """
        Create rule.
        
        Args:
            sla_id (int): Input parameter.
            payload (SLARuleCreateRequest): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            SLARule: The expected output.
        """
        self._check_write_access(current_user_role)
        await self._get_sla_or_404(sla_id)  # validate parent
        rule = SLARule(
            sla_id=sla_id,
            severity=payload.severity,
            priority=payload.priority,
            response_time_minutes=payload.response_time_minutes,
            resolution_time_minutes=payload.resolution_time_minutes,
            escalation_after_minutes=payload.escalation_after_minutes,
        )
        rule = await self._rule_repo.create(rule)
        await self.db.commit()
        logger.info(
            "sla_rule_created: id=%s sla=%s sev=%s pri=%s",
            rule.rule_id, sla_id, rule.severity, rule.priority,
        )
        return rule

    async def update_rule(
        self,
        rule_id: int,
        payload: SLARuleUpdateRequest,
        current_user_role: str,
    ) -> SLARule:
        """
        Update rule.
        
        Args:
            rule_id (int): Input parameter.
            payload (SLARuleUpdateRequest): Input parameter.
            current_user_role (str): Input parameter.
        
        Returns:
            SLARule: The expected output.
        """
        self._check_write_access(current_user_role)
        rule = await self._get_rule_or_404(rule_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
        await self._rule_repo.save(rule)
        await self.db.commit()
        logger.info("sla_rule_updated: id=%s", rule_id)
        return rule

    async def delete_rule(
        self,
        rule_id: int,
        current_user_role: str,
    ) -> None:
        """
        Delete rule.
        
        Args:
            rule_id (int): Input parameter.
            current_user_role (str): Input parameter.
        """
        self._check_write_access(current_user_role)
        rule = await self._get_rule_or_404(rule_id)
        await self._rule_repo.delete(rule)
        await self.db.commit()
        logger.info("sla_rule_deleted: id=%s", rule_id)
