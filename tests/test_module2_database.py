"""Module 2 tests: tables, enum types, relationships and data-safety rules."""
from datetime import date, timedelta

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.models import (Department, DevicePushToken, LeaveRequest, Notification,
                        Project, RefreshToken, Task, TaskComment, TaskHistory, User)
from app.models.enums import (LeaveStatus, LeaveType, Platform, Priority,
                              TaskStatus, UserRole)
from app.utils.dates import utc_now
from tests.conftest import alembic_config

TODAY = date(2026, 11, 2)
EXPECTED_TABLES = {
    "alembic_version", "departments", "users", "projects", "project_members",
    "tasks", "task_comments", "task_history", "leave_requests", "notifications",
    "refresh_tokens", "device_push_tokens",
}


# ---------- small helpers ----------
def make_department(db, name="Engineering"):
    d = Department(name=name)
    db.add(d)
    db.flush()
    return d


def make_user(db, email, role=UserRole.EMPLOYEE, department=None, name="Test User"):
    u = User(full_name=name, email=email, hashed_password="not-a-real-hash",
             role=role, department_id=department.id if department else None)
    db.add(u)
    db.flush()
    return u


def make_task(db, assignee, **kw):
    t = Task(title=kw.pop("title", "A task"), assignee_id=assignee.id,
             start_date=kw.pop("start_date", TODAY), due_date=kw.pop("due_date", TODAY),
             estimated_hours=kw.pop("estimated_hours", 4), **kw)
    db.add(t)
    db.flush()
    return t


def expect_integrity_error(db, obj):
    """The database must REFUSE this row. Only this insert is undone."""
    savepoint = db.begin_nested()
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.flush()
    savepoint.rollback()


# ---------- structure ----------
def test_all_tables_exist(test_engine):
    assert set(inspect(test_engine).get_table_names()) == EXPECTED_TABLES


def test_enum_types_match_frontend(test_engine):
    sql = text("""SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
                  FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
                  GROUP BY t.typname""")
    with test_engine.connect() as conn:
        enums = {name: list(values) for name, values in conn.execute(sql)}
    assert enums["user_role"] == ["admin", "teamlead", "employee"]
    assert enums["task_status"] == ["Not Started", "In Progress", "Submitted for Review",
                                    "Completed", "Delayed", "On Hold"]
    assert enums["priority"] == ["High", "Medium", "Low"]
    assert enums["leave_type"] == ["Annual", "Sick", "Casual", "Unpaid"]
    assert enums["leave_status"] == ["Pending", "Approved", "Rejected", "Cancelled"]
    assert enums["platform"] == ["web", "android", "ios"]


def test_models_and_database_are_in_sync(test_engine, test_db_url):
    # Fails if a model was changed without creating a new migration.
    command.check(alembic_config(test_db_url))


# ---------- relationships (full round trip) ----------
def test_full_relationship_round_trip(db):
    eng = make_department(db)
    lead = make_user(db, "lead@company.com", UserRole.TEAMLEAD, eng, "Rahul Verma")
    emp = make_user(db, "emp@company.com", UserRole.EMPLOYEE, eng, "Priya Nair")

    proj = Project(name="Company Website", manager_id=lead.id, start_date=TODAY,
                   end_date=TODAY + timedelta(days=30), priority=Priority.HIGH,
                   created_by_id=lead.id)
    proj.members.append(emp)
    db.add(proj)
    db.flush()

    task = make_task(db, emp, project_id=proj.id, assigned_by_id=lead.id,
                     due_date=TODAY + timedelta(days=3))
    db.add_all([
        TaskComment(task_id=task.id, author_id=lead.id, body="Looks good"),
        TaskHistory(task_id=task.id, actor_id=lead.id, message="Created by Rahul Verma"),
        LeaveRequest(employee_id=emp.id, leave_type=LeaveType.ANNUAL, start_date=TODAY,
                     end_date=TODAY + timedelta(days=2), days=3, reason="Family trip."),
        Notification(recipient_id=emp.id, message="New task assigned: A task",
                     category="task_assigned", entity_type="task", entity_id=task.id),
        RefreshToken(user_id=emp.id, jti="abc123", platform=Platform.ANDROID,
                     device_name="Pixel 8", expires_at=utc_now() + timedelta(days=30)),
        DevicePushToken(user_id=emp.id, platform=Platform.IOS, push_token="push-xyz"),
    ])
    db.flush()
    db.expire_all()

    emp = db.get(User, emp.id)
    task = db.get(Task, task.id)
    assert emp.department.name == "Engineering"
    assert [p.name for p in emp.projects] == ["Company Website"]
    assert proj.manager.full_name == "Rahul Verma"
    assert task.project.name == "Company Website"
    assert task.assignee.email == "emp@company.com"
    assert task.assigned_by.full_name == "Rahul Verma"
    assert task.status == TaskStatus.NOT_STARTED            # default
    assert task.priority == Priority.MEDIUM                 # default
    assert task.comments[0].body == "Looks good"
    assert task.history[0].message.startswith("Created")
    assert emp.notifications[0].entity_id == task.id
    assert emp.refresh_tokens[0].platform == Platform.ANDROID
    assert emp.push_tokens[0].push_token == "push-xyz"
    assert emp.is_active is True and emp.designation == "Associate"
    assert emp.created_at is not None and emp.joined_on is not None

    leave = db.scalars(select(LeaveRequest).where(LeaveRequest.employee_id == emp.id)).one()
    assert leave.status == LeaveStatus.PENDING


