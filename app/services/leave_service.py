from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.leave import LeaveRequest
from app.models.user import User
from app.schemas.leave import LeaveCreate, LeaveDecision


def get_role(user: User) -> str:
    role = getattr(user, "role", "")
    if hasattr(role, "value"):
        role = role.value
    return str(role).strip().lower().replace(" ", "").replace("-", "")


def check_reviewer_permission(user: User):
    role = get_role(user)
    allowed_roles = {"teamlead", "admin"} # FIXED HERE

    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage leave requests"
        )

    if role == "teamlead" and not getattr(user, "department_id", None): # FIXED HERE
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account does not have a department assigned"
        )


def apply_for_leave(db: Session, employee: User, data: LeaveCreate):
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="End date cannot be before start date")

    total_days = (data.end_date - data.start_date).days + 1

    overlapping_leave = db.query(LeaveRequest).filter(
        LeaveRequest.employee_id == employee.id,
        LeaveRequest.status.in_(["Pending", "Approved"]),
        LeaveRequest.start_date <= data.end_date,
        LeaveRequest.end_date >= data.start_date
    ).first()

    if overlapping_leave:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending or approved leave request for these dates"
        )

    leave = LeaveRequest(
        employee_id=employee.id,
        leave_type=data.leave_type,
        start_date=data.start_date,
        end_date=data.end_date,
        days=total_days,
        reason=data.reason,
        status="Pending"
    )

    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


def get_my_leaves(db: Session, employee: User):
    return (
        db.query(LeaveRequest)
        .filter(LeaveRequest.employee_id == employee.id)
        .order_by(LeaveRequest.created_at.desc())
        .all()
    )


def get_approval_queue(db: Session, current_user: User):
    check_reviewer_permission(current_user)

    query = db.query(LeaveRequest).filter(LeaveRequest.status == "Pending")
    role = get_role(current_user)

    if role == "teamlead": # FIXED HERE
        query = (
            query
            .join(User, LeaveRequest.employee_id == User.id)
            .filter(User.department_id == current_user.department_id)
        )

    return query.order_by(LeaveRequest.created_at.desc()).all()


def decide_leave(db: Session, leave_id: int, current_user: User, decision: LeaveDecision):
    check_reviewer_permission(current_user)

    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()

    if not leave:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave request not found")

    if leave.status != "Pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This leave request has already been decided")

    if leave.employee_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot approve your own leave")

    role = get_role(current_user)

    if role == "teamlead": # FIXED HERE
        employee = db.query(User).filter(User.id == leave.employee_id).first()
        if not employee or employee.department_id != current_user.department_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only decide leave requests from your department")

    leave.status = decision.status
    leave.decided_by_id = current_user.id
    leave.decided_at = date.today()
    leave.comment = decision.comment

    db.commit()
    db.refresh(leave)
    return leave