"""Module 5 tests: employees & departments, with role + department scoping."""
import pytest
from sqlalchemy import select

from app.models import RefreshToken, User
from scripts.seed import seed
from tests.factories import API, bearer, login

PW = {"admin": "Admin@123", "teamlead": "Lead@123", "employee": "Employee@123"}
EMAIL = {
    "aisha": "aisha@company.com", "fatima": "fatima@company.com",
    "rahul": "rahul@company.com", "neha": "neha@company.com",
    "mohammed": "mohammed@company.com", "priya": "priya@company.com", "sana": "sana@company.com",
}
ROLE = {"aisha": "admin", "fatima": "admin", "rahul": "teamlead", "neha": "teamlead",
        "mohammed": "employee", "priya": "employee", "sana": "employee"}


@pytest.fixture()
def company(db):
    seed(db)  # dates relative to the real "today", like production
    return {k: db.scalar(select(User).where(User.email == e)).id for k, e in EMAIL.items()}


@pytest.fixture()
def as_(api, company):
    """as_('rahul') -> auth headers for Rahul."""
    cache = {}

    def headers(who: str) -> dict:
        if who not in cache:
            r = login(api, EMAIL[who], PW[ROLE[who]])
            assert r.status_code == 200, r.text
            cache[who] = bearer(r.json()["access_token"])
        return cache[who]
    return headers


def names(resp) -> set[str]:
    return {u["full_name"] for u in resp.json()["items"]}


