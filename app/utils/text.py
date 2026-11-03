"""Small text clean-up helpers used by the input schemas."""
import re


def clean_spaces(value: str) -> str:
    """'  Maya   Patel ' -> 'Maya Patel'"""
    return re.sub(r"\s+", " ", value).strip()
