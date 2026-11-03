"""Module 8 tests: tasks - visibility, lifecycle, review, deadlines, comments, history."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Notification, Project, Task, TaskComment, TaskHistory, User
from app.utils.dates import company_today
from scripts.seed import seed
from tests import factories as F
from tests.factories import API, bearer, login

PW = {"aisha": "Admin@123", "fatima": "Admin@123", "rahul": "Lead@123", "neha": "Lead@123",
      "mohammed": "Employee@123", "priya": "Employee@123", "sana": "Employee@123"}
T = f"{API}/tasks"
TODAY = company_today()


@pytest.fixture()
def people(db):
    seed(db)
    return {u.email.split("@")[0]: u for u in db.scalars(select(User))}


@pytest.fixture()
def task(db, people):
    """task('Testing') -> Task id"""
    return lambda title: db.scalar(select(Task.id).where(Task.title == title))


@pytest.fixture()
def as_(api, people):
    cache = {}

    def headers(who):
        if who not in cache:
            r = login(api, f"{who}@company.com", PW.get(who, F.DEFAULT_PASSWORD))
            assert r.status_code == 200, r.text
            cache[who] = bearer(r.json()["access_token"])
        return cache[who]
    return headers


def titles(resp):
    return [t["title"] for t in resp.json()["items"]]


def notes_for(db, user, category=None):
    stmt = select(Notification).where(Notification.recipient_id == user.id)
    if category:
        stmt = stmt.where(Notification.category == category)
    return db.scalars(stmt.order_by(Notification.id)).all()


# ================================================================ visibility
def test_visibility_per_role(api, as_):
    seen = {w: set(titles(api.get(T, headers=as_(w)))) for w in PW}
    all_six = {"Website UI", "API work", "Database schema", "Backend", "Design system", "Testing"}
    assert seen["aisha"] == seen["fatima"] == all_six
    assert seen["rahul"] == all_six - {"Design system"}       # Engineering only
    assert seen["neha"] == {"Design system"}                    # Design only
    assert seen["mohammed"] == {"Website UI", "API work", "Testing"}
    assert seen["priya"] == {"Database schema", "Backend"}
    assert seen["sana"] == {"Design system"}


def test_hidden_task_is_404(api, as_, task):
    r = api.get(f"{T}/{task('Design system')}", headers=as_("rahul"))
    assert r.status_code == 404 and r.json()["code"] == "TASK_NOT_FOUND"
    assert api.get(f"{T}/{task('Backend')}", headers=as_("mohammed")).status_code == 404


def test_task_shape_and_sorting(api, as_):
    items = api.get(T, headers=as_("aisha")).json()["items"]
    assert [t["due_date"] for t in items] == sorted(t["due_date"] for t in items)
    db_schema = next(t for t in items if t["title"] == "Database schema")
    assert db_schema["is_overdue"] is True and db_schema["days_left"] == -2
    assert db_schema["assignee"]["full_name"] == "Priya Nair"
    assert db_schema["assigned_by"]["full_name"] == "Rahul Verma"
    assert db_schema["project"]["name"] == "Company Website"
    done = next(t for t in items if t["title"] == "Website UI")
    assert done["completed_on"] and done["rating"] == 85 and done["days_left"] is None


def test_filter_chips_and_counts(api, as_):
    h = as_("aisha")
    assert set(titles(api.get(T, headers=h, params={"filter": "overdue"}))) == {"Database schema"}
    assert set(titles(api.get(T, headers=h, params={"filter": "in_review"}))) == {"Design system"}
    assert set(titles(api.get(T, headers=h, params={"filter": "completed"}))) == {"Website UI"}
    assert api.get(T, headers=h, params={"filter": "open"}).json()["total"] == 5
    assert api.get(f"{T}/counts", headers=h).json() == {
        "all": 6, "open": 5, "overdue": 1, "in_review": 1, "completed": 1}
    assert api.get(f"{T}/counts", headers=as_("neha")).json()["all"] == 1


def test_search_and_other_filters(api, as_, people):
    h = as_("aisha")
    assert set(titles(api.get(T, headers=h, params={"q": "priya"}))) == {"Database schema", "Backend"}
    assert api.get(T, headers=h, params={"q": "website"}).json()["total"] == 6  # project name
    assert set(titles(api.get(T, headers=h, params={"q": "schema"}))) == {"Database schema"}
    assert api.get(T, headers=h, params={"assignee_id": people["sana"].id}).json()["total"] == 1
    assert api.get(T, headers=h, params={"independent": True}).json()["total"] == 0
    assert api.get(T, headers=h, params={"status": "In Progress"}).json()["total"] == 2
    assert api.get(T, headers=h, params={"priority": "Low"}).json()["total"] == 1
    assert api.get(T, headers=h, params={"due_from": str(TODAY), "due_to": str(TODAY)}).json()["total"] == 1
    assert set(titles(api.get(T, headers=as_("rahul"), params={"mine": True}))) == set()


def test_permission_flags(api, as_, task):
    def perms(who, title):
        return api.get(f"{T}/{task(title)}", headers=as_(who)).json()["permissions"]
    assert perms("mohammed", "API work") == {"can_update_status": True, "can_submit": True,
                                             "can_review": False, "can_manage": False,
                                             "can_comment": True}
    assert perms("mohammed", "Website UI")["can_submit"] is False          # completed
    assert perms("sana", "Design system")["can_update_status"] is False    # in review
    assert perms("neha", "Design system")["can_review"] is True
    assert perms("aisha", "Design system")["can_review"] is True
    assert perms("rahul", "API work")["can_manage"] is True
    assert perms("rahul", "API work")["can_review"] is False               # not in review


# ================================================================ create
def new_task(**extra):
    body = {"title": "Write docs", "start_date": str(TODAY),
            "due_date": str(TODAY + timedelta(days=2)), "estimated_hours": 6}
    body.update(extra)
    return body


def test_create_one_task_per_person(api, as_, db, people):
    r = api.post(T, headers=as_("rahul"),
                 json=new_task(assignee_ids=[people["mohammed"].id, people["priya"].id]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] == 2
    assert {t["assignee"]["full_name"] for t in body["tasks"]} == {"Mohammed Huzaifa", "Priya Nair"}
    t = body["tasks"][0]
    assert t["status"] == "Not Started" and t["priority"] == "Medium" and t["project"] is None
    assert t["assigned_by"]["full_name"] == "Rahul Verma"
    n = notes_for(db, people["priya"], "task_assigned")[-1]
    assert n.message == 'New task assigned: "Write docs"' and n.entity_type == "task"
    hist = db.scalars(select(TaskHistory).where(TaskHistory.task_id == t["id"])).all()
    assert [h.message for h in hist] == ["Created by Rahul Verma"]


def test_create_defaults_and_project(api, as_, db, people):
    pid = db.scalar(select(Project.id))
    r = api.post(T, headers=as_("rahul"), json={"title": "Quick fix", "project_id": pid,
                                                "assignee_ids": [people["rahul"].id]})
    assert r.status_code == 201
    t = r.json()["tasks"][0]
    assert t["start_date"] == t["due_date"] == str(TODAY) and t["estimated_hours"] == 4
    assert t["project"]["name"] == "Company Website"
    # Rahul assigned it to himself -> no notification to himself
    assert notes_for(db, people["rahul"], "task_assigned") == []


def test_create_rules(api, as_, people, db):
    h = as_("rahul")
    r = api.post(T, headers=h, json=new_task(assignee_ids=[people["sana"].id]))
    assert r.status_code == 422 and r.json()["code"] == "USER_NOT_FOUND"   # Sana hidden from Rahul
    r = api.post(T, headers=as_("aisha"), json=new_task(assignee_ids=[people["fatima"].id]))
    assert r.status_code == 403 and r.json()["code"] == "CANNOT_ASSIGN"
    people["priya"].is_active = False
    db.flush()
    r = api.post(T, headers=h, json=new_task(assignee_ids=[people["priya"].id]))
    assert r.status_code == 403 and "deactivated" in r.json()["detail"]
    r = api.post(T, headers=h, json=new_task(assignee_ids=[]))
    assert r.status_code == 422
    r = api.post(T, headers=h, json=new_task(assignee_ids=[people["mohammed"].id],
                                             due_date=str(TODAY - timedelta(days=1))))
    assert r.status_code == 422
    r = api.post(T, headers=h, json=new_task(assignee_ids=[people["mohammed"].id], estimated_hours=-1))
    assert r.status_code == 422
    r = api.post(T, headers=h, json=new_task(assignee_ids=[people["mohammed"].id], project_id=9999))
    assert r.status_code == 422 and r.json()["code"] == "PROJECT_NOT_FOUND"
    r = api.post(T, headers=as_("mohammed"), json=new_task(assignee_ids=[people["mohammed"].id]))
    assert r.status_code == 403 and r.json()["code"] == "ROLE_NOT_ALLOWED"
    # nothing was half-created
    assert db.scalar(select(Task).where(Task.title == "Write docs")) is None


def test_admin_can_assign_anyone_non_admin(api, as_, people):
    r = api.post(T, headers=as_("aisha"),
                 json=new_task(assignee_ids=[people["sana"].id, people["rahul"].id]))
    assert r.status_code == 201 and r.json()["created"] == 2


# ================================================================ assignee: status & submit
def test_assignee_updates_status(api, as_, task, db):
    tid = task("Testing")
    r = api.patch(f"{T}/{tid}/status", headers=as_("mohammed"), json={"status": "In Progress"})
    assert r.status_code == 200 and r.json()["status"] == "In Progress"
    assert r.json()["history"][0]["message"] == \
        "Status changed from Not Started to In Progress by Mohammed Huzaifa"
    assert r.json()["history"][0]["actor"]["full_name"] == "Mohammed Huzaifa"


def test_status_rules(api, as_, task):
    r = api.patch(f"{T}/{task('Testing')}/status", headers=as_("rahul"), json={"status": "On Hold"})
    assert r.status_code == 403 and r.json()["code"] == "NOT_YOUR_TASK"
    r = api.patch(f"{T}/{task('Testing')}/status", headers=as_("mohammed"), json={"status": "Completed"})
    assert r.status_code == 422
    r = api.patch(f"{T}/{task('Website UI')}/status", headers=as_("mohammed"), json={"status": "On Hold"})
    assert r.status_code == 409 and r.json()["code"] == "TASK_LOCKED"
    r = api.patch(f"{T}/{task('Design system')}/status", headers=as_("sana"), json={"status": "On Hold"})
    assert r.status_code == 409


def test_submit_notifies_assigner_and_department_leads(api, as_, task, db, people):
    r = api.post(f"{T}/{task('API work')}/submit", headers=as_("mohammed"))
    assert r.status_code == 200
    assert r.json()["status"] == "Submitted for Review" and r.json()["submitted_at"]
    n = notes_for(db, people["rahul"], "task_submitted")
    assert [x.message for x in n] == ['Mohammed Huzaifa submitted "API work" for review']
    assert notes_for(db, people["neha"], "task_submitted")[-1].message.startswith("Sana")  # seed only
    r = api.post(f"{T}/{task('API work')}/submit", headers=as_("mohammed"))
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_SUBMITTED"
    assert api.post(f"{T}/{task('Website UI')}/submit", headers=as_("mohammed")).status_code == 409
    assert api.post(f"{T}/{task('Backend')}/submit", headers=as_("rahul")).status_code == 403


def test_team_lead_own_task_review_goes_to_admins(api, as_, db, people):
    tid = api.post(T, headers=as_("rahul"), json=new_task(assignee_ids=[people["rahul"].id])).json()["tasks"][0]["id"]
    api.post(f"{T}/{tid}/submit", headers=as_("rahul"))
    assert notes_for(db, people["aisha"], "task_submitted")
    assert notes_for(db, people["fatima"], "task_submitted")
    # Rahul can't approve his own task, an admin can
    r = api.post(f"{T}/{tid}/approve", headers=as_("rahul"), json={"rating": 100})
    assert r.status_code == 403 and r.json()["code"] == "CANNOT_REVIEW_OWN_TASK"
    assert api.post(f"{T}/{tid}/approve", headers=as_("aisha"), json={}).json()["status"] == "Completed"


# ================================================================ review
def test_approve(api, as_, task, db, people):
    r = api.post(f"{T}/{task('Design system')}/approve", headers=as_("neha"), json={"rating": 92})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Completed" and body["rating"] == 92
    assert body["completed_on"] == str(TODAY) and body["is_overdue"] is False
    assert body["history"][0]["message"] == "Approved by Neha Kapoor (rating 92)"
    n = notes_for(db, people["sana"], "task_approved")[-1]
    assert n.message == 'Your task "Design system" was approved (rating 92)'


def test_approve_default_rating_and_rules(api, as_, task):
    tid = task("Design system")
    r = api.post(f"{T}/{tid}/approve", headers=as_("sana"), json={"rating": 100})
    assert r.status_code == 403 and r.json()["code"] == "CANNOT_REVIEW_OWN_TASK"
    assert api.post(f"{T}/{tid}/approve", headers=as_("rahul"), json={}).status_code == 404
    assert api.post(f"{T}/{tid}/approve", headers=as_("neha"), json={"rating": 101}).status_code == 422
    assert api.post(f"{T}/{tid}/approve", headers=as_("neha"), json={}).json()["rating"] == 85
    r = api.post(f"{T}/{tid}/approve", headers=as_("neha"), json={})
    assert r.status_code == 409 and r.json()["code"] == "TASK_NOT_IN_REVIEW"
    r = api.post(f"{T}/{task('API work')}/approve", headers=as_("rahul"), json={})
    assert r.status_code == 409


def test_request_changes(api, as_, task, db, people):
    tid = task("Design system")
    r = api.post(f"{T}/{tid}/request-changes", headers=as_("neha"), json={"reason": "  "})
    assert r.status_code == 422
    r = api.post(f"{T}/{tid}/request-changes", headers=as_("neha"),
                 json={"reason": "Use the brand colours"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "In Progress" and body["completed_on"] is None
    assert body["comments"][-1]["body"] == "Changes requested: Use the brand colours"
    assert body["comments"][-1]["author"]["full_name"] == "Neha Kapoor"
    assert body["history"][0]["message"] == "Changes requested by Neha Kapoor: Use the brand colours"
    assert notes_for(db, people["sana"], "task_rejected")[-1].message == \
        'Changes requested on "Design system": Use the brand colours'
    # Sana can work on it again and resubmit
    assert api.post(f"{T}/{tid}/submit", headers=as_("sana")).json()["status"] == "Submitted for Review"


# ================================================================ manager edits
def test_change_deadline(api, as_, task, db, people):
    tid = task("Database schema")
    new_due = TODAY + timedelta(days=5)
    r = api.put(f"{T}/{tid}/deadline", headers=as_("rahul"), json={"due_date": str(new_due)})
    assert r.status_code == 200 and r.json()["due_date"] == str(new_due)
    assert r.json()["is_overdue"] is False
    assert r.json()["history"][0]["message"].startswith("Deadline changed from")
    assert notes_for(db, people["priya"], "task_deadline_changed")
    r = api.put(f"{T}/{tid}/deadline", headers=as_("rahul"), json={"due_date": "2000-01-01"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_DATES"
    r = api.put(f"{T}/{tid}/deadline", headers=as_("priya"), json={"due_date": str(new_due)})
    assert r.status_code == 403 and r.json()["code"] == "CANNOT_MANAGE_TASK"


def test_reschedule_keeps_length(api, as_, task, db, people):
    tid = task("Backend")          # start 0, due +3
    new_start = TODAY + timedelta(days=10)
    r = api.put(f"{T}/{tid}/reschedule", headers=as_("rahul"), json={"start_date": str(new_start)})
    assert r.json()["start_date"] == str(new_start)
    assert r.json()["due_date"] == str(new_start + timedelta(days=3))
    n = notes_for(db, people["priya"], "task_rescheduled")[-1]
    assert n.message.startswith('Task rescheduled: "Backend" now starts')


def test_edit_details_and_reassign(api, as_, task, db, people):
    tid = task("Testing")
    r = api.patch(f"{T}/{tid}", headers=as_("rahul"),
                  json={"title": "Testing (e2e)", "estimated_hours": 8, "priority": "High",
                        "project_id": 0, "assignee_id": people["priya"].id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Testing (e2e)" and body["priority"] == "High" and body["project"] is None
    assert body["assignee"]["full_name"] == "Priya Nair"
    msgs = [h["message"] for h in body["history"]]
    assert "Edited (title, hours, priority, project) by Rahul Verma" in msgs
    assert "Reassigned from Mohammed Huzaifa to Priya Nair by Rahul Verma" in msgs
    assert notes_for(db, people["priya"], "task_assigned")[-1].message == 'New task assigned: "Testing (e2e)"'
    # Mohammed can no longer see it
    assert api.get(f"{T}/{tid}", headers=as_("mohammed")).status_code == 404


def test_edit_rules(api, as_, task, people):
    r = api.patch(f"{T}/{task('Testing')}", headers=as_("rahul"), json={"assignee_id": people["sana"].id})
    assert r.status_code == 422 and r.json()["code"] == "USER_NOT_FOUND"
    r = api.patch(f"{T}/{task('Website UI')}", headers=as_("rahul"), json={"assignee_id": people["priya"].id})
    assert r.status_code == 409 and r.json()["code"] == "TASK_COMPLETED"
    assert api.patch(f"{T}/{task('Testing')}", headers=as_("mohammed"), json={"title": "Mine now"}).status_code == 403
    # failed reassign didn't keep other changes
    r = api.patch(f"{T}/{task('Testing')}", headers=as_("rahul"),
                  json={"title": "Changed", "assignee_id": people["sana"].id})
    assert r.status_code == 422
    assert api.get(f"{T}/{task('Testing')}", headers=as_("rahul")).json()["title"] == "Testing"


def test_delete(api, as_, task, db):
    tid = task("Testing")
    api.post(f"{T}/{tid}/comments", headers=as_("mohammed"), json={"body": "Started"})
    assert api.delete(f"{T}/{tid}", headers=as_("mohammed")).status_code == 403
    assert api.delete(f"{T}/{task('Design system')}", headers=as_("rahul")).status_code == 404
    assert api.delete(f"{T}/{tid}", headers=as_("rahul")).status_code == 204
    assert api.get(f"{T}/{tid}", headers=as_("rahul")).status_code == 404
    assert db.scalars(select(TaskComment).where(TaskComment.task_id == tid)).all() == []


# ================================================================ comments & history
def test_comments(api, as_, task, db, people):
    tid = task("API work")
    r = api.post(f"{T}/{tid}/comments", headers=as_("mohammed"), json={"body": "  Halfway done  "})
    assert r.status_code == 201
    c = r.json()
    assert c["body"] == "Halfway done" and c["author"]["full_name"] == "Mohammed Huzaifa"
    assert c["can_delete"] is True
    # Rahul (assigned it) is notified, Mohammed (author) is not
    assert notes_for(db, people["rahul"], "task_comment")[-1].message == \
        'Mohammed Huzaifa commented on "API work"'
    assert notes_for(db, people["mohammed"], "task_comment") == []

    api.post(f"{T}/{tid}/comments", headers=as_("rahul"), json={"body": "Great"})
    comments = api.get(f"{T}/{tid}/comments", headers=as_("mohammed")).json()
    assert [x["body"] for x in comments] == ["Halfway done", "Great"]
    assert comments[1]["can_delete"] is False
    detail = api.get(f"{T}/{tid}", headers=as_("rahul")).json()
    assert detail["comment_count"] == 2
    assert api.post(f"{T}/{tid}/comments", headers=as_("mohammed"), json={"body": "   "}).status_code == 422
    assert api.post(f"{T}/{tid}/comments", headers=as_("neha"), json={"body": "hi"}).status_code == 404

    # delete: own comment ok, someone else's no, admin any
    rahul_c = comments[1]["id"]
    assert api.delete(f"{T}/{tid}/comments/{rahul_c}", headers=as_("mohammed")).status_code == 403
    assert api.delete(f"{T}/{tid}/comments/{rahul_c}", headers=as_("aisha")).status_code == 204
    assert api.delete(f"{T}/{tid}/comments/{rahul_c}", headers=as_("aisha")).status_code == 404


def test_history_newest_first(api, as_, task):
    tid = task("Website UI")
    hist = api.get(f"{T}/{tid}/history", headers=as_("mohammed")).json()
    assert [h["message"] for h in hist] == [
        "Approved by Rahul Verma (rating 85)",
        "Submitted for review by Mohammed Huzaifa",
        "Created by Rahul Verma",
    ]


def test_full_lifecycle(api, as_, people, db):
    """Create -> In Progress -> submit -> changes -> submit -> approve, like a real day."""
    tid = api.post(T, headers=as_("neha"),
                   json=new_task(assignee_ids=[people["sana"].id])).json()["tasks"][0]["id"]
    api.patch(f"{T}/{tid}/status", headers=as_("sana"), json={"status": "In Progress"})
    api.post(f"{T}/{tid}/submit", headers=as_("sana"))
    api.post(f"{T}/{tid}/request-changes", headers=as_("neha"), json={"reason": "Fix typos"})
    api.post(f"{T}/{tid}/submit", headers=as_("sana"))
    final = api.post(f"{T}/{tid}/approve", headers=as_("neha"), json={"rating": 90}).json()
    assert final["status"] == "Completed" and final["rating"] == 90
    assert len(final["history"]) == 6
    # Sana's stats on the Team page (Module 5) update automatically
    stats = api.get(f"{API}/users/{people['sana'].id}/stats", headers=as_("neha")).json()
    assert stats["done"] == 1 and stats["total"] == 2


def test_project_progress_updates(api, as_, task, db):
    pid = db.scalar(select(Project.id))
    api.post(f"{T}/{task('Design system')}/approve", headers=as_("neha"), json={})
    p = api.get(f"{API}/projects/{pid}", headers=as_("aisha")).json()
    assert p["progress"] == {"total": 6, "done": 2, "overdue": 1, "percent": 33}
