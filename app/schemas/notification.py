"""Shapes for the Inbox (notifications)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Page


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message: str = Field(examples=['New task assigned: "Testing"'])
    category: str = Field(examples=["task_assigned"])
    entity_type: str | None = Field(default=None, examples=["task"],
                                    description="What to open when tapped: task / leave / project")
    entity_id: int | None = Field(default=None, examples=[6])
    is_read: bool
    created_at: datetime = Field(description="UTC. Show it in the user's local time")


class NotificationPage(Page[NotificationOut]):
    """A normal page plus the badge number, so the Inbox needs only one request."""
    unread_count: int


class UnreadCount(BaseModel):
    unread_count: int


class NotificationReadUpdate(BaseModel):
    is_read: bool = True


class UpdatedCount(BaseModel):
    updated: int = Field(description="How many notifications were changed")


class DeletedCount(BaseModel):
    deleted: int
