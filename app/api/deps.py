"""
Reusable "dependencies" for routes.

  db: DbSession                 -> a database session for this request
  user: CurrentUser             -> the logged-in, active user (or 401)
  ctx: CurrentAuth              -> user + their current login session
  Depends(require_roles(...))   -> only these roles may call the route (or 403)

The token can come from:
  - the "Authorization: Bearer <token>" header (web and mobile apps), or
  - the Swagger UI "Authorize" button (same header, filled in for you).
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import RefreshToken, User
from app.models.enums import UserRole
from app.services.auth_service import session_is_usable

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/token",
    auto_error=False,
    description="Log in with your email (as username) and password.",
)

DbSession = Annotated[Session, Depends(get_db)]


@dataclass
class AuthContext:
    user: User
    session: RefreshToken


def get_auth_context(db: DbSession,
                     token: Annotated[str | None, Depends(oauth2_scheme)]) -> AuthContext:
    if not token:
        raise UnauthorizedError("Not authenticated. Please log in.", code="TOKEN_MISSING")

    payload = decode_token(token, "access")

    user = db.get(User, payload.user_id, options=[selectinload(User.department)])
    if user is None:
        raise UnauthorizedError("Invalid token", code="TOKEN_INVALID")
    if not user.is_active:
        raise UnauthorizedError("Your account is deactivated.", code="USER_INACTIVE")
    if user.password_changed_at and payload.issued_at < int(user.password_changed_at.timestamp()):
        raise UnauthorizedError("Your password was changed. Please log in again.",
                                code="SESSION_REVOKED")

    session = db.get(RefreshToken, payload.session_id)
    if session is None or session.user_id != user.id or not session_is_usable(session):
        raise UnauthorizedError("You have been logged out. Please log in again.",
                                code="SESSION_REVOKED")
    return AuthContext(user=user, session=session)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


def get_current_user(ctx: CurrentAuth) -> User:
    return ctx.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Usage:  dependencies=[Depends(require_roles(UserRole.ADMIN))]"""
    allowed = set(roles)

    def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise ForbiddenError("You are not allowed to perform this action",
                                 code="ROLE_NOT_ALLOWED")
        return user

    return checker


# Ready-made shortcuts
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
ManagerUser = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.TEAMLEAD))]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
