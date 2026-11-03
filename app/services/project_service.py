"""
Projects logic: who sees which project, create / edit / members / delete,
progress numbers for the cards, and "You were added to project X" notifications.

Rules (from the final decisions):
  See    : admin all | team lead: manages, member, or any member from own dept | employee: member
  Create : admin (any manager, any employees) | team lead (manager = themselves,
           members = employees of their own department)
  Edit   : admin any project | team lead only projects they manage
  Delete : admin only, and only if the project has no tasks
"""
from datetime import date

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import (ConflictError, ForbiddenError, NotFoundError,
                                 ValidationAppError)
from app.models import Project, Task, User
from app.models.enums import NotificationCategory, Priority, TaskStatus, UserRole
from app.schemas.project import (ProjectCreate, ProjectMembersUpdate, ProjectOut,
                                 ProjectProgress, ProjectUpdate)
from app.services import notification_service
from app.services import permissions as P
from app.utils.dates import company_today
from app.utils.pagination import PageParams, paginate


def _load():
    return (select(Project)
            .options(selectinload(Project.manager).selectinload(User.department),
                     selectinload(Project.members).selectinload(User.department)))


# ---------------------------------------------------------------- reading
def get_visible(db: Session, actor: User, project_id: int) -> Project:
    project = db.scalar(_load().where(Project.id == project_id))
    if project is None or not P.can_view_project(actor, project):
        raise NotFoundError("Project not found", code="PROJECT_NOT_FOUND")
    return project


def progress_for(db: Session, project_ids: list[int]) -> dict[int, ProjectProgress]:
    """Done / total / late for many projects in ONE query."""
    result = {pid: ProjectProgress() for pid in project_ids}
    if not project_ids:
        return result
    done = Task.status == TaskStatus.COMPLETED
    late = (Task.status != TaskStatus.COMPLETED) & (Task.due_date < company_today())
    rows = db.execute(
        select(Task.project_id, func.count(),
               func.count(case((done, 1))), func.count(case((late, 1))))
        .where(Task.project_id.in_(project_ids)).group_by(Task.project_id))
    for pid, total, n_done, n_late in rows:
        result[pid] = ProjectProgress(total=total, done=n_done, overdue=n_late,
                                      percent=round(n_done * 100 / total) if total else 0)
    return result


def to_out(db: Session, actor: User, projects: list[Project]) -> list[ProjectOut]:
    progress = progress_for(db, [p.id for p in projects])
    out = []
    for p in projects:
        item = ProjectOut.model_validate(p)
        item.members = sorted(item.members, key=lambda m: m.full_name.lower())
        item.progress = progress[p.id]
        item.can_edit = P.can_edit_project(actor, p)
        out.append(item)
    return out


def list_projects(db: Session, actor: User, params: PageParams, *, q: str | None = None,
                  priority: Priority | None = None, manager_id: int | None = None,
                  member_id: int | None = None, active_on: date | None = None
                  ) -> tuple[list[ProjectOut], int]:
    stmt = _load().where(P.visible_projects_condition(actor))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Project.name).like(like),
                              func.lower(Project.description).like(like)))
    if priority is not None:
        stmt = stmt.where(Project.priority == priority)
    if manager_id is not None:
        stmt = stmt.where(Project.manager_id == manager_id)
    if member_id is not None:
        stmt = stmt.where(Project.members.any(User.id == member_id))
    if active_on is not None:
        stmt = stmt.where(Project.start_date <= active_on, Project.end_date >= active_on)
    stmt = stmt.order_by(Project.created_at, Project.id)  # same order as the frontend
    projects, total = paginate(db, stmt, params)
    return to_out(db, actor, projects), total


