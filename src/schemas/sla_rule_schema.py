"""Pydantic v2 schemas for SLA & SLA Rule CRUD."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.constants.enum import Priority, Severity


# ── SLA ───────────────────────────────────────────────────────────────────────
class SLACreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    customer_tier_id: int
    is_active: bool = True


class SLAUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


class SLAResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sla_id: int
    name: str
    customer_tier_id: int
    is_active: bool
    created_at: datetime
    rules: list["SLARuleResponse"] = Field(default_factory=list)


# ── SLA Rule ──────────────────────────────────────────────────────────────────
class SLARuleCreateRequest(BaseModel):
    severity: Severity
    priority: Priority
    response_time_minutes: int = Field(..., gt=0)
    resolution_time_minutes: int = Field(..., gt=0)
    escalation_after_minutes: int = Field(..., gt=0)


class SLARuleUpdateRequest(BaseModel):
    response_time_minutes: Optional[int] = Field(default=None, gt=0)
    resolution_time_minutes: Optional[int] = Field(default=None, gt=0)
    escalation_after_minutes: Optional[int] = Field(default=None, gt=0)


class SLARuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    sla_id: int
    severity: Severity
    priority: Priority
    response_time_minutes: int
    resolution_time_minutes: int
    escalation_after_minutes: int


# ── List filters ──────────────────────────────────────────────────────────────
class SLAListFilters(BaseModel):
    is_active: Optional[bool] = None
    customer_tier_id: Optional[int] = None
    page: int = 1
    page_size: int = 20


# Resolve forward ref
SLAResponse.model_rebuild()
