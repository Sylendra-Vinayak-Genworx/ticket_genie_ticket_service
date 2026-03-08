"""Pydantic v2 schemas for Keyword Rule CRUD."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.constants.enum import MatchField, Severity


# ── Create / Update ──────────────────────────────────────────────────────────
class KeywordRuleCreateRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=255)
    match_field: MatchField
    target_severity: Severity
    is_active: bool = True


class KeywordRuleUpdateRequest(BaseModel):
    keyword: Optional[str] = Field(default=None, min_length=1, max_length=255)
    match_field: Optional[MatchField] = None
    target_severity: Optional[Severity] = None
    is_active: Optional[bool] = None


# ── Response ──────────────────────────────────────────────────────────────────
class KeywordRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    keyword_rule_id: int
    keyword: str
    match_field: MatchField
    target_severity: Severity
    is_active: bool
    created_at: datetime


# ── Filters ───────────────────────────────────────────────────────────────────
class KeywordRuleListFilters(BaseModel):
    is_active: Optional[bool] = None
    target_severity: Optional[Severity] = None
    match_field: Optional[MatchField] = None
    page: int = 1
    page_size: int = 20
