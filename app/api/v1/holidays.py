from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.holiday import Holiday

router = APIRouter()

class HolidayCreate(BaseModel):
    date: date
    name: str
    is_working_override: bool = False

class HolidayResponse(HolidayCreate):
    id: int
    class Config:
        from_attributes = True

@router.get("/", response_model=List[HolidayResponse])
def get_holidays(db: Session = Depends(get_db)):
    return db.query(Holiday).order_by(Holiday.date).all()

@router.post("/", response_model=HolidayResponse)
def add_holiday(holiday: HolidayCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Check if user is HR or Admin
    if current_user.role.value not in ['admin', 'hr']:
        raise HTTPException(status_code=403, detail="Only HR/Admin can manage holidays")
        
    existing = db.query(Holiday).filter(Holiday.date == holiday.date).first()
    if existing:
        raise HTTPException(status_code=400, detail="Holiday already exists for this date")
        
    new_holiday = Holiday(**holiday.model_dump())
    db.add(new_holiday)
    db.commit()
    db.refresh(new_holiday)
    return new_holiday

@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role.value not in ['admin', 'hr']:
        raise HTTPException(status_code=403, detail="Only HR/Admin can manage holidays")
        
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
        
    db.delete(holiday)
    db.commit()
    return {"message": "Holiday deleted successfully"}