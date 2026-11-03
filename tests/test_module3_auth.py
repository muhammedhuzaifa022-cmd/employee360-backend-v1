"""Module 3 tests: hashing, login, tokens, sessions, logout, password change, devices."""
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.core.security import hash_password, validate_password_strength, verify_password
from app.models import RefreshToken, User
from app.models.enums import UserRole
from tests.factories import API, DEFAULT_PASSWORD, bearer, login, tokens, user

ME = f"{API}/auth/me"


# ---------------- password hashing ----------------
def test_password_is_hashed_with_argon2_never_plain():
    h = hash_password("Secret123")
    assert h.startswith("$argon2id$") and "Secret123" not in h
    assert verify_password("Secret123", h)[0] is True
    assert verify_password("secret123", h)[0] is False
    assert hash_password("Secret123") != h  # random salt every time


def test_password_strength_rules():
    for bad in ["short1", "onlyletters", "12345678", " Spaced123"]:
        try:
            validate_password_strength(bad)
            raise AssertionError(f"{bad!r} should be rejected")
        except ValueError:
            pass
    assert validate_password_strength("GoodPass1") == "GoodPass1"


# ---------------- login ----------------
def test_login_success_returns_tokens_and_user(api, db):
    u = user(db, "priya@company.com", name="Priya Nair")
    r = login(api, "PRIYA@Company.com", platform="android", device_name="Pixel 8")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["user"]["email"] == "priya@company.com"
    assert body["user"]["role"] == "employee"
    assert body["user"]["department"]["name"] == "Engineering"
    assert "hashed_password" not in body["user"]

    db.refresh(u)
    assert u.last_login_at is not None
    session = db.query(RefreshToken).filter_by(user_id=u.id).one()
    assert session.platform.value == "android" and session.device_name == "Pixel 8"


def test_wrong_password_and_unknown_email_give_same_error(api, db):
    user(db, "rahul@company.com")
    a = login(api, "rahul@company.com", "WrongPass1")
    b = login(api, "nobody@company.com", "WrongPass1")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Invalid email or password",
                                    "code": "INVALID_CREDENTIALS", "fields": None}


def test_deactivated_user_cannot_log_in(api, db):
    user(db, "old@company.com", active=False)
    r = login(api, "old@company.com")
    assert r.status_code == 403 and r.json()["code"] == "ACCOUNT_DISABLED"


def test_invalid_login_body_gives_field_errors(api):
    r = api.post(f"{API}/auth/login", json={"email": "not-an-email", "password": ""})
    assert r.status_code == 422
    assert set(r.json()["fields"]) == {"email", "password"}


def test_too_many_failed_logins_are_blocked(api, db):
    user(db, "target@company.com")
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        assert login(api, "target@company.com", "Wrong1234").status_code == 401
    r = login(api, "target@company.com")  # even the right password is blocked now
    assert r.status_code == 429
    assert r.json()["code"] == "TOO_MANY_LOGIN_ATTEMPTS"
    assert int(r.headers["Retry-After"]) > 0


def test_swagger_form_login(api, db):
    user(db, "form@company.com")
    r = api.post(f"{API}/auth/token",
                 data={"username": "form@company.com", "password": DEFAULT_PASSWORD})
    assert r.status_code == 200 and r.json()["access_token"]


# ---------------- access token checks ----------------
def test_me_requires_a_token(api):
    r = api.get(ME)
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_MISSING"
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_me_with_valid_token(api, db):
    user(db, "me@company.com", role=UserRole.TEAMLEAD, name="Rahul Verma")
    t = tokens(api, "me@company.com")
    r = api.get(ME, headers=bearer(t["access_token"]))
    assert r.status_code == 200
    assert r.json()["full_name"] == "Rahul Verma" and r.json()["role"] == "teamlead"


