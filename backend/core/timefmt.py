"""Shared time-display helpers.

Image timestamps are stored as naive UTC (``Image.timestamp`` is
``DateTime(timezone=False)``). For any human-facing display we convert to the
capture-local timezone (``Image.timezone``, an IANA name propagated onto
segments and location visits) so summaries read in local wall-clock time.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def to_local(dt: datetime | None, tz_name: str | None) -> datetime | None:
    """Interpret a naive-UTC datetime in ``tz_name`` (IANA). Naive datetimes are
    assumed UTC; aware ones are converted as-is. Falls back to the original value
    when the zone is missing or unknown."""
    if dt is None:
        return None
    if tz_name:
        try:
            aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            return aware.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
    return dt


def fmt_hm(dt: datetime | None, tz_name: str | None) -> str:
    """Local ``HH:MM`` for a naive-UTC datetime; empty string when missing."""
    local = to_local(dt, tz_name)
    return local.strftime("%H:%M") if local else ""
