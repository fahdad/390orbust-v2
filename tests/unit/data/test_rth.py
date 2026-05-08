"""Tests for RTH (Regular Trading Hours) filtering — is_rth, filter_rth, get_rth_minutes."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from orbust.data.rth import filter_rth, get_rth_minutes, is_rth

# ═══════════════════════════════════════════════════════════════
# is_rth — classification of individual timestamps
# ═══════════════════════════════════════════════════════════════


class TestIsRth:
    """is_rth correctly classifies timestamps at various boundaries."""

    # EST (winter): UTC-5, 09:30 ET = 14:30 UTC
    # Use a winter weekday: 2023-03-02 is a Thursday
    WINTER_WEEKDAY = date(2023, 3, 2)  # Thursday, before DST

    # EDT (summer): UTC-4, 09:30 ET = 13:30 UTC
    # Use a summer weekday: 2023-06-15 is a Thursday
    SUMMER_WEEKDAY = date(2023, 6, 15)  # Thursday

    def test_pre_market_winter(self) -> None:
        """Pre-market bar (before 09:30 ET) is rejected."""
        # 09:29 ET = 14:29 UTC
        ts = datetime(2023, 3, 2, 14, 29, tzinfo=UTC)
        assert is_rth(ts) is False

    def test_exactly_open_winter(self) -> None:
        """Bar at exactly 09:30 ET is included (opening bar)."""
        # 09:30 ET = 14:30 UTC
        ts = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        assert is_rth(ts) is True

    def test_mid_session_winter(self) -> None:
        """Mid-session bar is included."""
        ts = datetime(2023, 3, 2, 17, 0, tzinfo=UTC)  # 12:00 ET
        assert is_rth(ts) is True

    def test_exactly_close_winter(self) -> None:
        """Bar at exactly 16:00 ET is excluded (last bar is 15:59)."""
        # 16:00 ET = 21:00 UTC
        ts = datetime(2023, 3, 2, 21, 0, tzinfo=UTC)
        assert is_rth(ts) is False

    def test_last_minute_winter(self) -> None:
        """Last valid bar at 15:59 ET is included."""
        # 15:59 ET = 20:59 UTC
        ts = datetime(2023, 3, 2, 20, 59, tzinfo=UTC)
        assert is_rth(ts) is True

    def test_after_hours_winter(self) -> None:
        """After-hours bar (after 16:00 ET) is rejected."""
        # 16:01 ET = 21:01 UTC
        ts = datetime(2023, 3, 2, 21, 1, tzinfo=UTC)
        assert is_rth(ts) is False

    def test_pre_market_summer(self) -> None:
        """Pre-market bar (before 09:30 ET) in EDT."""
        # 09:29 ET = 13:29 UTC
        ts = datetime(2023, 6, 15, 13, 29, tzinfo=UTC)
        assert is_rth(ts) is False

    def test_exactly_open_summer(self) -> None:
        """Bar at exactly 09:30 ET in EDT is included."""
        # 09:30 ET = 13:30 UTC
        ts = datetime(2023, 6, 15, 13, 30, tzinfo=UTC)
        assert is_rth(ts) is True

    def test_exactly_close_summer(self) -> None:
        """Bar at exactly 16:00 ET in EDT is excluded."""
        # 16:00 ET = 20:00 UTC
        ts = datetime(2023, 6, 15, 20, 0, tzinfo=UTC)
        assert is_rth(ts) is False

    def test_last_minute_summer(self) -> None:
        """Last valid bar at 15:59 ET in EDT is included."""
        # 15:59 ET = 19:59 UTC
        ts = datetime(2023, 6, 15, 19, 59, tzinfo=UTC)
        assert is_rth(ts) is True

    def test_weekend_rejected(self) -> None:
        """Saturday and Sunday are rejected regardless of time."""
        # Saturday 2023-03-04 at 14:30 UTC (09:30 ET)
        sat = datetime(2023, 3, 4, 14, 30, tzinfo=UTC)
        assert is_rth(sat) is False

        # Sunday 2023-03-05 at 14:30 UTC
        sun = datetime(2023, 3, 5, 14, 30, tzinfo=UTC)
        assert is_rth(sun) is False

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Naive datetime is treated as UTC."""
        ts = datetime(2023, 3, 2, 14, 30)  # 09:30 ET if UTC
        assert is_rth(ts) is True

        ts = datetime(2023, 3, 2, 21, 0)  # 16:00 ET if UTC
        assert is_rth(ts) is False


