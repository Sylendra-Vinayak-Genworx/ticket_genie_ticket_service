from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.product import Product


class ProductRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
    """Repository for managing products. Provides methods to list, get, create, update, and delete products. Each product represents a specific software product or service that tickets can be associated with. The repository interacts with the database using SQLAlchemy's AsyncSession and is designed to be used by the ProductService for business logic related to product management."""
    async def list_all(self, active_only: bool = False) -> list[Product]:
        q = select(Product).order_by(Product.name)
        if active_only:
            q = q.where(Product.is_active.is_(True))
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_by_id(self, product_id: int) -> Optional[Product]:
        result = await self.db.execute(
            select(Product).where(Product.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Product]:
        result = await self.db.execute(
            select(Product).where(Product.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, name: str, description: Optional[str] = None, is_active: bool = True) -> Product:
        product = Product(name=name, description=description, is_active=is_active)
        self.db.add(product)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def update(self, product: Product, **kwargs) -> Product:
        for key, value in kwargs.items():
            setattr(product, key, value)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def delete(self, product: Product) -> None:
        await self.db.delete(product)
        await self.db.flush()