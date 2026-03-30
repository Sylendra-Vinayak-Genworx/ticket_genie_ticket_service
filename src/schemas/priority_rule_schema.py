"""Pydantic v2 schemas for priority rule API requests and responses."""

from pydantic import BaseModel, ConfigDict

from src.constants.enum import Priority, Severity


class PriorityRuleCreateRequest(BaseModel):
    """Request schema for creating a new priority rule."""

    severity: Severity
    tier_name: str
    priority: Priority


class PriorityRuleUpdateRequest(BaseModel):
    """Request schema for updating the priority on an existing rule."""

    priority: Priority


class PriorityRuleResponse(BaseModel):
    """Response schema for a single priority rule."""

    rule_id: int
    severity: Severity
    tier_name: str
    priority: Priority

    model_config = ConfigDict(from_attributes=True)
