"""
Tasks logic - the heart of Employee360.

Life of a task (same as the frontend):
  Not Started / In Progress / On Hold / Delayed   (the assignee moves between these)
        |  assignee: "Submit for review"
        v
  Submitted for Review
        |  manager: "Approve" (rating 0-100)      -> Completed (completed_on = today)
        |  manager: "Request changes" (reason)    -> back to In Progress
Managers can also: edit details, reassign, change the deadline, reschedule, delete.

Every change writes a History line and (where useful) a Notification,
in the SAME database transaction as the change itself.
"""
from datetime import date

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models import Project, Task, TaskComment, TaskHistory, User
from app.models.enums import NotificationCategory, Priority, TaskStatus, UserRole
from app.schemas.task import (CommentOut, HistoryOut, TaskCreate, TaskDetail, TaskFilter,
                              TaskOut, TaskPermissions, TaskPerson, TaskUpdate)
from app.services import notification_service
from app.services import permissions as P
from app.utils.dates import company_today, fmt_date, utc_now
from app.utils.pagination import PageParams, paginate

LOCKED_FOR_ASSIGNEE = (TaskStatus.COMPLETED, TaskStatus.SUBMITTED)


# ================================================================ loading
def _load():
    return select(Task).options(
        selectinload(Task.assignee).selectinload(User.department),
        selectinload(Task.assigned_by).selectinload(User.department),
        selectinload(Task.project),
    )


def get_visible(db: Session, actor: User, task_id: int) -> Task:
    task = db.scalar(_load().where(Task.id == task_id))
    if task is None or not P.can_view_task(actor, task):
        raise NotFoundError("Task not found", code="TASK_NOT_FOUND")
    return task


def _permissions(actor: User, task: Task) -> TaskPermissions:
    mine = P.is_task_assignee(actor, task)
    open_for_me = mine and task.status not in LOCKED_FOR_ASSIGNEE
    return TaskPermissions(
        can_update_status=open_for_me,
        can_submit=open_for_me,
        can_review=task.status == TaskStatus.SUBMITTED and P.can_review_task(actor, task),
        can_manage=P.can_manage_task(actor, task),
        can_comment=True,  # anyone who can see a task may comment on it
    )


def _comment_counts(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(select(TaskComment.task_id, func.count())
                      .where(TaskComment.task_id.in_(ids)).group_by(TaskComment.task_id))
    return dict(rows.all())


def to_out(db: Session, actor: User, tasks: list[Task]) -> list[TaskOut]:
    today = company_today()
    counts = _comment_counts(db, [t.id for t in tasks])
    out = []
    for t in tasks:
        item = TaskOut.model_validate(t)
        done = t.status == TaskStatus.COMPLETED
        item.is_overdue = (not done) and t.due_date < today
        item.days_left = None if done else (t.due_date - today).days
        item.comment_count = counts.get(t.id, 0)
        item.permissions = _permissions(actor, t)
        out.append(item)
    return out


def to_detail(db: Session, actor: User, task: Task) -> TaskDetail:
    base = to_out(db, actor, [task])[0]
    comments = db.scalars(select(TaskComment)
                          .options(selectinload(TaskComment.author).selectinload(User.department))
                          .where(TaskComment.task_id == task.id)
                          .order_by(TaskComment.created_at, TaskComment.id)).all()
    history = db.scalars(select(TaskHistory)
                         .options(selectinload(TaskHistory.actor).selectinload(User.department))
                         .where(TaskHistory.task_id == task.id)
                         .order_by(TaskHistory.created_at.desc(), TaskHistory.id.desc())).all()
    return TaskDetail(
        **base.model_dump(),
        comments=[_comment_out(actor, c) for c in comments],
        history=[HistoryOut.model_validate(h) for h in history],
    )


def _comment_out(actor: User, c: TaskComment) -> CommentOut:
    return CommentOut(id=c.id, body=c.body, created_at=c.created_at,
                      author=TaskPerson.model_validate(c.author) if c.author else None,
                      can_delete=P.is_admin(actor) or c.author_id == actor.id)


# ================================================================ listing
def list_tasks(db: Session, actor: User, params: PageParams, *,
               filter: TaskFilter = TaskFilter.ALL, status: TaskStatus | None = None,
               priority: Priority | None = None, assignee_id: int | None = None,
               project_id: int | None = None, independent: bool = False, mine: bool = False,
               q: str | None = None, start_from: date | None = None, start_to: date | None = None,
               due_from: date | None = None, due_to: date | None = None
               ) -> tuple[list[TaskOut], int]:
    today = company_today()
    stmt = _load().where(P.visible_tasks_condition(actor))

    if filter == TaskFilter.OPEN:
        stmt = stmt.where(Task.status != TaskStatus.COMPLETED)
    elif filter == TaskFilter.OVERDUE:
        stmt = stmt.where(Task.status != TaskStatus.COMPLETED, Task.due_date < today)
    elif filter == TaskFilter.IN_REVIEW:
        stmt = stmt.where(Task.status == TaskStatus.SUBMITTED)
    elif filter == TaskFilter.COMPLETED:
        stmt = stmt.where(Task.status == TaskStatus.COMPLETED)

    if status is not None:
        stmt = stmt.where(Task.status == status)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if mine:
        stmt = stmt.where(Task.assignee_id == actor.id)
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if independent:
        stmt = stmt.where(Task.project_id.is_(None))
    elif project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if start_from:
        stmt = stmt.where(Task.start_date >= start_from)
    if start_to:
        stmt = stmt.where(Task.start_date <= start_to)
    if due_from:
        stmt = stmt.where(Task.due_date >= due_from)
    if due_to:
        stmt = stmt.where(Task.due_date <= due_to)
    if q and q.strip():
        # Frontend search: task title, assignee name, project name
        like = f"%{q.strip().lower()}%"
        Assignee = aliased(User)
        stmt = (stmt.join(Assignee, Assignee.id == Task.assignee_id)
                .outerjoin(Project, Project.id == Task.project_id)
                .where(or_(func.lower(Task.title).like(like),
                           func.lower(Assignee.full_name).like(like),
                           func.lower(Project.name).like(like))))

    # Same order as the frontend: earliest due date first
    stmt = stmt.order_by(Task.due_date, Task.id)
    tasks, total = paginate(db, stmt, params)
    return to_out(db, actor, tasks), total


# ================================================================ helpers
def _log(db: Session, task: Task, actor: User, message: str) -> None:
    db.add(TaskHistory(task_id=task.id, actor_id=actor.id, message=message[:500]))


def _notify(db: Session, actor: User, task: Task, recipients, message: str,
            category: NotificationCategory) -> None:
    notification_service.notify(db, recipients, message, category=category, entity_type="task",
                                entity_id=task.id, exclude_user_id=actor.id)


def _check_project(db: Session, actor: User, project_id: int | None) -> Project | None:
    if not project_id:
        return None
    project = db.scalar(select(Project).options(selectinload(Project.members))
                        .where(Project.id == project_id))
    if project is None or not P.can_view_project(actor, project):
        raise ValidationAppError("Project not found", code="PROJECT_NOT_FOUND",
                                 fields={"project_id": "Unknown project"})
    return project


def _check_assignee(db: Session, actor: User, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None or not P.can_view_user(actor, target):
        raise ValidationAppError("Person not found", code="USER_NOT_FOUND",
                                 fields={"assignee_ids": f"Unknown user id {user_id}"})
    if not P.can_assign_task_to(actor, target):
        if not target.is_active:
            msg = f"{target.full_name} is deactivated"
        elif target.role == UserRole.ADMIN:
            msg = "Tasks cannot be assigned to admins"
        else:
            msg = f"You cannot assign tasks to {target.full_name}"
        raise ForbiddenError(msg, code="CANNOT_ASSIGN", fields={"assignee_ids": msg})
    return target


def _require_manage(actor: User, task: Task) -> None:
    if not P.can_manage_task(actor, task):
        raise ForbiddenError("Only an admin or this employee's team lead can do this",
                             code="CANNOT_MANAGE_TASK")


def _require_assignee(actor: User, task: Task) -> None:
    if not P.is_task_assignee(actor, task):
        raise ForbiddenError("Only the person this task is assigned to can do this",
                             code="NOT_YOUR_TASK")


def _require_review(actor: User, task: Task) -> None:
    if P.is_task_assignee(actor, task):
        raise ForbiddenError("You cannot review your own task", code="CANNOT_REVIEW_OWN_TASK")
    if not P.can_review_task(actor, task):
        raise ForbiddenError("Only an admin or this employee's team lead can review it",
                             code="CANNOT_REVIEW")
    if task.status != TaskStatus.SUBMITTED:
        raise ConflictError("This task is not waiting for review", code="TASK_NOT_IN_REVIEW")


def _reviewers(db: Session, task: Task) -> list[int]:
    """Who hears about "submitted for review": the assigner + the assignee's team leads.
    If nobody is left (e.g. a team lead assigned a task to themselves) -> all admins."""
    assignee = task.assignee
    ids = [task.assigned_by_id] if task.assigned_by_id else []
    if assignee.role == UserRole.EMPLOYEE and assignee.department_id is not None:
        ids += db.scalars(select(User.id).where(User.role == UserRole.TEAMLEAD,
                                                User.department_id == assignee.department_id,
                                                User.is_active.is_(True))).all()
    ids = [i for i in ids if i != assignee.id]
    active = set(db.scalars(select(User.id).where(User.id.in_(ids), User.is_active.is_(True))))
    ids = [i for i in ids if i in active]
    if not ids:
        ids = list(db.scalars(select(User.id).where(User.role == UserRole.ADMIN,
                                                    User.is_active.is_(True),
                                                    User.id != assignee.id)))
    return ids


def _reload(db: Session, actor: User, task_id: int) -> Task:
    db.expire_all()
    return get_visible(db, actor, task_id)


# ================================================================ create
def create_tasks(db: Session, actor: User, body: TaskCreate) -> list[Task]:
    if not P.is_manager(actor):
        raise ForbiddenError("Only admins and team leads can create tasks",
                             code="ROLE_NOT_ALLOWED")
    project = _check_project(db, actor, body.project_id)
    assignees = [_check_assignee(db, actor, uid) for uid in body.assignee_ids]
    start = body.start_date or company_today()
    due = body.due_date or start
    if due < start:
        raise ValidationAppError("Due date must be on or after the start date",
                                 code="INVALID_DATES", fields={"due_date": "Before start date"})

    created = []
    for person in assignees:
        task = Task(title=body.title, description=body.description, assignee_id=person.id,
                    assigned_by_id=actor.id, project_id=project.id if project else None,
                    start_date=start, due_date=due, estimated_hours=body.estimated_hours,
                    priority=body.priority, status=TaskStatus.NOT_STARTED)
        db.add(task)
        db.flush()
        _log(db, task, actor, f"Created by {actor.full_name}")
        _notify(db, actor, task, [person], f'New task assigned: "{task.title}"',
                NotificationCategory.TASK_ASSIGNED)
        created.append(task.id)
    db.commit()
    return list(db.scalars(_load().where(Task.id.in_(created)).order_by(Task.id)))


# ================================================================ edit (managers)
def update_task(db: Session, actor: User, task_id: int, body: TaskUpdate) -> Task:
    task = get_visible(db, actor, task_id)
    _require_manage(actor, task)
    changes = body.model_dump(exclude_unset=True)
    edited = []

    for field, label in (("title", "title"), ("description", "description"),
                         ("estimated_hours", "hours"), ("priority", "priority")):
        new = changes.get(field)
        if new is not None and new != getattr(task, field):
            setattr(task, field, new)
            edited.append(label)

    if "project_id" in changes and changes["project_id"] is not None:
        new_pid = changes["project_id"] or None   # 0 -> Independent
        if new_pid != task.project_id:
            project = _check_project(db, actor, new_pid)
            task.project_id = project.id if project else None
            edited.append("project")

    if edited:
        _log(db, task, actor, f"Edited ({', '.join(edited)}) by {actor.full_name}")

    new_assignee_id = changes.get("assignee_id")
    if new_assignee_id is not None and new_assignee_id != task.assignee_id:
        if task.status == TaskStatus.COMPLETED:
            db.rollback()
            raise ConflictError("A completed task cannot be reassigned", code="TASK_COMPLETED")
        try:
            new_person = _check_assignee(db, actor, new_assignee_id)
        except Exception:
            db.rollback()
            raise
        old_name = task.assignee.full_name
        task.assignee_id = new_person.id
        _log(db, task, actor, f"Reassigned from {old_name} to {new_person.full_name} "
                              f"by {actor.full_name}")
        _notify(db, actor, task, [new_person], f'New task assigned: "{task.title}"',
                NotificationCategory.TASK_ASSIGNED)

    db.commit()
    return _reload(db, actor, task.id)


def change_deadline(db: Session, actor: User, task_id: int, new_due: date) -> Task:
    task = get_visible(db, actor, task_id)
    _require_manage(actor, task)
    if new_due < task.start_date:
        raise ValidationAppError("Due date must be on or after the start date",
                                 code="INVALID_DATES", fields={"due_date": "Before start date"})
    if new_due != task.due_date:
        old = task.due_date
        task.due_date = new_due
        _log(db, task, actor, f"Deadline changed from {fmt_date(old)} to {fmt_date(new_due)} "
                              f"by {actor.full_name}")
        _notify(db, actor, task, [task.assignee_id],
                f'Deadline changed for "{task.title}": now due {fmt_date(new_due)}',
                NotificationCategory.TASK_DEADLINE_CHANGED)
        db.commit()
    return _reload(db, actor, task.id)


def reschedule(db: Session, actor: User, task_id: int, new_start: date) -> Task:
    """Calendar drag & drop: keep the task's length, move both dates."""
    task = get_visible(db, actor, task_id)
    _require_manage(actor, task)
    if new_start != task.start_date:
        length = task.due_date - task.start_date
        task.start_date, task.due_date = new_start, new_start + length
        _log(db, task, actor, f"Rescheduled to {fmt_date(new_start)} by {actor.full_name}")
        _notify(db, actor, task, [task.assignee_id],
                f'Task rescheduled: "{task.title}" now starts {fmt_date(new_start)}',
                NotificationCategory.TASK_RESCHEDULED)
        db.commit()
    return _reload(db, actor, task.id)


def delete_task(db: Session, actor: User, task_id: int) -> None:
    task = get_visible(db, actor, task_id)
    _require_manage(actor, task)
    db.delete(task)  # comments and history are deleted with it
    db.commit()


# ================================================================ assignee actions
def set_status(db: Session, actor: User, task_id: int, new_status: TaskStatus) -> Task:
    task = get_visible(db, actor, task_id)
    _require_assignee(actor, task)
    if task.status in LOCKED_FOR_ASSIGNEE:
        raise ConflictError(f"The task is '{task.status.value}' and its status can't be changed "
                            "now", code="TASK_LOCKED")
    if new_status != task.status:
        old = task.status
        task.status = new_status
        _log(db, task, actor, f"Status changed from {old.value} to {new_status.value} "
                              f"by {actor.full_name}")
        db.commit()
    return _reload(db, actor, task.id)


def submit_for_review(db: Session, actor: User, task_id: int) -> Task:
    task = get_visible(db, actor, task_id)
    _require_assignee(actor, task)
    if task.status == TaskStatus.COMPLETED:
        raise ConflictError("This task is already completed", code="TASK_COMPLETED")
    if task.status == TaskStatus.SUBMITTED:
        raise ConflictError("This task is already waiting for review", code="ALREADY_SUBMITTED")
    task.status = TaskStatus.SUBMITTED
    task.submitted_at = utc_now()
    _log(db, task, actor, f"Submitted for review by {actor.full_name}")
    _notify(db, actor, task, _reviewers(db, task),
            f'{actor.full_name} submitted "{task.title}" for review',
            NotificationCategory.TASK_SUBMITTED)
    db.commit()
    return _reload(db, actor, task.id)


# ================================================================ review (managers)
def approve(db: Session, actor: User, task_id: int, rating: int) -> Task:
    task = get_visible(db, actor, task_id)
    _require_review(actor, task)
    task.status = TaskStatus.COMPLETED
    task.completed_on = company_today()
    task.rating = rating
    _log(db, task, actor, f"Approved by {actor.full_name} (rating {rating})")
    _notify(db, actor, task, [task.assignee_id],
            f'Your task "{task.title}" was approved (rating {rating})',
            NotificationCategory.TASK_APPROVED)
    db.commit()
    return _reload(db, actor, task.id)


def request_changes(db: Session, actor: User, task_id: int, reason: str) -> Task:
    task = get_visible(db, actor, task_id)
    _require_review(actor, task)
    task.status = TaskStatus.IN_PROGRESS
    task.completed_on = None
    task.rating = None
    db.add(TaskComment(task_id=task.id, author_id=actor.id, body=f"Changes requested: {reason}"))
    _log(db, task, actor, f"Changes requested by {actor.full_name}: {reason}")
    _notify(db, actor, task, [task.assignee_id],
            f'Changes requested on "{task.title}": {reason}',
            NotificationCategory.TASK_REJECTED)
    db.commit()
    return _reload(db, actor, task.id)


# ================================================================ comments & history
def add_comment(db: Session, actor: User, task_id: int, body: str) -> CommentOut:
    task = get_visible(db, actor, task_id)
    comment = TaskComment(task_id=task.id, author_id=actor.id, body=body)
    db.add(comment)
    _log(db, task, actor, f"Comment added by {actor.full_name}")
    people = [task.assignee_id] + ([task.assigned_by_id] if task.assigned_by_id else [])
    _notify(db, actor, task, people,
            f'{actor.full_name} commented on "{task.title}"', NotificationCategory.TASK_COMMENT)
    db.commit()
    db.refresh(comment)
    return _comment_out(actor, db.scalar(
        select(TaskComment).options(selectinload(TaskComment.author).selectinload(User.department))
        .where(TaskComment.id == comment.id)))


def list_comments(db: Session, actor: User, task_id: int) -> list[CommentOut]:
    return to_detail(db, actor, get_visible(db, actor, task_id)).comments


def delete_comment(db: Session, actor: User, task_id: int, comment_id: int) -> None:
    task = get_visible(db, actor, task_id)
    comment = db.get(TaskComment, comment_id)
    if comment is None or comment.task_id != task.id:
        raise NotFoundError("Comment not found", code="COMMENT_NOT_FOUND")
    if not (P.is_admin(actor) or comment.author_id == actor.id):
        raise ForbiddenError("You can only delete your own comments", code="NOT_YOUR_COMMENT")
    db.delete(comment)
    db.commit()


def list_history(db: Session, actor: User, task_id: int) -> list[HistoryOut]:
    return to_detail(db, actor, get_visible(db, actor, task_id)).history


# ================================================================ small numbers for pages
def counts_for_chips(db: Session, actor: User) -> dict[str, int]:
    """Numbers for the filter chips: all / open / overdue / in_review / completed."""
    today = company_today()
    not_done = Task.status != TaskStatus.COMPLETED
    row = db.execute(select(
        func.count(),
        func.count(case((not_done, 1))),
        func.count(case((not_done & (Task.due_date < today), 1))),
        func.count(case((Task.status == TaskStatus.SUBMITTED, 1))),
        func.count(case((Task.status == TaskStatus.COMPLETED, 1))),
    ).where(P.visible_tasks_condition(actor))).one()
    return dict(zip(("all", "open", "overdue", "in_review", "completed"), row))
