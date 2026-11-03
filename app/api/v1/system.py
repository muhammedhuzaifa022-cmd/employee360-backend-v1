"""
System endpoints.

- GET /api/v1/health : is the server running, and can it reach the database?
- GET /api/v1/meta   : fixed lists and rules that web and mobile apps can load.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core import constants as C
from app.core.config import settings
from app.db.session import check_database_connection
from app.models.enums import (EMPLOYEE_SETTABLE_STATUSES, LeaveStatus, LeaveType,
                              NotificationCategory, Platform, Priority, TaskStatus,
                              UserRole)
from app.schemas.common import (AppVersionInfo, DatabaseHealth, EnumLists,
                                HealthResponse, MetaResponse, WorkloadRules)
from app.utils.dates import company_today, utc_now

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    responses={503: {"model": HealthResponse, "description": "Database unreachable"}},
)
def health():
    """Returns `ok` when the API and the database are both working."""
    db_ok, info = check_database_connection()
    body = HealthResponse(
        status="ok" if db_ok else "degraded",
        app=settings.APP_NAME,
        environment=settings.APP_ENV,
        api_version=settings.API_VERSION,
        server_time_utc=utc_now(),
        database=DatabaseHealth(ok=db_ok, version=info if db_ok else None),
    )
    if not db_ok:
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))
    return body


@router.get("/meta", response_model=MetaResponse, summary="App metadata and fixed lists")
def meta():
    """
    Everything a client app needs to build its dropdowns and rules:
    statuses, priorities, leave types, workload limits, score weights,
    and app version info, so old mobile versions can be asked to update.
    """
    return MetaResponse(
        app=settings.APP_NAME,
        api_version=settings.API_VERSION,
        api_prefix=settings.API_V1_PREFIX,
        timezone=settings.COMPANY_TIMEZONE,
        server_time_utc=utc_now(),
        server_today=company_today(),
        app_version=AppVersionInfo(min_supported=settings.MIN_SUPPORTED_APP_VERSION,
                                   latest=settings.LATEST_APP_VERSION),
        enums=EnumLists(
            roles=[r.value for r in UserRole],
            task_statuses=[s.value for s in TaskStatus],
            employee_settable_statuses=[s.value for s in EMPLOYEE_SETTABLE_STATUSES],
            priorities=[p.value for p in Priority],
            leave_types=[t.value for t in LeaveType],
            leave_statuses=[s.value for s in LeaveStatus],
            platforms=[p.value for p in Platform],
            notification_categories=[c.value for c in NotificationCategory],
        ),
        workload=WorkloadRules(weekly_capacity_hours=C.WEEKLY_CAPACITY_HOURS,
                               busy_threshold_hours=C.BUSY_THRESHOLD_HOURS),
        performance_weights=C.PERFORMANCE_WEIGHTS,
        rating_range=[C.RATING_MIN, C.RATING_MAX],
        default_page_size=C.DEFAULT_PAGE_SIZE,
        max_page_size=C.MAX_PAGE_SIZE,
    )
