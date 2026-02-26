from typing import Generic, List, TypeVar

from sqlmodel import SQLModel

# T is a placeholder for any model (Shipment, User, etc.)
T = TypeVar("T")


class PaginatedResponse(SQLModel, Generic[T]):
    """
    Standard envelope for all list responses.
    """

    items: List[T]
    total: int
    page: int
    size: int
    pages: int
