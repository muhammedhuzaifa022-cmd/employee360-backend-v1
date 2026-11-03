"""Shapes for the Projects page."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Priority, UserRole
from app.schemas.user import DepartmentOut
from app.utils.text import clean_spaces

MAX_MEMBERS = 200


# ---------------- output ----------------
class ProjectPerson(BaseModel):
    """A manager or member as shown on the project card (avatar + name)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    role: UserRole
    designation: str
    department: DepartmentOut | None
    is_active: bool


class ProjectProgress(BaseModel):
    total: int = 0
    done: int = 0
    overdue: int = Field(default=0, description="Open tasks whose due date has passed ('late')")
    percent: int = Field(default=0, description="done / total * 100, rounded (0 when no tasks)")


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    priority: Priority
    start_date: date
    end_date: date
    manager: ProjectPerson
    members: list[ProjectPerson]
    progress: ProjectProgress = ProjectProgress()
    can_edit: bool = Field(default=False, description="True if YOU may edit this project")
    created_at: datetime
    updated_at: datetime


class PersonOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    designation: str
    department: DepartmentOut | None


class ProjectFormOptions(BaseModel):
    """What to show in the 'New project' dropdowns, already filtered for you."""
    managers: list[PersonOption]
    members: list[PersonOption]


# ---------------- input ----------------
def _tidy_name(v: str | None) -> str | None:
    if v is None:
        return v
    v = clean_spaces(v)
    if len(v) < 2:
        raise ValueError("Project name must be at least 2 characters")
    return v


def _unique_ids(v: list[int] | None) -> list[int] | None:
    if v is None:
        return v
    seen: list[int] = []
    for i in v:
        if i not in seen:
            seen.append(i)
    return seen


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150, examples=["Mobile app v2"])
    description: str = Field(default="", max_length=2000)
    manager_id: int | None = Field(default=None, ge=1,
                                   description="Admin/team lead. Team leads: leave empty (= you)")
    member_ids: list[int] = Field(default_factory=list, max_length=MAX_MEMBERS,
                                  description="Active employees")
    start_date: date
    end_date: date
    priority: Priority = Priority.MEDIUM

    @field_validator("name")
    @classmethod
    def tidy_name(cls, v: str | None) -> str | None:
        return _tidy_name(v)

    @field_validator("member_ids")
    @classmethod
    def no_duplicates(cls, v: list[int] | None) -> list[int] | None:
        return _unique_ids(v)

    @field_validator("description")
    @classmethod
    def tidy_description(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date")
        return self


class ProjectUpdate(BaseModel):
    """Send only what changes. Members are changed with the /members endpoints."""
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    manager_id: int | None = Field(default=None, ge=1, description="Admins only")
    start_date: date | None = None
    end_date: date | None = None
    priority: Priority | None = None

    @field_validator("name")
    @classmethod
    def tidy_name(cls, v: str | None) -> str | None:
        return _tidy_name(v)

    @field_validator("description")
    @classmethod
    def tidy_description(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class ProjectMembersUpdate(BaseModel):
    member_ids: list[int] = Field(max_length=MAX_MEMBERS)

    @field_validator("member_ids")
    @classmethod
    def no_duplicates(cls, v: list[int] | None) -> list[int] | None:
        return _unique_ids(v)
