"""
Authentication endpoints - identical for web, Android and iOS.

  POST /auth/login             email + password -> tokens   (apps use this)
  POST /auth/token             same, as a form              (Swagger "Authorize")
  POST /auth/refresh           refresh token -> new tokens
  POST /auth/logout            close this device's session
  POST /auth/logout-all        close every session of mine
  GET  /auth/me                who am I?
  POST /auth/change-password   change my password (logs out other devices)
  GET  /auth/sessions          my logged-in devices
  DELETE /auth/sessions/{id}   log out one device
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentAuth, CurrentUser, DbSession, client_ip
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.rate_limit import login_limiter
from app.models.enums import Platform
from app.schemas.auth import (ChangePasswordRequest, LoginRequest, RefreshRequest,
                              SessionOut, TokenResponse)
from app.schemas.common import MessageResponse
from app.schemas.user import UserMe
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _do_login(db, request: Request, *, email: str, password: str,
              platform: Platform, device_name: str | None) -> TokenResponse:
    ip = client_ip(request)
    key = login_limiter.key(ip, email)
    login_limiter.check(key)
    try:
        tokens = auth_service.login(
            db, email=email, password=password, platform=platform, device_name=device_name,
            user_agent=request.headers.get("user-agent"), ip_address=ip)
    except UnauthorizedError:
        login_limiter.record_failure(key)
        raise
    login_limiter.reset(key)
    return tokens


@router.post("/login", response_model=TokenResponse, summary="Log in (web and mobile apps)")
def login(body: LoginRequest, request: Request, db: DbSession):
    """
    Send email and password. You get an **access_token** (send it as
    `Authorization: Bearer <token>`) and a **refresh_token** (keep it safe;
    use it at `/auth/refresh` when the access token expires).
    """
    return _do_login(db, request, email=body.email, password=body.password,
                     platform=body.platform, device_name=body.device_name)


@router.post("/token", response_model=TokenResponse,
             summary="Log in with a form (used by the Swagger Authorize button)")
def login_form(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request,
               db: DbSession):
    """Type your **email in the username box**. Leave client_id/secret empty."""
    return _do_login(db, request, email=form.username, password=form.password,
                     platform=Platform.WEB, device_name="Swagger UI")


@router.post("/refresh", response_model=TokenResponse, summary="Get new tokens")
def refresh(body: RefreshRequest, request: Request, db: DbSession):
    """
    Returns a NEW access token **and a new refresh token**. The old refresh token
    stops working immediately; always store the new one.
    """
    return auth_service.refresh(db, refresh_token=body.refresh_token, ip_address=client_ip(request))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             summary="Log out this device")
def logout(body: RefreshRequest, db: DbSession):
    auth_service.logout(db, refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", response_model=MessageResponse, summary="Log out every device")
def logout_all(user: CurrentUser, db: DbSession):
    count = auth_service.revoke_all_sessions(db, user.id)
    db.commit()
    return MessageResponse(message=f"Logged out of {count} session(s)")


@router.get("/me", response_model=UserMe, summary="The logged-in user")
def me(user: CurrentUser):
    return user


@router.post("/change-password", response_model=TokenResponse, summary="Change my password")
def change_password(body: ChangePasswordRequest, ctx: CurrentAuth, db: DbSession):
    """All devices are logged out. New tokens for THIS device are returned."""
    return auth_service.change_password(db, user=ctx.user, current_session=ctx.session,
                                        current_password=body.current_password,
                                        new_password=body.new_password)


@router.get("/sessions", response_model=list[SessionOut], summary="My logged-in devices")
def sessions(ctx: CurrentAuth, db: DbSession):
    result = []
    for s in auth_service.list_active_sessions(db, ctx.user.id):
        item = SessionOut.model_validate(s)
        item.is_current = s.id == ctx.session.id
        result.append(item)
    return result


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Log out one device")
def revoke_session(session_id: int, user: CurrentUser, db: DbSession):
    if not auth_service.revoke_session(db, user.id, session_id):
        raise NotFoundError("Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
