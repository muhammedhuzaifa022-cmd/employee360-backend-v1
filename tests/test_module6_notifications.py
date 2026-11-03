"""Module 6 tests: the Inbox (notifications) + the notify() helper."""
import pytest
from sqlalchemy import select

from app.models import Notification, User
from app.models.enums import NotificationCategory
from app.services import notification_service as svc
from scripts.seed import seed
from tests.factories import API, bearer, login

PW = {"aisha": "Admin@123", "fatima": "Admin@123", "rahul": "Lead@123", "neha": "Lead@123",
      "mohammed": "Employee@123", "priya": "Employee@123", "sana": "Employee@123"}
N = f"{API}/notifications"


@pytest.fixture()
def people(db):
    seed(db)
    return {u.email.split("@")[0]: u for u in db.scalars(select(User))}


@pytest.fixture()
def as_(api, people):
    cache = {}

    def headers(who):
        if who not in cache:
            r = login(api, f"{who}@company.com", PW[who])
            assert r.status_code == 200, r.text
            cache[who] = bearer(r.json()["access_token"])
        return cache[who]
    return headers


# ---------------- reading ----------------
def test_list_my_notifications_newest_first(api, as_):
    r = api.get(N, headers=as_("mohammed"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["unread_count"] == 1
    first, second = body["items"]
    assert first["message"] == 'New task assigned: "Testing"' and first["is_read"] is False
    assert first["category"] == "task_assigned" and first["entity_type"] == "task"
    assert second["is_read"] is True
    assert first["created_at"] > second["created_at"]
    assert "recipient_id" not in first


def test_everyone_sees_only_their_own(api, as_):
    counts = {w: api.get(N, headers=as_(w)).json()["total"] for w in PW}
    assert counts == {"aisha": 1, "fatima": 1, "rahul": 1, "neha": 1,
                      "mohammed": 2, "priya": 1, "sana": 0}
    # even admins can't see other people's Inbox
    msgs = [n["message"] for n in api.get(N, headers=as_("aisha")).json()["items"]]
    assert msgs == ["Mohammed Huzaifa requested Annual leave (3 days)"]


def test_empty_inbox(api, as_):
    body = api.get(N, headers=as_("sana")).json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0,
                    "unread_count": 0}


def test_filters_and_unread_count(api, as_):
    h = as_("mohammed")
    assert api.get(N, headers=h, params={"unread_only": True}).json()["total"] == 1
    assert api.get(N, headers=h, params={"category": "task_approved"}).json()["total"] == 1
    assert api.get(N, headers=h, params={"category": "nonsense"}).status_code == 422
    assert api.get(f"{N}/unread-count", headers=h).json() == {"unread_count": 1}


def test_requires_login(api, people):
    assert api.get(N).status_code == 401
    assert api.get(f"{N}/unread-count").status_code == 401


# ---------------- changing ----------------
def test_mark_one_read_and_unread(api, as_):
    h = as_("mohammed")
    nid = api.get(N, headers=h, params={"unread_only": True}).json()["items"][0]["id"]
    r = api.patch(f"{N}/{nid}", headers=h, json={"is_read": True})
    assert r.status_code == 200 and r.json()["is_read"] is True
    assert api.get(f"{N}/unread-count", headers=h).json()["unread_count"] == 0
    api.patch(f"{N}/{nid}", headers=h, json={"is_read": False})
    assert api.get(f"{N}/unread-count", headers=h).json()["unread_count"] == 1
    # empty body = mark as read
    assert api.patch(f"{N}/{nid}", headers=h, json={}).json()["is_read"] is True


def test_cannot_touch_someone_elses_notification(api, as_):
    nid = api.get(N, headers=as_("mohammed")).json()["items"][0]["id"]
    for method in ("patch", "delete"):
        kwargs = {"json": {"is_read": True}} if method == "patch" else {}
        r = getattr(api, method)(f"{N}/{nid}", headers=as_("aisha"), **kwargs)
        assert r.status_code == 404 and r.json()["code"] == "NOTIFICATION_NOT_FOUND"
    assert api.get(f"{N}/unread-count", headers=as_("mohammed")).json()["unread_count"] == 1


def test_mark_all_as_read_only_affects_me(api, as_):
    r = api.post(f"{N}/read-all", headers=as_("rahul"))
    assert r.json() == {"updated": 1}
    assert api.post(f"{N}/read-all", headers=as_("rahul")).json() == {"updated": 0}
    assert api.get(f"{N}/unread-count", headers=as_("aisha")).json()["unread_count"] == 1


def test_delete_one_and_clear_read(api, as_):
    h = as_("mohammed")
    items = api.get(N, headers=h).json()["items"]
    unread = next(i for i in items if not i["is_read"])
    assert api.delete(f"{N}/read", headers=h).json() == {"deleted": 1}  # the old read one
    assert api.get(N, headers=h).json()["total"] == 1
    assert api.delete(f"{N}/{unread['id']}", headers=h).status_code == 204
    assert api.get(N, headers=h).json()["total"] == 0
    assert api.delete(f"{N}/{unread['id']}", headers=h).status_code == 404


def test_pagination(api, as_, db, people):
    for i in range(25):
        svc.notify(db, [people["sana"]], f"Message {i}")
    db.commit()
    page = api.get(N, headers=as_("sana"), params={"page": 2, "page_size": 10}).json()
    assert page["total"] == 25 and page["pages"] == 3 and len(page["items"]) == 10
    assert page["unread_count"] == 25


# ---------------- the notify() helper ----------------
def test_notify_skips_actor_duplicates_and_inactive(db, people):
    p = people
    p["priya"].is_active = False
    db.flush()
    created = svc.notify(db, [p["mohammed"], p["mohammed"].id, p["rahul"], p["priya"]],
                         "  Hello team  ", category=NotificationCategory.TASK_COMMENT,
                         entity_type="task", entity_id=1, exclude_user_id=p["rahul"].id)
    assert [n.recipient_id for n in created] == [p["mohammed"].id]
    assert created[0].message == "Hello team" and created[0].category == "task_comment"
    assert svc.notify(db, [], "nobody") == []


def test_notify_does_not_commit(db, people):
    before = db.scalar(select(Notification).where(Notification.message == "Draft")) is None
    svc.notify(db, [people["sana"]], "Draft")
    db.rollback()  # caller's action failed -> notification disappears too
    assert before and db.scalar(select(Notification).where(Notification.message == "Draft")) is None


def test_notify_trims_very_long_messages(db, people):
    n = svc.notify(db, [people["sana"]], "x" * 900)[0]
    db.flush()
    assert len(n.message) == 500


def test_approvers_follow_department_rules(db, people):
    names = lambda who: {u.full_name for u in svc.approvers_for(db, people[who])}  # noqa: E731
    assert names("mohammed") == {"Rahul Verma", "Aisha Khan", "Fatima Sheikh"}
    assert names("sana") == {"Neha Kapoor", "Aisha Khan", "Fatima Sheikh"}
    assert names("rahul") == {"Aisha Khan", "Fatima Sheikh"}
    assert names("aisha") == {"Fatima Sheikh"}


def test_approvers_skip_inactive_people(db, people):
    people["rahul"].is_active = False
    db.flush()
    assert {u.full_name for u in svc.approvers_for(db, people["priya"])} == {
        "Aisha Khan", "Fatima Sheikh"}


# ---------------- account notifications (Module 5 hook) ----------------
def test_role_and_department_change_notify_the_person(api, as_, people):
    sana = people["sana"]
    r = api.patch(f"{API}/users/{sana.id}", headers=as_("aisha"),
                  json={"role": "teamlead", "department": "Engineering"})
    assert r.status_code == 200
    msgs = {n["message"]: n for n in api.get(N, headers=as_("sana")).json()["items"]}
    assert "Your role was changed to Team Lead by Aisha Khan" in msgs
    assert "You were moved to the Engineering department by Aisha Khan" in msgs
    assert all(n["category"] == "account" for n in msgs.values())


def test_name_only_edit_sends_nothing(api, as_, people):
    api.patch(f"{API}/users/{people['sana'].id}", headers=as_("aisha"), json={"full_name": "Sana A."})
    assert api.get(N, headers=as_("sana")).json()["total"] == 0


def test_meta_lists_notification_categories(api):
    cats = api.get(f"{API}/meta").json()["enums"]["notification_categories"]
    assert "task_assigned" in cats and "leave_requested" in cats and "account" in cats
