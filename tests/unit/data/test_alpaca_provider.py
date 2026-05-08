"""Tests for AlpacaBarProvider — caching, RTH filtering, data format."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd
import pytest

from orbust.config import AlpacaConfig, DataPaths, SystemConfig
from orbust.data.alpaca import ALL_FIELDS, AlpacaBarProvider, AlpacaFetcher
from orbust.types import Timeframe

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _make_bars_df(
    symbols: list[str],
    start: datetime,
    periods: int,
) -> pd.DataFrame:
    """Create a wide-format bar DataFrame matching Alpaca output."""
    idx = pd.date_range(start, periods=periods, freq="min", tz="UTC")
    idx.name = "timestamp"
    data: dict[str, list[float]] = {}
    base_price = 100.0
    for sym in symbols:
        for field in ALL_FIELDS:
            data[f"{sym}_{field}"] = [base_price] * periods
        base_price += 50.0
    return pd.DataFrame(data, index=idx)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def alpaca_provider(tmp_path) -> AlpacaBarProvider:
    """AlpacaBarProvider with temp data dir and no RTH."""
    config = SystemConfig(
        alpaca=AlpacaConfig(key_id="test", secret_key="test"),
        data=DataPaths(data_dir=str(tmp_path)),
    )
    return AlpacaBarProvider(config, rth_only=False)


@pytest.fixture
def alpaca_provider_rth(tmp_path) -> AlpacaBarProvider:
    """AlpacaBarProvider with RTH filtering enabled."""
    config = SystemConfig(
        alpaca=AlpacaConfig(key_id="test", secret_key="test"),
        data=DataPaths(data_dir=str(tmp_path)),
    )
    return AlpacaBarProvider(config, rth_only=True)


# ═══════════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════════


class TestConstruction:
    def test_accepts_system_config(self, tmp_path) -> None:
        """Can instantiate with SystemConfig."""
        config = SystemConfig(
            alpaca=AlpacaConfig(key_id="test", secret_key="test"),
            data=DataPaths(data_dir=str(tmp_path)),
        )
        provider = AlpacaBarProvider(config)
        assert provider._config is config
        assert provider._rth_only is True  # default

    def test_rth_only_default(self, tmp_path) -> None:
        """Default rth_only is True."""
        config = SystemConfig(
            alpaca=AlpacaConfig(key_id="test", secret_key="test"),
            data=DataPaths(data_dir=str(tmp_path)),
        )
        provider = AlpacaBarProvider(config)
        assert provider._rth_only is True

    def test_rth_only_false(self, tmp_path) -> None:
        """Can disable RTH filtering."""
        config = SystemConfig(
            alpaca=AlpacaConfig(key_id="test", secret_key="test"),
            data=DataPaths(data_dir=str(tmp_path)),
        )
        provider = AlpacaBarProvider(config, rth_only=False)
        assert provider._rth_only is False

    def test_creates_fetcher_with_alpaca_config(self, tmp_path) -> None:
        """Internal AlpacaFetcher receives the alpaca config."""
        config = SystemConfig(
            alpaca=AlpacaConfig(key_id="test_key", secret_key="test_secret"),
            data=DataPaths(data_dir=str(tmp_path)),
        )
        provider = AlpacaBarProvider(config)
        assert provider._fetcher._config.key_id == "test_key"
        assert provider._fetcher._config.secret_key == "test_secret"

    def test_store_created_lazily(self, alpaca_provider) -> None:
        """ParquetStore instances are created lazily per timeframe."""
        assert len(alpaca_provider._stores) == 0
        store = alpaca_provider._get_store(Timeframe.MINUTE_1)
        assert store is not None
        assert Timeframe.MINUTE_1 in alpaca_provider._stores
        # Same store returned on second call
        assert alpaca_provider._get_store(Timeframe.MINUTE_1) is store

    def test_provider_is_context_manager(self, tmp_path) -> None:
        """AlpacaBarProvider supports context manager protocol."""
        config = SystemConfig(
            alpaca=AlpacaConfig(key_id="test", secret_key="test"),
            data=DataPaths(data_dir=str(tmp_path)),
        )
        with AlpacaBarProvider(config) as provider:
            assert isinstance(provider, AlpacaBarProvider)
        # Context manager exits without error


# ═══════════════════════════════════════════════════════════════
# available_fields
# ═══════════════════════════════════════════════════════════════


class TestAvailableFields:
    def test_returns_all_7_fields(self, alpaca_provider) -> None:
        """available_fields returns all 7 bar fields."""
        fields = alpaca_provider.available_fields()
        assert len(fields) == 7
        assert "open" in fields
        assert "high" in fields
        assert "low" in fields
        assert "close" in fields
        assert "volume" in fields
        assert "trade_count" in fields
        assert "vwap" in fields


# ═══════════════════════════════════════════════════════════════
# stream_bars
# ═══════════════════════════════════════════════════════════════


class TestStreamBars:
    def test_raises_not_implemented(self, alpaca_provider) -> None:
        """stream_bars raises NotImplementedError (Phase 2 placeholder)."""
        with pytest.raises(NotImplementedError, match="not implemented"):
            alpaca_provider.stream_bars(["XOM"], Timeframe.MINUTE_1)


# ═══════════════════════════════════════════════════════════════
# get_bars — caching behavior
# ═══════════════════════════════════════════════════════════════


class TestGetBarsCaching:
    """get_bars caching: full hit, partial hit, full miss."""

    START = datetime(2023, 3, 1, 14, 30, tzinfo=UTC)  # 09:30 ET
    # 30 bars: 14:30 -> 14:59.  END aligns with the last bar.
    END = datetime(2023, 3, 1, 14, 59, tzinfo=UTC)  # 09:59 ET

    def test_cache_hit_no_api_call(self, alpaca_provider) -> None:
        """Fully cached range returns from cache without calling Alpaca."""
        # Pre-seed the cache
        df = _make_bars_df(["XOM"], self.START, 30)
        store = alpaca_provider._get_store(Timeframe.MINUTE_1)
        store.write(df)

        with patch.object(AlpacaFetcher, "fetch_bars") as mock_fetch:
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)

        assert not mock_fetch.called, "Alpaca should not be called on cache hit"
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 30
        assert "XOM_close" in result.columns

    def test_cache_miss_fetches_from_alpaca(self, alpaca_provider) -> None:
        """Empty cache fetches from Alpaca and caches the result."""
        mock_df = _make_bars_df(["XOM"], self.START, 30)

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df) as mock_fetch:
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)

        mock_fetch.assert_called_once()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 30
        assert "XOM_close" in result.columns

    def test_partial_cache_fetches_only_missing(self, alpaca_provider) -> None:
        """Partially cached data fetches only the missing sub-range."""
        # Cache the first 15 minutes
        cached_df = _make_bars_df(["XOM"], self.START, 15)
        store = alpaca_provider._get_store(Timeframe.MINUTE_1)
        store.write(cached_df)

        # Request full 30 minutes — need to fetch the remaining 15
        missing_start = datetime(2023, 3, 1, 14, 45, tzinfo=UTC)
        mock_df = _make_bars_df(["XOM"], missing_start, 15)

        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df) as mock_fetch:
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)

        mock_fetch.assert_called_once()
        # Verify the fetch was for the missing range
        call_args = mock_fetch.call_args[0]
        assert len(call_args[0]) == 1  # symbols
        # The fetch range should be close to the missing part
        fetched_start = call_args[1]
        assert fetched_start >= missing_start - pd.Timedelta(minutes=1)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 30
        assert "XOM_close" in result.columns

    def test_no_data_returns_empty_dataframe(self, alpaca_provider) -> None:
        """When neither cache nor Alpaca has data, returns empty DataFrame."""
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=pd.DataFrame()):
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        # Should still have the expected columns
        assert "XOM_close" in result.columns
        assert "XOM_open" in result.columns
        assert result.index.tz is not None

    def test_multiple_symbols_cached(self, alpaca_provider) -> None:
        """Multi-symbol query returns all symbols with correct columns."""
        df = _make_bars_df(["XOM", "XOP"], self.START, 30)
        store = alpaca_provider._get_store(Timeframe.MINUTE_1)
        store.write(df)

        with patch.object(AlpacaFetcher, "fetch_bars") as mock_fetch:
            result = alpaca_provider.get_bars(
                ["XOM", "XOP"], self.START, self.END, Timeframe.MINUTE_1
            )

        assert not mock_fetch.called
        assert "XOM_close" in result.columns
        assert "XOP_close" in result.columns
        assert len(result) == 30

    def test_subsequent_call_uses_cache(self, alpaca_provider) -> None:
        """Second call with same range is a cache hit."""
        # First call: cache miss
        mock_df = _make_bars_df(["XOM"], self.START, 30)
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)

        # Second call: cache hit
        with patch.object(AlpacaFetcher, "fetch_bars") as mock_fetch:
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)
        assert not mock_fetch.called
        assert len(result) == 30

    def test_different_timeframe_separate_cache(self, alpaca_provider) -> None:
        """Different timeframes use separate ParquetStore instances."""
        # Cache 1-min data
        df_1min = _make_bars_df(["XOM"], self.START, 30)
        store_1min = alpaca_provider._get_store(Timeframe.MINUTE_1)
        store_1min.write(df_1min)

        # Request 5-min data (different store, should be cache miss)
        mock_5min = _make_bars_df(["XOM"], self.START, 6)
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_5min) as mock_fetch:
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_5)

        mock_fetch.assert_called_once()
        assert len(result) == 6


# ═══════════════════════════════════════════════════════════════
# get_bars — RTH filtering
# ═══════════════════════════════════════════════════════════════


class TestGetBarsRthFiltering:
    def test_rth_only_filters_non_rth_bars(self, alpaca_provider_rth, tmp_path) -> None:
        """RTH filtering removes pre-market and after-hours bars."""
        # Cache data that spans pre-market + RTH + after-hours
        start = datetime(2023, 3, 1, 13, 0, tzinfo=UTC)  # 08:00 ET
        # 540 bars: 13:00 -> 21:59.  end aligns with the last bar.
        end = datetime(2023, 3, 1, 21, 59, tzinfo=UTC)  # 16:59 ET
        full_df = _make_bars_df(["XOM"], start, 540)
        store = alpaca_provider_rth._get_store(Timeframe.MINUTE_1)
        store.write(full_df)

        with patch.object(AlpacaFetcher, "fetch_bars") as mock_fetch:
            result = alpaca_provider_rth.get_bars(["XOM"], start, end, Timeframe.MINUTE_1)

        assert not mock_fetch.called
        assert len(result) < 540  # RTH filtered
        # First bar should be at 14:30 UTC (09:30 ET)
        assert result.index[0].hour == 14
        assert result.index[0].minute == 30

    def test_rth_only_disabled_returns_all_bars(self, alpaca_provider, tmp_path) -> None:
        """rth_only=False returns all bars including pre/after-market."""
        start = datetime(2023, 3, 1, 13, 0, tzinfo=UTC)  # 08:00 ET
        # 540 bars: 13:00 -> 21:59.  end aligns with the last bar.
        end = datetime(2023, 3, 1, 21, 59, tzinfo=UTC)  # 16:59 ET
        full_df = _make_bars_df(["XOM"], start, 540)
        store = alpaca_provider._get_store(Timeframe.MINUTE_1)
        store.write(full_df)

        with patch.object(AlpacaFetcher, "fetch_bars") as mock_fetch:
            result = alpaca_provider.get_bars(["XOM"], start, end, Timeframe.MINUTE_1)

        assert not mock_fetch.called
        assert len(result) == 540  # No filtering


# ═══════════════════════════════════════════════════════════════
# get_bars — data format
# ═══════════════════════════════════════════════════════════════


class TestGetBarsDataFormat:
    """get_bars returns data in the expected format."""

    START = datetime(2023, 3, 1, 14, 30, tzinfo=UTC)
    END = datetime(2023, 3, 1, 15, 0, tzinfo=UTC)

    def test_utc_datetimeindex(self, alpaca_provider) -> None:
        """Returned DataFrame has UTC-aware DatetimeIndex."""
        mock_df = _make_bars_df(["XOM"], self.START, 30)
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_column_naming_convention(self, alpaca_provider) -> None:
        """Columns use {SYM}_{field} format."""
        mock_df = _make_bars_df(["XOM"], self.START, 30)
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)
        for col in result.columns:
            assert "_" in col
            assert col.startswith("XOM_")

    def test_temporal_alignment(self, alpaca_provider) -> None:
        """All symbols share the same timestamp index."""
        mock_df = _make_bars_df(["XOM", "XOP"], self.START, 30)
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = alpaca_provider.get_bars(
                ["XOM", "XOP"], self.START, self.END, Timeframe.MINUTE_1
            )
        # Verify all timestamps are the same shape
        assert len(result.index) == 30
        # No NaN should exist because all symbols have data
        assert not result.isnull().any().any()

    def test_index_has_name(self, alpaca_provider) -> None:
        """DatetimeIndex has a name attribute."""
        mock_df = _make_bars_df(["XOM"], self.START, 30)
        with patch.object(AlpacaFetcher, "fetch_bars", return_value=mock_df):
            result = alpaca_provider.get_bars(["XOM"], self.START, self.END, Timeframe.MINUTE_1)
        assert result.index.name is not None


# ═══════════════════════════════════════════════════════════════
# Import from orbust.data
# ═══════════════════════════════════════════════════════════════


def test_importable_from_data_module() -> None:
    """AlpacaBarProvider is importable from orbust.data."""
    from orbust.data import AlpacaBarProvider

    assert AlpacaBarProvider is not None