def form_options(db: Session, actor: User) -> dict:
    """People to show in the 'New project' form, filtered for the actor."""
    if not P.can_create_project(actor):
        raise ForbiddenError("Only admins and team leads can create projects",
                             code="ROLE_NOT_ALLOWED")
    base = select(User).options(selectinload(User.department)).where(User.is_active.is_(True))
    order = (func.lower(User.full_name), User.id)
    if P.is_admin(actor):
        managers = db.scalars(base.where(User.role.in_([UserRole.ADMIN, UserRole.TEAMLEAD]))
                              .order_by(*order)).all()
        members = db.scalars(base.where(User.role == UserRole.EMPLOYEE).order_by(*order)).all()
    else:
        managers = [actor]
        members = db.scalars(base.where(User.role == UserRole.EMPLOYEE,
                                        User.department_id == actor.department_id)
                             .order_by(*order)).all()
    return {"managers": list(managers), "members": list(members)}


# ---------------------------------------------------------------- helpers
def _load_users(db: Session, ids: list[int]) -> list[User]:
    if not ids:
        return []
    found = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValidationAppError("Some members do not exist", code="USER_NOT_FOUND",
                                 fields={"member_ids": f"Unknown user id(s): {missing}"})
    return [found[i] for i in ids]


def _check_new_member(actor: User, member: User) -> None:
    if not member.is_active:
        raise ValidationAppError(f"{member.full_name} is deactivated", code="MEMBER_INACTIVE",
                                 fields={"member_ids": f"{member.full_name} is deactivated"})
    if not P.can_change_project_member(actor, member):
        if member.role != UserRole.EMPLOYEE:
            msg = f"{member.full_name} is not an employee. Members must be employees"
        else:
            msg = f"{member.full_name} is not in your department"
        raise ForbiddenError(msg, code="MEMBER_NOT_ALLOWED", fields={"member_ids": msg})


def _resolve_manager(db: Session, actor: User, manager_id: int | None) -> User:
    if manager_id is None or manager_id == actor.id:
        if not P.can_be_project_manager(actor):
            raise ValidationAppError("Choose a project manager", code="MANAGER_REQUIRED",
                                     fields={"manager_id": "Required"})
        return actor
    if not P.is_admin(actor):
        raise ForbiddenError("Team leads can only create projects they manage themselves",
                             code="MANAGER_NOT_ALLOWED", fields={"manager_id": "Must be you"})
    manager = db.get(User, manager_id)
    if manager is None or not P.can_be_project_manager(manager):
        raise ValidationAppError("The project manager must be an active admin or team lead",
                                 code="INVALID_MANAGER",
                                 fields={"manager_id": "Must be an active admin or team lead"})
    return manager


def _notify_added(db: Session, actor: User, project: Project, users: list[User]) -> None:
    notification_service.notify(
        db, users, f'You were added to project "{project.name}"',
        category=NotificationCategory.PROJECT_ADDED, entity_type="project",
        entity_id=project.id, exclude_user_id=actor.id)


def _notify_new_manager(db: Session, actor: User, project: Project) -> None:
    notification_service.notify(
        db, [project.manager_id], f'You are now the manager of project "{project.name}"',
        category=NotificationCategory.PROJECT_ADDED, entity_type="project",
        entity_id=project.id, exclude_user_id=actor.id)


def _get_editable(db: Session, actor: User, project_id: int) -> Project:
    project = get_visible(db, actor, project_id)        # hidden -> 404
    if not P.can_edit_project(actor, project):           # visible, not yours -> 403
        raise ForbiddenError("Only an admin or this project's manager can change it",
                             code="NOT_PROJECT_MANAGER")
    return project


# ---------------------------------------------------------------- writing
def create_project(db: Session, actor: User, body: ProjectCreate) -> Project:
    if not P.can_create_project(actor):
        raise ForbiddenError("Only admins and team leads can create projects",
                             code="ROLE_NOT_ALLOWED")
    manager = _resolve_manager(db, actor, body.manager_id)
    members = _load_users(db, body.member_ids)
    for m in members:
        _check_new_member(actor, m)

    project = Project(name=body.name, description=body.description, manager_id=manager.id,
                      start_date=body.start_date, end_date=body.end_date,
                      priority=body.priority, created_by_id=actor.id, members=members)
    db.add(project)
    db.flush()  # gives the project its id (needed for the notifications)
    _notify_added(db, actor, project, members)
    _notify_new_manager(db, actor, project)
    db.commit()
    return get_visible(db, actor, project.id)


