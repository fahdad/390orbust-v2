"""Tests for notebook helper functions — quick_fetch, summarize, check."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from orbust.data.notebook import check, quick_fetch, summarize
from orbust.data.quality import QualityReport
from orbust.types import Timeframe


def _make_sample_df() -> pd.DataFrame:
    """Create a sample bar DataFrame for testing."""
    idx = pd.date_range(
        datetime(2023, 3, 2, 14, 30, tzinfo=UTC),
        periods=390,
        freq="min",
        tz="UTC",
    )
    idx.name = "timestamp"
    data: dict[str, list[float]] = {}
    for sym in ("XOM", "CVX"):
        for field in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
            data[f"{sym}_{field}"] = [100.0] * 390
    return pd.DataFrame(data, index=idx)


class TestQuickFetch:
    """quick_fetch is importable and returns expected types."""

    def test_importable(self) -> None:
        """quick_fetch is importable from orbust.data.notebook."""
        from orbust.data.notebook import quick_fetch

        assert quick_fetch is not None

    def test_signature_has_defaults(self) -> None:
        """quick_fetch has the expected parameter defaults."""
        import inspect

        sig = inspect.signature(quick_fetch)
        assert "symbols" in sig.parameters
        assert "days_back" in sig.parameters
        assert "timeframe" in sig.parameters
        # Check defaults
        assert sig.parameters["days_back"].default == 5
        assert sig.parameters["timeframe"].default == Timeframe.MINUTE_1


class TestSummarize:
    """summarize returns correct summary statistics."""

    def test_returns_dataframe(self) -> None:
        """summarize returns a DataFrame."""
        df = _make_sample_df()
        result = summarize(df)
        assert isinstance(result, pd.DataFrame)

    def test_has_expected_columns(self) -> None:
        """Summary has symbol, rows, start, end, completeness_pct, gap_segments."""
        df = _make_sample_df()
        result = summarize(df)
        expected = {"symbol", "rows", "start", "end", "completeness_pct", "gap_segments"}
        assert expected.issubset(set(result.columns))

    def test_one_row_per_symbol(self) -> None:
        """Summary has one row per symbol."""
        df = _make_sample_df()
        result = summarize(df)
        assert len(result) == 2  # XOM, CVX
        assert result.iloc[0]["symbol"] == "CVX" or result.iloc[0]["symbol"] == "XOM"

    def test_completeness_for_full_rth_day(self) -> None:
        """Full RTH session shows 100% completeness."""
        df = _make_sample_df()
        result = summarize(df)
        # 390 bars / 390 expected = 100%
        assert result.iloc[0]["completeness_pct"] == 100.0

    def test_empty_dataframe_returns_empty_summary(self) -> None:
        """Empty DataFrame returns empty summary."""
        df = pd.DataFrame()
        result = summarize(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


class TestCheck:
    """check wraps check_quality with sensible defaults."""

    def test_returns_quality_report(self) -> None:
        """check returns a QualityReport instance."""
        df = _make_sample_df()
        report = check(df)
        assert isinstance(report, QualityReport)

    def test_clean_data(self) -> None:
        """Clean RTH data passes check."""
        df = _make_sample_df()
        report = check(df)
        assert report.is_clean is True

    def test_detects_gaps(self) -> None:
        """Data with missing bars is detected."""
        df = _make_sample_df()
        gapped = df.drop(df.index[10:15])
        report = check(gapped)
        assert report.is_clean is False
        assert len(report.gaps) >= 1


def test_importable_from_data_module() -> None:
    """Notebook helpers are importable from orbust.data."""
    from orbust.data import check, quick_fetch, summarize

    assert quick_fetch is not None
    assert summarize is not None
    assert check is not None
