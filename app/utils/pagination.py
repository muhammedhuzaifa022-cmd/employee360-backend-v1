"""
Pagination: return big lists in small pages (good for phones).

Every list endpoint accepts ?page=1&page_size=20 and returns
{"items": [...], "total": 57, "page": 1, "page_size": 20, "pages": 3}
"""
import math
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@dataclass
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, description="Page number, starting at 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE,
                                    description=f"Items per page (max {MAX_PAGE_SIZE})")] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(page_params)]


def paginate(db: Session, stmt: Select, params: PageParams) -> tuple[list, int]:
    """Runs `stmt` for one page. Returns (rows, total_count)."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.limit(params.page_size).offset(params.offset)).unique())
    return rows, total


def page_response(items: list, total: int, params: PageParams) -> dict:
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "pages": math.ceil(total / params.page_size) if total else 0,
    }
