"""Table: users (Admin, Team Lead, Employee)."""
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey,
                        Index, String, Time, func, true)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin
from app.models.types import pg_enum

if TYPE_CHECKING:
    from app.models.auth import DevicePushToken, RefreshToken
    from app.models.department import Department
    from app.models.notification import Notification
    from app.models.project import Project


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False, default=UserRole.EMPLOYEE,
        server_default=UserRole.EMPLOYEE.value)
    designation: Mapped[str] = mapped_column(String(100), nullable=False, default="Associate",
                                             server_default="Associate")

    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True, index=True)
    custom_shift_start: Mapped[time | None] = mapped_column(Time, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                            server_default=true())
    joined_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Login tokens issued before this moment are rejected (used on password change)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ---- relationships ----
    department: Mapped["Department | None"] = relationship(back_populates="users")
    managed_projects: Mapped[list["Project"]] = relationship(
        back_populates="manager", foreign_keys="Project.manager_id")
    projects: Mapped[list["Project"]] = relationship(
        secondary="project_members", back_populates="members")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="recipient", cascade="all, delete-orphan", passive_deletes=True)
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    push_tokens: Mapped[list["DevicePushToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        # Emails are unique, ignoring capital letters
        Index("uq_users_email_lower", func.lower(email), unique=True),
        # Team leads and employees MUST belong to a department (admins may not)
        CheckConstraint("role = 'admin' OR department_id IS NOT NULL",
                        name="department_required_for_non_admin"),
        Index("ix_users_role_active", "role", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} {self.role.value}>"
