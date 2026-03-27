from typing import Optional

from fastapi import APIRouter, Query, status

from src.api.rest.dependencies import (
    CurrentUserRole,
    SLARuleManagementServiceDep,
)
from src.schemas.common_schema import PaginatedResponse
from src.schemas.sla_rule_schema import (
    SLACreateRequest,
    SLAListFilters,
    SLAResponse,
    SLARuleCreateRequest,
    SLARuleResponse,
    SLARuleUpdateRequest,
    SLAUpdateRequest,
)

router = APIRouter(prefix="/sla-rules", tags=["sla-rules"])

"""list SLAs with optional filters for active status and customer tier. Supports pagination."""
@router.get(
    "",
    response_model=PaginatedResponse[SLAResponse],
    summary="List SLAs",
    description="Retrieve a paginated list of SLAs with optional filters.",
)
async def list_slas(
    svc: SLARuleManagementServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: Optional[bool] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
)-> PaginatedResponse[SLAResponse]:
    """
    List slas.
    
    Args:
        svc (SLARuleManagementServiceDep): Input parameter.
        page (int): Input parameter.
        page_size (int): Input parameter.
        is_active (Optional[bool]): Input parameter.
        customer_tier_id (Optional[int]): Input parameter.
    
    Returns:
        PaginatedResponse[SLAResponse]: The expected output.
    """
    filters = SLAListFilters(
        is_active=is_active,
        customer_tier_id=customer_tier_id,
        page=page,
        page_size=page_size,
    )
    total, slas = await svc.list_slas(filters)
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[SLAResponse.model_validate(s) for s in slas],
    )

"""Get SLA details by ID, including nested rules."""
@router.get(
    "/{sla_id}",
    response_model=SLAResponse,
    summary="Get SLA detail (with nested rules)",
    description="Retrieve the details of a specific SLA.",
)
async def get_sla(sla_id: int, svc: SLARuleManagementServiceDep)-> SLAResponse:
    """
    Get sla.
    
    Args:
        sla_id (int): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
    
    Returns:
        SLAResponse: The expected output.
    """
    sla = await svc.get_sla(sla_id)
    return SLAResponse.model_validate(sla)

"""Create a new SLA with associated rules. Only accessible by LEAD or ADMIN roles."""
@router.post(
    "",
    response_model=SLAResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an SLA (LEAD / ADMIN)",
    description="Create a new SLA and its associated rules.",
)
async def create_sla(
    payload: SLACreateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
)-> SLAResponse:
    """
    Create sla.
    
    Args:
        payload (SLACreateRequest): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        SLAResponse: The expected output.
    """
    sla = await svc.create_sla(payload, current_user_role=user_role)
    return SLAResponse.model_validate(sla)

"""Update an existing SLA by ID. Only accessible by LEAD or ADMIN roles."""
@router.put(
    "/{sla_id}",
    response_model=SLAResponse,
    summary="Update an SLA (LEAD / ADMIN)",
    description="Update the configuration of an existing SLA.",
)
async def update_sla(
    sla_id: int,
    payload: SLAUpdateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
)-> SLAResponse:
    """
    Update sla.
    
    Args:
        sla_id (int): Input parameter.
        payload (SLAUpdateRequest): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        SLAResponse: The expected output.
    """
    sla = await svc.update_sla(sla_id, payload, current_user_role=user_role)
    return SLAResponse.model_validate(sla)

"""Delete an SLA by ID. Only accessible by LEAD or ADMIN roles."""
@router.delete(
    "/{sla_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an SLA (LEAD / ADMIN)",
    description="Delete an SLA from the system.",
)
async def delete_sla(
    sla_id: int,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
) -> None:
    """
    Delete sla.
    
    Args:
        sla_id (int): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    """
    await svc.delete_sla(sla_id, current_user_role=user_role)



@router.get(
    "/{sla_id}/rules",
    response_model=list[SLARuleResponse],
    summary="List rules for an SLA",
    description="Retrieve a list of rules for a specific SLA.",
)
async def list_rules(sla_id: int, svc: SLARuleManagementServiceDep)-> list[SLARuleResponse]:
    """
    List rules.
    
    Args:
        sla_id (int): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
    
    Returns:
        list[SLARuleResponse]: The expected output.
    """
    rules = await svc.list_rules(sla_id)
    return [SLARuleResponse.model_validate(r) for r in rules]


@router.get(
    "/rules/{rule_id}",
    response_model=SLARuleResponse,
    summary="Get a single SLA rule",
    description="Retrieve the details of a specific SLA rule.",
)
async def get_rule(rule_id: int, svc: SLARuleManagementServiceDep)-> SLARuleResponse:
    """
    Get rule.
    
    Args:
        rule_id (int): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
    
    Returns:
        SLARuleResponse: The expected output.
    """
    rule = await svc.get_rule(rule_id)
    return SLARuleResponse.model_validate(rule)


@router.post(
    "/{sla_id}/rules",
    response_model=SLARuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an SLA rule (LEAD / ADMIN)",
    description="Create a new rule for a specific SLA.",
)
async def create_rule(
    sla_id: int,
    payload: SLARuleCreateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
)-> SLARuleResponse:
    """
    Create rule.
    
    Args:
        sla_id (int): Input parameter.
        payload (SLARuleCreateRequest): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        SLARuleResponse: The expected output.
    """
    rule = await svc.create_rule(sla_id, payload, current_user_role=user_role)
    return SLARuleResponse.model_validate(rule)


@router.put(
    "/rules/{rule_id}",
    response_model=SLARuleResponse,
    summary="Update an SLA rule (LEAD / ADMIN)",
    description="Update the configuration of a specific SLA rule.",
)
async def update_rule(
    rule_id: int,
    payload: SLARuleUpdateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
)-> SLARuleResponse:
    """
    Update rule.
    
    Args:
        rule_id (int): Input parameter.
        payload (SLARuleUpdateRequest): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    
    Returns:
        SLARuleResponse: The expected output.
    """
    rule = await svc.update_rule(rule_id, payload, current_user_role=user_role)
    return SLARuleResponse.model_validate(rule)


@router.delete(
    "/rules/{rule_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an SLA rule (LEAD / ADMIN)",
    description="Delete a specific SLA rule.",
)
async def delete_rule(
    rule_id: int,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
) -> None:
    """
    Delete rule.
    
    Args:
        rule_id (int): Input parameter.
        svc (SLARuleManagementServiceDep): Input parameter.
        user_role (CurrentUserRole): Input parameter.
    """
    await svc.delete_rule(rule_id, current_user_role=user_role)

