"""Module 4 tests: the demo data is correct, consistent with the rules, and safe to re-run."""
from datetime import date, timedelta

from sqlalchemy import func, select

from app.models import (Department, LeaveRequest, Notification, Project, Task,
                        TaskHistory, User)
from app.models.enums import LeaveStatus, TaskStatus, UserRole
from app.services import permissions as P
from scripts.seed import PASSWORDS, seed
from tests.factories import API, bearer, login

TODAY = date(2026, 11, 2)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def by_email(db, email):
    return db.scalar(select(User).where(User.email == email))


def test_seed_creates_the_demo_company(db):
    r = seed(db, today=TODAY)
    assert r.demo_data_created
    assert count(db, Department) == 3
    assert count(db, User) == 7
    assert count(db, Project) == 1
    assert count(db, Task) == 6
    assert count(db, LeaveRequest) == 2
    assert count(db, Notification) == 7
    assert count(db, TaskHistory) >= 6

    roles = {u.email: u.role for u in db.scalars(select(User))}
    assert roles["aisha@company.com"] == UserRole.ADMIN
    assert roles["rahul@company.com"] == UserRole.TEAMLEAD
    assert roles["neha@company.com"] == UserRole.TEAMLEAD
    assert roles["mohammed@company.com"] == UserRole.EMPLOYEE


def test_tasks_match_the_frontend_demo(db):
    seed(db, today=TODAY)
    tasks = {t.title: t for t in db.scalars(select(Task))}
    d = lambda n: TODAY + timedelta(days=n)  # noqa: E731

    ui = tasks["Website UI"]
    assert ui.status == TaskStatus.COMPLETED and ui.completed_on == d(-4) and ui.rating == 85
    assert (ui.start_date, ui.due_date, ui.estimated_hours) == (d(-6), d(-4), 8)
    assert tasks["Database schema"].status == TaskStatus.DELAYED
    assert tasks["Design system"].status == TaskStatus.SUBMITTED
    assert tasks["Design system"].due_date == TODAY
    assert tasks["Testing"].start_date == d(2) and tasks["Testing"].priority.value == "Low"
    assert all(t.project.name == "Company Website" for t in tasks.values())


def test_every_demo_record_respects_the_permission_rules(db):
    seed(db, today=TODAY)
    for task in db.scalars(select(Task)):
        assert P.can_assign_task_to(task.assigned_by, task.assignee), task.title
    for leave in db.scalars(select(LeaveRequest).where(LeaveRequest.decided_by_id.is_not(None))):
        assert P.can_decide_leave(leave.decided_by, leave.employee)


def test_leave_and_notifications(db):
    seed(db, today=TODAY)
    pending = db.scalar(select(LeaveRequest).where(LeaveRequest.status == LeaveStatus.PENDING))
    assert pending.employee.full_name == "Mohammed Huzaifa" and pending.days == 3
    approved = db.scalar(select(LeaveRequest).where(LeaveRequest.status == LeaveStatus.APPROVED))
    assert approved.decided_by.full_name == "Rahul Verma"

    # The pending leave notified Rahul (Engineering lead) and both admins - NOT Neha (Design)
    leave_notes = db.scalars(select(Notification).where(Notification.category == "leave_requested"))
    recipients = {n.recipient.email for n in leave_notes}
    assert recipients == {"rahul@company.com", "aisha@company.com", "fatima@company.com"}


def test_running_seed_twice_adds_nothing(db):
    seed(db, today=TODAY)
    before = {m.__name__: count(db, m) for m in (Department, User, Project, Task,
                                                 LeaveRequest, Notification, TaskHistory)}
    r = seed(db, today=TODAY + timedelta(days=5))  # even on another day
    after = {m.__name__: count(db, m) for m in (Department, User, Project, Task,
                                                LeaveRequest, Notification, TaskHistory)}
    assert before == after
    assert not r.demo_data_created and r.users_created == [] and len(r.users_kept) == 7


def test_existing_admin_password_is_kept(api, db):
    from tests.factories import user
    user(db, "aisha@company.com", UserRole.ADMIN, "Management", password="MyOwnPass9")
    r = seed(db, today=TODAY)
    assert "aisha@company.com" in r.users_kept
    assert login(api, "aisha@company.com", "MyOwnPass9").status_code == 200
    assert login(api, "aisha@company.com", PASSWORDS[UserRole.ADMIN]).status_code == 401


def test_every_seeded_user_can_log_in(api, db):
    seed(db, today=TODAY)
    for u in db.scalars(select(User)):
        r = login(api, u.email, PASSWORDS[u.role])
        assert r.status_code == 200, u.email
        me = api.get(f"{API}/auth/me", headers=bearer(r.json()["access_token"])).json()
        assert me["role"] == u.role.value and me["department"]["name"]


def test_passwords_are_hashed(db):
    seed(db, today=TODAY)
    for u in db.scalars(select(User)):
        assert u.hashed_password.startswith("$argon2id$")
        assert PASSWORDS[u.role] not in u.hashed_password
