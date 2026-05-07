"""Tests for RTH filtering — DST-aware, boundary conditions, edge cases."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from orbust.data.rth import (
    RTH_END_ET,
    RTH_START_ET,
    filter_rth,
    get_rth_minutes,
    is_rth,
)

_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


# Helpers for test readability
def _utc(y: int, m: int, d: int, h: int, mi: int) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=_UTC)


def _et(y: int, m: int, d: int, h: int, mi: int) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=_ET)


# ═══════════════════════════════════════════════════════════════
# is_rth
# ═══════════════════════════════════════════════════════════════


class TestIsRth:
    def test_inside_rth(self) -> None:
        """09:30 ET is inside RTH."""
        assert is_rth(_et(2023, 3, 1, 9, 30))

    def test_after_hours(self) -> None:
        """16:00 ET is outside RTH (exclusive boundary)."""
        assert not is_rth(_et(2023, 3, 1, 16, 0))

    def test_pre_market(self) -> None:
        """09:29 ET is outside RTH."""
        assert not is_rth(_et(2023, 3, 1, 9, 29))

    def test_last_minute(self) -> None:
        """15:59 ET is inside RTH (last valid minute)."""
        assert is_rth(_et(2023, 3, 1, 15, 59))

    def test_weekend(self) -> None:
        """Saturday is outside RTH."""
        # March 4, 2023 is a Saturday
        assert not is_rth(_et(2023, 3, 4, 10, 0))

    def test_sunday(self) -> None:
        """Sunday is outside RTH."""
        assert not is_rth(_et(2023, 3, 5, 10, 0))

    def test_midday_monday(self) -> None:
        """Monday midday is inside RTH."""
        # March 6, 2023 is a Monday
        assert is_rth(_et(2023, 3, 6, 12, 0))

    def test_utc_input(self) -> None:
        """UTC timestamp converts correctly to ET for RTH check."""
        # 14:30 UTC on a weekday = 09:30 ET (standard time)
        assert is_rth(_utc(2023, 3, 1, 14, 30))

    def test_utc_after_hours(self) -> None:
        """21:00 UTC on a weekday = 16:00 ET — outside RTH."""
        assert not is_rth(_utc(2023, 3, 1, 21, 0))

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Naive datetime is treated as UTC."""
        assert is_rth(datetime(2023, 3, 1, 14, 30))  # 09:30 ET

    def test_rth_constants(self) -> None:
        """RTH constants are set correctly."""
        assert time(9, 30) == RTH_START_ET
        assert time(16, 0) == RTH_END_ET


# ═══════════════════════════════════════════════════════════════
# DST transitions
# ═══════════════════════════════════════════════════════════════


class TestDstTransitions:
    """RTH filtering must work correctly across DST boundaries."""

    def test_est_standard_time(self) -> None:
        """November trading day in EST (UTC-5)."""
        # 14:30 UTC = 09:30 EST
        assert is_rth(_utc(2023, 11, 1, 14, 30))
        # 21:00 UTC = 16:00 EST — after hours
        assert not is_rth(_utc(2023, 11, 1, 21, 0))

    def test_edt_daylight_time(self) -> None:
        """June trading day in EDT (UTC-4)."""
        # 13:30 UTC = 09:30 EDT
        assert is_rth(_utc(2023, 6, 1, 13, 30))
        # 20:00 UTC = 16:00 EDT — after hours
        assert not is_rth(_utc(2023, 6, 1, 20, 0))

    def test_spring_forward_march(self) -> None:
        """DST spring-forward: clocks skip 2:00 ET → 3:00 ET."""
        # March 12, 2023 is spring-forward day (Sunday)
        # 09:30 EDT exists normally on Monday March 13
        assert is_rth(_et(2023, 3, 13, 9, 30))  # Monday after spring-forward

    def test_fall_back_november(self) -> None:
        """DST fall-back: clocks repeat 2:00 ET hour."""
        # November 5, 2023 is fall-back day (Sunday)
        # 09:30 EST on Monday Nov 6 is fine
        assert is_rth(_et(2023, 11, 6, 9, 30))  # Monday after fall-back


# ═══════════════════════════════════════════════════════════════
# filter_rth
# ═══════════════════════════════════════════════════════════════


