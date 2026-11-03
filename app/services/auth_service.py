"""
Login logic. Routes call these functions; the rules live here.

A "session" = one row in refresh_tokens = one logged-in browser or phone.
Refresh-token ROTATION: every refresh gives a brand-new refresh token and
the old one stops working. If an old one is ever used again, someone may
have stolen it, so the whole session is closed (TOKEN_REUSED).
"""
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import BadRequestError, ForbiddenError, UnauthorizedError
from app.core.security import (create_access_token, create_refresh_token, decode_token,
                               fake_password_check, hash_password, new_jti, verify_password)
from app.models import RefreshToken, User
from app.models.enums import Platform
from app.schemas.auth import TokenResponse
from app.schemas.user import UserMe
from app.utils.dates import utc_now

INVALID_LOGIN = "Invalid email or password"


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(
        select(User).options(selectinload(User.department))
        .where(func.lower(User.email) == email.strip().lower())
    )


def authenticate(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None:
        fake_password_check(password)  # same timing as a real check
        raise UnauthorizedError(INVALID_LOGIN, code="INVALID_CREDENTIALS")

    ok, upgraded_hash = verify_password(password, user.hashed_password)
    if not ok:
        raise UnauthorizedError(INVALID_LOGIN, code="INVALID_CREDENTIALS")
    if upgraded_hash:
        user.hashed_password = upgraded_hash
    if not user.is_active:
        raise ForbiddenError("Your account is deactivated. Please contact your administrator.",
                             code="ACCOUNT_DISABLED")
    return user


# ---------------- sessions & tokens ----------------
def _refresh_lifetime() -> timedelta:
    return timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def create_session(db: Session, user: User, *, platform: Platform, device_name: str | None,
                   user_agent: str | None, ip_address: str | None) -> RefreshToken:
    session = RefreshToken(
        user_id=user.id, jti=new_jti(), platform=platform,
        device_name=(device_name or None),
        user_agent=(user_agent or "")[:300] or None,
        ip_address=(ip_address or "")[:45] or None,
        expires_at=utc_now() + _refresh_lifetime(),
    )
    db.add(session)
    db.flush()  # gives the session its id
    return session


def build_token_response(user: User, session: RefreshToken) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, session.id, user.role.value),
        refresh_token=create_refresh_token(user.id, session.id, session.jti),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        user=UserMe.model_validate(user),
    )


def login(db: Session, *, email: str, password: str, platform: Platform,
          device_name: str | None, user_agent: str | None, ip_address: str | None) -> TokenResponse:
    user = authenticate(db, email, password)
    session = create_session(db, user, platform=platform, device_name=device_name,
                             user_agent=user_agent, ip_address=ip_address)
    user.last_login_at = utc_now()
    db.commit()
    return build_token_response(user, session)


def session_is_usable(session: RefreshToken | None) -> bool:
    return session is not None and session.revoked_at is None and session.expires_at > utc_now()


def refresh(db: Session, *, refresh_token: str, ip_address: str | None) -> TokenResponse:
    payload = decode_token(refresh_token, "refresh")
    session = db.get(RefreshToken, payload.session_id, with_for_update=True)

    if session is None or session.user_id != payload.user_id or not session_is_usable(session):
        raise UnauthorizedError("Your session has ended. Please log in again.",
                                code="SESSION_REVOKED")

    if session.jti != payload.jti:
        # An OLD refresh token was used again -> possible theft -> close the session.
        session.revoked_at = utc_now()
        db.commit()
        raise UnauthorizedError("This login was used elsewhere and has been closed for safety. "
                                "Please log in again.", code="TOKEN_REUSED")

    user = db.get(User, session.user_id, options=[selectinload(User.department)])
    if user is None or not user.is_active:
        session.revoked_at = utc_now()
        db.commit()
        raise UnauthorizedError("Your account is deactivated.", code="USER_INACTIVE")

    # Rotate: new jti, sliding expiry
    session.jti = new_jti()
    session.last_used_at = utc_now()
    session.expires_at = utc_now() + _refresh_lifetime()
    if ip_address:
        session.ip_address = ip_address[:45]
    db.commit()
    return build_token_response(user, session)


def logout(db: Session, *, refresh_token: str) -> None:
    """Close the session that belongs to this refresh token (works even if expired)."""
    payload = decode_token(refresh_token, "refresh", verify_exp=False)
    session = db.get(RefreshToken, payload.session_id)
    if session and session.user_id == payload.user_id and session.revoked_at is None:
        session.revoked_at = utc_now()
        db.commit()


def revoke_all_sessions(db: Session, user_id: int, *, except_session_id: int | None = None) -> int:
    stmt = (update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utc_now()))
    if except_session_id is not None:
        stmt = stmt.where(RefreshToken.id != except_session_id)
    result = db.execute(stmt)
    return result.rowcount or 0


def list_active_sessions(db: Session, user_id: int) -> list[RefreshToken]:
    return list(db.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None),
               RefreshToken.expires_at > utc_now())
        .order_by(RefreshToken.created_at.desc())
    ))


def revoke_session(db: Session, user_id: int, session_id: int) -> bool:
    session = db.get(RefreshToken, session_id)
    if session is None or session.user_id != user_id or session.revoked_at is not None:
        return False
    session.revoked_at = utc_now()
    db.commit()
    return True


def change_password(db: Session, *, user: User, current_session: RefreshToken,
                    current_password: str, new_password: str) -> TokenResponse:
    ok, _ = verify_password(current_password, user.hashed_password)
    if not ok:
        raise BadRequestError("Your current password is incorrect", code="WRONG_PASSWORD",
                              fields={"current_password": "Incorrect password"})
    if verify_password(new_password, user.hashed_password)[0]:
        raise BadRequestError("The new password must be different from the current one",
                              code="SAME_PASSWORD", fields={"new_password": "Same as current"})

    user.hashed_password = hash_password(new_password)
    user.password_changed_at = utc_now()
    # Log out EVERY device, then start a fresh session for this one.
    revoke_all_sessions(db, user.id)
    new_session = create_session(db, user, platform=current_session.platform,
                                 device_name=current_session.device_name,
                                 user_agent=current_session.user_agent,
                                 ip_address=current_session.ip_address)
    db.commit()
    return build_token_response(user, new_session)
