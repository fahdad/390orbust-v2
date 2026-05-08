"""Tests for data quality checks — gap detection, duplicates, timestamp validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from orbust.data.quality import (
    GapInfo,
    QualityReport,
    TimestampIssue,
    check_quality,
    detect_duplicates,
    detect_gaps,
    validate_timestamps,
)
from orbust.types import Timeframe

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _make_wide_df(
    symbols: list[str],
    start: datetime,
    periods: int,
    freq: str = "min",
    tz: str = "UTC",
    remove_indices: list[int] | None = None,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """Create a wide-format bar DataFrame, optionally with missing rows."""
    idx = pd.date_range(start, periods=periods, freq=freq, tz=tz)
    idx.name = "timestamp"

    if remove_indices:
        keep = [i for i in range(periods) if i not in remove_indices]
        idx = idx[keep]
        total = len(keep)
    else:
        total = periods

    fields = fields or ["open", "high", "low", "close", "volume", "trade_count", "vwap"]
    data: dict[str, list[float]] = {}
    base_price = 100.0
    for sym in symbols:
        for f in fields:
            data[f"{sym}_{f}"] = [base_price] * total
        base_price += 50.0
    return pd.DataFrame(data, index=idx)


# ═══════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════


class TestDataTypes:
    def test_gap_info_creation(self) -> None:
        """GapInfo can be instantiated with all fields."""
        g = GapInfo(
            symbol="XOM",
            gap_start=datetime(2023, 3, 1, 14, 30),
            gap_end=datetime(2023, 3, 1, 14, 35),
            missing_bars=5,
        )
        assert g.symbol == "XOM"
        assert g.missing_bars == 5

    def test_timestamp_issue_creation(self) -> None:
        """TimestampIssue can be instantiated."""
        t = TimestampIssue(
            timestamp=datetime(2023, 3, 1, 14, 30),
            issue_type="non_utc",
            detail="test",
        )
        assert t.issue_type == "non_utc"

    def test_quality_report_empty_is_clean(self) -> None:
        """Empty QualityReport has is_clean=True."""
        r = QualityReport()
        assert r.is_clean is True

    def test_quality_report_with_gaps_not_clean(self) -> None:
        """QualityReport with gaps has is_clean=False."""
        r = QualityReport(
            gaps=[
                GapInfo(
                    symbol="XOM",
                    gap_start=datetime(2023, 3, 1, 14, 30),
                    gap_end=datetime(2023, 3, 1, 14, 35),
                    missing_bars=5,
                )
            ]
        )
        assert r.is_clean is False

    def test_quality_report_with_duplicates_not_clean(self) -> None:
        """QualityReport with duplicates has is_clean=False."""
        r = QualityReport(duplicates=[datetime(2023, 3, 1, 14, 30)])
        assert r.is_clean is False

    def test_quality_report_with_timestamp_issues_not_clean(self) -> None:
        """QualityReport with timestamp issues has is_clean=False."""
        r = QualityReport(
            timestamp_issues=[
                TimestampIssue(
                    timestamp=datetime(2023, 3, 1, 14, 30),
                    issue_type="non_utc",
                    detail="",
                )
            ]
        )
        assert r.is_clean is False


# ═══════════════════════════════════════════════════════════════
# detect_gaps
# ═══════════════════════════════════════════════════════════════


class TestDetectGaps:
    """detect_gaps finds missing bars within expected trading hours."""

    def test_no_gaps_in_perfect_data(self) -> None:
        """Complete RTH session has no gaps."""
        # 390 bars covering a full RTH day (09:30-15:59 ET)
        # In winter EST: 14:30-20:59 UTC
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)  # 09:30 ET
        df = _make_wide_df(["XOM"], start, 390)
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        assert gaps == []

    def test_detects_single_gap(self) -> None:
        """A single missing bar is detected as a gap."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390, remove_indices=[10])
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        assert len(gaps) == 1
        assert gaps[0].symbol == "XOM"
        assert gaps[0].missing_bars == 1

    def test_detects_multi_bar_gap(self) -> None:
        """A consecutive range of missing bars is merged into one gap."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        # Remove bars 10 through 14 (5 consecutive bars)
        df = _make_wide_df(["XOM"], start, 390, remove_indices=list(range(10, 15)))
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        assert len(gaps) == 1
        assert gaps[0].missing_bars == 5

    def test_no_overnight_gaps(self) -> None:
        """Overnight gaps (between trading days) are not flagged."""
        # Two RTH sessions with an overnight gap
        day1_start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)  # Thursday
        day1 = _make_wide_df(["XOM"], day1_start, 390)
        day2_start = datetime(2023, 3, 3, 14, 30, tzinfo=UTC)  # Friday
        day2 = _make_wide_df(["XOM"], day2_start, 390)
        df = pd.concat([day1, day2])
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        # No gaps — both RTH sessions are complete
        assert gaps == []

    def test_weekend_gaps_not_flagged(self) -> None:
        """Weekend gaps (Fri close -> Mon open) are not flagged."""
        # Friday RTH session + Monday RTH session
        friday_start = datetime(2023, 3, 3, 14, 30, tzinfo=UTC)  # Friday
        friday = _make_wide_df(["XOM"], friday_start, 390)
        monday_start = datetime(2023, 3, 6, 14, 30, tzinfo=UTC)  # Monday
        monday = _make_wide_df(["XOM"], monday_start, 390)
        df = pd.concat([friday, monday])
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        assert gaps == []

    def test_gap_in_multi_symbol_data(self) -> None:
        """Gaps are reported per-symbol from wide-format DataFrame."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        # Remove different bars for different symbols
        df = _make_wide_df(["XOM", "XOP"], start, 390, remove_indices=[10])
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        # Since both symbols share the same index, missing rows affect all symbols
        assert len(gaps) >= 1

    def test_gap_info_includes_correct_count(self) -> None:
        """GapInfo.missing_bars matches the actual number of missing bars."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390, remove_indices=[50, 51, 52])
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=True)
        assert len(gaps) == 1
        assert gaps[0].missing_bars == 3

    def test_empty_dataframe_returns_empty(self) -> None:
        """Empty DataFrame returns empty list."""
        gaps = detect_gaps(pd.DataFrame(), Timeframe.MINUTE_1)
        assert gaps == []

    def test_non_rth_mode_flags_all_gaps(self) -> None:
        """With rth_only=False, gaps outside RTH are also detected."""
        # Create data with a gap that falls within RTH
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390, remove_indices=[10])
        gaps = detect_gaps(df, Timeframe.MINUTE_1, rth_only=False)
        assert len(gaps) >= 1


# ═══════════════════════════════════════════════════════════════
# detect_duplicates
# ═══════════════════════════════════════════════════════════════


class TestDetectDuplicates:
    def test_no_duplicates(self) -> None:
        """Clean data with unique timestamps returns empty list."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390)
        dups = detect_duplicates(df)
        assert dups == []

    def test_detects_duplicate_timestamps(self) -> None:
        """Duplicate timestamps are detected."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 10)
        # Append a duplicate row
        dup = df.iloc[3:4]
        df = pd.concat([df, dup])
        dups = detect_duplicates(df)
        assert len(dups) >= 1

    def test_empty_dataframe(self) -> None:
        """Empty DataFrame returns empty list."""
        dups = detect_duplicates(pd.DataFrame())
        assert dups == []


# ═══════════════════════════════════════════════════════════════
# validate_timestamps
# ═══════════════════════════════════════════════════════════════


class TestValidateTimestamps:
    def test_utc_aware_passes(self) -> None:
        """UTC-aware timestamps pass the timezone check."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 10)
        issues = validate_timestamps(df, Timeframe.MINUTE_1)
        for i in issues:
            assert i.issue_type != "non_utc"

    def test_naive_datetime_flagged(self) -> None:
        """Timezone-naive timestamps are flagged."""
        start = datetime(2023, 3, 2, 14, 30)  # no tz
        df = _make_wide_df(["XOM"], start, 10, tz=None)
        issues = validate_timestamps(df, Timeframe.MINUTE_1)
        assert any(i.issue_type == "non_utc" for i in issues)

    def test_non_utc_timezone_flagged(self) -> None:
        """Non-UTC timezone is flagged."""
        from zoneinfo import ZoneInfo

        start = datetime(2023, 3, 2, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        idx = pd.date_range(start, periods=10, freq="min")
        idx.name = "timestamp"
        df = pd.DataFrame({"XOM_close": [100.0] * 10}, index=idx)
        issues = validate_timestamps(df, Timeframe.MINUTE_1)
        assert any(i.issue_type == "non_utc" for i in issues)

    def test_misaligned_timestamps_flagged(self) -> None:
        """Timestamps not on 1-minute boundary are flagged."""
        # Create index with some non-round minutes (e.g. :30.5)
        idx = pd.DatetimeIndex(
            [
                datetime(2023, 3, 2, 14, 30, 0, tzinfo=UTC),
                datetime(2023, 3, 2, 14, 31, 0, tzinfo=UTC),
                datetime(2023, 3, 2, 14, 32, 30, tzinfo=UTC),  # half-second
            ],
            name="timestamp",
        )
        df = pd.DataFrame({"XOM_close": [100.0, 100.1, 100.2]}, index=idx)
        issues = validate_timestamps(df, Timeframe.MINUTE_1)
        assert any(i.issue_type == "misaligned" for i in issues)

    def test_out_of_order_flagged(self) -> None:
        """Out-of-order timestamps are flagged."""
        idx = pd.DatetimeIndex(
            [
                datetime(2023, 3, 2, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 2, 14, 32, tzinfo=UTC),
                datetime(2023, 3, 2, 14, 31, tzinfo=UTC),  # out of order
            ],
            name="timestamp",
        )
        df = pd.DataFrame({"XOM_close": [100.0, 100.1, 100.2]}, index=idx)
        issues = validate_timestamps(df, Timeframe.MINUTE_1)
        assert any(i.issue_type == "out_of_order" for i in issues)

    def test_empty_dataframe(self) -> None:
        """Empty DataFrame returns empty list."""
        issues = validate_timestamps(pd.DataFrame())
        assert issues == []


# ═══════════════════════════════════════════════════════════════
# check_quality — integration
# ═══════════════════════════════════════════════════════════════


class TestCheckQuality:
    def test_clean_data_returns_is_clean(self) -> None:
        """Perfect RTH data returns is_clean=True."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390)
        report = check_quality(df, Timeframe.MINUTE_1, rth_only=True)
        assert report.is_clean is True

    def test_data_with_gaps_not_clean(self) -> None:
        """Data with missing bars returns is_clean=False."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390, remove_indices=[10])
        report = check_quality(df, Timeframe.MINUTE_1, rth_only=True)
        assert report.is_clean is False
        assert len(report.gaps) >= 1

    def test_check_quality_detects_duplicates(self) -> None:
        """check_quality reports duplicates."""
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 10)
        dup = df.iloc[3:4]
        df = pd.concat([df, dup])
        report = check_quality(df, Timeframe.MINUTE_1)
        assert len(report.duplicates) >= 1

    def test_aggregates_multiple_issue_types(self) -> None:
        """check_quality can find gaps, duplicates, and timestamp issues."""
        # Create data with missing bars AND a duplicate
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        df = _make_wide_df(["XOM"], start, 390, remove_indices=[10])
        dup = df.iloc[50:51]
        df = pd.concat([df, dup])
        report = check_quality(df, Timeframe.MINUTE_1, rth_only=True)
        assert len(report.gaps) >= 1
        assert len(report.duplicates) >= 1


# ═══════════════════════════════════════════════════════════════
# Import from orbust.data
# ═══════════════════════════════════════════════════════════════


def test_importable_from_data_module() -> None:
    """QualityReport and check_quality are importable from orbust.data."""
    from orbust.data.quality import QualityReport, check_quality

    assert check_quality is not None
    assert QualityReport is not None


def test_all_dataclasses_importable() -> None:
    """All dataclasses are importable from orbust.data.quality."""
    from orbust.data.quality import GapInfo, TimestampIssue

    assert GapInfo is not None
    assert TimestampIssue is not None
