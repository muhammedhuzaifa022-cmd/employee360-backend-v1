"""
Employees (users) endpoints - the Team page and admin tools.

  GET    /users                        list (filtered by your role) + task counts
  GET    /users/assignable             people you may assign tasks to
  GET    /users/{id}                   one person
  GET    /users/{id}/stats             their open / done / overdue counts
  POST   /users                        add employee                (admin)
  PATCH  /users/{id}                   edit name, email, role...   (admin)
  PATCH  /users/{id}/status            activate / deactivate       (admin)
  POST   /users/{id}/reset-password    set a new password          (admin)
"""
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.models.enums import UserRole
from app.schemas.common import Page
from app.schemas.user import (PasswordResetRequest, PasswordResetResponse, UserBrief,
                              UserCreate, UserCreatedResponse, UserOut, UserStats,
                              UserStatusUpdate, UserUpdate)
from app.services import user_service
from app.utils.pagination import Pagination, page_response

router = APIRouter(prefix="/users", tags=["Employees"])


@router.get("", response_model=Page[UserOut], summary="List employees")
def list_users(
    user: CurrentUser, db: DbSession, pagination: Pagination,
    department_id: Annotated[int | None, Query(description="Filter by department id")] = None,
    department: Annotated[str | None, Query(description="Filter by department name (Team page chips)")] = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Search name, email or designation")] = None,
    include_stats: bool = True,
):
    """
    **Admin:** everyone. **Team lead:** own department only. **Employee:** only themselves.
    Each item includes `stats` (open / done / overdue) for the Team cards.
    """
    items, total = user_service.list_users(
        db, user, pagination, department_id=department_id, department=department,
        role=role, is_active=is_active, q=q, include_stats=include_stats)
    return page_response(items, total, pagination)


@router.get("/assignable", response_model=list[UserBrief],
            summary="People I may assign tasks to")
def assignable(user: CurrentUser, db: DbSession):
    """Admin: all active non-admins. Team lead: themselves + active employees of their department."""
    return user_service.assignable_users(db, user)


@router.get("/{user_id}", response_model=UserOut, summary="One employee")
def get_user(user_id: int, user: CurrentUser, db: DbSession):
    target = user_service.get_visible(db, user, user_id)
    item = UserOut.model_validate(target)
    item.stats = user_service.stats_for(db, [target.id])[target.id]
    return item


@router.get("/{user_id}/stats", response_model=UserStats, summary="Task counts for one employee")
def get_stats(user_id: int, user: CurrentUser, db: DbSession):
    target = user_service.get_visible(db, user, user_id)
    return user_service.stats_for(db, [target.id])[target.id]


@router.post("", response_model=UserCreatedResponse, status_code=status.HTTP_201_CREATED,
             summary="Add employee (admin)")
def create_user(body: UserCreate, admin: AdminUser, db: DbSession):
    """
    Same fields as the frontend form: name, email, department (name or id), role.
    If you do not send `password`, a **temporary password** is generated and returned once.
    """
    new_user, temp = user_service.create_user(db, admin, body)
    out = UserOut.model_validate(new_user)
    out.stats = UserStats()
    return UserCreatedResponse(user=out, temporary_password=temp)


@router.patch("/{user_id}", response_model=UserOut, summary="Edit employee (admin)")
def update_user(user_id: int, body: UserUpdate, admin: AdminUser, db: DbSession):
    updated = user_service.update_user(db, admin, user_id, body)
    out = UserOut.model_validate(updated)
    out.stats = user_service.stats_for(db, [updated.id])[updated.id]
    return out


@router.patch("/{user_id}/status", response_model=UserOut,
              summary="Activate / deactivate (admin)")
def set_status(user_id: int, body: UserStatusUpdate, admin: AdminUser, db: DbSession):
    """Deactivated users are logged out of every device immediately and cannot log in."""
    updated = user_service.set_active(db, admin, user_id, body.is_active)
    out = UserOut.model_validate(updated)
    out.stats = user_service.stats_for(db, [updated.id])[updated.id]
    return out


@router.post("/{user_id}/reset-password", response_model=PasswordResetResponse,
             summary="Reset someone's password (admin)")
def reset_password(user_id: int, body: PasswordResetRequest, admin: AdminUser, db: DbSession):
    temp = user_service.reset_password(db, admin, user_id, body.new_password)
    return PasswordResetResponse(
        message="Password reset. The user has been logged out of all devices.",
        temporary_password=temp)
