"""Request and response shapes for login, tokens, sessions and devices."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import PASSWORD_MAX_LENGTH, validate_password_strength
from app.models.enums import Platform
from app.schemas.user import UserMe


class LoginRequest(BaseModel):
    email: EmailStr = Field(examples=["aisha@company.com"])
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH, examples=["Admin@123"])
    platform: Platform = Field(default=Platform.WEB, description="web / android / ios")
    device_name: str | None = Field(default=None, max_length=120, examples=["Chrome on Windows"])

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    refresh_expires_in: int = Field(description="Refresh token lifetime in seconds")
    user: UserMe


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=2000)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def strong(cls, v: str) -> str:
        return validate_password_strength(v)


class SessionOut(BaseModel):
    """One logged-in browser or phone."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: Platform
    device_name: str | None
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    is_current: bool = False


class DeviceRegisterRequest(BaseModel):
    """Future mobile apps send their push-notification token here."""
    push_token: str = Field(min_length=10, max_length=512)
    platform: Platform
    device_name: str | None = Field(default=None, max_length=120)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: Platform
    device_name: str | None
    created_at: datetime
    last_seen_at: datetime | None