# ---------------- listing & scoping ----------------
def test_admin_sees_everyone(api, as_):
    r = api.get(f"{API}/users", headers=as_("aisha"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7 and body["page"] == 1 and body["pages"] == 1
    assert len(names(r)) == 7


def test_team_lead_sees_only_own_department(api, as_):
    assert names(api.get(f"{API}/users", headers=as_("rahul"))) == {
        "Rahul Verma", "Mohammed Huzaifa", "Priya Nair"}
    assert names(api.get(f"{API}/users", headers=as_("neha"))) == {"Neha Kapoor", "Sana Ali"}


def test_employee_sees_only_self(api, as_):
    assert names(api.get(f"{API}/users", headers=as_("mohammed"))) == {"Mohammed Huzaifa"}


def test_team_card_stats_match_frontend(api, as_):
    items = {u["full_name"]: u["stats"] for u in
             api.get(f"{API}/users", headers=as_("aisha")).json()["items"]}
    # Mohammed: Website UI (done), API work, Testing (open)
    assert items["Mohammed Huzaifa"] == {"total": 3, "open": 2, "done": 1, "overdue": 0, "in_review": 0}
    # Priya: Database schema (Delayed, overdue), Backend
    assert items["Priya Nair"] == {"total": 2, "open": 2, "done": 0, "overdue": 1, "in_review": 0}
    # Sana: Design system (in review, due today -> not overdue)
    assert items["Sana Ali"] == {"total": 1, "open": 1, "done": 0, "overdue": 0, "in_review": 1}
    assert items["Aisha Khan"]["total"] == 0


def test_filters_search_and_pagination(api, as_):
    h = as_("aisha")
    assert names(api.get(f"{API}/users", headers=h, params={"department": "design"})) == {
        "Neha Kapoor", "Sana Ali"}
    assert names(api.get(f"{API}/users", headers=h, params={"role": "teamlead"})) == {
        "Rahul Verma", "Neha Kapoor"}
    assert names(api.get(f"{API}/users", headers=h, params={"q": "priya"})) == {"Priya Nair"}
    assert api.get(f"{API}/users", headers=h, params={"department": "Nope"}).json()["total"] == 0

    page = api.get(f"{API}/users", headers=h, params={"page": 2, "page_size": 3}).json()
    assert page["total"] == 7 and page["pages"] == 3 and len(page["items"]) == 3
    assert api.get(f"{API}/users", headers=h, params={"page_size": 1000}).status_code == 422


def test_team_lead_department_filter_cannot_escape_scope(api, as_, company):
    r = api.get(f"{API}/users", headers=as_("rahul"), params={"department": "Design"})
    assert r.json()["total"] == 0


def test_get_one_user_visibility_returns_404_not_403(api, as_, company):
    assert api.get(f"{API}/users/{company['priya']}", headers=as_("rahul")).status_code == 200
    r = api.get(f"{API}/users/{company['sana']}", headers=as_("rahul"))
    assert r.status_code == 404 and r.json()["code"] == "USER_NOT_FOUND"
    assert api.get(f"{API}/users/{company['priya']}", headers=as_("mohammed")).status_code == 404
    me = api.get(f"{API}/users/{company['mohammed']}", headers=as_("mohammed")).json()
    assert me["stats"]["done"] == 1
    assert api.get(f"{API}/users/999999", headers=as_("aisha")).status_code == 404


def test_stats_endpoint(api, as_, company):
    r = api.get(f"{API}/users/{company['priya']}/stats", headers=as_("rahul"))
    assert r.json()["overdue"] == 1


def test_assignable_users(api, as_):
    get = lambda who: {u["full_name"] for u in api.get(f"{API}/users/assignable", headers=as_(who)).json()}  # noqa: E731
    assert get("rahul") == {"Rahul Verma", "Mohammed Huzaifa", "Priya Nair"}
    assert get("neha") == {"Neha Kapoor", "Sana Ali"}
    assert get("aisha") == {"Rahul Verma", "Neha Kapoor", "Mohammed Huzaifa", "Priya Nair", "Sana Ali"}
    assert get("mohammed") == set()


# ---------------- add employee ----------------
def test_admin_adds_employee_with_generated_password(api, as_):
    r = api.post(f"{API}/users", headers=as_("aisha"),
                 json={"full_name": "  Maya   Patel ", "email": "Maya@Company.com",
                       "department": "Engineering", "role": "employee"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["full_name"] == "Maya Patel"
    assert body["user"]["email"] == "maya@company.com"
    assert body["user"]["designation"] == "Associate"
    assert body["user"]["department"]["name"] == "Engineering"
    temp = body["temporary_password"]
    assert temp and len(temp) == 12
    # "They can sign in immediately"
    assert login(api, "maya@company.com", temp).status_code == 200
    # Rahul (Engineering lead) now sees her
    assert "Maya Patel" in names(api.get(f"{API}/users", headers=as_("rahul")))


def test_add_employee_with_own_password_and_new_department(api, as_):
    r = api.post(f"{API}/users", headers=as_("aisha"),
                 json={"full_name": "Omar Farooq", "email": "omar@company.com",
                       "department": "Marketing", "role": "teamlead", "password": "Marketing1"})
    assert r.status_code == 201
    assert r.json()["temporary_password"] is None
    assert r.json()["user"]["designation"] == "Team Lead"
    depts = {d["name"] for d in api.get(f"{API}/departments", headers=as_("aisha")).json()}
    assert "Marketing" in depts
    assert login(api, "omar@company.com", "Marketing1").status_code == 200


def test_add_employee_validation(api, as_):
    h = as_("aisha")
    r = api.post(f"{API}/users", headers=h, json={"full_name": "X", "email": "bad"})
    assert r.status_code == 422 and {"full_name", "email"} <= set(r.json()["fields"])
    r = api.post(f"{API}/users", headers=h, json={"full_name": "No Dept", "email": "nd@company.com"})
    assert r.status_code == 422 and "Department is required" in str(r.json()["fields"])
    r = api.post(f"{API}/users", headers=h, json={"full_name": "Weak", "email": "w@company.com",
                                                  "department": "Design", "password": "abc"})
    assert r.status_code == 422 and "password" in r.json()["fields"]
    r = api.post(f"{API}/users", headers=h, json={"full_name": "Dup", "email": "PRIYA@company.com",
                                                  "department": "Design"})
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_EXISTS"
    r = api.post(f"{API}/users", headers=h, json={"full_name": "Bad Id", "email": "bi@company.com",
                                                  "department_id": 9999})
    assert r.status_code == 422 and r.json()["code"] == "DEPARTMENT_NOT_FOUND"


def test_only_admin_can_add_employees(api, as_):
    body = {"full_name": "Sneaky", "email": "s@company.com", "department": "Engineering"}
    for who in ("rahul", "mohammed"):
        r = api.post(f"{API}/users", headers=as_(who), json=body)
        assert r.status_code == 403 and r.json()["code"] == "ROLE_NOT_ALLOWED"


# ---------------- edit ----------------
def test_admin_edits_user_and_role_change_updates_designation(api, as_, company):
    r = api.patch(f"{API}/users/{company['priya']}", headers=as_("aisha"),
                  json={"role": "teamlead", "full_name": "Priya N."})
    assert r.status_code == 200
    assert r.json()["role"] == "teamlead" and r.json()["designation"] == "Team Lead"
    assert r.json()["full_name"] == "Priya N."


def test_move_user_to_other_department(api, as_, company):
    r = api.patch(f"{API}/users/{company['sana']}", headers=as_("aisha"),
                  json={"department": "Engineering"})
    assert r.json()["department"]["name"] == "Engineering"
    assert "Sana Ali" in names(api.get(f"{API}/users", headers=as_("rahul")))
    assert "Sana Ali" not in names(api.get(f"{API}/users", headers=as_("neha")))


def test_edit_rules(api, as_, company):
    h = as_("aisha")
    r = api.patch(f"{API}/users/{company['aisha']}", headers=h, json={"role": "employee"})
    assert r.json()["code"] == "CANNOT_CHANGE_OWN_ROLE"
    r = api.patch(f"{API}/users/{company['sana']}", headers=h, json={"email": "rahul@company.com"})
    assert r.status_code == 409
    r = api.patch(f"{API}/users/{company['rahul']}", headers=as_("rahul"), json={"full_name": "Boss"})
    assert r.status_code == 403


def test_cannot_remove_last_active_admin(api, as_, company):
    h = as_("aisha")
    # Demote Fatima -> fine (Aisha is still admin)
    assert api.patch(f"{API}/users/{company['fatima']}", headers=h,
                     json={"role": "employee"}).status_code == 200
    # Now log in as... Aisha is the last admin; nobody else can demote her, and she can't herself.
    r = api.patch(f"{API}/users/{company['aisha']}/status", headers=h, json={"is_active": False})
    assert r.json()["code"] == "CANNOT_DEACTIVATE_SELF"


# ---------------- activate / deactivate ----------------
def test_deactivate_logs_user_out_and_blocks_login(api, as_, company, db):
    mohammed_headers = as_("mohammed")
    assert api.get(f"{API}/auth/me", headers=mohammed_headers).status_code == 200

    r = api.patch(f"{API}/users/{company['mohammed']}/status", headers=as_("aisha"),
                  json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    assert api.get(f"{API}/auth/me", headers=mohammed_headers).status_code == 401
    assert login(api, EMAIL["mohammed"], PW["employee"]).json()["code"] == "ACCOUNT_DISABLED"
    open_sessions = db.scalars(select(RefreshToken).where(
        RefreshToken.user_id == company["mohammed"], RefreshToken.revoked_at.is_(None))).all()
    assert open_sessions == []

    # Re-activate -> can log in again; list shows inactive filter correctly
    api.patch(f"{API}/users/{company['mohammed']}/status", headers=as_("aisha"), json={"is_active": True})
    assert login(api, EMAIL["mohammed"], PW["employee"]).status_code == 200


def test_inactive_filter(api, as_, company):
    api.patch(f"{API}/users/{company['sana']}/status", headers=as_("aisha"), json={"is_active": False})
    r = api.get(f"{API}/users", headers=as_("aisha"), params={"is_active": False})
    assert names(r) == {"Sana Ali"}
    assert "Sana Ali" not in {u["full_name"] for u in
                              api.get(f"{API}/users/assignable", headers=as_("neha")).json()}


def test_non_admin_cannot_deactivate(api, as_, company):
    r = api.patch(f"{API}/users/{company['mohammed']}/status", headers=as_("rahul"),
                  json={"is_active": False})
    assert r.status_code == 403


# ---------------- reset password ----------------
def test_admin_resets_password(api, as_, company):
    priya_headers = as_("priya")
    r = api.post(f"{API}/users/{company['priya']}/reset-password", headers=as_("aisha"), json={})
    temp = r.json()["temporary_password"]
    assert r.status_code == 200 and temp
    assert api.get(f"{API}/auth/me", headers=priya_headers).status_code == 401
    assert login(api, EMAIL["priya"], PW["employee"]).status_code == 401
    assert login(api, EMAIL["priya"], temp).status_code == 200

    r = api.post(f"{API}/users/{company['aisha']}/reset-password", headers=as_("aisha"), json={})
    assert r.json()["code"] == "USE_CHANGE_PASSWORD"


# ---------------- departments ----------------
def test_department_list_is_scoped(api, as_):
    admin = {d["name"]: d for d in api.get(f"{API}/departments", headers=as_("aisha")).json()}
    assert set(admin) == {"Design", "Engineering", "Management"}
    assert admin["Engineering"]["member_count"] == 3
    assert [d["name"] for d in api.get(f"{API}/departments", headers=as_("rahul")).json()] == ["Engineering"]
    assert [d["name"] for d in api.get(f"{API}/departments", headers=as_("sana")).json()] == ["Design"]


def test_department_admin_actions(api, as_):
    h = as_("aisha")
    r = api.post(f"{API}/departments", headers=h, json={"name": "  Human   Resources "})
    assert r.status_code == 201 and r.json()["name"] == "Human Resources"
    dept_id = r.json()["id"]
    assert api.post(f"{API}/departments", headers=h, json={"name": "human resources"}).status_code == 409
    assert api.patch(f"{API}/departments/{dept_id}", headers=h, json={"name": "People"}).json()["name"] == "People"
    assert api.post(f"{API}/departments", headers=as_("rahul"), json={"name": "X Team"}).status_code == 403

    eng = next(d for d in api.get(f"{API}/departments", headers=h).json() if d["name"] == "Engineering")
    r = api.delete(f"{API}/departments/{eng['id']}", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "DEPARTMENT_NOT_EMPTY"
    assert api.delete(f"{API}/departments/{dept_id}", headers=h).status_code == 204


def test_responses_never_contain_password_hash(api, as_):
    text = api.get(f"{API}/users", headers=as_("aisha")).text
    assert "hashed_password" not in text and "argon2" not in text
