from datetime import date, time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


AttendanceStatus = Literal[
    "Present",
    "Absent",
    "Half-Day",
    "Late",
    "Holiday",
    "WFH",
    "Sick Leave",
    "Casual Leave",
]


class AttendanceCreate(BaseModel):
    employee_id: Optional[int] = Field(default=None, gt=0)
    date: date
    status: AttendanceStatus
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    remarks: Optional[str] = Field(default=None, max_length=500)


class AttendanceResponse(BaseModel):
    id: int
    employee_id: int
    date: date
    status: str
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    remarks: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AttendanceSummary(BaseModel):
    year: int
    month: int
    total_records: int
    present_count: int
    absent_count: int
    half_day_count: int
    late_arrivals: int
    holiday_count: int