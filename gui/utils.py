"""Shared paths and display formatting, independent of the window controller."""

from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:8893"


def compact(value: int) -> str:
    for divisor, unit in [(1_000_000_000, "B"), (1_000_000, "M"), (1000, "K")]:
        if value >= divisor:
            return f"{value / divisor:,.2f}".rstrip("0").rstrip(".") + unit
    return f"{value:,}"


def period_end(exclusive: str) -> str:
    return (date.fromisoformat(exclusive) - timedelta(days=1)).isoformat()
