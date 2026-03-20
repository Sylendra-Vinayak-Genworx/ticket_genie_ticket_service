
from typing import Optional

from fastapi import APIRouter, Query, status

from src.api.rest.dependencies import (
    CurrentUserRole,
    KeywordRuleServiceDep,
)
from src.constants.enum import MatchField, Severity
from src.schemas.common_schema import PaginatedResponse
from src.schemas.keyword_rule_schema import (
    KeywordRuleCreateRequest,
    KeywordRuleListFilters,
    KeywordRuleResponse,
    KeywordRuleUpdateRequest,
)

router = APIRouter(prefix="/keyword-rules", tags=["keyword-rules"])



@router.get(
    "",
    response_model=PaginatedResponse[KeywordRuleResponse],
    summary="List keyword rules",
)
async def list_rules(
    svc: KeywordRuleServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: Optional[bool] = Query(default=None),
    target_severity: Optional[Severity] = Query(default=None),
    match_field: Optional[MatchField] = Query(default=None),
):
    filters = KeywordRuleListFilters(
        is_active=is_active,
        target_severity=target_severity,
        match_field=match_field,
        page=page,
        page_size=page_size,
    )
    total, rules = await svc.list_rules(filters)
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[KeywordRuleResponse.model_validate(r) for r in rules],
    )


@router.get(
    "/{rule_id}",
    response_model=KeywordRuleResponse,
    summary="Get a keyword rule",
)
async def get_rule(rule_id: int, svc: KeywordRuleServiceDep):
    rule = await svc.get_rule(rule_id)
    return KeywordRuleResponse.model_validate(rule)


@router.post(
    "",
    response_model=KeywordRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a keyword rule (LEAD / ADMIN)",
)
async def create_rule(
    payload: KeywordRuleCreateRequest,
    svc: KeywordRuleServiceDep,
    user_role: CurrentUserRole,
):
    rule = await svc.create_rule(payload, current_user_role=user_role)
    return KeywordRuleResponse.model_validate(rule)


@router.put(
    "/{rule_id}",
    response_model=KeywordRuleResponse,
    summary="Update a keyword rule (LEAD / ADMIN)",
)
async def update_rule(
    rule_id: int,
    payload: KeywordRuleUpdateRequest,
    svc: KeywordRuleServiceDep,
    user_role: CurrentUserRole,
):
    rule = await svc.update_rule(rule_id, payload, current_user_role=user_role)
    return KeywordRuleResponse.model_validate(rule)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a keyword rule (LEAD / ADMIN)",
)
async def delete_rule(
    rule_id: int,
    svc: KeywordRuleServiceDep,
    user_role: CurrentUserRole,
):
    await svc.delete_rule(rule_id, current_user_role=user_role)
