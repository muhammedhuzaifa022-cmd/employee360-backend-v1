from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.report import DailyReport
from app.models.user import User
from app.schemas.report import DailyReportCreate


def get_role(user: User) -> str:
    role = getattr(user, "role", "")

    if hasattr(role, "value"):
        role = role.value

    return str(role).strip().lower().replace(" ", "").replace("-", "")


# --------------------------------------------------
# SUBMIT DAILY REPORT
# --------------------------------------------------

def submit_report(
    db: Session,
    employee: User,
    data: DailyReportCreate
):
    existing_report = (
        db.query(DailyReport)
        .filter(
            DailyReport.employee_id == employee.id,
            DailyReport.report_date == data.report_date
        )
        .first()
    )

    if existing_report:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted a report for this date"
        )

    report = DailyReport(
        employee_id=employee.id,
        report_date=data.report_date,
        content=data.content
    )

    db.add(report)

    try:
        db.commit()
    except IntegrityError:
        # Also handles duplicate submissions arriving simultaneously.
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A report already exists for this date"
        )

    db.refresh(report)

    return report


# --------------------------------------------------
# GET MY REPORTS
# --------------------------------------------------

def get_my_reports(
    db: Session,
    employee: User
):
    return (
        db.query(DailyReport)
        .filter(DailyReport.employee_id == employee.id)
        .order_by(
            DailyReport.report_date.desc(),
            DailyReport.created_at.desc()
        )
        .all()
    )


# --------------------------------------------------
# GET TEAM REPORTS
# --------------------------------------------------

def get_team_reports(
    db: Session,
    current_user: User,
    report_date: date = None
):
    role = get_role(current_user)

    allowed_roles = {"manager", "teamlead", "admin"}

    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view team reports"
        )

    query = (
        db.query(DailyReport)
        .join(User, DailyReport.employee_id == User.id)
    )

    # Team leads can only see reports from their department.
    if role == "teamlead":
        if not getattr(current_user, "department_id", None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account does not have a department assigned"
            )

        query = query.filter(
            User.department_id == current_user.department_id
        )

    # Optional date filter.
    if report_date:
        query = query.filter(
            DailyReport.report_date == report_date
        )

    return (
        query
        .order_by(
            DailyReport.report_date.desc(),
            DailyReport.created_at.desc()
        )
        .all()
    )