"""Regular Trading Hours (RTH) filtering for US equities.

RTH is defined as 09:30-16:00 ET, Monday through Friday,
excluding US exchange holidays (not filtered here — handled externally).

Provides:
    filter_rth: Remove bars outside RTH from a wide-format DataFrame.
    is_rth: Check if a single timestamp falls within RTH.
    get_rth_minutes: Generate all RTH minute timestamps for a trading day.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

# ET (Eastern Time) timezone — handles both EST and EDT automatically
_ET = ZoneInfo("America/New_York")

# RTH window in ET
RTH_START_ET = time(9, 30)  # 09:30 ET — market open
RTH_END_ET = time(16, 0)    # 16:00 ET — market close (exclusive)

# Number of RTH minutes per trading day: (16:00 - 09:30) * 60 = 390
_RTH_MINUTES_PER_DAY = 390


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════


def is_rth(timestamp: datetime) -> bool:
    """Check if a timestamp falls within US Regular Trading Hours.

    RTH is 09:30-16:00 ET, Monday through Friday.
    The 16:00 ET boundary is exclusive (last bar is at 15:59 ET).

    Args:
        timestamp: A timezone-aware or naive datetime.
            Naive datetimes are treated as UTC.

    Returns:
        True if the timestamp falls within RTH.
    """
    # Normalize to ET
    ts_et = _to_et(timestamp)

    # Weekend check: Monday=0, Friday=4, Saturday=5, Sunday=6
    if ts_et.weekday() >= 5:
        return False

    # Time-of-day check: [09:30, 16:00) ET
    t = ts_et.timetz()
    return RTH_START_ET <= t < RTH_END_ET


def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Remove bars outside Regular Trading Hours from a DataFrame.

    The DataFrame must have a ``DatetimeIndex`` (timezone-aware or naive).
    Naive indices are treated as UTC and converted to ET for filtering.

    Args:
        df: DataFrame with ``DatetimeIndex``.

    Returns:
        DataFrame with only RTH bars. Returns an empty DataFrame
        (same columns, no rows) if no RTH bars exist.
    """
    if df.empty:
        return df

    mask = df.index.map(is_rth)
    return df.loc[mask]


def get_rth_minutes(trading_date: date) -> list[datetime]:
    """Generate all RTH minute timestamps for a given trading day.

    Returns timestamps in UTC for the ET trading session.
    For a standard day (no DST transition), this produces 390 timestamps
    at 09:30-15:59 ET.

    Args:
        trading_date: The trading day in question (date only, ignored time).

    Returns:
        List of UTC-aware datetime objects, one per RTH minute.
    """
    # Build start time in ET
    start_dt_et = datetime.combine(
        trading_date,
        RTH_START_ET,
        tzinfo=_ET,
    )

    # Generate all minutes in ET
    et_times: list[datetime] = []
    for i in range(_RTH_MINUTES_PER_DAY):
        minute_dt = start_dt_et + timedelta(minutes=i)
        et_times.append(minute_dt)

    # Convert to UTC for output consistency
    return [t.astimezone(ZoneInfo("UTC")) for t in et_times]


# ═══════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════


def _to_et(dt: datetime) -> datetime:
    """Convert a datetime to ET. Naive inputs are treated as UTC."""
    if dt.tzinfo is None:
        # Treat naive as UTC
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(_ET)
