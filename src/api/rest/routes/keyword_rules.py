
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


"""List keyword rules with optional filters for active status, target severity, and match field. Supports pagination."""
@router.get(
    "",
    response_model=PaginatedResponse[KeywordRuleResponse],
    summary="List keyword rules",
    description="Retrieve a paginated list of keyword rules with optional filters.",
)
async def list_rules(
    svc: KeywordRuleServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: Optional[bool] = Query(default=None),
    target_severity: Optional[Severity] = Query(default=None),
    match_field: Optional[MatchField] = Query(default=None),
)-> PaginatedResponse[KeywordRuleResponse]:
    """
    List rules.
    
    Args:
        svc (KeywordRuleServiceDep): Input parameter.
        page (int): Input parameter.
        page_size (int): Input parameter.
        is_active (Optional[bool]): Input parameter.
        target_severity (Optional[Severity]): Input parameter.
        match_field (Optional[MatchField]): Input parameter.
    
    Returns:
        PaginatedResponse[KeywordRuleResponse]: The expected output.
    """
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

"""Get a keyword rule by ID."""
@router.get(
    "/{rule_id}",
    response_model=KeywordRuleResponse,
    summary="Get a keyword rule",
    description="Retrieve the details of a specific keyword rule by its ID.",
)
async def get_rule(rule_id: int, svc: KeywordRuleServiceDep)-> KeywordRuleResponse:
    """
    Get rule.
    
    Args:
        rule_id (int): Input parameter.
        svc (KeywordRuleServiceDep): Input parameter.
    
    Returns:
        KeywordRuleResponse: The expected output.
    """
    rule = await svc.get_rule(rule_id)
    return KeywordRuleResponse.model_validate(rule)

"""Create a new keyword rule. Only accessible by LEAD or ADMIN roles."""
@router.post(
    "",
    response_model=KeywordRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a keyword rule (LEAD / ADMIN)",
    description="Create a new keyword rule in the system.",
)
async def create_rule(
    payload: KeywordRuleCreateRequest,
    svc: KeywordRuleServiceDep,
    user_role: CurrentUserRole,
)-> KeywordRuleResponse:
    """
    Create rule.
    
    Args:
        payload (KeywordRuleCreateRequest): Input parameter.
        svc (KeywordRuleServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        KeywordRuleResponse: The expected output.
    """
    rule = await svc.create_rule(payload, current_user_role=user_role)
    return KeywordRuleResponse.model_validate(rule)

"""Update an existing keyword rule by ID. Only accessible by LEAD or ADMIN roles."""
@router.put(
    "/{rule_id}",
    response_model=KeywordRuleResponse,
    summary="Update a keyword rule (LEAD / ADMIN)",
    description="Update the configuration of an existing keyword rule.",
)
async def update_rule(
    rule_id: int,
    payload: KeywordRuleUpdateRequest,
    svc: KeywordRuleServiceDep,
    user_role: CurrentUserRole,
)-> KeywordRuleResponse:
    """
    Update rule.
    
    Args:
        rule_id (int): Input parameter.
        payload (KeywordRuleUpdateRequest): Input parameter.
        svc (KeywordRuleServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        KeywordRuleResponse: The expected output.
    """
    rule = await svc.update_rule(rule_id, payload, current_user_role=user_role)
    return KeywordRuleResponse.model_validate(rule)

"""Delete a keyword rule by ID. Only accessible by LEAD or ADMIN roles."""
@router.delete(
    "/{rule_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a keyword rule (LEAD / ADMIN)",
    description="Delete a keyword rule from the system."
)
async def delete_rule(
    rule_id: int,
    svc: KeywordRuleServiceDep,
    user_role: CurrentUserRole,
) -> None:
    """
    Delete rule.
    
    Args:
        rule_id (int): Input parameter.
        svc (KeywordRuleServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    """
    await svc.delete_rule(rule_id, current_user_role=user_role)
