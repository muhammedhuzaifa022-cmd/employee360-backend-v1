"""Tables: tasks, task_comments, task_history."""
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
                        SmallInteger, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Priority, TaskStatus
from app.models.mixins import CreatedAtMixin, TimestampMixin
from app.models.types import pg_enum

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    assignee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # NULL project = "Independent task" in the frontend
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True, index=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    estimated_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0,
                                                   server_default="0")

    priority: Mapped[Priority] = mapped_column(
        pg_enum(Priority, "priority"), nullable=False, default=Priority.MEDIUM,
        server_default=Priority.MEDIUM.value)
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, "task_status"), nullable=False, default=TaskStatus.NOT_STARTED,
        server_default=TaskStatus.NOT_STARTED.value, index=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_on: Mapped[date | None] = mapped_column(Date)
    rating: Mapped[int | None] = mapped_column(SmallInteger)  # manager evaluation 0-100

    assignee: Mapped["User"] = relationship(foreign_keys=[assignee_id])
    assigned_by: Mapped["User | None"] = relationship(foreign_keys=[assigned_by_id])
    project: Mapped["Project | None"] = relationship(back_populates="tasks")
    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True,
        order_by="TaskComment.created_at")
    history: Mapped[list["TaskHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True,
        order_by="TaskHistory.created_at")

    __table_args__ = (
        CheckConstraint("due_date >= start_date", name="due_after_start"),
        CheckConstraint("estimated_hours >= 0 AND estimated_hours <= 1000", name="hours_range"),
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 100)", name="rating_range"),
        # A completion date exists if and only if the task is Completed
        CheckConstraint("(status = 'Completed') = (completed_on IS NOT NULL)",
                        name="completed_on_matches_status"),
        Index("ix_tasks_assignee_status", "assignee_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Task {self.id} {self.title!r} {self.status.value}>"


class TaskComment(CreatedAtMixin, Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    task: Mapped["Task"] = relationship(back_populates="comments")
    author: Mapped["User | None"] = relationship()

    __table_args__ = (CheckConstraint("length(trim(body)) > 0", name="body_not_empty"),)


class TaskHistory(CreatedAtMixin, Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)

    task: Mapped["Task"] = relationship(back_populates="history")
    actor: Mapped["User | None"] = relationship()
