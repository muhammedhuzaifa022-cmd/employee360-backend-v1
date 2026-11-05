from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user

from app.models.user import User

from app.schemas.attendance import (
    AttendanceCreate,
    AttendanceResponse,
    AttendanceSummary,
)

from app.services.attendance_service import (
    mark_attendance,
    get_my_attendance,
    get_team_attendance,
    get_summary,
)


router = APIRouter(
    prefix="/attendance",
    tags=["Attendance"],
)


# --------------------------------------------------
# POST /attendance/mark
# --------------------------------------------------

@router.post(
    "/mark",
    response_model=AttendanceResponse,
)
def mark_attendance_route(
    attendance_data: AttendanceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return mark_attendance(
        db=db,
        current_user=current_user,
        attendance_data=attendance_data,
    )


# --------------------------------------------------
# GET /attendance/my-attendance
# --------------------------------------------------

@router.get(
    "/my-attendance",
    response_model=list[AttendanceResponse],
)
def get_my_attendance_route(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_my_attendance(
        db=db,
        current_user=current_user,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )


# --------------------------------------------------
# GET /attendance/team-attendance
# --------------------------------------------------

@router.get(
    "/team-attendance",
    response_model=list[AttendanceResponse],
)
def get_team_attendance_route(
    department_id: Optional[int] = Query(None, gt=0),
    employee_id: Optional[int] = Query(None, gt=0),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_team_attendance(
        db=db,
        current_user=current_user,
        department_id=department_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )


# --------------------------------------------------
# GET /attendance/summary
# --------------------------------------------------

@router.get(
    "/summary",
    response_model=AttendanceSummary,
)
def get_attendance_summary_route(
    employee_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_summary(
        db=db,
        current_user=current_user,
        employee_id=employee_id,
    )