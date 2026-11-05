from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Text,
    ForeignKey,
    func,
)

from app.db.base import Base
from app.models.user import User


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)

    employee_id = Column(
        Integer,
        ForeignKey(f"{User.__tablename__}.id"),
        nullable=False,
        index=True
    )

    leave_type = Column(String(50), nullable=False)

    start_date = Column(Date, nullable=False)

    end_date = Column(Date, nullable=False)

    days = Column(Integer, nullable=False)

    reason = Column(Text, nullable=False)

    status = Column(
        String(20),
        nullable=False,
        default="Pending",
        server_default="Pending",
        index=True
    )

    decided_by_id = Column(
        Integer,
        ForeignKey(f"{User.__tablename__}.id"),
        nullable=True
    )

    decided_at = Column(Date, nullable=True)

    comment = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )