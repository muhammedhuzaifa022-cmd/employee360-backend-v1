"""Table: departments (Engineering, Design, Management, ...)."""
from typing import TYPE_CHECKING

from sqlalchemy import Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.user import User


class Department(CreatedAtMixin, Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="department")

    __table_args__ = (
        # "Engineering" and "engineering" count as the same department
        Index("uq_departments_name_lower", func.lower(name), unique=True),
    )

    def __repr__(self) -> str:
        return f"<Department {self.id} {self.name}>"
