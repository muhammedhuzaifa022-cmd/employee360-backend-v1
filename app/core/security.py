"""
Security tools: password hashing and JWT tokens.

PASSWORDS
  - Hashed with Argon2 (the current best practice). The real password is
    never stored, logged or returned.
  - verify_and_update() also tells us when an old hash should be upgraded.

TOKENS (JWT)
  - Access token  : short life (30 min). Sent on every request as
                    "Authorization: Bearer <token>".
  - Refresh token : long life (30 days). Used ONLY to get a new access token.
  - Both carry "sid" = the login session (one row in refresh_tokens),
    so logging out a device immediately blocks its tokens.
"""
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings
from app.core.constants import PASSWORD_MIN_LENGTH
from app.core.exceptions import UnauthorizedError

TokenType = Literal["access", "refresh"]
PASSWORD_MAX_LENGTH = 128

# ---------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------
_password_hash = PasswordHash((Argon2Hasher(),))

# Used when the email does not exist, so a wrong email takes the same time
# as a wrong password (attackers cannot discover which emails exist).
_DUMMY_HASH = _password_hash.hash("dummy-password-used-for-timing-only")


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> tuple[bool, str | None]:
    """Returns (is_correct, new_hash_if_upgrade_needed)."""
    try:
        return _password_hash.verify_and_update(plain, hashed)
    except Exception:  # noqa: BLE001 - malformed hash in DB = wrong password
        return False, None


def fake_password_check(plain: str) -> None:
    _password_hash.verify(plain, _DUMMY_HASH)


def validate_password_strength(password: str) -> str:
    """At least 8 characters, at least one letter and one number."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters long")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number")
    if password.strip() != password:
        raise ValueError("Password must not start or end with a space")
    return password


def generate_temporary_password(length: int = 12) -> str:
    """A random password that always passes the strength rules."""
    import string
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw):
            return pw


# ---------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------
@dataclass(frozen=True)
class TokenPayload:
    user_id: int
    session_id: int
    token_type: TokenType
    role: str | None
    issued_at: int          # seconds since 1970 (UTC)
    expires_at: int
    jti: str | None = None  # only in refresh tokens


def new_jti() -> str:
    """A random, unguessable ID for a refresh token."""
    return secrets.token_urlsafe(32)


def _encode(claims: dict) -> str:
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _base_claims(user_id: int, session_id: int, token_type: TokenType,
                 lifetime: timedelta) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sub": str(user_id),
        "sid": session_id,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }


def create_access_token(user_id: int, session_id: int, role: str) -> str:
    claims = _base_claims(user_id, session_id, "access",
                          timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    claims["role"] = role
    return _encode(claims)


def create_refresh_token(user_id: int, session_id: int, jti: str) -> str:
    claims = _base_claims(user_id, session_id, "refresh",
                          timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    claims["jti"] = jti
    return _encode(claims)


def decode_token(token: str, expected_type: TokenType, *, verify_exp: bool = True) -> TokenPayload:
    """Checks signature, expiry, issuer, audience and token type."""
    try:
        data = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],   # never accept other algorithms
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"require": ["sub", "sid", "type", "iat", "exp"],
                     "verify_exp": verify_exp},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Your session has expired. Please log in again.",
                                code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid token", code="TOKEN_INVALID") from exc

    if data.get("type") != expected_type:
        raise UnauthorizedError(f"A {expected_type} token is required", code="TOKEN_WRONG_TYPE")
    try:
        payload = TokenPayload(
            user_id=int(data["sub"]),
            session_id=int(data["sid"]),
            token_type=data["type"],
            role=data.get("role"),
            issued_at=int(data["iat"]),
            expires_at=int(data["exp"]),
            jti=data.get("jti"),
        )
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid token", code="TOKEN_INVALID") from exc
    if expected_type == "refresh" and not payload.jti:
        raise UnauthorizedError("Invalid token", code="TOKEN_INVALID")
    return payload
