from sqlalchemy import (
    Column,
    Integer,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    func,
)

from app.db.base import Base
from app.models.user import User


class DailyReport(Base):
    __tablename__ = "daily_reports"

    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "report_date",
            name="uq_daily_report_employee_date"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    employee_id = Column(
        Integer,
        ForeignKey(f"{User.__tablename__}.id"),
        nullable=False,
        index=True
    )

    report_date = Column(Date, nullable=False, index=True)

    content = Column(Text, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )