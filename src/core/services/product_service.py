from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.product import Product
from src.data.repositories.product_repository import ProductRepository
from src.core.exceptions.base import NotFoundError, ConflictError


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        """
          init  .
        
        Args:
            session (AsyncSession): Input parameter.
        """
        self._repo = ProductRepository(session)
    """Service layer for managing products. Provides methods to list, get, create, update, and delete products. Each product represents a specific software product or service that tickets can be associated with. The service interacts with the ProductRepository to perform database operations and includes business logic such as checking for duplicate product names during creation and updates."""
    async def list_products(self, active_only: bool = False) -> list[Product]:
        """
        List products.
        
        Args:
            active_only (bool): Input parameter.
        
        Returns:
            list[Product]: The expected output.
        """
        return await self._repo.list_all(active_only=active_only)

    async def get_product(self, product_id: int) -> Product:
        """
        Get product.
        
        Args:
            product_id (int): Input parameter.
        
        Returns:
            Product: The expected output.
        """
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
        """
        Create product.
        
        Args:
            name (str): Input parameter.
            description (Optional[str]): Input parameter.
            is_active (bool): Input parameter.
        
        Returns:
            Product: The expected output.
        """
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
        """
        Update product.
        
        Args:
            product_id (int): Input parameter.
            name (Optional[str]): Input parameter.
            description (Optional[str]): Input parameter.
            is_active (Optional[bool]): Input parameter.
        
        Returns:
            Product: The expected output.
        """
        product = await self.get_product(product_id)
        if name and name != product.name:
            existing = await self._repo.get_by_name(name)
            if existing:
                raise ConflictError(f"Product with name '{name}' already exists")
        updates = {k: v for k, v in {"name": name, "description": description, "is_active": is_active}.items() if v is not None}
        return await self._repo.update(product, **updates)

    async def delete_product(self, product_id: int) -> None:
        """
        Delete product.
        
        Args:
            product_id (int): Input parameter.
        """
        product = await self.get_product(product_id)
        await self._repo.delete(product)