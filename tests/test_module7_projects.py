"""Module 7 tests: projects - visibility, create/edit/members/delete, progress, notifications."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import Notification, Project, User
from app.models.enums import UserRole
from scripts.seed import seed
from tests import factories as F
from tests.factories import API, bearer, login

PW = {"aisha": "Admin@123", "fatima": "Admin@123", "rahul": "Lead@123", "neha": "Lead@123",
      "mohammed": "Employee@123", "priya": "Employee@123", "sana": "Employee@123"}
P = f"{API}/projects"
TODAY = date.today()


@pytest.fixture()
def people(db):
    seed(db)
    return {u.email.split("@")[0]: u for u in db.scalars(select(User))}


@pytest.fixture()
def website(db, people):
    return db.scalar(select(Project).where(Project.name == "Company Website"))


@pytest.fixture()
def as_(api, people):
    cache = {}

    def headers(who):
        if who not in cache:
            pw = PW.get(who, F.DEFAULT_PASSWORD)
            r = login(api, f"{who}@company.com", pw)
            assert r.status_code == 200, r.text
            cache[who] = bearer(r.json()["access_token"])
        return cache[who]
    return headers


def new_project(**extra):
    body = {"name": "Mobile app v2", "description": "Phone app", "start_date": str(TODAY),
            "end_date": str(TODAY + timedelta(days=30)), "priority": "High"}
    body.update(extra)
    return body


def project_names(resp):
    return [p["name"] for p in resp.json()["items"]]


# ---------------- reading ----------------
def test_project_card_matches_frontend(api, as_, people):
    r = api.get(P, headers=as_("aisha"))
    assert r.status_code == 200 and r.json()["total"] == 1
    p = r.json()["items"][0]
    assert p["name"] == "Company Website" and p["description"] == "Public site rebuild"
    assert p["priority"] == "High" and p["manager"]["full_name"] == "Rahul Verma"
    assert [m["full_name"] for m in p["members"]] == ["Mohammed Huzaifa", "Priya Nair", "Sana Ali"]
    # 6 tasks: Website UI done, Database schema late  -> 1/6 = 17 %
    assert p["progress"] == {"total": 6, "done": 1, "overdue": 1, "percent": 17}
    assert p["can_edit"] is True
    assert "email" not in p["members"][0]


def test_visibility_rules(api, as_, people, db):
    # A Design-only project created directly in the DB
    design = Project(name="Brand refresh", manager_id=people["neha"].id, start_date=TODAY,
                     end_date=TODAY, members=[people["sana"]])
    db.add(design)
    db.flush()
    seen = {w: set(project_names(api.get(P, headers=as_(w)))) for w in PW}
    assert seen["aisha"] == seen["fatima"] == {"Company Website", "Brand refresh"}
    assert seen["rahul"] == {"Company Website"}                    # manages it
    assert seen["neha"] == {"Company Website", "Brand refresh"}    # Sana (Design) is in Website
    assert seen["mohammed"] == {"Company Website"}                  # member
    assert seen["sana"] == {"Company Website", "Brand refresh"}
    # Rahul can't open the Design project at all -> 404
    r = api.get(f"{P}/{design.id}", headers=as_("rahul"))
    assert r.status_code == 404 and r.json()["code"] == "PROJECT_NOT_FOUND"


def test_employee_not_in_project_sees_nothing(api, as_, db, website):
    F.user(db, "omar@company.com", UserRole.EMPLOYEE, "Engineering")
    assert api.get(P, headers=as_("omar")).json()["total"] == 0
    assert api.get(f"{P}/{website.id}", headers=as_("omar")).status_code == 404


def test_can_edit_flag(api, as_, website):
    flags = {w: api.get(f"{P}/{website.id}", headers=as_(w)).json()["can_edit"]
             for w in ("aisha", "rahul", "neha", "mohammed")}
    assert flags == {"aisha": True, "rahul": True, "neha": False, "mohammed": False}


def test_filters(api, as_, people):
    h = as_("aisha")
    assert project_names(api.get(P, headers=h, params={"q": "website"})) == ["Company Website"]
    assert api.get(P, headers=h, params={"q": "zzz"}).json()["total"] == 0
    assert api.get(P, headers=h, params={"priority": "Low"}).json()["total"] == 0
    assert api.get(P, headers=h, params={"manager_id": people["rahul"].id}).json()["total"] == 1
    assert api.get(P, headers=h, params={"member_id": people["sana"].id}).json()["total"] == 1
    assert api.get(P, headers=h, params={"member_id": people["rahul"].id}).json()["total"] == 0
    assert api.get(P, headers=h, params={"active_on": str(TODAY)}).json()["total"] == 1
    assert api.get(P, headers=h,
                   params={"active_on": str(TODAY + timedelta(days=365))}).json()["total"] == 0


def test_form_options(api, as_):
    admin = api.get(f"{P}/form-options", headers=as_("aisha")).json()
    assert {m["full_name"] for m in admin["managers"]} == {
        "Aisha Khan", "Fatima Sheikh", "Rahul Verma", "Neha Kapoor"}
    assert {m["full_name"] for m in admin["members"]} == {
        "Mohammed Huzaifa", "Priya Nair", "Sana Ali"}
    lead = api.get(f"{P}/form-options", headers=as_("rahul")).json()
    assert [m["full_name"] for m in lead["managers"]] == ["Rahul Verma"]
    assert {m["full_name"] for m in lead["members"]} == {"Mohammed Huzaifa", "Priya Nair"}
    assert api.get(f"{P}/form-options", headers=as_("mohammed")).status_code == 403


# ---------------- create ----------------
def test_team_lead_creates_project_and_members_are_notified(api, as_, people, db):
    r = api.post(P, headers=as_("rahul"), json=new_project(
        name="  Mobile   app v2 ", member_ids=[people["mohammed"].id, people["priya"].id]))
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["name"] == "Mobile app v2" and p["manager"]["full_name"] == "Rahul Verma"
    assert p["progress"] == {"total": 0, "done": 0, "overdue": 0, "percent": 0}
    notes = db.scalars(select(Notification).where(Notification.entity_type == "project",
                                                  Notification.entity_id == p["id"])).all()
    assert sorted(n.recipient_id for n in notes) == sorted([people["mohammed"].id,
                                                            people["priya"].id])
    assert notes[0].message == 'You were added to project "Mobile app v2"'
    assert notes[0].category == "project_added"
    # Mohammed now sees two projects
    assert api.get(P, headers=as_("mohammed")).json()["total"] == 2


def test_team_lead_create_rules(api, as_, people):
    h = as_("rahul")
    r = api.post(P, headers=h, json=new_project(member_ids=[people["sana"].id]))
    assert r.status_code == 403 and r.json()["code"] == "MEMBER_NOT_ALLOWED"
    r = api.post(P, headers=h, json=new_project(manager_id=people["neha"].id))
    assert r.status_code == 403 and r.json()["code"] == "MANAGER_NOT_ALLOWED"
    assert api.post(P, headers=h, json=new_project(manager_id=people["rahul"].id)).status_code == 201


def test_admin_creates_with_any_manager_and_members(api, as_, people, db):
    r = api.post(P, headers=as_("aisha"), json=new_project(
        manager_id=people["neha"].id, member_ids=[people["sana"].id, people["priya"].id]))
    assert r.status_code == 201
    assert r.json()["manager"]["full_name"] == "Neha Kapoor"
    assert r.json()["can_edit"] is True
    note = db.scalar(select(Notification).where(Notification.recipient_id == people["neha"].id,
                                                Notification.entity_type == "project"))
    assert note.message == 'You are now the manager of project "Mobile app v2"'


def test_create_validation(api, as_, people, db):
    h = as_("aisha")
    r = api.post(P, headers=h, json=new_project(name=" "))
    assert r.status_code == 422 and "name" in r.json()["fields"]
    r = api.post(P, headers=h, json=new_project(end_date=str(TODAY - timedelta(days=1))))
    assert r.status_code == 422 and "End date" in str(r.json()["fields"])
    r = api.post(P, headers=h, json=new_project(manager_id=people["mohammed"].id))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_MANAGER"
    r = api.post(P, headers=h, json=new_project(member_ids=[999999]))
    assert r.status_code == 422 and r.json()["code"] == "USER_NOT_FOUND"
    r = api.post(P, headers=h, json=new_project(member_ids=[people["rahul"].id]))
    assert r.status_code == 403 and "not an employee" in r.json()["detail"]
    people["priya"].is_active = False
    db.flush()
    r = api.post(P, headers=h, json=new_project(member_ids=[people["priya"].id]))
    assert r.status_code == 422 and r.json()["code"] == "MEMBER_INACTIVE"
    # Admin as manager needs a manager_id? No - the admin becomes the manager
    r = api.post(P, headers=h, json=new_project(name="Admin project"))
    assert r.status_code == 201 and r.json()["manager"]["full_name"] == "Aisha Khan"


def test_employee_cannot_create(api, as_):
    r = api.post(P, headers=as_("mohammed"), json=new_project())
    assert r.status_code == 403 and r.json()["code"] == "ROLE_NOT_ALLOWED"


# ---------------- edit ----------------
def test_manager_edits_details(api, as_, website):
    r = api.patch(f"{P}/{website.id}", headers=as_("rahul"),
                  json={"name": "Company Website 2.0", "priority": "Medium",
                        "end_date": str(TODAY + timedelta(days=60))})
    assert r.status_code == 200
    assert r.json()["name"] == "Company Website 2.0" and r.json()["priority"] == "Medium"


def test_edit_rules(api, as_, website, people):
    r = api.patch(f"{P}/{website.id}", headers=as_("neha"), json={"name": "Hacked"})
    assert r.status_code == 403 and r.json()["code"] == "NOT_PROJECT_MANAGER"
    assert api.patch(f"{P}/{website.id}", headers=as_("mohammed"), json={"name": "X1"}).status_code == 403
    r = api.patch(f"{P}/{website.id}", headers=as_("rahul"),
                  json={"end_date": "2000-01-01"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_DATES"
    r = api.patch(f"{P}/{website.id}", headers=as_("rahul"), json={"manager_id": people["neha"].id})
    assert r.status_code == 403 and r.json()["code"] == "MANAGER_NOT_ALLOWED"
    # nothing was changed by the failed calls
    assert api.get(f"{P}/{website.id}", headers=as_("aisha")).json()["name"] == "Company Website"


def test_admin_changes_manager(api, as_, website, people):
    r = api.patch(f"{P}/{website.id}", headers=as_("aisha"), json={"manager_id": people["neha"].id})
    assert r.json()["manager"]["full_name"] == "Neha Kapoor"
    # Rahul still sees it (Mohammed & Priya are Engineering) but can no longer edit
    p = api.get(f"{P}/{website.id}", headers=as_("rahul")).json()
    assert p["can_edit"] is False


# ---------------- members ----------------
def test_add_and_remove_members(api, as_, db, website, people):
    omar = F.user(db, "omar@company.com", UserRole.EMPLOYEE, "Engineering", name="Omar Farooq")
    h = as_("rahul")
    r = api.post(f"{P}/{website.id}/members", headers=h, json={"member_ids": [omar.id, people["priya"].id]})
    assert r.status_code == 200
    assert "Omar Farooq" in [m["full_name"] for m in r.json()["members"]]
    # only Omar is notified (Priya was already a member)
    notes = db.scalars(select(Notification).where(Notification.entity_type == "project")).all()
    assert [n.recipient_id for n in notes] == [omar.id]

    r = api.delete(f"{P}/{website.id}/members/{omar.id}", headers=h)
    assert "Omar Farooq" not in [m["full_name"] for m in r.json()["members"]]
    r = api.delete(f"{P}/{website.id}/members/{omar.id}", headers=h)
    assert r.status_code == 404 and r.json()["code"] == "MEMBER_NOT_FOUND"


def test_team_lead_cannot_remove_other_department_member(api, as_, website, people):
    r = api.delete(f"{P}/{website.id}/members/{people['sana'].id}", headers=as_("rahul"))
    assert r.status_code == 403 and r.json()["code"] == "MEMBER_NOT_ALLOWED"
    # ...but an admin can
    r = api.delete(f"{P}/{website.id}/members/{people['sana'].id}", headers=as_("aisha"))
    assert "Sana Ali" not in [m["full_name"] for m in r.json()["members"]]
    # and now Neha no longer sees the project
    assert api.get(P, headers=as_("neha")).json()["total"] == 0


def test_replace_members(api, as_, website, people):
    h = as_("rahul")
    # Rahul must keep Sana (other department) in the list
    r = api.put(f"{P}/{website.id}/members", headers=h, json={"member_ids": [people["mohammed"].id]})
    assert r.status_code == 403
    r = api.put(f"{P}/{website.id}/members", headers=h,
                json={"member_ids": [people["mohammed"].id, people["sana"].id]})
    assert r.status_code == 200
    assert [m["full_name"] for m in r.json()["members"]] == ["Mohammed Huzaifa", "Sana Ali"]
    r = api.put(f"{P}/{website.id}/members", headers=as_("aisha"), json={"member_ids": []})
    assert r.json()["members"] == []


# ---------------- delete ----------------
def test_delete_rules(api, as_, website):
    r = api.delete(f"{P}/{website.id}", headers=as_("aisha"))
    assert r.status_code == 409 and r.json()["code"] == "PROJECT_HAS_TASKS"
    pid = api.post(P, headers=as_("rahul"), json=new_project()).json()["id"]
    r = api.delete(f"{P}/{pid}", headers=as_("rahul"))
    assert r.status_code == 403 and r.json()["code"] == "ROLE_NOT_ALLOWED"
    assert api.delete(f"{P}/{pid}", headers=as_("aisha")).status_code == 204
    assert api.get(f"{P}/{pid}", headers=as_("aisha")).status_code == 404


def test_pagination(api, as_):
    h = as_("aisha")
    for i in range(4):
        api.post(P, headers=h, json=new_project(name=f"Project {i}"))
    page = api.get(P, headers=h, params={"page": 2, "page_size": 2}).json()
    assert page["total"] == 5 and page["pages"] == 3
    assert [p["name"] for p in page["items"]] == ["Project 1", "Project 2"]  # creation order
