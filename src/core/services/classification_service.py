import logging
from dataclasses import dataclass

from src.constants.enum import MatchField, Priority, Severity
from src.data.models.postgres.keyword_rule import KeywordRule
from src.data.repositories.keyword_repository import KeywordRepository

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
    def __init__(self, keyword_repo: KeywordRepository) -> None:
        """
          init  .
        
        Args:
            keyword_repo (KeywordRepository): Input parameter.
        """
        self._repo = keyword_repo          

    async def classify(self, title: str, description: str) -> ClassificationResult:
        """
        Run all active keyword rules against title + description.
        Returns the highest-severity match, or LOW/P3 default.
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
            logger.debug(
                "classification: matched rule_id=%s keyword=%r severity=%s",
                best.keyword_rule_id, best.keyword, best.target_severity,
            )
            return ClassificationResult(
                severity=best.target_severity,
                priority=_SEVERITY_TO_PRIORITY[best.target_severity],
                matched_rule_id=best.keyword_rule_id,
                matched_keyword=best.keyword,
            )

        logger.debug("classification: no keyword match — defaulting to LOW / P3")
        return ClassificationResult(severity=Severity.LOW, priority=Priority.P3)