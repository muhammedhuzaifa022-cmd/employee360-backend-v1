"""
Helper that turns a Python Enum into a PostgreSQL ENUM type.

`values_callable` makes PostgreSQL store the VALUE ("Submitted for Review")
instead of the Python name (SUBMITTED). That is what the frontend expects.
"""
import enum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
