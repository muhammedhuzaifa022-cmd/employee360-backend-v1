"""
Employee (user) rules.

  Admin     : sees and manages everyone.
  Team lead : sees their own department (read-only here).
  Employee  : sees only themselves.

Things people may NOT see are answered with 404 (not 403), so nobody can
discover other departments' users by guessing IDs.
"""
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import generate_temporary_password, hash_password
from app.models import Task, User
from app.models.enums import NotificationCategory, TaskStatus, UserRole
from app.schemas.user import UserCreate, UserOut, UserStats, UserUpdate
from app.services import auth_service, department_service, notification_service
from app.services import permissions as P
from app.utils.dates import company_today, utc_now
from app.utils.pagination import PageParams, paginate

DEFAULT_DESIGNATION = {
    UserRole.ADMIN: "Administrator",
    UserRole.TEAMLEAD: "Team Lead",
    UserRole.EMPLOYEE: "Associate",
}


# ---------------- reading ----------------
def _base_query():
    return select(User).options(selectinload(User.department))


def get_visible(db: Session, actor: User, user_id: int) -> User:
    user = db.get(User, user_id, options=[selectinload(User.department)])
    if user is None or not P.can_view_user(actor, user):
        raise NotFoundError("User not found", code="USER_NOT_FOUND")
    return user


def stats_for(db: Session, user_ids: list[int]) -> dict[int, UserStats]:
    """Open / done / overdue counts for many users in ONE query."""
    if not user_ids:
        return {}
    today = company_today()
    not_done = Task.status != TaskStatus.COMPLETED
    rows = db.execute(
        select(
            Task.assignee_id,
            func.count(Task.id),
            func.sum(case((not_done, 1), else_=0)),
            func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)),
            func.sum(case((not_done & (Task.due_date < today), 1), else_=0)),
            func.sum(case((Task.status == TaskStatus.SUBMITTED, 1), else_=0)),
        ).where(Task.assignee_id.in_(user_ids)).group_by(Task.assignee_id)
    )
    result = {uid: UserStats() for uid in user_ids}
    for uid, total, open_, done, overdue, review in rows:
        result[uid] = UserStats(total=total, open=open_ or 0, done=done or 0,
                                overdue=overdue or 0, in_review=review or 0)
    return result


def list_users(db: Session, actor: User, params: PageParams, *, department_id: int | None = None,
               department: str | None = None, role: UserRole | None = None,
               is_active: bool | None = None, q: str | None = None,
               include_stats: bool = True) -> tuple[list[UserOut], int]:
    stmt = _base_query().where(P.visible_users_condition(actor))
    if department_id is not None:
        stmt = stmt.where(User.department_id == department_id)
    if department:
        dept = department_service.find_by_name(db, department)
        stmt = stmt.where(User.department_id == (dept.id if dept else -1))
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like),
                              func.lower(User.email).like(like),
                              func.lower(User.designation).like(like)))
    stmt = stmt.order_by(func.lower(User.full_name), User.id)

    users, total = paginate(db, stmt, params)
    stats = stats_for(db, [u.id for u in users]) if include_stats else {}
    items = []
    for u in users:
        item = UserOut.model_validate(u)
        item.stats = stats.get(u.id) if include_stats else None
        items.append(item)
    return items, total


def assignable_users(db: Session, actor: User) -> list[User]:
    """People `actor` may assign a task to (the 'Assign to' dropdown)."""
    if not P.is_manager(actor):
        return []
    candidates = db.scalars(
        _base_query().where(User.is_active.is_(True), User.role != UserRole.ADMIN,
                            P.visible_users_condition(actor))
        .order_by(func.lower(User.full_name))
    )
    return [u for u in candidates if P.can_assign_task_to(actor, u)]


# ---------------- writing (admin only) ----------------
def _ensure_email_free(db: Session, email: str, except_id: int | None = None) -> None:
    other = auth_service.get_user_by_email(db, email)
    if other is not None and other.id != except_id:
        raise ConflictError("A user with this email already exists", code="EMAIL_EXISTS",
                            fields={"email": "Already in use"})


def _active_admin_count(db: Session, exclude_id: int | None = None) -> int:
    stmt = select(func.count(User.id)).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) or 0


def create_user(db: Session, actor: User, body: UserCreate) -> tuple[User, str | None]:
    if not P.can_administer_accounts(actor):
        raise ForbiddenError("Only admins can add employees", code="ROLE_NOT_ALLOWED")
    _ensure_email_free(db, body.email)
    dept = department_service.resolve(db, department_id=body.department_id, name=body.department)

    temp_password = None
    password = body.password
    if not password:
        password = temp_password = generate_temporary_password()

    user = User(full_name=body.full_name, email=body.email, hashed_password=hash_password(password),
                role=body.role, designation=body.designation or DEFAULT_DESIGNATION[body.role],
                department_id=dept.id if dept else None,
                joined_on=body.joined_on or company_today())
    db.add(user)
    db.commit()
    db.refresh(user, attribute_names=["department"])
    return user, temp_password


