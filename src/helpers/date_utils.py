"""
Date and time utilities.
"""

from datetime import datetime


def time_now_iso() -> str:
    """Return current local time formatted as ISO 8601 string."""
    return datetime.now().isoformat()


def time_now_formatted(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Return current local time formatted with custom format string."""
    return datetime.now().strftime(fmt)
