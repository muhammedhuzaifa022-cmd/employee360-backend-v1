from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User

from app.schemas.report import (
    DailyReportCreate,
    DailyReportResponse
)

from app.services import report_service


router = APIRouter(
    prefix="/reports",
    tags=["Daily Reports"]
)


# --------------------------------------------------
# SUBMIT DAILY REPORT
# POST /reports/submit
# --------------------------------------------------

@router.post(
    "/submit",
    response_model=DailyReportResponse,
    status_code=201
)
def submit_daily_report(
    data: DailyReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return report_service.submit_report(
        db=db,
        employee=current_user,
        data=data
    )


# --------------------------------------------------
# GET MY REPORTS
# GET /reports/my-reports
# --------------------------------------------------

@router.get(
    "/my-reports",
    response_model=List[DailyReportResponse]
)
def my_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return report_service.get_my_reports(
        db=db,
        employee=current_user
    )


# --------------------------------------------------
# GET TEAM REPORTS
# GET /reports/team
# --------------------------------------------------

@router.get(
    "/team",
    response_model=List[DailyReportResponse]
)
def team_reports(
    report_date: date = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return report_service.get_team_reports(
        db=db,
        current_user=current_user,
        report_date=report_date
    )