def update_user(db: Session, actor: User, user_id: int, body: UserUpdate) -> User:
    if not P.can_administer_accounts(actor):
        raise ForbiddenError("Only admins can edit employees", code="ROLE_NOT_ALLOWED")
    user = get_visible(db, actor, user_id)
    changes = body.model_dump(exclude_unset=True)
    old_role, old_department_id = user.role, user.department_id

    if "email" in changes and changes["email"]:
        _ensure_email_free(db, changes["email"], except_id=user.id)
        user.email = changes["email"]
    if changes.get("full_name"):
        user.full_name = changes["full_name"]
    if changes.get("designation"):
        user.designation = changes["designation"]
    if changes.get("joined_on"):
        user.joined_on = changes["joined_on"]

    if "department_id" in changes or "department" in changes:
        dept = department_service.resolve(db, department_id=changes.get("department_id"),
                                          name=changes.get("department"))
        user.department_id = dept.id if dept else None

    new_role = changes.get("role")
    if new_role is not None and new_role != user.role:
        if user.id == actor.id:
            raise BadRequestError("You cannot change your own role", code="CANNOT_CHANGE_OWN_ROLE")
        if user.role == UserRole.ADMIN and user.is_active and _active_admin_count(db, user.id) == 0:
            raise BadRequestError("The company needs at least one active admin", code="LAST_ADMIN")
        # Keep the automatic job title in step with the role, unless it was customised
        if "designation" not in changes and user.designation == DEFAULT_DESIGNATION[user.role]:
            user.designation = DEFAULT_DESIGNATION[new_role]
        user.role = new_role

    # Final check on the result: team leads and employees always need a department
    if user.role != UserRole.ADMIN and user.department_id is None:
        db.rollback()
        raise BadRequestError("Team leads and employees need a department",
                              code="DEPARTMENT_REQUIRED", fields={"department": "Required"})

    _notify_account_changes(db, actor, user, old_role, old_department_id)
    db.commit()
    db.refresh(user, attribute_names=["department"])
    return user


ROLE_LABEL = {UserRole.ADMIN: "Admin", UserRole.TEAMLEAD: "Team Lead", UserRole.EMPLOYEE: "Employee"}


def _notify_account_changes(db: Session, actor: User, user: User, old_role: UserRole,
                            old_department_id: int | None) -> None:
    """Tell the person when an admin changes their role or department."""
    messages = []
    if user.role != old_role:
        messages.append(f"Your role was changed to {ROLE_LABEL[user.role]} by {actor.full_name}")
    if user.department_id != old_department_id and user.department_id is not None:
        dept = department_service.get(db, user.department_id)
        messages.append(f"You were moved to the {dept.name} department by {actor.full_name}")
    for text in messages:
        notification_service.notify(db, [user], text, category=NotificationCategory.ACCOUNT,
                                    entity_type="user", entity_id=user.id)


def set_active(db: Session, actor: User, user_id: int, is_active: bool) -> User:
    if not P.can_administer_accounts(actor):
        raise ForbiddenError("Only admins can activate or deactivate users", code="ROLE_NOT_ALLOWED")
    user = get_visible(db, actor, user_id)
    if user.id == actor.id:
        raise BadRequestError("You cannot deactivate yourself", code="CANNOT_DEACTIVATE_SELF")
    if not is_active and user.role == UserRole.ADMIN and _active_admin_count(db, user.id) == 0:
        raise BadRequestError("The company needs at least one active admin", code="LAST_ADMIN")
    user.is_active = is_active
    if not is_active:
        auth_service.revoke_all_sessions(db, user.id)  # logged out everywhere, immediately
    db.commit()
    return user


def reset_password(db: Session, actor: User, user_id: int, new_password: str | None) -> str | None:
    """Admin sets a new password for someone (e.g. they forgot it)."""
    if not P.can_administer_accounts(actor):
        raise ForbiddenError("Only admins can reset passwords", code="ROLE_NOT_ALLOWED")
    user = get_visible(db, actor, user_id)
    if user.id == actor.id:
        raise BadRequestError("Use change-password for your own account", code="USE_CHANGE_PASSWORD")
    temp = None
    if not new_password:
        new_password = temp = generate_temporary_password()
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = utc_now()
    auth_service.revoke_all_sessions(db, user.id)
    db.commit()
    return temp
