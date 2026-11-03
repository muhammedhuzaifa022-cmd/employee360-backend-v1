"""
Date helpers.

"Today" is ALWAYS decided by the server in the company time zone,
never by the user's browser or phone clock.
"""
from datetime import date, datetime, timezone

from app.core.config import settings


def utc_now() -> datetime:
    """Current moment in UTC (stored in the database)."""
    return datetime.now(timezone.utc)


def company_now() -> datetime:
    """Current moment in the company's time zone (Asia/Kolkata)."""
    return datetime.now(settings.tz)


def company_today() -> date:
    """Today's date in the company's time zone."""
    return company_now().date()


def days_inclusive(start: date, end: date) -> int:
    """Number of calendar days, counting both ends (same as the frontend)."""
    return (end - start).days + 1


def fmt_date(d: date) -> str:
    """Readable date for history / notification texts: 04 Nov 2026."""
    return d.strftime("%d %b %Y")