def update_project(db: Session, actor: User, project_id: int, body: ProjectUpdate) -> Project:
    project = _get_editable(db, actor, project_id)
    changes = body.model_dump(exclude_unset=True)

    for field in ("name", "description", "priority", "start_date", "end_date"):
        if changes.get(field) is not None:
            setattr(project, field, changes[field])
    if project.end_date < project.start_date:
        db.rollback()
        raise ValidationAppError("End date must be on or after the start date",
                                 code="INVALID_DATES", fields={"end_date": "Before start date"})

    new_manager_id = changes.get("manager_id")
    if new_manager_id is not None and new_manager_id != project.manager_id:
        if not P.is_admin(actor):
            db.rollback()
            raise ForbiddenError("Only admins can change the project manager",
                                 code="MANAGER_NOT_ALLOWED")
        manager = db.get(User, new_manager_id)
        if manager is None or not P.can_be_project_manager(manager):
            db.rollback()
            raise ValidationAppError("The project manager must be an active admin or team lead",
                                     code="INVALID_MANAGER",
                                     fields={"manager_id": "Must be an active admin or team lead"})
        project.manager_id = manager.id
        _notify_new_manager(db, actor, project)

    db.commit()
    db.expire(project)
    return get_visible(db, actor, project.id)


def add_members(db: Session, actor: User, project_id: int, member_ids: list[int]) -> Project:
    project = _get_editable(db, actor, project_id)
    current = {m.id for m in project.members}
    new = [u for u in _load_users(db, member_ids) if u.id not in current]
    for u in new:
        _check_new_member(actor, u)
    project.members.extend(new)
    _notify_added(db, actor, project, new)
    db.commit()
    return get_visible(db, actor, project.id)


def remove_member(db: Session, actor: User, project_id: int, user_id: int) -> Project:
    project = _get_editable(db, actor, project_id)
    member = next((m for m in project.members if m.id == user_id), None)
    if member is None:
        raise NotFoundError("This person is not a member of the project",
                            code="MEMBER_NOT_FOUND")
    _check_removable(actor, member)
    project.members.remove(member)
    db.commit()
    return get_visible(db, actor, project.id)


def _check_removable(actor: User, member: User) -> None:
    # A team lead may only remove people from their own department
    # (an admin may have added someone from another department).
    if not P.is_admin(actor) and not P.same_department(actor, member):
        raise ForbiddenError(f"{member.full_name} is not in your department; ask an admin",
                             code="MEMBER_NOT_ALLOWED")


def set_members(db: Session, actor: User, project_id: int, body: ProjectMembersUpdate) -> Project:
    """Replace the whole member list (handy for a multi-select form)."""
    project = _get_editable(db, actor, project_id)
    wanted = _load_users(db, body.member_ids)
    wanted_ids = {u.id for u in wanted}
    current_ids = {m.id for m in project.members}

    added = [u for u in wanted if u.id not in current_ids]
    removed = [m for m in project.members if m.id not in wanted_ids]
    for u in added:
        _check_new_member(actor, u)
    for m in removed:
        _check_removable(actor, m)

    project.members = [m for m in project.members if m.id in wanted_ids] + added
    _notify_added(db, actor, project, added)
    db.commit()
    return get_visible(db, actor, project.id)


def delete_project(db: Session, actor: User, project_id: int) -> None:
    project = get_visible(db, actor, project_id)
    if not P.is_admin(actor):
        raise ForbiddenError("Only admins can delete projects", code="ROLE_NOT_ALLOWED")
    task_count = db.scalar(select(func.count()).select_from(Task)
                           .where(Task.project_id == project.id)) or 0
    if task_count:
        raise ConflictError(f"This project still has {task_count} task(s). "
                            "Move or delete them first", code="PROJECT_HAS_TASKS")
    db.delete(project)
    db.commit()


