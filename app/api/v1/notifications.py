"""
Notifications (the Inbox and the unread badge).
Everyone sees ONLY their own notifications - no role differences here.

  GET    /notifications                list (newest first) + unread_count
  GET    /notifications/unread-count   just the badge number (cheap, for polling)
  POST   /notifications/read-all       "Mark all as read"
  DELETE /notifications/read           clear all read notifications
  PATCH  /notifications/{id}           mark one read / unread
  DELETE /notifications/{id}           delete one
"""
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.models.enums import NotificationCategory
from app.schemas.notification import (DeletedCount, NotificationOut, NotificationPage,
                                      NotificationReadUpdate, UnreadCount, UpdatedCount)
from app.services import notification_service as svc
from app.utils.pagination import Pagination, page_response

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationPage, summary="My notifications")
def list_notifications(
    user: CurrentUser, db: DbSession, pagination: Pagination,
    unread_only: bool = False,
    category: Annotated[NotificationCategory | None, Query()] = None,
):
    items, total = svc.list_for(db, user, pagination, unread_only=unread_only,
                                category=category.value if category else None)
    return {**page_response(items, total, pagination), "unread_count": svc.unread_count(db, user)}


@router.get("/unread-count", response_model=UnreadCount, summary="Unread badge number")
def get_unread_count(user: CurrentUser, db: DbSession):
    return UnreadCount(unread_count=svc.unread_count(db, user))


@router.post("/read-all", response_model=UpdatedCount, summary="Mark all as read")
def read_all(user: CurrentUser, db: DbSession):
    return UpdatedCount(updated=svc.mark_all_read(db, user))


@router.delete("/read", response_model=DeletedCount, summary="Delete all read notifications")
def clear_read(user: CurrentUser, db: DbSession):
    return DeletedCount(deleted=svc.delete_read(db, user))


@router.patch("/{notification_id}", response_model=NotificationOut,
              summary="Mark one as read (or unread)")
def set_read(notification_id: int, body: NotificationReadUpdate, user: CurrentUser, db: DbSession):
    return svc.set_read(db, user, notification_id, body.is_read)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete one notification")
def delete_notification(notification_id: int, user: CurrentUser, db: DbSession):
    svc.delete_one(db, user, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
