from datetime import datetime
from zoneinfo import ZoneInfo
from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.attendance import Attendance
from app.models.user import User
from app.schemas.attendance import AttendanceCreate, AttendanceSummary


# --------------------------------------------------
# ROLE HELPERS
# --------------------------------------------------

def _get_role(user: User) -> str:
    """
    Normalize role names.

    Examples:
    Admin     -> admin
    HR        -> hr
    TeamLead  -> teamlead
    team_lead -> teamlead
    """
    role = getattr(user.role, "value", user.role)

    return (
        str(role)
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def _is_manager(user: User) -> bool:
    return _get_role(user) in {"admin", "hr", "teamlead"}


def _require_manager(user: User) -> None:
    if not _is_manager(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin, HR, or TeamLead can access this feature.",
        )


# --------------------------------------------------
# EMPLOYEE ACCESS VALIDATION
# --------------------------------------------------

def _get_authorized_employee(
    db: Session,
    current_user: User,
    employee_id: Optional[int] = None,
) -> User:
    """
    Employees can access their own attendance.

    Admin/HR can access any employee.
    TeamLead can access employees in their own department.
    """

    target_id = employee_id or current_user.id

    employee = (
        db.query(User)
        .filter(User.id == target_id)
        .first()
    )

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found.",
        )

    # Employees can access only their own records.
    if employee.id != current_user.id:

        if not _is_manager(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only access your own attendance.",
            )

        # TeamLead can access only their department.
        if _get_role(current_user) == "teamlead":

            if (
                current_user.department_id is None
                or employee.department_id != current_user.department_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only manage employees in your department.",
                )

    return employee


def _validate_date_range(
    start_date: Optional[date],
    end_date: Optional[date],
) -> None:

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date.",
        )


# --------------------------------------------------
# MARK ATTENDANCE
# --------------------------------------------------
def mark_attendance(db: Session, current_user: User, attendance_data: AttendanceCreate):
    # NEW RULE: Only HR or Admin can mark attendance
    role = _get_role(current_user)
    if role not in {"hr", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin can mark attendance."
        )
    
    # ... (rest of the function stays the same)
def mark_attendance(
    db: Session,
    current_user: User,
    attendance_data: AttendanceCreate,
):
    """
    Mark attendance for an employee.

    Rules:
    1. Employee can mark their own attendance.
    2. Admin/HR/TeamLead can mark for others.
    3. TeamLead is restricted to their department.
    4. Saturdays and Sundays are automatically marked Holiday.
    5. Existing records are updated instead of duplicated.
    """

    employee = _get_authorized_employee(
        db=db,
        current_user=current_user,
        employee_id=attendance_data.employee_id,
    )

    attendance_date = attendance_data.date

    existing_attendance = (
        db.query(Attendance)
        .filter(
            Attendance.employee_id == employee.id,
            Attendance.date == attendance_date,
        )
        .first()
    )

    # --------------------------------------------------
    # WEEKEND HOLIDAY LOGIC
    # Monday = 0, Saturday = 5, Sunday = 6
    # --------------------------------------------------

    if attendance_date.weekday() in (5, 6):

        attendance_values = {
            "status": "Holiday",
            "check_in": None,
            "check_out": None,
            "remarks": "Automatically marked as Holiday (weekend).",
        }

    else:

        attendance_values = {
            "status": attendance_data.status,
            "check_in": attendance_data.check_in,
            "check_out": attendance_data.check_out,
            "remarks": attendance_data.remarks,
        }

    # --------------------------------------------------
    # CREATE OR UPDATE
    # --------------------------------------------------

    if existing_attendance:

        for field, value in attendance_values.items():
            setattr(existing_attendance, field, value)

        attendance = existing_attendance

    else:

        attendance = Attendance(
            employee_id=employee.id,
            date=attendance_date,
            **attendance_values,
        )

        db.add(attendance)

    try:
        db.commit()
        db.refresh(attendance)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance could not be saved because a record already exists for this employee and date.",
        )

    return attendance


# --------------------------------------------------
# GET MY ATTENDANCE
# --------------------------------------------------

def get_my_attendance(
    db: Session,
    current_user: User,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
):

    _validate_date_range(start_date, end_date)

    query = db.query(Attendance).filter(
        Attendance.employee_id == current_user.id
    )

    if start_date:
        query = query.filter(Attendance.date >= start_date)

    if end_date:
        query = query.filter(Attendance.date <= end_date)

    return (
        query
        .order_by(Attendance.date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# --------------------------------------------------
# GET TEAM ATTENDANCE
# --------------------------------------------------

def get_team_attendance(
    db: Session,
    current_user: User,
    department_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
):

    _require_manager(current_user)
    _validate_date_range(start_date, end_date)

    role = _get_role(current_user)

    query = (
        db.query(Attendance)
        .join(User, Attendance.employee_id == User.id)
    )

    # TeamLead can only view their own department.
    if role == "teamlead":

        if current_user.department_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not assigned to a department.",
            )

        if (
            department_id is not None
            and department_id != current_user.department_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot access another department.",
            )

        query = query.filter(
            User.department_id == current_user.department_id
        )

    # Admin and HR can optionally filter by department.
    elif department_id is not None:

        query = query.filter(
            User.department_id == department_id
        )

    # Optionally filter by one employee.
    if employee_id is not None:

        _get_authorized_employee(
            db=db,
            current_user=current_user,
            employee_id=employee_id,
        )

        query = query.filter(
            Attendance.employee_id == employee_id
        )

    if start_date:
        query = query.filter(
            Attendance.date >= start_date
        )

    if end_date:
        query = query.filter(
            Attendance.date <= end_date
        )

    return (
        query
        .order_by(Attendance.date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# --------------------------------------------------
# MONTHLY ATTENDANCE SUMMARY
# --------------------------------------------------

def get_summary(
    db: Session,
    current_user: User,
    employee_id: Optional[int] = None,
) -> AttendanceSummary:

    employee = _get_authorized_employee(
        db=db,
        current_user=current_user,
        employee_id=employee_id,
    )

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()

    first_day = today.replace(day=1)

    query = (
        db.query(
            Attendance.status,
            func.count(Attendance.id),
        )
        .filter(
            Attendance.employee_id == employee.id,
            Attendance.date >= first_day,
            Attendance.date <= today,
        )
        .group_by(Attendance.status)
    )

    counts = {
        attendance_status: count
        for attendance_status, count in query.all()
    }

    present = counts.get("Present", 0)
    absent = counts.get("Absent", 0)
    half_day = counts.get("Half-Day", 0)
    late = counts.get("Late", 0)
    holidays = counts.get("Holiday", 0)

    return AttendanceSummary(
        year=today.year,
        month=today.month,
        total_records=present + absent + half_day + late + holidays,
        present_count=present,
        absent_count=absent,
        half_day_count=half_day,
        late_arrivals=late,
        holiday_count=holidays,
    )