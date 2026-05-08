"""Integration tests for the data pipeline — fetch → cache → quality.

All tests use mocked HTTP responses and a real temporary filesystem for
the ParquetStore.  No real Alpaca API calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd

from orbust.data.alpaca import AlpacaFetcher
from orbust.data.quality import check_quality
from orbust.types import Timeframe

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

WINTER_START = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)  # 09:30 ET
WINTER_END = datetime(2023, 3, 2, 15, 29, tzinfo=UTC)  # 10:29 ET (60 bars)
TEST_BARS = 60


# ═══════════════════════════════════════════════════════════════
# Test: Full fetch → cache → read cycle
# ═══════════════════════════════════════════════════════════════


class TestFullFetchCacheReadCycle:
    """Verifies: Fetch -> write Parquet -> read back -> data matches."""

    def test_fetched_data_matches_cached_data(
        self, provider, mock_fetch_multi_symbol
    ) -> None:
        """Data returned by get_bars matches what the fetcher produced."""
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_fetch_multi_symbol):
            result = provider.get_bars(
                ["XOM", "CVX"], WINTER_START, WINTER_END, Timeframe.MINUTE_1
            )

        assert isinstance(result, pd.DataFrame)
        assert len(result) == TEST_BARS
        assert "XOM_close" in result.columns
        assert "CVX_close" in result.columns
        # Verify UTC DatetimeIndex
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_cached_data_persists_across_calls(
        self, provider, mock_fetch_multi_symbol
    ) -> None:
        """Data cached by one call is available to a subsequent call."""
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_fetch_multi_symbol):
            provider.get_bars(["XOM"], WINTER_START, WINTER_END, Timeframe.MINUTE_1)

        # Second call should read from cache (no fetch)
        with patch.object(AlpacaFetcher, "fetch_bars") as mock_fetch:
            result = provider.get_bars(
                ["XOM"], WINTER_START, WINTER_END, Timeframe.MINUTE_1
            )
        assert not mock_fetch.called
        assert len(result) == TEST_BARS


# ═══════════════════════════════════════════════════════════════
# Test: Partial cache → refetch only missing
# ═══════════════════════════════════════════════════════════════


class TestPartialCacheRefetch:
    """Verifies: Cached range + missing range -> only missing fetched."""

    def test_refetches_only_missing_range(
        self, provider, mock_fetch_multi_symbol
    ) -> None:
        """When first half is cached, only the second half is fetched."""
        mid = TEST_BARS // 2  # bar 30

        # Cache the first half via a direct store write
        first_half = mock_fetch_multi_symbol.iloc[:mid]
        store = provider._get_store(Timeframe.MINUTE_1)
        store.write(first_half)

        # Request full range — should only fetch the missing second half
        second_half = mock_fetch_multi_symbol.iloc[mid:]
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=second_half) as mock_fetch:
            result = provider.get_bars(
                ["XOM"], WINTER_START, WINTER_END, Timeframe.MINUTE_1
            )

        mock_fetch.assert_called_once()
        assert len(result) == TEST_BARS


# ═══════════════════════════════════════════════════════════════
# Test: RTH filtering end-to-end
# ═══════════════════════════════════════════════════════════════


class TestRthFilteringEndToEnd:
    """Verifies: Raw data with extended hours -> filtered to RTH bars."""

    def test_rth_filters_extended_hours(self, provider_rth) -> None:
        """Extended-hours data is filtered to RTH only."""
        start = datetime(2023, 3, 2, 13, 0, tzinfo=UTC)  # 08:00 ET
        end = datetime(2023, 3, 2, 22, 0, tzinfo=UTC)  # 17:00 ET
        mock_df = _make_extended_df(start, 540)

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = provider_rth.get_bars(
                ["XOM"], start, end, Timeframe.MINUTE_1
            )

        # RTH on March 2 (EST): 14:30-20:59 UTC = 390 bars
        assert len(result) == 390
        assert result.index[0].hour == 14
        assert result.index[0].minute == 30
        assert result.index[-1].hour == 20
        assert result.index[-1].minute == 59

    def test_rth_disabled_returns_all_bars(self, provider) -> None:
        """With rth_only=False, all bars including extended hours returned."""
        start = datetime(2023, 3, 2, 13, 0, tzinfo=UTC)
        end = datetime(2023, 3, 2, 22, 0, tzinfo=UTC)
        mock_df = _make_extended_df(start, 540)

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = provider.get_bars(["XOM"], start, end, Timeframe.MINUTE_1)

        assert len(result) == 540  # no filtering


# ═══════════════════════════════════════════════════════════════
# Test: Quality on clean data
# ═══════════════════════════════════════════════════════════════


class TestQualityOnCleanData:
    """Verifies: Clean fetched data passes all quality checks."""

    def test_clean_pipeline_data_passes_quality(
        self, provider
    ) -> None:
        """Data from the pipeline with no gaps passes quality checks."""
        # Full RTH session (390 bars) to match quality check expectations
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        end = datetime(2023, 3, 2, 20, 59, tzinfo=UTC)
        mock_df = _make_full_rth_df("XOM", start)
        assert len(mock_df) == 390

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = provider.get_bars(
                ["XOM"], start, end, Timeframe.MINUTE_1
            )

        report = check_quality(result, Timeframe.MINUTE_1, rth_only=True)
        assert report.is_clean is True, f"Quality issues: {report}"


# ═══════════════════════════════════════════════════════════════
# Test: Quality on gapped data
# ═══════════════════════════════════════════════════════════════


class TestQualityOnGappedData:
    """Verifies: Data with intentional gaps detected correctly."""

    def test_gaps_in_pipeline_data_detected(
        self, provider
    ) -> None:
        """Data with missing bars produces quality report with gaps."""
        # Full RTH session with 5 bars removed
        start = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)
        end = datetime(2023, 3, 2, 20, 59, tzinfo=UTC)
        full = _make_full_rth_df("XOM", start)
        gapped = full.drop(full.index[10:15])

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=gapped):
            result = provider.get_bars(
                ["XOM"], start, end, Timeframe.MINUTE_1
            )

        report = check_quality(result, Timeframe.MINUTE_1, rth_only=True)
        assert report.is_clean is False
        assert len(report.gaps) >= 1
        # The gap should be 5 missing bars
        found = False
        for g in report.gaps:
            if g.missing_bars == 5:
                found = True
                break
        assert found, f"Expected gap of 5 bars, got: {report.gaps}"


# ═══════════════════════════════════════════════════════════════
# Test: Multi-symbol temporal alignment
# ═══════════════════════════════════════════════════════════════


class TestMultiSymbolTemporalAlignment:
    """Verifies: Multiple symbols share identical timestamp index."""

    def test_symbols_have_identical_index(
        self, provider, mock_fetch_multi_symbol
    ) -> None:
        """All symbols returned by get_bars share the same timestamps."""
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_fetch_multi_symbol):
            result = provider.get_bars(
                ["XOM", "CVX"], WINTER_START, WINTER_END, Timeframe.MINUTE_1
            )

        assert len(result.index) == TEST_BARS
        # No NaN for any field since all symbols have data
        assert not result.isnull().any().any()


# ═══════════════════════════════════════════════════════════════
# Test: DST transition handling
# ═══════════════════════════════════════════════════════════════


class TestDstTransitionHandling:
    """Verifies: Data spanning DST change has correct RTH boundaries."""

    # Spring forward: 2023-03-13 (Monday after DST)
    SPRING_START = datetime(2023, 3, 13, 13, 0, tzinfo=UTC)  # 09:00 EDT
    SPRING_END = datetime(2023, 3, 13, 21, 0, tzinfo=UTC)  # 17:00 EDT

    # Fall back: 2023-11-06 (Monday after DST ends)
    FALL_START = datetime(2023, 11, 6, 14, 0, tzinfo=UTC)  # 09:00 EST
    FALL_END = datetime(2023, 11, 6, 22, 0, tzinfo=UTC)  # 17:00 EST

    def test_spring_dst_rth_boundary(self, provider_rth) -> None:
        """Spring-forward day has correct RTH boundary (13:30 UTC open)."""
        mock_df = _make_extended_df(self.SPRING_START, 480)

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = provider_rth.get_bars(
                ["XOM"], self.SPRING_START, self.SPRING_END, Timeframe.MINUTE_1
            )

        # First RTH bar should be at 13:30 UTC (09:30 EDT)
        assert len(result) > 0
        assert result.index[0].hour == 13
        assert result.index[0].minute == 30

    def test_fall_dst_rth_boundary(self, provider_rth) -> None:
        """Fall-back day has correct RTH boundary (14:30 UTC open)."""
        mock_df = _make_extended_df(self.FALL_START, 480)

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = provider_rth.get_bars(
                ["XOM"], self.FALL_START, self.FALL_END, Timeframe.MINUTE_1
            )

        # First RTH bar should be at 14:30 UTC (09:30 EST)
        assert len(result) > 0
        assert result.index[0].hour == 14
        assert result.index[0].minute == 30


# ═══════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════


def _make_extended_df(start: datetime, periods: int) -> pd.DataFrame:
    """Create a DataFrame spanning pre-market + RTH + after-hours."""
    idx = pd.date_range(start, periods=periods, freq="min", tz="UTC")
    idx.name = "timestamp"
    all_fields = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]
    data: dict[str, list[float]] = {}
    for field in all_fields:
        data[f"XOM_{field}"] = [100.0] * periods
    return pd.DataFrame(data, index=idx)


def _make_full_rth_df(symbol: str, start: datetime) -> pd.DataFrame:
    """Create a complete 390-bar RTH session DataFrame."""
    idx = pd.date_range(start, periods=390, freq="min", tz="UTC")
    idx.name = "timestamp"
    all_fields = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]
    data: dict[str, list[float]] = {}
    for field in all_fields:
        data[f"{symbol}_{field}"] = [100.0] * 390
    return pd.DataFrame(data, index=idx)
