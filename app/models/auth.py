"""
Tables for login sessions and future mobile push notifications.

refresh_tokens      : one row per logged-in device/browser. Lets us
                      log out one device, log out everywhere, and rotate tokens.
device_push_tokens  : phone push-notification addresses (used later).
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Platform
from app.models.mixins import CreatedAtMixin
from app.models.types import pg_enum

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(CreatedAtMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Unique ID written inside the refresh JWT ("jti"). The token itself is never stored.
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    platform: Mapped[Platform] = mapped_column(
        pg_enum(Platform, "platform"), nullable=False, default=Platform.WEB,
        server_default=Platform.WEB.value)
    device_name: Mapped[str | None] = mapped_column(String(120))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class DevicePushToken(CreatedAtMixin, Base):
    __tablename__ = "device_push_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform: Mapped[Platform] = mapped_column(pg_enum(Platform, "platform"), nullable=False)
    push_token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    device_name: Mapped[str | None] = mapped_column(String(120))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="push_tokens")
