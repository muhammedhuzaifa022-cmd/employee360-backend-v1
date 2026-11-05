from sqlalchemy import Column, Date, ForeignKey, Integer, String, Time, UniqueConstraint, Index
from app.db.base import Base

class Attendance(Base):
    __tablename__ = "attendance"

    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "date",
            name="uq_attendance_employee_date",
        ),
        Index("ix_attendance_employee_date", "employee_id", "date"),
    )

    id = Column(Integer, primary_key=True, index=True)

    employee_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    date = Column(Date, nullable=False, index=True)

    status = Column(String(20), nullable=False)

    check_in = Column(Time, nullable=True)

    check_out = Column(Time, nullable=True)

    remarks = Column(String(500), nullable=True)