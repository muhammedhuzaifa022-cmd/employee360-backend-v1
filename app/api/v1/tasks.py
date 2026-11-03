"""
Tasks endpoints (Tasks page, task-details window, Home page lists).

Reading
  GET    /tasks                          list + filters (chips, search, person, project, dates)
  GET    /tasks/counts                   numbers for the filter chips
  GET    /tasks/{id}                     details + comments + history
  GET    /tasks/{id}/comments            comments only
  GET    /tasks/{id}/history             history only
Managers (admin / the employee's team lead)
  POST   /tasks                          create - one task per selected person
  PATCH  /tasks/{id}                     edit details / reassign
  PUT    /tasks/{id}/deadline            change due date
  PUT    /tasks/{id}/reschedule          move start date (calendar drag & drop)
  POST   /tasks/{id}/approve             approve with rating -> Completed
  POST   /tasks/{id}/request-changes     send back with a reason -> In Progress
  DELETE /tasks/{id}                     delete
Assignee
  PATCH  /tasks/{id}/status              Not Started / In Progress / On Hold / Delayed
  POST   /tasks/{id}/submit              submit for review
Anyone who can see the task
  POST   /tasks/{id}/comments            add a comment
  DELETE /tasks/{id}/comments/{cid}      delete own comment (admins: any)
"""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, ManagerUser
from app.models.enums import Priority, TaskStatus
from app.schemas.common import Page
from app.schemas.task import (CommentCreate, CommentOut, HistoryOut, TaskApprove, TaskCreate,
                              TaskCreatedResponse, TaskDeadlineUpdate, TaskDetail, TaskFilter,
                              TaskOut, TaskRequestChanges, TaskReschedule, TaskStatusUpdate,
                              TaskUpdate)
from app.services import task_service as svc
from app.utils.pagination import Pagination, page_response

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _detail(db, user, task) -> TaskDetail:
    return svc.to_detail(db, user, task)


# ---------------------------------------------------------------- reading
@router.get("", response_model=Page[TaskOut], summary="List tasks")
def list_tasks(
    user: CurrentUser, db: DbSession, pagination: Pagination,
    filter: Annotated[TaskFilter, Query(description="The chips: all / open / overdue / "
                                                    "in_review / completed")] = TaskFilter.ALL,
    q: Annotated[str | None, Query(max_length=100,
                                   description="Search title, person or project")] = None,
    assignee_id: int | None = None,
    project_id: int | None = None,
    independent: Annotated[bool, Query(description="Only tasks without a project")] = False,
    mine: Annotated[bool, Query(description="Only tasks assigned to me")] = False,
    status_: Annotated[TaskStatus | None, Query(alias="status")] = None,
    priority: Priority | None = None,
    start_from: date | None = None, start_to: date | None = None,
    due_from: date | None = None, due_to: date | None = None,
):
    """
    **Admin:** all tasks. **Team lead:** tasks of people in their department (and their own).
    **Employee:** only their own. Sorted by due date (earliest first), like the frontend.
    """
    items, total = svc.list_tasks(
        db, user, pagination, filter=filter, status=status_, priority=priority,
        assignee_id=assignee_id, project_id=project_id, independent=independent, mine=mine,
        q=q, start_from=start_from, start_to=start_to, due_from=due_from, due_to=due_to)
    return page_response(items, total, pagination)


@router.get("/counts", response_model=dict[str, int], summary="Numbers for the filter chips")
def counts(user: CurrentUser, db: DbSession):
    return svc.counts_for_chips(db, user)


@router.get("/{task_id}", response_model=TaskDetail, summary="Task details")
def get_task(task_id: int, user: CurrentUser, db: DbSession):
    return _detail(db, user, svc.get_visible(db, user, task_id))


@router.get("/{task_id}/comments", response_model=list[CommentOut], summary="Comments")
def get_comments(task_id: int, user: CurrentUser, db: DbSession):
    return svc.list_comments(db, user, task_id)


@router.get("/{task_id}/history", response_model=list[HistoryOut], summary="History")
def get_history(task_id: int, user: CurrentUser, db: DbSession):
    return svc.list_history(db, user, task_id)


# ---------------------------------------------------------------- managers
@router.post("", response_model=TaskCreatedResponse, status_code=status.HTTP_201_CREATED,
             summary="Create task(s) (admin, team lead)")
def create_tasks(body: TaskCreate, user: ManagerUser, db: DbSession):
    """
    Same as the "Assign task" form. **One task is created for each person** in
    `assignee_ids`, and each person gets a notification.
    Team leads can assign to themselves and to active employees of their department.
    """
    tasks = svc.create_tasks(db, user, body)
    return TaskCreatedResponse(created=len(tasks), tasks=svc.to_out(db, user, tasks))


@router.patch("/{task_id}", response_model=TaskDetail, summary="Edit details / reassign")
def update_task(task_id: int, body: TaskUpdate, user: CurrentUser, db: DbSession):
    return _detail(db, user, svc.update_task(db, user, task_id, body))


@router.put("/{task_id}/deadline", response_model=TaskDetail, summary="Change deadline")
def change_deadline(task_id: int, body: TaskDeadlineUpdate, user: CurrentUser, db: DbSession):
    return _detail(db, user, svc.change_deadline(db, user, task_id, body.due_date))


@router.put("/{task_id}/reschedule", response_model=TaskDetail,
            summary="Reschedule (calendar drag & drop)")
def reschedule(task_id: int, body: TaskReschedule, user: CurrentUser, db: DbSession):
    """Moves the start date; the due date moves by the same number of days."""
    return _detail(db, user, svc.reschedule(db, user, task_id, body.start_date))


@router.post("/{task_id}/approve", response_model=TaskDetail, summary="Approve & complete")
def approve(task_id: int, body: TaskApprove, user: CurrentUser, db: DbSession):
    """Only for tasks 'Submitted for Review'. Never your own task. Rating 0-100 (default 85)."""
    return _detail(db, user, svc.approve(db, user, task_id, body.rating))


@router.post("/{task_id}/request-changes", response_model=TaskDetail, summary="Request changes")
def request_changes(task_id: int, body: TaskRequestChanges, user: CurrentUser, db: DbSession):
    """Sends the task back to 'In Progress' and adds the reason as a comment."""
    return _detail(db, user, svc.request_changes(db, user, task_id, body.reason))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete task")
def delete_task(task_id: int, user: CurrentUser, db: DbSession):
    svc.delete_task(db, user, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- assignee
@router.patch("/{task_id}/status", response_model=TaskDetail, summary="Update my task's status")
def set_status(task_id: int, body: TaskStatusUpdate, user: CurrentUser, db: DbSession):
    return _detail(db, user, svc.set_status(db, user, task_id, body.status))


@router.post("/{task_id}/submit", response_model=TaskDetail, summary="Submit for review")
def submit(task_id: int, user: CurrentUser, db: DbSession):
    return _detail(db, user, svc.submit_for_review(db, user, task_id))


# ---------------------------------------------------------------- comments
@router.post("/{task_id}/comments", response_model=CommentOut,
             status_code=status.HTTP_201_CREATED, summary="Add a comment")
def add_comment(task_id: int, body: CommentCreate, user: CurrentUser, db: DbSession):
    return svc.add_comment(db, user, task_id, body.body)


@router.delete("/{task_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a comment")
def delete_comment(task_id: int, comment_id: int, user: CurrentUser, db: DbSession):
    svc.delete_comment(db, user, task_id, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
