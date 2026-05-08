"""Data quality checks for bar DataFrames.

Detects gaps, duplicates, timestamp anomalies, and aggregates results
into a structured ``QualityReport``.

All functions work with wide-format DataFrames (``{SYM}_{field}`` columns)
with a ``DatetimeIndex``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from orbust.data.rth import filter_rth
from orbust.types import Timeframe

if TYPE_CHECKING:
    pass

# ═══════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════


@dataclass
class GapInfo:
    """A gap in bar data for a single symbol.

    Attributes:
        symbol: Ticker symbol missing bars.
        gap_start: Start of the missing range (UTC, inclusive).
        gap_end: End of the missing range (UTC, exclusive).
        missing_bars: Number of bars expected but not present.
    """

    symbol: str
    gap_start: datetime
    gap_end: datetime
    missing_bars: int


@dataclass
class TimestampIssue:
    """An issue with a specific timestamp in the data.

    Attributes:
        timestamp: The problematic timestamp.
        issue_type: Short identifier (e.g. ``non_utc``, ``misaligned``,
            ``out_of_order``).
        detail: Human-readable explanation.
    """

    timestamp: datetime
    issue_type: str
    detail: str


@dataclass
class QualityReport:
    """Aggregated results from all quality checks.

    Attributes:
        gaps: Detected gaps in bar coverage per symbol.
        duplicates: Timestamps that appear more than once.
        timestamp_issues: Anomalies in timestamp metadata.
        is_clean: ``True`` when no issues were found.
    """

    gaps: list[GapInfo] = field(default_factory=list)
    duplicates: list[datetime] = field(default_factory=list)
    timestamp_issues: list[TimestampIssue] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.gaps or self.duplicates or self.timestamp_issues)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════


def check_quality(
    df: pd.DataFrame,
    timeframe: Timeframe,
    rth_only: bool = True,
) -> QualityReport:
    """Run all quality checks on a bar DataFrame.

    Args:
        df: Wide-format bar DataFrame with ``DatetimeIndex``.
        timeframe: Bar aggregation period (e.g. ``Timeframe.MINUTE_1``).
        rth_only: When ``True``, gap detection only checks RTH minutes.

    Returns:
        A ``QualityReport`` with all findings.
    """
    gaps = detect_gaps(df, timeframe, rth_only=rth_only)
    duplicates = detect_duplicates(df)
    timestamp_issues = validate_timestamps(df, timeframe)

    return QualityReport(
        gaps=gaps,
        duplicates=duplicates,
        timestamp_issues=timestamp_issues,
    )


def detect_gaps(
    df: pd.DataFrame,
    timeframe: Timeframe,
    rth_only: bool = True,
) -> list[GapInfo]:
    """Find missing bars within expected trading hours.

    Compares the timestamps present in *df* against the set of expected
    timestamps (RTH minutes when ``rth_only=True``, full 24h range
    otherwise).  Consecutive missing minutes are merged into a single
    ``GapInfo`` with an accurate ``missing_bars`` count.

    Overnight and weekend gaps are never flagged — the range is constrained
    to expected trading periods.

    Args:
        df: Wide-format bar DataFrame with ``DatetimeIndex``.
        timeframe: Bar aggregation period.
        rth_only: When ``True``, only check RTH minutes.

    Returns:
        List of ``GapInfo``, one per gap per symbol.
    """
    if df.empty:
        return []

    # Collect symbols from column names
    symbols = _extract_symbols(df.columns)
    if not symbols:
        return []

    # Determine expected timestamps for the date range
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    if str(idx.tz) != "UTC":
        idx = idx.tz_convert("UTC")

    start_date = idx.min().date()
    end_date = idx.max().date()

    # Build the set of expected timestamps
    expected = _expected_timestamps(start_date, end_date, timeframe, rth_only)
    if not expected:
        return []

    # Drop tz info for comparison to handle both naive and aware indices consistently
    idx_naive = idx.tz_localize(None) if idx.tz is not None else idx
    actual_set = set(idx_naive)
    timedelta_step = _timeframe_delta(timeframe)

    # Compute index-level gaps ONCE (all symbols share the index)
    missing_timestamps = sorted(expected - actual_set)
    index_gaps: list[tuple[datetime, datetime, int]] = []
    if missing_timestamps:
        gap_start = missing_timestamps[0]
        prev = gap_start
        count = 1
        for ts in missing_timestamps[1:]:
            if ts - prev == timedelta_step:
                count += 1
            else:
                index_gaps.append((gap_start, prev + timedelta_step, count))
                gap_start = ts
                count = 1
            prev = ts
        index_gaps.append((gap_start, prev + timedelta_step, count))

    # Emit one GapInfo per symbol per gap
    results: list[GapInfo] = []
    for sym in symbols:
        for gs, ge, cnt in index_gaps:
            results.append(
                GapInfo(
                    symbol=sym,
                    gap_start=gs,
                    gap_end=ge,
                    missing_bars=cnt,
                )
            )
    return results


def detect_duplicates(df: pd.DataFrame) -> list[datetime]:
    """Find timestamps that appear more than once in the index.

    Args:
        df: Bar DataFrame with ``DatetimeIndex``.

    Returns:
        List of duplicate timestamps (sorted, deduplicated).
    """
    if df.empty:
        return []

    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")

    dups = idx[idx.duplicated(keep="first")]
    return sorted(set(dups))


def validate_timestamps(
    df: pd.DataFrame,
    timeframe: Timeframe | None = None,
) -> list[TimestampIssue]:
    """Check timestamp metadata for anomalies.

    Checks performed:
    - Non-UTC timezone (expects UTC-aware)
    - Timestamps not aligned to the *timeframe* boundary
    - Index not sorted (out-of-order timestamps)

    Args:
        df: Bar DataFrame with ``DatetimeIndex``.
        timeframe: Optional — when provided, checks alignment to the
            timeframe boundary (e.g. 1-minute boundaries for 1Min data).

    Returns:
        List of ``TimestampIssue``, empty if all checks pass.
    """
    if df.empty:
        return []

    idx = df.index
    issues: list[TimestampIssue] = []

    # Check timezone
    if idx.tz is None:
        issues.append(
            TimestampIssue(
                timestamp=idx[0],
                issue_type="non_utc",
                detail="DatetimeIndex is timezone-naive; expected UTC",
            )
        )
    elif str(idx.tz) != "UTC":
        issues.append(
            TimestampIssue(
                timestamp=idx[0],
                issue_type="non_utc",
                detail=f"DatetimeIndex is {idx.tz}; expected UTC",
            )
        )

    # Check alignment to timeframe boundary
    if timeframe is not None:
        delta = _timeframe_delta(timeframe)
        delta_ns = int(delta.total_seconds() * 1_000_000_000)
        # Ensure index is UTC for consistent comparison
        utc_idx = idx.tz_convert("UTC") if idx.tz is not None else idx
        # Check alignment relative to the first timestamp (avoids epoch drift)
        # NOTE: .asi8 gives int64 in the index's native resolution (us or ns)
        offset_ns = (utc_idx.asi8 - utc_idx.asi8[0]) * 1000
        misaligned_mask = (offset_ns % delta_ns) != 0
        misaligned = idx[misaligned_mask].tolist()
        if misaligned:
            issues.append(
                TimestampIssue(
                    timestamp=misaligned[0],
                    issue_type="misaligned",
                    detail=f"{len(misaligned)} timestamps not aligned to "
                    f"{delta.total_seconds():.0f}s boundary "
                    f"(e.g. {misaligned[0]})",
                )
            )

    # Check sort order
    if not idx.is_monotonic_increasing:
        out_of_order = [(i, ts) for i, ts in enumerate(idx) if i > 0 and ts < idx[i - 1]]
        if out_of_order:
            issues.append(
                TimestampIssue(
                    timestamp=out_of_order[0][1],
                    issue_type="out_of_order",
                    detail=f"Index is not sorted — first break at row "
                    f"{out_of_order[0][0]} ({out_of_order[0][1]})",
                )
            )

    return issues


# ═══════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════


def _extract_symbols(columns: pd.Index) -> list[str]:
    """Extract unique ticker symbols from wide-format column names.

    Columns follow the ``{SYM}_{field}`` convention.  Non-standard
    columns (e.g. ``day_of_year``) are ignored.
    """
    _known_fields = {"open", "high", "low", "close", "volume", "trade_count", "vwap"}
    symbols: list[str] = []
    seen: set[str] = set()
    for col in columns:
        for fld in _known_fields:
            suffix = f"_{fld}"
            if col.endswith(suffix):
                sym = col[: -len(suffix)]
                if sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)
                break
    return symbols


def _expected_timestamps(
    start_date: date,
    end_date: date,
    timeframe: Timeframe,
    rth_only: bool,
) -> set[datetime]:
    """Build the set of expected UTC timestamps for a date range."""
    delta = _timeframe_delta(timeframe)
    # Generate range covering the full days in UTC
    idx = pd.date_range(
        start=pd.Timestamp(start_date, tz="UTC"),
        end=pd.Timestamp(end_date, tz="UTC") + timedelta(days=1),
        freq=delta,
        inclusive="left",
    )

    if rth_only:
        idx = filter_rth(pd.DataFrame(index=idx)).index

    # Return as naive UTC datetimes for comparison with localized-to-naive index
    return set(idx.tz_localize(None))


def _timeframe_delta(timeframe: Timeframe) -> timedelta:
    """Convert a ``Timeframe`` enum to a ``timedelta``."""
    mapping = {
        Timeframe.MINUTE_1: timedelta(minutes=1),
        Timeframe.MINUTE_5: timedelta(minutes=5),
        Timeframe.MINUTE_15: timedelta(minutes=15),
        Timeframe.DAY: timedelta(days=1),
    }
    return mapping[timeframe]
