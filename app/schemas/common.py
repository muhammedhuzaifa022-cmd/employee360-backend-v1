"""Shared response shapes used across the whole API."""
from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Not found"])
    code: str = Field(examples=["NOT_FOUND"])
    fields: dict[str, str] | None = Field(default=None, examples=[None])


class MessageResponse(BaseModel):
    message: str


class Page(BaseModel, Generic[T]):
    """Paginated list - used by every list endpoint from Module 5."""
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


# Shown in Swagger for every endpoint, so app developers know the error shape.
COMMON_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Bad request"},
    401: {"model": ErrorResponse, "description": "Not logged in / token invalid"},
    403: {"model": ErrorResponse, "description": "Not allowed for your role"},
    404: {"model": ErrorResponse, "description": "Not found (or not visible to you)"},
    409: {"model": ErrorResponse, "description": "Conflict (duplicate / overlap)"},
    422: {"model": ErrorResponse, "description": "Invalid input"},
}


class DatabaseHealth(BaseModel):
    ok: bool
    version: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    app: str
    environment: str
    api_version: str
    server_time_utc: datetime
    database: DatabaseHealth


class AppVersionInfo(BaseModel):
    min_supported: str
    latest: str


class WorkloadRules(BaseModel):
    weekly_capacity_hours: int
    busy_threshold_hours: int


class EnumLists(BaseModel):
    roles: list[str]
    task_statuses: list[str]
    employee_settable_statuses: list[str]
    priorities: list[str]
    leave_types: list[str]
    leave_statuses: list[str]
    platforms: list[str]
    notification_categories: list[str]


class MetaResponse(BaseModel):
    app: str
    api_version: str
    api_prefix: str
    timezone: str
    server_time_utc: datetime
    server_today: date
    app_version: AppVersionInfo
    enums: EnumLists
    workload: WorkloadRules
    performance_weights: dict[str, float]
    rating_range: list[int]
    default_page_size: int
    max_page_size: int
