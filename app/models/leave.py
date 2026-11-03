"""Table: leave_requests."""
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index,
                        Integer, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LeaveStatus, LeaveType
from app.models.mixins import TimestampMixin
from app.models.types import pg_enum

if TYPE_CHECKING:
    from app.models.user import User


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    leave_type: Mapped[LeaveType] = mapped_column(pg_enum(LeaveType, "leave_type"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    status: Mapped[LeaveStatus] = mapped_column(
        pg_enum(LeaveStatus, "leave_status"), nullable=False, default=LeaveStatus.PENDING,
        server_default=LeaveStatus.PENDING.value, index=True)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str] = mapped_column(Text, nullable=False, default="",
                                                  server_default="")

    employee: Mapped["User"] = relationship(foreign_keys=[employee_id])
    decided_by: Mapped["User | None"] = relationship(foreign_keys=[decided_by_id])

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="end_after_start"),
        CheckConstraint("days >= 1", name="days_positive"),
        Index("ix_leave_requests_employee_dates", "employee_id", "start_date", "end_date"),
    )

    def __repr__(self) -> str:
        return f"<LeaveRequest {self.id} {self.leave_type.value} {self.status.value}>"
