"""
Application settings.

All configuration is read from the ".env" file (or real environment
variables). Nothing secret is written in the code.
"""
from functools import lru_cache
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- General ----
    APP_NAME: str = "Employee360 API"
    APP_ENV: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    API_VERSION: str = "1.0.0"

    # ---- Database ----
    DATABASE_URL: str
    TEST_DATABASE_URL: str | None = None
    DB_ECHO_SQL: bool = False  # set true to print every SQL query (debugging)

    # ---- Security ----
    SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, ge=1, le=365)
    JWT_ISSUER: str = "employee360"
    JWT_AUDIENCE: str = "employee360-api"

    # ---- Login protection ----
    LOGIN_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=100)      # failed tries allowed...
    LOGIN_WINDOW_MINUTES: int = Field(default=15, ge=1, le=1440)  # ...within this many minutes

    # ---- CORS (browsers only) ----
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # ---- Company ----
    COMPANY_TIMEZONE: str = "Asia/Kolkata"

    # ---- Mobile app versions ----
    MIN_SUPPORTED_APP_VERSION: str = "1.0.0"
    LATEST_APP_VERSION: str = "1.0.0"

    # ---------- validators ----------
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def split_origins(cls, value):
        """Allow 'a,b,c' in .env and turn it into ['a', 'b', 'c']."""
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("DATABASE_URL", "TEST_DATABASE_URL")
    @classmethod
    def check_db_url(cls, value):
        if value and not value.startswith("postgresql+psycopg://"):
            raise ValueError("Database URL must start with 'postgresql+psycopg://'")
        return value

    @field_validator("COMPANY_TIMEZONE")
    @classmethod
    def check_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown time zone: {value}") from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.COMPANY_TIMEZONE)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """Read settings once and reuse them everywhere."""
    return Settings()


settings = get_settings()