def test_garbage_and_tampered_tokens_are_rejected(api, db):
    user(db, "t@company.com")
    t = tokens(api, "t@company.com")["access_token"]
    assert api.get(ME, headers=bearer("abc.def.ghi")).json()["code"] == "TOKEN_INVALID"
    tampered = t[:-3] + ("aaa" if t[-3:] != "aaa" else "bbb")
    assert api.get(ME, headers=bearer(tampered)).json()["code"] == "TOKEN_INVALID"
    forged = jwt.encode({"sub": "1", "sid": 1, "type": "access", "iat": 0, "exp": 9999999999},
                        "a-different-secret-key-that-is-long-enough", algorithm="HS256")
    assert api.get(ME, headers=bearer(forged)).status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(api, db):
    user(db, "r@company.com")
    t = tokens(api, "r@company.com")
    r = api.get(ME, headers=bearer(t["refresh_token"]))
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_WRONG_TYPE"


def test_expired_access_token(api, db):
    u = user(db, "exp@company.com")
    t = tokens(api, "exp@company.com")
    sid = jwt.decode(t["access_token"], options={"verify_signature": False})["sid"]
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    expired = jwt.encode({"sub": str(u.id), "sid": sid, "type": "access", "role": "employee",
                          "iat": int(past.timestamp()), "exp": int(past.timestamp()) + 60,
                          "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
                         settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    r = api.get(ME, headers=bearer(expired))
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"


def test_deactivating_user_blocks_existing_token_immediately(api, db):
    u = user(db, "soon-gone@company.com")
    t = tokens(api, "soon-gone@company.com")
    u.is_active = False
    db.flush()
    r = api.get(ME, headers=bearer(t["access_token"]))
    assert r.status_code == 401 and r.json()["code"] == "USER_INACTIVE"


# ---------------- refresh rotation ----------------
def test_refresh_rotates_and_detects_reuse(api, db):
    user(db, "rot@company.com")
    first = tokens(api, "rot@company.com")

    r = api.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert api.get(ME, headers=bearer(second["access_token"])).status_code == 200

    # Re-using the OLD refresh token = possible theft -> session closed
    r = api.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_REUSED"
    # ...and the NEW tokens of that session die too
    r = api.post(f"{API}/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.json()["code"] == "SESSION_REVOKED"
    assert api.get(ME, headers=bearer(second["access_token"])).json()["code"] == "SESSION_REVOKED"


def test_access_token_cannot_be_used_to_refresh(api, db):
    user(db, "x@company.com")
    t = tokens(api, "x@company.com")
    r = api.post(f"{API}/auth/refresh", json={"refresh_token": t["access_token"]})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_WRONG_TYPE"


# ---------------- logout & sessions ----------------
def test_logout_closes_only_this_device(api, db):
    user(db, "two@company.com")
    web = tokens(api, "two@company.com")
    phone = tokens(api, "two@company.com")

    assert api.post(f"{API}/auth/logout", json={"refresh_token": web["refresh_token"]}).status_code == 204
    assert api.get(ME, headers=bearer(web["access_token"])).json()["code"] == "SESSION_REVOKED"
    assert api.post(f"{API}/auth/refresh", json={"refresh_token": web["refresh_token"]}).status_code == 401
    assert api.get(ME, headers=bearer(phone["access_token"])).status_code == 200


def test_logout_all(api, db):
    user(db, "all@company.com")
    a, b = tokens(api, "all@company.com"), tokens(api, "all@company.com")
    r = api.post(f"{API}/auth/logout-all", headers=bearer(a["access_token"]))
    assert r.status_code == 200 and r.json()["message"] == "Logged out of 2 session(s)"
    for t in (a, b):
        assert api.get(ME, headers=bearer(t["access_token"])).status_code == 401


def test_list_and_revoke_sessions(api, db):
    user(db, "dev@company.com")
    web = tokens(api, "dev@company.com")
    login(api, "dev@company.com", platform="ios", device_name="iPhone 16")

    r = api.get(f"{API}/auth/sessions", headers=bearer(web["access_token"]))
    sessions = r.json()
    assert len(sessions) == 2
    assert sum(s["is_current"] for s in sessions) == 1
    phone = next(s for s in sessions if s["platform"] == "ios")
    assert phone["device_name"] == "iPhone 16"

    assert api.delete(f"{API}/auth/sessions/{phone['id']}",
                      headers=bearer(web["access_token"])).status_code == 204
    assert len(api.get(f"{API}/auth/sessions", headers=bearer(web["access_token"])).json()) == 1
    assert api.delete(f"{API}/auth/sessions/999999",
                      headers=bearer(web["access_token"])).status_code == 404


def test_cannot_revoke_someone_elses_session(api, db):
    user(db, "a1@company.com")
    user(db, "b1@company.com")
    a = tokens(api, "a1@company.com")
    b = tokens(api, "b1@company.com")
    b_sid = jwt.decode(b["access_token"], options={"verify_signature": False})["sid"]
    r = api.delete(f"{API}/auth/sessions/{b_sid}", headers=bearer(a["access_token"]))
    assert r.status_code == 404
    assert api.get(ME, headers=bearer(b["access_token"])).status_code == 200


# ---------------- change password ----------------
def test_change_password_flow(api, db):
    u = user(db, "cp@company.com")
    old_hash = u.hashed_password
    this_device = tokens(api, "cp@company.com")
    other_device = tokens(api, "cp@company.com")
    h = bearer(this_device["access_token"])

    r = api.post(f"{API}/auth/change-password", headers=h,
                 json={"current_password": "WrongOld1", "new_password": "NewPass123"})
    assert r.status_code == 400 and r.json()["code"] == "WRONG_PASSWORD"

    r = api.post(f"{API}/auth/change-password", headers=h,
                 json={"current_password": DEFAULT_PASSWORD, "new_password": "weak"})
    assert r.status_code == 422 and "new_password" in r.json()["fields"]

    r = api.post(f"{API}/auth/change-password", headers=h,
                 json={"current_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD})
    assert r.status_code == 400 and r.json()["code"] == "SAME_PASSWORD"

    r = api.post(f"{API}/auth/change-password", headers=h,
                 json={"current_password": DEFAULT_PASSWORD, "new_password": "NewPass123"})
    assert r.status_code == 200
    fresh = r.json()

    db.refresh(u)
    assert u.hashed_password != old_hash and u.hashed_password.startswith("$argon2id$")
    # every old token is dead, the fresh one works
    assert api.get(ME, headers=bearer(other_device["access_token"])).status_code == 401
    assert api.get(ME, headers=h).status_code == 401
    assert api.get(ME, headers=bearer(fresh["access_token"])).status_code == 200
    # old password no longer works, new one does
    assert login(api, "cp@company.com").status_code == 401
    assert login(api, "cp@company.com", "NewPass123").status_code == 200


# ---------------- devices (future mobile push) ----------------
def test_register_list_and_delete_push_device(api, db):
    user(db, "m1@company.com")
    user(db, "m2@company.com")
    h1 = bearer(tokens(api, "m1@company.com")["access_token"])
    h2 = bearer(tokens(api, "m2@company.com")["access_token"])
    payload = {"push_token": "fcm-token-1234567890", "platform": "android", "device_name": "Pixel"}

    r = api.post(f"{API}/devices", headers=h1, json=payload)
    assert r.status_code == 201
    device_id = r.json()["id"]
    assert len(api.get(f"{API}/devices", headers=h1).json()) == 1

    # same phone, different person logs in -> device moves to them
    assert api.post(f"{API}/devices", headers=h2, json=payload).json()["id"] == device_id
    assert api.get(f"{API}/devices", headers=h1).json() == []
    assert api.delete(f"{API}/devices/{device_id}", headers=h1).status_code == 404
    assert api.delete(f"{API}/devices/{device_id}", headers=h2).status_code == 204


def test_user_row_never_exposes_password(api, db):
    user(db, "safe@company.com")
    t = tokens(api, "safe@company.com")
    text_dump = api.get(ME, headers=bearer(t["access_token"])).text
    assert "hashed_password" not in text_dump and "argon2" not in text_dump
    assert isinstance(db.query(User).filter_by(email="safe@company.com").one().hashed_password, str)
