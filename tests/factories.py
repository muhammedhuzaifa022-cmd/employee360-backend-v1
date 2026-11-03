"""Helpers that create test data quickly."""
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password
from app.models import Department, User
from app.models.enums import UserRole

API = settings.API_V1_PREFIX
DEFAULT_PASSWORD = "Passw0rd123"
_HASH_CACHE: dict[str, str] = {}


def department(db, name: str) -> Department:
    d = db.scalar(select(Department).where(func.lower(Department.name) == name.lower()))
    if d is None:
        d = Department(name=name)
        db.add(d)
        db.flush()
    return d


def user(db, email: str, role: UserRole = UserRole.EMPLOYEE, dept: str | None = "Engineering",
         password: str = DEFAULT_PASSWORD, active: bool = True, name: str | None = None) -> User:
    if password not in _HASH_CACHE:          # hashing is slow on purpose; reuse in tests
        _HASH_CACHE[password] = hash_password(password)
    u = User(full_name=name or email.split("@")[0].title(), email=email,
             hashed_password=_HASH_CACHE[password], role=role, is_active=active,
             department_id=department(db, dept).id if dept else None)
    db.add(u)
    db.flush()
    return u


def login(api, email: str, password: str = DEFAULT_PASSWORD, **extra):
    return api.post(f"{API}/auth/login", json={"email": email, "password": password, **extra})


def tokens(api, email: str, password: str = DEFAULT_PASSWORD) -> dict:
    r = login(api, email, password)
    assert r.status_code == 200, r.text
    return r.json()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
