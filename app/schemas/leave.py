from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeaveCreate(BaseModel):
    leave_type: str = Field(min_length=2, max_length=50)

    start_date: date

    end_date: date

    reason: str = Field(min_length=3)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date")

        return self


class LeaveDecision(BaseModel):
    status: Literal["Approved", "Rejected"]

    comment: Optional[str] = None


class LeaveResponse(BaseModel):
    id: int

    employee_id: int

    leave_type: str

    start_date: date

    end_date: date

    days: int

    reason: str

    status: str

    decided_by_id: Optional[int] = None

    decided_at: Optional[date] = None

    comment: Optional[str] = None

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)