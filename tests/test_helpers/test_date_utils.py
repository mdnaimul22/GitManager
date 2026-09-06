"""
Date utilities unit tests.

Covers:
- time_now_iso
- time_now_formatted
"""

from datetime import datetime
import pytest
from src.helpers import time_now_iso, time_now_formatted


class TestDateUtils:
    """Unit tests for date and time helper functions."""

    def test_time_now_iso_format(self):
        iso_str = time_now_iso()
        assert isinstance(iso_str, str)
        # Should be parseable by datetime.fromisoformat
        parsed = datetime.fromisoformat(iso_str)
        assert parsed is not None

    def test_time_now_formatted_default(self):
        dt_str = time_now_formatted()
        assert isinstance(dt_str, str)
        # Default is %Y-%m-%d %H:%M:%S (19 chars)
        assert len(dt_str) == 19
        assert dt_str[4] == "-" and dt_str[7] == "-"

    def test_time_now_formatted_custom(self):
        dt_str = time_now_formatted("%Y/%m/%d")
        assert len(dt_str) == 10
        assert dt_str[4] == "/" and dt_str[7] == "/"
