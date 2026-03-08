"""Shared pagination and response envelope schemas."""

from typing import Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class ErrorResponse(BaseModel):
    detail: str
    error_type: str