def test_deleting_task_removes_comments_and_history(db):
    eng = make_department(db)
    emp = make_user(db, "e1@company.com", department=eng)
    task = make_task(db, emp)
    db.add_all([TaskComment(task_id=task.id, author_id=emp.id, body="hi"),
                TaskHistory(task_id=task.id, actor_id=emp.id, message="Created")])
    db.flush()
    task_id = task.id
    db.delete(task)
    db.flush()
    assert db.scalar(select(TaskComment).where(TaskComment.task_id == task_id)) is None
    assert db.scalar(select(TaskHistory).where(TaskHistory.task_id == task_id)) is None


# ---------- data-safety rules ----------
def test_email_unique_ignoring_case(db):
    eng = make_department(db)
    make_user(db, "aisha@company.com", department=eng)
    expect_integrity_error(db, User(full_name="X", email="AISHA@company.com",
                                    hashed_password="x", department_id=eng.id))


def test_department_name_unique_ignoring_case(db):
    make_department(db, "Design")
    expect_integrity_error(db, Department(name="design"))


def test_employee_must_have_department_but_admin_need_not(db):
    make_user(db, "admin@company.com", role=UserRole.ADMIN, department=None)  # allowed
    expect_integrity_error(db, User(full_name="X", email="nodept@company.com",
                                    hashed_password="x", role=UserRole.EMPLOYEE))


def test_task_due_date_cannot_be_before_start(db):
    emp = make_user(db, "e2@company.com", department=make_department(db))
    expect_integrity_error(db, Task(title="t", assignee_id=emp.id, start_date=TODAY,
                                    due_date=TODAY - timedelta(days=1)))


def test_task_rating_must_be_0_to_100(db):
    emp = make_user(db, "e3@company.com", department=make_department(db))
    expect_integrity_error(db, Task(title="t", assignee_id=emp.id, start_date=TODAY,
                                    due_date=TODAY, rating=101))


def test_task_hours_cannot_be_negative(db):
    emp = make_user(db, "e4@company.com", department=make_department(db))
    expect_integrity_error(db, Task(title="t", assignee_id=emp.id, start_date=TODAY,
                                    due_date=TODAY, estimated_hours=-1))


def test_completed_task_needs_completion_date(db):
    emp = make_user(db, "e5@company.com", department=make_department(db))
    expect_integrity_error(db, Task(title="t", assignee_id=emp.id, start_date=TODAY,
                                    due_date=TODAY, status=TaskStatus.COMPLETED))
    ok = make_task(db, emp, status=TaskStatus.COMPLETED, completed_on=TODAY, rating=85)
    assert ok.id is not None


def test_leave_end_cannot_be_before_start(db):
    emp = make_user(db, "e6@company.com", department=make_department(db))
    expect_integrity_error(db, LeaveRequest(employee_id=emp.id, leave_type=LeaveType.SICK,
                                            start_date=TODAY, end_date=TODAY - timedelta(days=1),
                                            days=1))


def test_project_end_cannot_be_before_start(db):
    eng = make_department(db)
    lead = make_user(db, "l2@company.com", UserRole.TEAMLEAD, eng)
    expect_integrity_error(db, Project(name="P", manager_id=lead.id, start_date=TODAY,
                                       end_date=TODAY - timedelta(days=1)))


def test_user_with_tasks_cannot_be_hard_deleted(db):
    # Users are deactivated, never deleted - the database enforces it.
    emp = make_user(db, "e7@company.com", department=make_department(db))
    make_task(db, emp)
    savepoint = db.begin_nested()
    db.delete(emp)
    with pytest.raises(IntegrityError):
        db.flush()
    savepoint.rollback()
