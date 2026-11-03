"""
Fill the database with the Employee360 demo company.

The data matches the frontend's built-in demo (same people, project,
tasks and leave), adjusted for the department rules:
  * Design gets its own team lead (Neha Kapoor), because a team lead may
    only manage their own department. She assigns and reviews Sana's work.
  * A second admin (Fatima Sheikh) exists, so an admin's leave can be
    approved by another admin.

Dates are relative to TODAY (company time zone), like the frontend.

SAFE TO RUN MORE THAN ONCE:
  * Departments and users are matched by name/email. Existing users are
    NOT changed (their passwords are kept).
  * Project, tasks, leave and notifications are only created the first
    time (when the "Company Website" project does not exist yet).

Usage (from the project folder):
    python -m scripts.seed            # add demo data
    python -m scripts.seed --reset    # ERASE ALL DATA, then add demo data
"""
import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (Department, LeaveRequest, Notification, Project, Task,
                        TaskHistory, User)
from app.models.enums import LeaveStatus, LeaveType, Priority, TaskStatus, UserRole
from app.utils.dates import company_today

# ------------------------------------------------------------------
# Demo accounts (FOR TESTING ONLY - change or delete before going live)
# ------------------------------------------------------------------
PASSWORDS = {
    UserRole.ADMIN: "Admin@123",
    UserRole.TEAMLEAD: "Lead@123",
    UserRole.EMPLOYEE: "Employee@123",
}
DESIGNATIONS = {
    UserRole.ADMIN: "Administrator",
    UserRole.TEAMLEAD: "Team Lead",
    UserRole.EMPLOYEE: "Associate",
}
JOINED_ON = date(2025, 1, 6)

# key, full name, email, department, role
USERS = [
    ("aisha",    "Aisha Khan",       "aisha@company.com",    "Management",  UserRole.ADMIN),
    ("fatima",   "Fatima Sheikh",    "fatima@company.com",   "Management",  UserRole.ADMIN),
    ("rahul",    "Rahul Verma",      "rahul@company.com",    "Engineering", UserRole.TEAMLEAD),
    ("neha",     "Neha Kapoor",      "neha@company.com",     "Design",      UserRole.TEAMLEAD),
    ("mohammed", "Mohammed Huzaifa", "mohammed@company.com", "Engineering", UserRole.EMPLOYEE),
    ("priya",    "Priya Nair",       "priya@company.com",    "Engineering", UserRole.EMPLOYEE),
    ("sana",     "Sana Ali",         "sana@company.com",     "Design",      UserRole.EMPLOYEE),
]

PROJECT_NAME = "Company Website"

# title, assignee, assigned by, status, start offset, due offset, hours, priority
TASKS = [
    ("Website UI",      "mohammed", "rahul", TaskStatus.COMPLETED,   -6, -4,  8, Priority.HIGH),
    ("API work",        "mohammed", "rahul", TaskStatus.IN_PROGRESS, -1,  2, 10, Priority.MEDIUM),
    ("Database schema", "priya",    "rahul", TaskStatus.DELAYED,     -8, -2, 12, Priority.HIGH),
    ("Backend",         "priya",    "rahul", TaskStatus.IN_PROGRESS,  0,  3, 16, Priority.MEDIUM),
    ("Design system",   "sana",     "neha",  TaskStatus.SUBMITTED,   -4,  0, 10, Priority.MEDIUM),
    ("Testing",         "mohammed", "rahul", TaskStatus.NOT_STARTED,  2,  4,  6, Priority.LOW),
]
DEFAULT_RATING = 85


@dataclass
class SeedReport:
    departments_created: int = 0
    users_created: list[str] = field(default_factory=list)
    users_kept: list[str] = field(default_factory=list)
    demo_data_created: bool = False
    tasks: int = 0
    leaves: int = 0
    notifications: int = 0


# ------------------------------------------------------------------
def _at(day: date, hour: int = 10) -> datetime:
    """A moment on `day` in the company time zone (stored as UTC)."""
    return datetime.combine(day, time(hour, 0), tzinfo=settings.tz)


def _get_or_create_department(db: Session, name: str, report: SeedReport) -> Department:
    dept = db.scalar(select(Department).where(func.lower(Department.name) == name.lower()))
    if dept is None:
        dept = Department(name=name)
        db.add(dept)
        db.flush()
        report.departments_created += 1
    return dept


def _get_or_create_user(db: Session, full_name: str, email: str, dept: Department,
                        role: UserRole, report: SeedReport, hashes: dict) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is not None:
        report.users_kept.append(email)
        return user
    if role not in hashes:
        hashes[role] = hash_password(PASSWORDS[role])
    user = User(full_name=full_name, email=email, hashed_password=hashes[role], role=role,
                designation=DESIGNATIONS[role], department_id=dept.id, joined_on=JOINED_ON)
    db.add(user)
    db.flush()
    report.users_created.append(email)
    return user


def _notify(db: Session, recipient: User, message: str, category: str,
            entity_type: str, entity_id: int, when: datetime, read: bool = False) -> None:
    db.add(Notification(recipient_id=recipient.id, message=message, category=category,
                        entity_type=entity_type, entity_id=entity_id, is_read=read,
                        created_at=when))


