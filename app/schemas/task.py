"""Shapes for the Tasks page and the task-details window."""
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import DEFAULT_RATING, RATING_MAX, RATING_MIN
from app.models.enums import EMPLOYEE_SETTABLE_STATUSES, Priority, TaskStatus
from app.schemas.user import DepartmentOut
from app.utils.text import clean_spaces

MAX_ASSIGNEES = 50
MAX_HOURS = 1000


# ---------------- output ----------------
class TaskPerson(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    designation: str
    department: DepartmentOut | None


class TaskProjectRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TaskPermissions(BaseModel):
    """What YOU may do with this task - lets web/mobile show the right buttons."""
    can_update_status: bool = False
    can_submit: bool = False
    can_review: bool = False
    can_manage: bool = False
    can_comment: bool = False


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: TaskStatus
    priority: Priority
    start_date: date
    due_date: date
    estimated_hours: float
    completed_on: date | None
    rating: int | None
    submitted_at: datetime | None
    assignee: TaskPerson
    assigned_by: TaskPerson | None
    project: TaskProjectRef | None = Field(description="null = Independent task")
    is_overdue: bool = False
    days_left: int | None = Field(default=None,
                                  description="due_date - today (negative = overdue). null when Completed")
    comment_count: int = 0
    permissions: TaskPermissions = TaskPermissions()
    created_at: datetime
    updated_at: datetime


class CommentOut(BaseModel):
    id: int
    body: str
    author: TaskPerson | None
    created_at: datetime
    can_delete: bool = False


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message: str
    actor: TaskPerson | None
    created_at: datetime


class TaskDetail(TaskOut):
    comments: list[CommentOut] = Field(description="Oldest first")
    history: list[HistoryOut] = Field(description="Newest first (same as the frontend)")


class TaskFilter(str, Enum):
    """The chips on the Tasks page."""
    ALL = "all"
    OPEN = "open"            # frontend "Open" (= not Completed)
    OVERDUE = "overdue"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"


# ---------------- input ----------------
def _title(v: str | None) -> str | None:
    if v is None:
        return v
    v = clean_spaces(v)
    if len(v) < 2:
        raise ValueError("Title must be at least 2 characters")
    return v


class TaskCreate(BaseModel):
    """'Assign task' form. One task is created for EACH selected person."""
    title: str = Field(min_length=1, max_length=200, examples=["Finalise onboarding flow"])
    description: str = Field(default="", max_length=5000)
    assignee_ids: list[int] = Field(min_length=1, max_length=MAX_ASSIGNEES,
                                    description="At least one person")
    project_id: int | None = Field(default=None, ge=1, description="null = Independent task")
    start_date: date | None = Field(default=None, description="Default: today")
    due_date: date | None = Field(default=None, description="Default: the start date")
    estimated_hours: float = Field(default=4, ge=0, le=MAX_HOURS)
    priority: Priority = Priority.MEDIUM

    @field_validator("title")
    @classmethod
    def tidy_title(cls, v: str) -> str:
        return _title(v)

    @field_validator("description")
    @classmethod
    def tidy_description(cls, v: str) -> str:
        return v.strip()

    @field_validator("assignee_ids")
    @classmethod
    def no_duplicates(cls, v: list[int]) -> list[int]:
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("Due date must be on or after the start date")
        return self


class TaskUpdate(BaseModel):
    """Edit details (managers). Use the dedicated endpoints for status, deadline, reschedule."""
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    project_id: int | None = Field(default=None, ge=0, description="0 = make it Independent")
    estimated_hours: float | None = Field(default=None, ge=0, le=MAX_HOURS)
    priority: Priority | None = None
    assignee_id: int | None = Field(default=None, ge=1, description="Reassign to someone else")

    @field_validator("title")
    @classmethod
    def tidy_title(cls, v: str | None) -> str | None:
        return _title(v)

    @field_validator("description")
    @classmethod
    def tidy_description(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class TaskStatusUpdate(BaseModel):
    status: TaskStatus = Field(description="Not Started, In Progress, On Hold or Delayed")

    @field_validator("status")
    @classmethod
    def only_settable(cls, v: TaskStatus) -> TaskStatus:
        if v not in EMPLOYEE_SETTABLE_STATUSES:
            allowed = ", ".join(s.value for s in EMPLOYEE_SETTABLE_STATUSES)
            raise ValueError(f"Status must be one of: {allowed}. "
                             "Use 'submit' for review; only a manager can complete a task")
        return v


class TaskApprove(BaseModel):
    rating: int = Field(default=DEFAULT_RATING, ge=RATING_MIN, le=RATING_MAX,
                        description="Manager evaluation 0-100 (slider in the frontend)")


class TaskRequestChanges(BaseModel):
    reason: str = Field(min_length=3, max_length=1000,
                        examples=["Please add validation to the form"])

    @field_validator("reason")
    @classmethod
    def tidy(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Please explain what needs to change (at least 3 characters)")
        return v


class TaskDeadlineUpdate(BaseModel):
    due_date: date


class TaskReschedule(BaseModel):
    """Calendar drag & drop: move the start date; the due date moves by the same amount."""
    start_date: date


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment cannot be empty")
        return v


class TaskCreatedResponse(BaseModel):
    created: int
    tasks: list[TaskOut]
