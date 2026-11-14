"""Request and response shapes for users (employees) and departments."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.security import validate_password_strength
from app.models.enums import UserRole
from app.utils.text import clean_spaces


# ---------------- departments ----------------
class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class DepartmentWithCount(DepartmentOut):
    member_count: int = Field(description="Active users in this department")
    total_count: int = Field(description="All users, including inactive")


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100, examples=["Marketing"])

    @field_validator("name")
    @classmethod
    def tidy(cls, v: str) -> str:
        v = clean_spaces(v)
        if len(v) < 2:
            raise ValueError("Department name must be at least 2 characters")
        return v


DepartmentUpdate = DepartmentCreate


# ---------------- users: output ----------------
class UserStats(BaseModel):
    """The counters on a Team card."""
    total: int = 0
    open: int = 0          # not Completed
    done: int = 0          # Completed
    overdue: int = 0       # not Completed and due date before today
    in_review: int = 0     # Submitted for Review


class UserMe(BaseModel):
    """A user as returned by the API. Never contains the password hash."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: UserRole
    designation: str
    custom_shift_start: str | None = None  # <--- ADDED HERE
    department: DepartmentOut | None
    is_active: bool
    joined_on: date
    last_login_at: datetime | None
    created_at: datetime


class UserOut(UserMe):
    stats: UserStats | None = None


class UserBrief(BaseModel):
    """Small version for dropdowns (Assign to, Project manager...)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: str
    role: UserRole
    designation: str
    department: DepartmentOut | None


class UserCreatedResponse(BaseModel):
    user: UserOut
    temporary_password: str | None = Field(
        default=None,
        description="Only present when the server generated a password. Shown ONCE - give it to the employee.")


# ---------------- users: input ----------------
def _name(v: str) -> str:
    v = clean_spaces(v)
    if len(v) < 2:
        raise ValueError("Full name must be at least 2 characters")
    return v


class _DepartmentChoice(BaseModel):
    """Send EITHER department_id (existing) OR department (a name - created if new)."""
    department_id: int | None = Field(default=None, ge=1)
    department: str | None = Field(default=None, min_length=2, max_length=100,
                                   examples=["Engineering"])

    @field_validator("department")
    @classmethod
    def tidy_dept(cls, v: str | None) -> str | None:
        return clean_spaces(v) if v else v

    @model_validator(mode="after")
    def not_both(self):
        if self.department_id is not None and self.department:
            raise ValueError("Send either department_id or department, not both")
        return self


class UserCreate(_DepartmentChoice):
    full_name: str = Field(min_length=2, max_length=120, examples=["Maya Patel"])
    email: EmailStr = Field(examples=["maya@company.com"])
    role: UserRole = UserRole.EMPLOYEE
    designation: str | None = Field(default=None, max_length=100,
                                    description="Default: Associate / Team Lead / Administrator")
    joined_on: date | None = None
    password: str | None = Field(default=None, description="Leave empty to generate a temporary password")
    custom_shift_start: str | None = Field(default=None, description="HH:MM format like 09:00 or 13:00")  # <--- ADDED HERE

    @field_validator("full_name")
    @classmethod
    def tidy_name(cls, v: str) -> str:
        return _name(v)

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("designation")
    @classmethod
    def tidy_designation(cls, v: str | None) -> str | None:
        return (clean_spaces(v) or None) if v else None

    @field_validator("password")
    @classmethod
    def strong(cls, v: str | None) -> str | None:
        return validate_password_strength(v) if v else None

    @model_validator(mode="after")
    def department_required(self):
        # The frontend form always asks for a department.
        if self.department_id is None and not self.department:
            raise ValueError("Department is required")
        return self


class UserUpdate(_DepartmentChoice):
    """Admin edits. Send only the fields you want to change."""
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    role: UserRole | None = None
    designation: str | None = Field(default=None, min_length=1, max_length=100)
    joined_on: date | None = None
    custom_shift_start: str | None = None  # <--- ADDED HERE

    @field_validator("full_name")
    @classmethod
    def tidy_name(cls, v: str | None) -> str | None:
        return _name(v) if v is not None else v

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str | None) -> str | None:
        return v.strip().lower() if v else v

    @field_validator("designation")
    @classmethod
    def tidy_designation(cls, v: str | None) -> str | None:
        return clean_spaces(v) if v else v


class UserStatusUpdate(BaseModel):
    is_active: bool


class PasswordResetRequest(BaseModel):
    new_password: str | None = Field(default=None, description="Leave empty to generate one")

    @field_validator("new_password")
    @classmethod
    def strong(cls, v: str | None) -> str | None:
        return validate_password_strength(v) if v else None


class PasswordResetResponse(BaseModel):
    message: str
    temporary_password: str | None = None