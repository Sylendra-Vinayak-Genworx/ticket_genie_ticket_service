from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db, require_admin, CurrentUserID
from src.core.services.product_service import ProductService
from src.core.exceptions.base import NotFoundError, ConflictError
from src.schemas.product_schema import ProductResponse, ProductCreateRequest, ProductUpdateRequest

router = APIRouter(prefix="/products", tags=["products"])


def _svc(db: AsyncSession = Depends(get_db)) -> ProductService:
    return ProductService(db)


# ── Public: list active products (used by ticket creation dropdown) ─────────
@router.get(
    "",
    response_model=list[ProductResponse],
    summary="List products",
    description="Return active products for ticket creation dropdowns.",
)
async def list_products(
    active_only: bool = Query(default=True, description="Return only active products"),
    svc: ProductService = Depends(_svc),
) -> list[ProductResponse]:
    """Return products for ticket creation dropdowns. Defaults to active only."""
    return await svc.list_products(active_only=active_only)


# ── Admin: get single product ───────────────────────────────────────────────
@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product",
    description="Retrieve a single product by its ID.",
)
async def get_product(
    product_id: int,
    svc: ProductService = Depends(_svc),
    _: str = Depends(require_admin),
) -> ProductResponse:
    """
    Get product.
    
    Args:
        product_id (int): Input parameter.
        svc (ProductService): Input parameter.
    
    Returns:
        ProductResponse: The expected output.
    """
    try:
        return await svc.get_product(product_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Admin: create product ───────────────────────────────────────────────────
@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    description="Create a new product with the specified details.",
)
async def create_product(
    payload: ProductCreateRequest,
    svc: ProductService = Depends(_svc),
    _: str = Depends(require_admin),
) -> ProductResponse:
    """
    Create product.
    
    Args:
        payload (ProductCreateRequest): Input parameter.
        svc (ProductService): Input parameter.
    
    Returns:
        ProductResponse: The expected output.
    """
    try:
        return await svc.create_product(
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Admin: update product ───────────────────────────────────────────────────
@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product",
    description="Update the details of an existing product.",
)
async def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    svc: ProductService = Depends(_svc),
    _: str = Depends(require_admin),
) -> ProductResponse:
    """
    Update product.
    
    Args:
        product_id (int): Input parameter.
        payload (ProductUpdateRequest): Input parameter.
        svc (ProductService): Input parameter.
    
    Returns:
        ProductResponse: The expected output.
    """
    try:
        return await svc.update_product(
            product_id=product_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Admin: delete product ───────────────────────────────────────────────────
@router.delete(
    "/{product_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product",
    description="Delete a product by its ID.",
)
async def delete_product(
    product_id: int,
    svc: ProductService = Depends(_svc),
    _: str = Depends(require_admin),
) -> None:
    """
    Delete product.
    
    Args:
        product_id (int): Input parameter.
        svc (ProductService): Input parameter.
    """
    try:
        await svc.delete_product(product_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))