# ═══════════════════════════════════════════════════════════════
# filter_rth — DataFrame filtering
# ═══════════════════════════════════════════════════════════════


class TestFilterRth:
    """filter_rth returns only RTH bars from a DataFrame."""

    def test_removes_pre_market(self) -> None:
        """Pre-market bars before 09:30 ET are removed."""
        # Create index spanning pre-market + RTH
        idx = pd.date_range(
            datetime(2023, 3, 2, 13, 0),  # 08:00 ET
            periods=200,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
        result = filter_rth(df)
        assert len(result) < len(df)
        # First bar should be at 14:30 UTC (09:30 ET)
        assert result.index[0].hour == 14
        assert result.index[0].minute == 30

    def test_removes_after_hours(self) -> None:
        """After-hours bars at or after 16:00 ET are removed."""
        # Create index spanning RTH + after-hours
        idx = pd.date_range(
            datetime(2023, 3, 2, 14, 30),  # 09:30 ET
            periods=500,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
        result = filter_rth(df)
        assert len(result) < len(df)
        # Last bar should be at 20:59 UTC (15:59 ET)
        last_ts = result.index[-1]
        assert last_ts.hour == 20
        assert last_ts.minute == 59

    def test_removes_weekend_bars(self) -> None:
        """Weekend bars are removed."""
        # Create a range that includes a weekend
        idx = pd.date_range(
            datetime(2023, 3, 3, 14, 30),  # Friday
            periods=3000,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
        result = filter_rth(df)
        # No weekend timestamps should remain
        for ts in result.index:
            assert ts.weekday() < 5  # Monday=0, Sunday=6

    def test_preserves_exactly_0930_et(self) -> None:
        """Bar at exactly 09:30 ET is preserved (opening bar)."""
        idx = pd.date_range(
            datetime(2023, 3, 2, 14, 30),  # 09:30 ET
            periods=5,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
        result = filter_rth(df)
        assert len(result) == 5  # all in RTH
        assert result.index[0].hour == 14 and result.index[0].minute == 30

    def test_removes_exactly_1600_et(self) -> None:
        """Bar at exactly 16:00 ET is removed (last bar is 15:59)."""
        # Create index ending at 16:00 ET
        idx = pd.date_range(
            datetime(2023, 3, 2, 20, 50),  # 15:50 ET
            periods=20,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
        result = filter_rth(df)
        # 16:00 ET = 21:00 UTC — should be removed
        assert datetime(2023, 3, 2, 21, 0, tzinfo=UTC) not in result.index

    def test_preserves_column_structure(self) -> None:
        """Output DataFrame has the same columns as input."""
        idx = pd.date_range(
            datetime(2023, 3, 2, 14, 30),
            periods=390,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame(
            {
                "XOM_open": [100.0] * 390,
                "XOM_close": [100.1] * 390,
                "XOM_volume": [1_000_000] * 390,
                "XOP_open": [50.0] * 390,
                "XOP_close": [50.1] * 390,
            },
            index=idx,
        )
        result = filter_rth(df)
        assert list(result.columns) == list(df.columns)
        assert len(result) == 390  # all 390 minutes are in RTH

    def test_empty_dataframe(self) -> None:
        """Empty input returns empty DataFrame."""
        empty = pd.DataFrame()
        result = filter_rth(empty)
        assert result.empty

    def test_utc_index_on_output(self) -> None:
        """Output has UTC-aware DatetimeIndex."""
        idx = pd.date_range(
            datetime(2023, 3, 2, 14, 30),
            periods=10,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * 10}, index=idx)
        result = filter_rth(df)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_dst_transition_spring(self) -> None:
        """Works correctly through spring DST transition (EST -> EDT)."""
        # 2023-03-13 (Monday after DST spring forward)
        idx = pd.date_range(
            datetime(2023, 3, 13, 13, 0),  # 09:00 EDT
            periods=180,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * 180}, index=idx)
        result = filter_rth(df)
        # First RTH bar should be at 13:30 UTC (09:30 EDT)
        if len(result) > 0:
            first_valid = result.index[0]
            assert first_valid.hour == 13 and first_valid.minute == 30
        assert len(result) == 150  # 09:30-15:59 EDT = 180 - 30 pre-market

    def test_dst_transition_fall(self) -> None:
        """Works correctly through fall DST transition (EDT -> EST)."""
        # 2023-11-06 (Monday after DST fall back)
        idx = pd.date_range(
            datetime(2023, 11, 6, 14, 0),  # 09:00 EST
            periods=180,
            freq="min",
            tz="UTC",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * 180}, index=idx)
        result = filter_rth(df)
        # First RTH bar should be at 14:30 UTC (09:30 EST)
        if len(result) > 0:
            first_valid = result.index[0]
            assert first_valid.hour == 14 and first_valid.minute == 30
        assert len(result) == 150

    def test_naive_datetime_index(self) -> None:
        """Naive DatetimeIndex is handled correctly (treated as UTC)."""
        idx = pd.date_range(
            datetime(2023, 3, 2, 13, 0),  # no tz
            periods=200,
            freq="min",
        )
        df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
        result = filter_rth(df)
        assert len(result) > 0  # doesn't crash


# ═══════════════════════════════════════════════════════════════
# get_rth_minutes
# ═══════════════════════════════════════════════════════════════


class TestGetRthMinutes:
    """get_rth_minutes returns correct number and range of timestamps."""

    def test_returns_390_timestamps(self) -> None:
        """Full trading day returns exactly 390 timestamps."""
        timestamps = get_rth_minutes(date(2023, 3, 2))
        assert len(timestamps) == 390

    def test_first_and_last_timestamps_winter(self) -> None:
        """First is 09:30 ET, last is 15:59 ET in EST."""
        timestamps = get_rth_minutes(date(2023, 3, 2))
        # EST: 09:30 ET = 14:30 UTC, 15:59 ET = 20:59 UTC
        assert timestamps[0] == datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        assert timestamps[-1] == datetime(2023, 3, 2, 20, 59, tzinfo=UTC)

    def test_first_and_last_timestamps_summer(self) -> None:
        """First is 09:30 ET, last is 15:59 ET in EDT."""
        timestamps = get_rth_minutes(date(2023, 6, 15))
        # EDT: 09:30 ET = 13:30 UTC, 15:59 ET = 19:59 UTC
        assert timestamps[0] == datetime(2023, 6, 15, 13, 30, tzinfo=UTC)
        assert timestamps[-1] == datetime(2023, 6, 15, 19, 59, tzinfo=UTC)

    def test_returns_utc_aware_datetimes(self) -> None:
        """Output timestamps are UTC-aware."""
        timestamps = get_rth_minutes(date(2023, 3, 2))
        for ts in timestamps:
            assert ts.tzinfo is not None, f"Expected aware datetime, got {ts.tzinfo}"
            assert str(ts.tzinfo) == "UTC"

    def test_consecutive_minute_intervals(self) -> None:
        """Each timestamp is exactly 1 minute after the previous."""
        timestamps = get_rth_minutes(date(2023, 3, 2))
        diffs = [
            (timestamps[i + 1] - timestamps[i]).total_seconds()
            for i in range(len(timestamps) - 1)
        ]
        assert all(d == 60 for d in diffs)


# ═══════════════════════════════════════════════════════════════
# Import from orbust.data
# ═══════════════════════════════════════════════════════════════


def test_importable_from_data_module() -> None:
    """RTH functions are importable from orbust.data."""
    from orbust.data import filter_rth, get_rth_minutes, is_rth

    assert filter_rth is not None
    assert is_rth is not None
    assert get_rth_minutes is not None
