from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.product import Product
from src.data.repositories.product_repository import ProductRepository
from src.core.exceptions.base import NotFoundError, ConflictError


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = ProductRepository(session)

    async def list_products(self, active_only: bool = False) -> list[Product]:
        return await self._repo.list_all(active_only=active_only)

    async def get_product(self, product_id: int) -> Product:
        product = await self._repo.get_by_id(product_id)
        if not product:
            raise NotFoundError(f"Product {product_id} not found")
        return product

    async def create_product(
        self,
        name: str,
        description: Optional[str] = None,
        is_active: bool = True,
    ) -> Product:
        existing = await self._repo.get_by_name(name)
        if existing:
            raise ConflictError(f"Product with name '{name}' already exists")
        return await self._repo.create(name=name, description=description, is_active=is_active)

    async def update_product(
        self,
        product_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Product:
        product = await self.get_product(product_id)
        if name and name != product.name:
            existing = await self._repo.get_by_name(name)
            if existing:
                raise ConflictError(f"Product with name '{name}' already exists")
        updates = {k: v for k, v in {"name": name, "description": description, "is_active": is_active}.items() if v is not None}
        return await self._repo.update(product, **updates)

    async def delete_product(self, product_id: int) -> None:
        product = await self.get_product(product_id)
        await self._repo.delete(product)