class TestFilterRth:
    @pytest.fixture
    def trading_day_index(self) -> pd.DatetimeIndex:
        """390-minute RTH index for a trading day."""
        start = _et(2023, 3, 1, 9, 30)
        return pd.date_range(start, periods=390, freq="min", tz=_ET)

    def test_removes_pre_market(self) -> None:
        """Bars before 09:30 ET are removed."""
        idx = pd.DatetimeIndex(
            [
                _utc(2023, 3, 1, 13, 0),  # 08:00 ET — pre-market
                _utc(2023, 3, 1, 14, 30),  # 09:30 ET — open
            ]
        )
        df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
        result = filter_rth(df)
        assert len(result) == 1
        assert result.index[0].hour == 14  # 14:30 UTC = 09:30 ET

    def test_removes_after_hours(self) -> None:
        """Bars at or after 16:00 ET are removed."""
        idx = pd.DatetimeIndex(
            [
                _utc(2023, 3, 1, 20, 30),  # 15:30 ET — inside
                _utc(2023, 3, 1, 21, 0),  # 16:00 ET — close
            ]
        )
        df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
        result = filter_rth(df)
        assert len(result) == 1

    def test_removes_weekends(self) -> None:
        """Weekend bars are removed."""
        idx = pd.DatetimeIndex(
            [
                _utc(2023, 3, 3, 14, 30),  # Friday — RTH
                _utc(2023, 3, 4, 14, 30),  # Saturday — no
                _utc(2023, 3, 5, 14, 30),  # Sunday — no
                _utc(2023, 3, 6, 14, 30),  # Monday — RTH
            ]
        )
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]}, index=idx)
        result = filter_rth(df)
        assert len(result) == 2

    def test_preserves_bar_at_0930(self) -> None:
        """Exactly 09:30 ET is kept."""
        df = pd.DataFrame({"close": [1.0]}, index=[_et(2023, 3, 1, 9, 30)])
        result = filter_rth(df)
        assert len(result) == 1

    def test_removes_bar_at_1600(self) -> None:
        """Exactly 16:00 ET is removed (last valid bar is 15:59)."""
        df = pd.DataFrame({"close": [1.0]}, index=[_et(2023, 3, 1, 16, 0)])
        result = filter_rth(df)
        assert len(result) == 0

    def test_empty_dataframe(self) -> None:
        """Empty DataFrame returns empty DataFrame."""
        df = pd.DataFrame()
        result = filter_rth(df)
        assert len(result) == 0

    def test_same_column_structure(self) -> None:
        """Output DataFrame has same columns as input."""
        idx = pd.DatetimeIndex([_utc(2023, 3, 1, 14, 30)])
        df = pd.DataFrame({"open": [1.0], "close": [2.0], "volume": [100]}, index=idx)
        result = filter_rth(df)
        assert list(result.columns) == ["open", "close", "volume"]

    def test_utc_index(self) -> None:
        """UTC-indexed DataFrame is filtered correctly."""
        # 14:30 UTC = 09:30 ET (standard time)
        idx = pd.DatetimeIndex(
            [
                _utc(2023, 3, 1, 13, 0),  # 08:00 ET — pre-market
                _utc(2023, 3, 1, 14, 30),  # 09:30 ET — open
            ]
        )
        df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
        result = filter_rth(df)
        assert len(result) == 1

    def test_est_utc_offset(self) -> None:
        """Works correctly during EST (UTC-5, November)."""
        # 14:30 UTC = 09:30 EST
        assert is_rth(_utc(2023, 11, 1, 14, 30))
        assert not is_rth(_utc(2023, 11, 1, 21, 0))


# ═══════════════════════════════════════════════════════════════
# get_rth_minutes
# ═══════════════════════════════════════════════════════════════


class TestGetRthMinutes:
    def test_exactly_390_minutes(self) -> None:
        """get_rth_minutes returns exactly 390 timestamps for a trading day."""
        times = get_rth_minutes(date(2023, 3, 1))
        assert len(times) == 390

    def test_all_utc_aware(self) -> None:
        """All returned timestamps are UTC-aware."""
        times = get_rth_minutes(date(2023, 3, 1))
        for t in times:
            assert t.tzinfo is not None
            assert str(t.tzinfo) == "UTC"

    def test_first_and_last_minute_est(self) -> None:
        """First bar is 09:30 ET, last is 15:59 ET (standard time)."""
        times = get_rth_minutes(date(2023, 3, 1))
        first_et = times[0].astimezone(_ET)
        last_et = times[-1].astimezone(_ET)
        assert first_et.hour == 9 and first_et.minute == 30
        assert last_et.hour == 15 and last_et.minute == 59

    def test_first_and_last_minute_edt(self) -> None:
        """Same check during EDT (June)."""
        times = get_rth_minutes(date(2023, 6, 1))
        first_et = times[0].astimezone(_ET)
        last_et = times[-1].astimezone(_ET)
        assert first_et.hour == 9 and first_et.minute == 30
        assert last_et.hour == 15 and last_et.minute == 59

    def test_all_consecutive(self) -> None:
        """All 390 timestamps are consecutive minutes."""
        times = get_rth_minutes(date(2023, 3, 1))
        for i in range(1, len(times)):
            assert (times[i] - times[i - 1]).seconds == 60

    def test_utc_hours_differ_by_dst(self) -> None:
        """UTC hour of 09:30 ET differs between EST (14:30) and EDT (13:30)."""
        est_times = get_rth_minutes(date(2023, 3, 1))  # EST
        edt_times = get_rth_minutes(date(2023, 6, 1))  # EDT
        assert est_times[0].hour == 14  # 09:30 EST = 14:30 UTC
        assert edt_times[0].hour == 13  # 09:30 EDT = 13:30 UTC


# ═══════════════════════════════════════════════════════════════
# Import verification
# ═══════════════════════════════════════════════════════════════


def test_importable() -> None:
    """filter_rth, is_rth, get_rth_minutes are importable."""
    from orbust.data.rth import filter_rth, get_rth_minutes, is_rth

    assert filter_rth is not None
    assert is_rth is not None
    assert get_rth_minutes is not None
