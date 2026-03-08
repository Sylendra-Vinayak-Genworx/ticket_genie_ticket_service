"""
SLA + SLA-Rule management routes.

SLA:
  GET    /sla-rules                list SLAs (with filters & pagination)
  GET    /sla-rules/{id}           SLA detail (incl. nested rules)
  POST   /sla-rules                create SLA     (LEAD / ADMIN)
  PUT    /sla-rules/{id}           update SLA     (LEAD / ADMIN)
  DELETE /sla-rules/{id}           delete SLA     (LEAD / ADMIN)

SLA Rule (nested):
  GET    /sla-rules/{sla_id}/rules            list rules for an SLA
  GET    /sla-rules/rules/{rule_id}           single rule detail
  POST   /sla-rules/{sla_id}/rules            create rule   (LEAD / ADMIN)
  PUT    /sla-rules/rules/{rule_id}           update rule   (LEAD / ADMIN)
  DELETE /sla-rules/rules/{rule_id}           delete rule   (LEAD / ADMIN)
"""

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



@router.get(
    "",
    response_model=PaginatedResponse[SLAResponse],
    summary="List SLAs",
)
async def list_slas(
    svc: SLARuleManagementServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: Optional[bool] = Query(default=None),
    customer_tier_id: Optional[int] = Query(default=None),
):
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


@router.get(
    "/{sla_id}",
    response_model=SLAResponse,
    summary="Get SLA detail (with nested rules)",
)
async def get_sla(sla_id: int, svc: SLARuleManagementServiceDep):
    sla = await svc.get_sla(sla_id)
    return SLAResponse.model_validate(sla)


@router.post(
    "",
    response_model=SLAResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an SLA (LEAD / ADMIN)",
)
async def create_sla(
    payload: SLACreateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
):
    sla = await svc.create_sla(payload, current_user_role=user_role)
    return SLAResponse.model_validate(sla)


@router.put(
    "/{sla_id}",
    response_model=SLAResponse,
    summary="Update an SLA (LEAD / ADMIN)",
)
async def update_sla(
    sla_id: int,
    payload: SLAUpdateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
):
    sla = await svc.update_sla(sla_id, payload, current_user_role=user_role)
    return SLAResponse.model_validate(sla)


@router.delete(
    "/{sla_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an SLA (LEAD / ADMIN)",
)
async def delete_sla(
    sla_id: int,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
):
    await svc.delete_sla(sla_id, current_user_role=user_role)



@router.get(
    "/{sla_id}/rules",
    response_model=list[SLARuleResponse],
    summary="List rules for an SLA",
)
async def list_rules(sla_id: int, svc: SLARuleManagementServiceDep):
    rules = await svc.list_rules(sla_id)
    return [SLARuleResponse.model_validate(r) for r in rules]


@router.get(
    "/rules/{rule_id}",
    response_model=SLARuleResponse,
    summary="Get a single SLA rule",
)
async def get_rule(rule_id: int, svc: SLARuleManagementServiceDep):
    rule = await svc.get_rule(rule_id)
    return SLARuleResponse.model_validate(rule)


@router.post(
    "/{sla_id}/rules",
    response_model=SLARuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an SLA rule (LEAD / ADMIN)",
)
async def create_rule(
    sla_id: int,
    payload: SLARuleCreateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
):
    rule = await svc.create_rule(sla_id, payload, current_user_role=user_role)
    return SLARuleResponse.model_validate(rule)


@router.put(
    "/rules/{rule_id}",
    response_model=SLARuleResponse,
    summary="Update an SLA rule (LEAD / ADMIN)",
)
async def update_rule(
    rule_id: int,
    payload: SLARuleUpdateRequest,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
):
    rule = await svc.update_rule(rule_id, payload, current_user_role=user_role)
    return SLARuleResponse.model_validate(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an SLA rule (LEAD / ADMIN)",
)
async def delete_rule(
    rule_id: int,
    svc: SLARuleManagementServiceDep,
    user_role: CurrentUserRole,
):
    await svc.delete_rule(rule_id, current_user_role=user_role)

