"""通用分页模型。"""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PageOut(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
