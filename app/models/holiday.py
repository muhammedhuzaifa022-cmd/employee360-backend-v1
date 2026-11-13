"""Table: holidays (Predefined and custom company holidays)."""
from datetime import date
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, Date, String, true
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # If HR clicks "Unlock as Working Day", this becomes True
    is_working_override: Mapped[bool] = mapped_column(Boolean, default=False, server_default=true())

    def _repr_(self) -> str:
        return f"<Holiday {self.date} {self.name}>"