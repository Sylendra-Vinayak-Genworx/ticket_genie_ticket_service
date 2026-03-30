from fastapi import APIRouter, status

from src.api.rest.dependencies import (
    CurrentUserRole,
    PriorityRuleServiceDep,
)
from src.schemas.priority_rule_schema import (
    PriorityRuleCreateRequest,
    PriorityRuleResponse,
    PriorityRuleUpdateRequest,
)

router = APIRouter(prefix="/priority-rules", tags=["priority-rules"])


@router.get(
    "",
    response_model=list[PriorityRuleResponse],
    summary="List priority rules",
    description="Retrieve all priority rules (severity × tier → priority mapping). Accessible to any authenticated user.",
)
async def list_rules(svc: PriorityRuleServiceDep) -> list[PriorityRuleResponse]:
    """
    List rules.

    Args:
        svc (PriorityRuleServiceDep): Injected service.

    Returns:
        list[PriorityRuleResponse]: All priority rules.
    """
    rules = await svc.list_rules()
    return [PriorityRuleResponse.model_validate(r) for r in rules]


@router.get(
    "/{rule_id}",
    response_model=PriorityRuleResponse,
    summary="Get a priority rule",
    description="Retrieve a single priority rule by ID. Accessible to any authenticated user.",
)
async def get_rule(rule_id: int, svc: PriorityRuleServiceDep) -> PriorityRuleResponse:
    """
    Get rule.

    Args:
        rule_id (int): Rule primary key.
        svc (PriorityRuleServiceDep): Injected service.

    Returns:
        PriorityRuleResponse: The priority rule.
    """
    rule = await svc.get_rule(rule_id)
    return PriorityRuleResponse.model_validate(rule)


@router.post(
    "",
    response_model=PriorityRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a priority rule (ADMIN only)",
    description="Create a new (severity, tier_name) → priority mapping. Requires ADMIN role.",
)
async def create_rule(
    payload: PriorityRuleCreateRequest,
    svc: PriorityRuleServiceDep,
    user_role: CurrentUserRole,
) -> PriorityRuleResponse:
    """
    Create rule.

    Args:
        payload (PriorityRuleCreateRequest): Rule data.
        svc (PriorityRuleServiceDep): Injected service.
        user_role (CurrentUserRole): Current user's role (enforced in service).

    Returns:
        PriorityRuleResponse: The created rule.
    """
    rule = await svc.create_rule(payload, current_user_role=user_role)
    return PriorityRuleResponse.model_validate(rule)


@router.put(
    "/{rule_id}",
    response_model=PriorityRuleResponse,
    summary="Update a priority rule (ADMIN only)",
    description="Update the priority value of an existing rule. Requires ADMIN role.",
)
async def update_rule(
    rule_id: int,
    payload: PriorityRuleUpdateRequest,
    svc: PriorityRuleServiceDep,
    user_role: CurrentUserRole,
) -> PriorityRuleResponse:
    """
    Update rule.

    Args:
        rule_id (int): Rule primary key.
        payload (PriorityRuleUpdateRequest): New priority.
        svc (PriorityRuleServiceDep): Injected service.
        user_role (CurrentUserRole): Current user's role (enforced in service).

    Returns:
        PriorityRuleResponse: The updated rule.
    """
    rule = await svc.update_rule(rule_id, payload, current_user_role=user_role)
    return PriorityRuleResponse.model_validate(rule)


@router.delete(
    "/{rule_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a priority rule (ADMIN only)",
    description="Delete a priority rule by ID. Requires ADMIN role.",
)
async def delete_rule(
    rule_id: int,
    svc: PriorityRuleServiceDep,
    user_role: CurrentUserRole,
) -> None:
    """
    Delete rule.

    Args:
        rule_id (int): Rule primary key.
        svc (PriorityRuleServiceDep): Injected service.
        user_role (CurrentUserRole): Current user's role (enforced in service).
    """
    await svc.delete_rule(rule_id, current_user_role=user_role)
