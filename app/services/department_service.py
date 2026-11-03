"""Department rules: who sees which departments, create / rename / delete."""
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import Department, User
from app.services import permissions as P


def find_by_name(db: Session, name: str) -> Department | None:
    return db.scalar(select(Department).where(func.lower(Department.name) == name.strip().lower()))


def get_or_create(db: Session, name: str) -> Department:
    dept = find_by_name(db, name)
    if dept is None:
        dept = Department(name=name.strip())
        db.add(dept)
        db.flush()
    return dept


def get(db: Session, department_id: int) -> Department:
    dept = db.get(Department, department_id)
    if dept is None:
        raise NotFoundError("Department not found", code="DEPARTMENT_NOT_FOUND")
    return dept


def resolve(db: Session, *, department_id: int | None, name: str | None) -> Department | None:
    """Turn the 'department_id OR department name' input into a Department."""
    if department_id is not None:
        dept = db.get(Department, department_id)
        if dept is None:
            raise ValidationAppError("Department does not exist", code="DEPARTMENT_NOT_FOUND",
                                     fields={"department_id": "Unknown department"})
        return dept
    if name:
        return get_or_create(db, name)
    return None


def list_visible(db: Session, actor: User) -> list[dict]:
    """Admin: all departments. Team lead / employee: only their own."""
    stmt = (
        select(Department,
               func.count(User.id).label("total"),
               func.coalesce(func.sum(case((User.is_active, 1), else_=0)), 0).label("active"))
        .outerjoin(User, User.department_id == Department.id)
        .group_by(Department.id)
        .order_by(Department.name)
    )
    if not P.is_admin(actor):
        stmt = stmt.where(Department.id == actor.department_id)
    return [{"id": d.id, "name": d.name, "member_count": int(active), "total_count": int(total)}
            for d, total, active in db.execute(stmt)]


def create(db: Session, name: str) -> Department:
    if find_by_name(db, name):
        raise ConflictError(f'Department "{name}" already exists', code="DEPARTMENT_EXISTS")
    dept = Department(name=name)
    db.add(dept)
    db.commit()
    return dept


def rename(db: Session, department_id: int, name: str) -> Department:
    dept = get(db, department_id)
    other = find_by_name(db, name)
    if other and other.id != dept.id:
        raise ConflictError(f'Department "{name}" already exists', code="DEPARTMENT_EXISTS")
    dept.name = name
    db.commit()
    return dept


def delete(db: Session, department_id: int) -> None:
    dept = get(db, department_id)
    if db.scalar(select(func.count(User.id)).where(User.department_id == dept.id)):
        raise ConflictError("Move or remove this department's users first",
                            code="DEPARTMENT_NOT_EMPTY")
    db.delete(dept)
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - safety net
        db.rollback()
        raise ConflictError("Department is still in use", code="DEPARTMENT_NOT_EMPTY") from exc
