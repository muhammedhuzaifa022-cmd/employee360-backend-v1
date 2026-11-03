"""
Push-notification devices (for the FUTURE Android/iOS apps).

The phone app sends its push token after login. It is only STORED now;
actually sending push messages is added when the mobile app is built.
"""
from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.models import DevicePushToken
from app.schemas.auth import DeviceOut, DeviceRegisterRequest
from app.utils.dates import utc_now

router = APIRouter(prefix="/devices", tags=["Devices (mobile)"])


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED,
             summary="Register this phone for push notifications")
def register_device(body: DeviceRegisterRequest, user: CurrentUser, db: DbSession):
    device = db.scalar(select(DevicePushToken).where(DevicePushToken.push_token == body.push_token))
    if device is None:
        device = DevicePushToken(push_token=body.push_token, user_id=user.id,
                                 platform=body.platform)
        db.add(device)
    # The same phone may now belong to a different user (someone else logged in).
    device.user_id = user.id
    device.platform = body.platform
    device.device_name = body.device_name
    device.last_seen_at = utc_now()
    db.commit()
    db.refresh(device)
    return device


@router.get("", response_model=list[DeviceOut], summary="My registered phones")
def list_devices(user: CurrentUser, db: DbSession):
    return list(db.scalars(select(DevicePushToken).where(DevicePushToken.user_id == user.id)
                           .order_by(DevicePushToken.created_at.desc())))


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Unregister a phone (e.g. on logout)")
def delete_device(device_id: int, user: CurrentUser, db: DbSession):
    device = db.get(DevicePushToken, device_id)
    if device is None or device.user_id != user.id:
        raise NotFoundError("Device not found")
    db.delete(device)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
