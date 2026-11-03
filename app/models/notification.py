"""
Table: notifications (the Inbox).

`category`, `entity_type` and `entity_id` are extra, mobile-ready fields.
They let a future phone app open the right screen when a notification
is tapped, e.g. entity_type="task", entity_id=12. The current web page
just shows `message`.
"""
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.user import User


class Notification(CreatedAtMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general",
                                          server_default="general")
    entity_type: Mapped[str | None] = mapped_column(String(30))   # "task" / "leave" / "project"
    entity_id: Mapped[int | None] = mapped_column(Integer)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                          server_default=false())

    recipient: Mapped["User"] = relationship(back_populates="notifications")

    __table_args__ = (
        Index("ix_notifications_recipient_read", "recipient_id", "is_read"),
        Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
    )
