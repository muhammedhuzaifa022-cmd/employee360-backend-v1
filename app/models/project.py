"""Tables: projects and project_members (who is in which project)."""
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (CheckConstraint, Column, Date, DateTime, ForeignKey,
                        String, Table, Text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Priority
from app.models.mixins import TimestampMixin
from app.models.types import pg_enum

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


# Link table: many users <-> many projects
project_members = Table(
    "project_members",
    Base.metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[Priority] = mapped_column(
        pg_enum(Priority, "priority"), nullable=False, default=Priority.MEDIUM,
        server_default=Priority.MEDIUM.value)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    manager: Mapped["User"] = relationship(back_populates="managed_projects",
                                           foreign_keys=[manager_id])
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    members: Mapped[list["User"]] = relationship(secondary=project_members,
                                                 back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="end_after_start"),
    )

    def __repr__(self) -> str:
        return f"<Project {self.id} {self.name}>"
