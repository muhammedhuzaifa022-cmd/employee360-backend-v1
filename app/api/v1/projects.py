"""
Projects endpoints (the Projects page).

  GET    /projects                          list (filtered by your role) + progress
  GET    /projects/form-options             who can be picked in "New project"   (managers)
  GET    /projects/{id}                     one project
  POST   /projects                          create                (admin, team lead)
  PATCH  /projects/{id}                     edit details          (admin, project's manager)
  PUT    /projects/{id}/members             replace member list   (admin, project's manager)
  POST   /projects/{id}/members             add members           (admin, project's manager)
  DELETE /projects/{id}/members/{user_id}   remove one member     (admin, project's manager)
  DELETE /projects/{id}                     delete if no tasks    (admin)
"""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, ManagerUser
from app.models.enums import Priority
from app.schemas.common import Page
from app.schemas.project import (ProjectCreate, ProjectFormOptions, ProjectMembersUpdate,
                                 ProjectOut, ProjectUpdate)
from app.services import project_service as svc
from app.utils.pagination import Pagination, page_response

router = APIRouter(prefix="/projects", tags=["Projects"])


def _one(db, user, project) -> ProjectOut:
    return svc.to_out(db, user, [project])[0]


@router.get("", response_model=Page[ProjectOut], summary="List projects")
def list_projects(
    user: CurrentUser, db: DbSession, pagination: Pagination,
    q: Annotated[str | None, Query(max_length=100, description="Search name / description")] = None,
    priority: Priority | None = None,
    manager_id: int | None = None,
    member_id: int | None = None,
    active_on: Annotated[date | None, Query(description="Only projects running on this date")] = None,
):
    """
    **Admin:** all projects. **Team lead:** projects they manage or belong to, plus any
    project with a member from their department. **Employee:** projects they belong to.
    Each project includes `progress` (done / total / late / percent) and `can_edit`.
    """
    items, total = svc.list_projects(db, user, pagination, q=q, priority=priority,
                                     manager_id=manager_id, member_id=member_id,
                                     active_on=active_on)
    return page_response(items, total, pagination)


@router.get("/form-options", response_model=ProjectFormOptions,
            summary="People for the 'New project' dropdowns")
def form_options(user: ManagerUser, db: DbSession):
    """Admin: all active admins/team leads and all active employees.
    Team lead: only themselves as manager and their own department's employees."""
    return svc.form_options(db, user)


@router.get("/{project_id}", response_model=ProjectOut, summary="One project")
def get_project(project_id: int, user: CurrentUser, db: DbSession):
    return _one(db, user, svc.get_visible(db, user, project_id))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED,
             summary="Create project (admin, team lead)")
def create_project(body: ProjectCreate, user: ManagerUser, db: DbSession):
    """
    Same fields as the frontend form. Team leads: leave `manager_id` empty (you become
    the manager) and pick employees from your own department. Members get a notification.
    """
    return _one(db, user, svc.create_project(db, user, body))


@router.patch("/{project_id}", response_model=ProjectOut, summary="Edit project")
def update_project(project_id: int, body: ProjectUpdate, user: CurrentUser, db: DbSession):
    """Admin or the project's manager. Only admins can change `manager_id`."""
    return _one(db, user, svc.update_project(db, user, project_id, body))


@router.put("/{project_id}/members", response_model=ProjectOut, summary="Replace members")
def set_members(project_id: int, body: ProjectMembersUpdate, user: CurrentUser, db: DbSession):
    return _one(db, user, svc.set_members(db, user, project_id, body))


@router.post("/{project_id}/members", response_model=ProjectOut, summary="Add members")
def add_members(project_id: int, body: ProjectMembersUpdate, user: CurrentUser, db: DbSession):
    return _one(db, user, svc.add_members(db, user, project_id, body.member_ids))


@router.delete("/{project_id}/members/{user_id}", response_model=ProjectOut,
               summary="Remove one member")
def remove_member(project_id: int, user_id: int, user: CurrentUser, db: DbSession):
    return _one(db, user, svc.remove_member(db, user, project_id, user_id))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete project (admin, only if it has no tasks)")
def delete_project(project_id: int, user: CurrentUser, db: DbSession):
    svc.delete_project(db, user, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