def seed(db: Session, today: date | None = None) -> SeedReport:
    today = today or company_today()
    d = lambda offset: today + timedelta(days=offset)  # noqa: E731
    report = SeedReport()
    hashes: dict = {}

    # ---- departments & users (always checked) ----
    users: dict[str, User] = {}
    for key, name, email, dept_name, role in USERS:
        dept = _get_or_create_department(db, dept_name, report)
        users[key] = _get_or_create_user(db, name, email, dept, role, report, hashes)

    # ---- demo project, tasks, leave, notifications (first time only) ----
    if db.scalar(select(Project).where(Project.name == PROJECT_NAME)) is not None:
        db.commit()
        return report

    rahul, neha = users["rahul"], users["neha"]
    project = Project(name=PROJECT_NAME, description="Public site rebuild", manager_id=rahul.id,
                      start_date=d(-20), end_date=d(30), priority=Priority.HIGH,
                      created_by_id=rahul.id)
    project.members.extend([users["mohammed"], users["priya"], users["sana"]])
    db.add(project)
    db.flush()

    tasks: dict[str, Task] = {}
    for title, who, by, status, s, due, hours, prio in TASKS:
        assignee, assigner = users[who], users[by]
        done = status == TaskStatus.COMPLETED
        task = Task(title=title, description="", assignee_id=assignee.id,
                    assigned_by_id=assigner.id, project_id=project.id,
                    start_date=d(s), due_date=d(due), estimated_hours=hours, priority=prio,
                    status=status,
                    completed_on=d(due) if done else None,
                    rating=DEFAULT_RATING if done else None,
                    submitted_at=_at(d(due - 1)) if status in (TaskStatus.SUBMITTED, TaskStatus.COMPLETED) else None)
        db.add(task)
        db.flush()
        tasks[title] = task

        history = [(assigner, f"Created by {assigner.full_name}", _at(d(min(s, 0) - 1), 9))]
        if status in (TaskStatus.SUBMITTED, TaskStatus.COMPLETED):
            history.append((assignee, f"Submitted for review by {assignee.full_name}", _at(d(due - 1), 17)))
        if done:
            history.append((assigner, f"Approved by {assigner.full_name} (rating {DEFAULT_RATING})", _at(d(due), 11)))
        if status in (TaskStatus.IN_PROGRESS, TaskStatus.DELAYED):
            history.append((assignee, f"Status changed to {status.value}", _at(d(min(s, 0) - 1), 15)))
        for actor, message, when in history:
            db.add(TaskHistory(task_id=task.id, actor_id=actor.id, message=message, created_at=when))
        report.tasks += 1

    # Leave l1: Mohammed, Annual, pending.  Leave l2: Priya, Sick, approved by Rahul.
    l1 = LeaveRequest(employee_id=users["mohammed"].id, leave_type=LeaveType.ANNUAL,
                      start_date=d(7), end_date=d(9), days=3, reason="Family trip.",
                      status=LeaveStatus.PENDING, created_at=_at(d(-1)))
    l2 = LeaveRequest(employee_id=users["priya"].id, leave_type=LeaveType.SICK,
                      start_date=d(-3), end_date=d(-2), days=2, reason="Flu, doctor advised rest.",
                      status=LeaveStatus.APPROVED, decided_by_id=rahul.id,
                      decided_at=_at(d(-3), 11), created_at=_at(d(-4)))
    db.add_all([l1, l2])
    db.flush()
    report.leaves = 2

    # Notifications - same messages and recipients the real modules will produce.
    notes = [
        (users["mohammed"], 'New task assigned: "Testing"', "task_assigned", "task",
         tasks["Testing"].id, _at(d(-1), 9), False),
        (users["mohammed"], 'Your task "Website UI" was approved (rating 85)', "task_approved",
         "task", tasks["Website UI"].id, _at(d(-4), 11), True),
        (neha, 'Sana Ali submitted "Design system" for review', "task_submitted", "task",
         tasks["Design system"].id, _at(d(-1), 17), False),
        (users["priya"], "Your Sick leave request was approved", "leave_approved", "leave",
         l2.id, _at(d(-3), 11), True),
    ]
    # Employee leave -> team leads of that department + all admins
    for approver in (rahul, users["aisha"], users["fatima"]):
        notes.append((approver, "Mohammed Huzaifa requested Annual leave (3 days)",
                      "leave_requested", "leave", l1.id, _at(d(-1)), False))
    for args in notes:
        _notify(db, *args)
    report.notifications = len(notes)

    report.demo_data_created = True
    db.commit()
    return report


def reset_all_data(db: Session) -> None:
    """Delete EVERY row from every app table (keeps the tables themselves)."""
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    db.commit()


# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Employee360 demo data")
    parser.add_argument("--reset", action="store_true",
                        help="ERASE ALL DATA first (development only)")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    if args.reset:
        if settings.is_production:
            sys.exit("Refusing to --reset when APP_ENV=production")
        if not args.yes:
            answer = input("This ERASES ALL DATA in the database. Type YES to continue: ")
            if answer.strip() != "YES":
                sys.exit("Cancelled.")

    with SessionLocal() as db:
        if args.reset:
            reset_all_data(db)
            print("All data erased.")
        r = seed(db)

    print(f"Departments created : {r.departments_created}")
    print(f"Users created       : {len(r.users_created)}")
    for email in r.users_created:
        print(f"    + {email}")
    if r.users_kept:
        print(f"Users already there : {len(r.users_kept)} (left unchanged, passwords kept)")
        for email in r.users_kept:
            print(f"    = {email}")
    if r.demo_data_created:
        print(f"Demo data created   : 1 project, {r.tasks} tasks, {r.leaves} leave requests, "
              f"{r.notifications} notifications")
    else:
        print("Demo data           : already present - nothing added")

    print("\nTest logins (new users only):")
    for role, pw in PASSWORDS.items():
        print(f"    {role.value:<9} password: {pw}")


if __name__ == "__main__":
    main()
