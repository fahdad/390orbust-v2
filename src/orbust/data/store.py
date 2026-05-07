"""Parquet-based market data store.

Writes and reads wide-format bar DataFrames to/from partitioned Parquet
files. One file per trading day per timeframe.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from orbust.types import Timeframe


class ParquetStore:
    """Persistent Parquet-backed storage for bar data.

    Stores data partitioned by date, one file per day. Files follow the
    naming convention: ``{timeframe}/{YYYY}/{MM}/{DD}.parquet``.
    """

    def __init__(self, base_dir: str | Path, timeframe: Timeframe) -> None:
        self._base = Path(base_dir)
        self._timeframe = timeframe

    # ── Public API ────────────────────────────────────────────────

    def write(self, df: pd.DataFrame, symbols: list[str] | None = None) -> list[Path]:
        """Write a wide-format DataFrame to partitioned Parquet files.

        One file per unique date in the index.  Omits columns for symbols
        not in *symbols* when provided.

        Returns:
            List of paths to the written files.
        """
        if df.empty:
            return []

        df = df.copy()
        if symbols:
            cols = [c for c in df.columns if self._col_symbol(c) in symbols]
            df = df[cols]

        paths: list[Path] = []
        for day_val, group in df.groupby(df.index.date):
            day = day_val if isinstance(day_val, date) else date.min
            path = self._date_path(day)
            path.parent.mkdir(parents=True, exist_ok=True)

            write_df = group.copy()
            idx_utc = write_df.index.tz_convert("UTC") if write_df.index.tz else write_df.index  # type: ignore[union-attr]
            write_df.index = idx_utc  # type: ignore[assignment]

            table = pa.Table.from_pandas(write_df)
            pq.write_table(table, str(path))

            paths.append(path)

        return paths

    def read(
        self,
        symbols: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame | None:
        """Read bar data from cached Parquet files.

        Args:
            symbols: If provided, only return columns for these symbols.
            start: Earliest timestamp (UTC, inclusive).
            end: Latest timestamp (UTC, inclusive).

        Returns:
            Wide-format DataFrame with UTC DatetimeIndex, or ``None``
            when no data exists for the requested range.
        """
        paths = self._find_files(start, end)
        if not paths:
            return None

        tables: list[pa.Table] = []
        for p in paths:
            table = pq.read_table(str(p))
            tables.append(table)

        if not tables:
            return None

        combined = pa.concat_tables(tables)
        df = combined.to_pandas()

        if df.empty:
            return None

        # Ensure UTC-aware index
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # Sort by timestamp
        df = df.sort_index()

        # Filter symbols
        if symbols:
            cols = [c for c in df.columns if self._col_symbol(c) in symbols]
            if not cols:
                return None
            df = df[cols]

        # Filter time range
        if start is not None:
            start_ts = pd.Timestamp(start)
            if start_ts.tz is None:
                start_ts = start_ts.tz_localize("UTC")
            df = df[df.index >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end)
            if end_ts.tz is None:
                end_ts = end_ts.tz_localize("UTC")
            df = df[df.index <= end_ts]

        return df

    def get_cached_ranges(
        self,
        symbols: list[str] | None = None,
    ) -> list[tuple[datetime, datetime]]:
        """Return sorted list of (start, end) tuples for cached date ranges.

        Omits empty days.  When *symbols* is provided, only considers
        files that contain data for at least one of those symbols.
        """
        cached = sorted(self._iter_date_paths(symbols))
        if not cached:
            return []

        ranges: list[tuple[datetime, datetime]] = []
        for path in cached:
            # Read first and last timestamps from metadata
            try:
                pq.read_metadata(str(path))
            except Exception:
                continue

            full = pq.read_table(str(path))
            pdf = full.to_pandas()
            if pdf.empty:
                continue

            if pdf.index.tz is None:
                pdf.index = pdf.index.tz_localize("UTC")

            start_ts = pdf.index.min().to_pydatetime()
            end_ts = pdf.index.max().to_pydatetime()
            ranges.append((start_ts, end_ts))

        # Merge contiguous / overlapping ranges
        ranges.sort(key=lambda r: r[0])
        merged: list[tuple[datetime, datetime]] = []
        for r in ranges:
            if merged and r[0] <= merged[-1][1]:
                prev = merged.pop()
                merged.append((prev[0], max(prev[1], r[1])))
            else:
                merged.append(r)

        return merged

    def find_missing_ranges(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """Return sub-ranges of [*start*, *end*] that are not yet cached.

        Useful for incremental fetching: only request data for the
        missing portions.
        """
        cached = self.get_cached_ranges(symbols)
        if not cached:
            return [(start, end)]

        # Find gaps between cached ranges within [start, end]
        missing: list[tuple[datetime, datetime]] = []
        cursor = start

        for c_start, c_end in sorted(cached):
            if cursor < c_start:
                missing.append((cursor, min(c_start, end)))
            cursor = max(cursor, c_end)
            if cursor >= end:
                break

        if cursor < end:
            missing.append((cursor, end))

        return missing

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def _col_symbol(col_name: str) -> str:
        """Extract symbol from ``{SYM}_{field}`` column name."""
        return col_name.rsplit("_", 1)[0]

    @staticmethod
    def _index_date(df: pd.DataFrame) -> pd.Series:
        """Extract date from a DatetimeIndex for groupby."""
        import numpy as np
        return pd.Series(np.asarray(df.index.date, dtype="object"), index=df.index)  # type: ignore[no-any-return]

    def _timeframe_dir(self) -> str:
        return self._timeframe.value.replace("Min", "min").lower()

    def _date_path(self, day: date) -> Path:
        """Build path: ``{base}/{timeframe}/{YYYY}/{MM}/{DD}.parquet``."""
        return (
            self._base
            / self._timeframe_dir()
            / str(day.year)
            / f"{day.month:02d}"
            / f"{day.day:02d}.parquet"
        )

    def _iter_date_paths(
        self,
        symbols: list[str] | None = None,
    ) -> list[Path]:
        """Walk the store directory and return all existing parquet paths.

        When *symbols* is provided, only returns paths for dates where
        the parquet file is non-empty and contains at least one of the
        requested symbols.  This is expensive for many symbols — prefer
        ``get_cached_ranges()``.
        """
        timeframe_dir = self._base / self._timeframe_dir()
        if not timeframe_dir.is_dir():
            return []

        paths: list[Path] = list(timeframe_dir.rglob("*.parquet"))

        if symbols:
            filtered: list[Path] = []
            symbol_set = set(symbols)
            for p in paths:
                try:
                    schema = pq.read_schema(str(p))
                except Exception:
                    continue
                col_symbols = {self._col_symbol(name) for name in schema.names if "_" in name}
                if col_symbols & symbol_set:
                    filtered.append(p)
            return sorted(filtered)

        return sorted(paths)

    def _find_files(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Path]:
        """Collect Parquet paths whose date falls within [*start*, *end*]."""
        timeframe_dir = self._base / self._timeframe_dir()
        if not timeframe_dir.is_dir():
            return []

        all_paths = sorted(timeframe_dir.rglob("*.parquet"))

        if start is None and end is None:
            return all_paths

        start_date = start.date() if start else date.min
        end_date = end.date() if end else date.max

        filtered: list[Path] = []
        for p in all_paths:
            try:
                parts = p.relative_to(timeframe_dir).parts
                if len(parts) >= 3:
                    year, month, day_file = parts[0], parts[1], parts[2]
                    day_str = day_file.replace(".parquet", "")
                    file_date = date(int(year), int(month), int(day_str))
                    if start_date <= file_date <= end_date:
                        filtered.append(p)
            except (ValueError, IndexError):
                continue

        return filtered
