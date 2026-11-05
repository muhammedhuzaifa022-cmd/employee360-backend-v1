from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DailyReportCreate(BaseModel):
    report_date: date = Field(default_factory=date.today)

    content: str = Field(min_length=5)


class DailyReportResponse(BaseModel):
    id: int

    employee_id: int

    report_date: date

    content: str

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)