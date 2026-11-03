"""
Notifications ("Inbox") logic.

Two jobs:
1. Reading: list my notifications, unread count, mark read, delete.
   Everyone ONLY ever sees their own notifications.
2. Writing: `notify()` - the ONE helper every other module (tasks, leave,
   projects, accounts) calls to create notifications.

`notify()` never commits. It adds rows to the caller's transaction, so the
notification is saved together with the action (e.g. "task approved").
If the action fails, no notification is left behind.
"""
from collections.abc import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Notification, User
from app.models.enums import NotificationCategory, UserRole
from app.utils.pagination import PageParams, paginate

MAX_MESSAGE_LENGTH = 500


# ---------------------------------------------------------------- writing
def notify(
    db: Session,
    recipients: Iterable[User | int],
    message: str,
    *,
    category: NotificationCategory | str = NotificationCategory.GENERAL,
    entity_type: str | None = None,
    entity_id: int | None = None,
    exclude_user_id: int | None = None,
) -> list[Notification]:
    """
    Create one notification per recipient.
      - duplicates are removed (nobody gets the same message twice)
      - `exclude_user_id` (usually the person doing the action) is skipped
      - deactivated users are skipped
    """
    ids: list[int] = []
    for r in recipients:
        rid = r.id if isinstance(r, User) else int(r)
        if rid != exclude_user_id and rid not in ids:
            ids.append(rid)
    if not ids:
        return []

    active_ids = set(db.scalars(select(User.id).where(User.id.in_(ids), User.is_active.is_(True))))
    text = message.strip()[:MAX_MESSAGE_LENGTH]
    cat = category.value if isinstance(category, NotificationCategory) else str(category)

    created = [Notification(recipient_id=rid, message=text, category=cat,
                            entity_type=entity_type, entity_id=entity_id)
               for rid in ids if rid in active_ids]
    db.add_all(created)
    return created


def approvers_for(db: Session, requester: User) -> list[User]:
    """
    Who should hear about this person's requests (leave, etc.)?
      employee  -> team leads of their department + all admins
      team lead -> all admins
      admin     -> the OTHER admins
    Same rule as "who can decide their leave" (Module 3 permissions).
    """
    cond = (User.role == UserRole.ADMIN)
    if requester.role == UserRole.EMPLOYEE and requester.department_id is not None:
        cond = cond | ((User.role == UserRole.TEAMLEAD) &
                       (User.department_id == requester.department_id))
    stmt = (select(User).where(cond, User.is_active.is_(True), User.id != requester.id)
            .order_by(User.id))
    return list(db.scalars(stmt))


# ---------------------------------------------------------------- reading
def _mine(user: User):
    return Notification.recipient_id == user.id


def list_for(db: Session, user: User, params: PageParams, *, unread_only: bool = False,
             category: str | None = None) -> tuple[list[Notification], int]:
    stmt = select(Notification).where(_mine(user))
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if category:
        stmt = stmt.where(Notification.category == category)
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
    return paginate(db, stmt, params)


def unread_count(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(Notification)
                     .where(_mine(user), Notification.is_read.is_(False))) or 0


def _get_own(db: Session, user: User, notification_id: int) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.recipient_id != user.id:  # someone else's -> "not found"
        raise NotFoundError("Notification not found", code="NOTIFICATION_NOT_FOUND")
    return n


def set_read(db: Session, user: User, notification_id: int, is_read: bool) -> Notification:
    n = _get_own(db, user, notification_id)
    n.is_read = is_read
    db.commit()
    db.refresh(n)
    return n


def mark_all_read(db: Session, user: User) -> int:
    result = db.execute(update(Notification)
                        .where(_mine(user), Notification.is_read.is_(False))
                        .values(is_read=True))
    db.commit()
    return result.rowcount or 0


def delete_one(db: Session, user: User, notification_id: int) -> None:
    db.delete(_get_own(db, user, notification_id))
    db.commit()


def delete_read(db: Session, user: User) -> int:
    result = db.execute(delete(Notification)
                        .where(_mine(user), Notification.is_read.is_(True)))
    db.commit()
    return result.rowcount or 0
