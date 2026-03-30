import logging
from dataclasses import dataclass
from typing import Optional

from src.constants.enum import MatchField, Priority, Severity
from src.data.models.postgres.keyword_rule import KeywordRule
from src.data.repositories.keyword_repository import KeywordRepository
from src.data.repositories.priority_rule_repository import PriorityRuleRepository
from src.data.repositories.customer_tier_repository import CustomerTierRepository

logger = logging.getLogger(__name__)

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH:     1,
    Severity.MEDIUM:   2,
    Severity.LOW:      3,
}

_SEVERITY_TO_PRIORITY: dict[Severity, Priority] = {
    Severity.CRITICAL: Priority.P0,
    Severity.HIGH:     Priority.P1,
    Severity.MEDIUM:   Priority.P2,
    Severity.LOW:      Priority.P3,
}


@dataclass
class ClassificationResult:
    severity: Severity
    priority: Priority
    matched_rule_id: int | None = None
    matched_keyword: str | None = None


class ClassificationService:
    def __init__(
        self,
        keyword_repo: KeywordRepository,
        priority_rule_repo: Optional[PriorityRuleRepository] = None,
        customer_tier_repo: Optional[CustomerTierRepository] = None,
    ) -> None:
        """
        Init.

        Args:
            keyword_repo (KeywordRepository): Active keyword rules repository.
            priority_rule_repo (Optional[PriorityRuleRepository]): DB priority rule repo.
                When None the service falls back to the static mapping.
            customer_tier_repo (Optional[CustomerTierRepository]): Customer tier repo
                used to resolve tier_name from tier_id.
        """
        self._repo = keyword_repo
        self._priority_rule_repo = priority_rule_repo
        self._customer_tier_repo = customer_tier_repo

    async def _resolve_priority(
        self,
        severity: Severity,
        customer_tier_id: Optional[int],
    ) -> Priority:
        """
        Resolve priority via DB lookup with safe fallback to static mapping.

        Resolution flow:
        1. If both repos are injected AND customer_tier_id is present → DB lookup.
        2. Rule found → return DB priority (debug log).
        3. Rule missing → warning log, fallback.
        4. Any exception → exception log, fallback.

        Args:
            severity (Severity): Ticket severity.
            customer_tier_id (Optional[int]): Customer tier primary key.

        Returns:
            Priority: Resolved priority, never raises.
        """
        fallback = _SEVERITY_TO_PRIORITY[severity]

        if (
            self._priority_rule_repo is not None
            and self._customer_tier_repo is not None
            and customer_tier_id is not None
        ):
            try:
                tier = await self._customer_tier_repo.get_by_id(customer_tier_id)
                if tier is not None:
                    rule = await self._priority_rule_repo.get_by_severity_and_tier(
                        severity, tier.name
                    )
                    if rule is not None:
                        logger.debug(
                            "classification: DB priority resolved — "
                            "severity=%s tier=%r priority=%s rule_id=%s",
                            severity, tier.name, rule.priority, rule.rule_id,
                        )
                        return rule.priority
                    logger.warning(
                        "classification: no DB rule for (severity=%s, tier=%r) — fallback to %s",
                        severity, tier.name, fallback,
                    )
                else:
                    logger.warning(
                        "classification: tier_id=%s not found — fallback to %s",
                        customer_tier_id, fallback,
                    )
            except Exception:
                logger.exception(
                    "classification: DB priority lookup failed — fallback to %s", fallback
                )

        return fallback

    async def classify(
        self,
        title: str,
        description: str,
        customer_tier_id: Optional[int] = None,
    ) -> ClassificationResult:
        """
        Run all active keyword rules against title + description,
        then resolve priority via DB lookup (with safe fallback).

        Args:
            title (str): Ticket title.
            description (str): Ticket description.
            customer_tier_id (Optional[int]): Customer tier ID for priority lookup.

        Returns:
            ClassificationResult: severity, priority, matched rule info.
        """
        rules: list[KeywordRule] = await self._repo.get_active_rules()

        best: KeywordRule | None = None
        best_rank: int = len(_SEVERITY_RANK)

        title_lower = title.lower()
        body_lower  = description.lower()

        for rule in rules:
            kw = rule.keyword.lower()
            match = False

            if rule.match_field == MatchField.SUBJECT:
                match = kw in title_lower
            elif rule.match_field == MatchField.BODY:
                match = kw in body_lower
            elif rule.match_field == MatchField.BOTH:
                match = kw in title_lower or kw in body_lower

            if match:
                rank = _SEVERITY_RANK.get(rule.target_severity, 99)
                if rank < best_rank:
                    best_rank = rank
                    best = rule

        if best:
            severity = best.target_severity
            logger.debug(
                "classification: matched rule_id=%s keyword=%r severity=%s",
                best.keyword_rule_id, best.keyword, severity,
            )
            priority = await self._resolve_priority(severity, customer_tier_id)
            return ClassificationResult(
                severity=severity,
                priority=priority,
                matched_rule_id=best.keyword_rule_id,
                matched_keyword=best.keyword,
            )

        logger.debug("classification: no keyword match — defaulting to LOW")
        severity = Severity.LOW
        priority = await self._resolve_priority(severity, customer_tier_id)
        return ClassificationResult(severity=severity, priority=priority)