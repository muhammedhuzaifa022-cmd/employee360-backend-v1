from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db          # FIXED HERE
from app.api.deps import get_current_user  # FIXED HERE
from app.models.user import User

from app.schemas.leave import LeaveCreate, LeaveDecision, LeaveResponse
from app.services import leave_service

router = APIRouter(prefix="/leave", tags=["Leave Requests"])

@router.post("/apply", response_model=LeaveResponse, status_code=201)
def apply_leave(data: LeaveCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return leave_service.apply_for_leave(db=db, employee=current_user, data=data)

@router.get("/my-leaves", response_model=List[LeaveResponse])
def my_leaves(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return leave_service.get_my_leaves(db=db, employee=current_user)

@router.get("/queue", response_model=List[LeaveResponse])
def approval_queue(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return leave_service.get_approval_queue(db=db, current_user=current_user)

@router.patch("/{id}/decide", response_model=LeaveResponse)
def decide_leave_request(id: int, decision: LeaveDecision, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return leave_service.decide_leave(db=db, leave_id=id, current_user=current_user, decision=decision)