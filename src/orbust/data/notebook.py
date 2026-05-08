"""Notebook-friendly helpers for quick data exploration in Jupyter.

Provides one-liner functions for fetching, inspecting, and checking
bar data quality without boilerplate.

Usage in a notebook::

    from orbust.data.notebook import quick_fetch, summarize, check

    df = quick_fetch(["XOM", "CVX"], days_back=5)
    summarize(df)
    check(df)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from orbust.config import SystemConfig
from orbust.data.alpaca import AlpacaBarProvider
from orbust.data.quality import QualityReport, check_quality
from orbust.types import Timeframe


def quick_fetch(
    symbols: list[str],
    days_back: int = 5,
    timeframe: Timeframe = Timeframe.MINUTE_1,
) -> pd.DataFrame:
    """Fetch recent bar data for one or more symbols.

    Creates an ``AlpacaBarProvider`` from the default system config
    (``config/system.yaml``) and fetches *days_back* of trading data.

    Args:
        symbols: List of ticker symbols (e.g. ``["XOM", "CVX"]``).
        days_back: Number of trading days to fetch (default 5).
        timeframe: Bar aggregation period (default 1-minute).

    Returns:
        Wide-format DataFrame with UTC DatetimeIndex and
        ``{SYM}_{field}`` columns.
    """
    config = SystemConfig.load()
    end = datetime.now(UTC)
    start = end - timedelta(days=days_back * 2)  # generous window

    with AlpacaBarProvider(config, rth_only=True) as provider:
        return provider.get_bars(symbols, start, end, timeframe)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Print and return per-symbol summary statistics.

    Computes for each symbol: row count, date range, completeness
    percentage (actual bars vs expected RTH bars), and the number of
    gap-free segments.

    Args:
        df: Wide-format bar DataFrame with ``DatetimeIndex``.

    Returns:
        DataFrame with one row per symbol and columns:
        ``symbol``, ``rows``, ``start``, ``end``, ``completeness_pct``,
        ``gap_segments``.
    """
    if df.empty:
        result = pd.DataFrame(
            columns=["symbol", "rows", "start", "end", "completeness_pct", "gap_segments"]
        )
        print(result.to_string(index=False))
        return result

    # Extract symbols using known field names (avoids rsplit bug on trade_count)
    _known_fields = {"open", "high", "low", "close", "volume", "trade_count", "vwap"}
    symbols = sorted({
        c[: -len(sfx) - 1] for c in df.columns if "_" in c
        for sfx in _known_fields if c.endswith(f"_{sfx}")
    })
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")

    rows: list[dict] = []
    for sym in symbols:
        sym_cols = [c for c in df.columns if c.startswith(f"{sym}_")]
        if not sym_cols:
            continue

        # Count rows where this symbol has at least one non-NaN value
        sym_data = df[sym_cols]
        valid = sym_data.notna().any(axis=1)
        valid_count = valid.sum()

        # Estimate completeness
        days_covered = (idx.max().date() - idx.min().date()).days + 1
        expected_bars = days_covered * 390  # RTH bars per day
        completeness = min(100.0, round(valid_count / max(expected_bars, 1) * 100, 1))

        # Count gap segments (consecutive valid blocks)
        transitions = (valid != valid.shift(1)).sum()
        gap_segments = max(0, (transitions - 1) // 2)

        rows.append(
            {
                "symbol": sym,
                "rows": valid_count,
                "start": idx[valid].min().strftime("%Y-%m-%d %H:%M UTC"),
                "end": idx[valid].max().strftime("%Y-%m-%d %H:%M UTC"),
                "completeness_pct": completeness,
                "gap_segments": gap_segments,
            }
        )

    result = pd.DataFrame(rows)
    print(result.to_string(index=False))
    return result


def check(
    df: pd.DataFrame,
    timeframe: Timeframe = Timeframe.MINUTE_1,
) -> QualityReport:
    """Run quality checks on a bar DataFrame with sensible defaults.

    Wraps :func:`orbust.data.quality.check_quality` for quick notebook use.

    Args:
        df: Wide-format bar DataFrame.
        timeframe: Bar aggregation period (default 1-minute).

    Returns:
        A ``QualityReport`` instance.  Prints a summary when displayed
        in a notebook.
    """
    use_rth = _is_likely_rth_data(df)
    report = check_quality(df, timeframe, rth_only=use_rth)

    # Pretty print summary
    status = "CLEAN" if report.is_clean else "ISSUES FOUND"
    print(f"Quality: {status}")
    if report.gaps:
        total_missing = sum(g.missing_bars for g in report.gaps)
        print(f"  Gaps: {len(report.gaps)} gap(s), {total_missing} total missing bars")
    if report.duplicates:
        print(f"  Duplicates: {len(report.duplicates)} timestamp(s)")
    if report.timestamp_issues:
        print(f"  Timestamp issues: {len(report.timestamp_issues)}")

    return report


def _is_likely_rth_data(df: pd.DataFrame) -> bool:
    """Heuristic: if data spans more than 16h/day, assume full-day."""
    if df.empty or len(df) < 2:
        return True
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    span_hours = (idx.max() - idx.min()).total_seconds() / 3600
    days = max(1, (idx.max().date() - idx.min().date()).days)
    avg_hours_per_day = span_hours / days
    return avg_hours_per_day <= 16  # RTH is 6.5h, give headroom
