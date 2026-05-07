"""Tests for ParquetStore — write, read, range queries, round-trip fidelity."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from orbust.data.store import ParquetStore
from orbust.types import Timeframe


@pytest.fixture
def store(temp_data_dir) -> ParquetStore:
    return ParquetStore(temp_data_dir, Timeframe.MINUTE_1)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """One day of 1-min bars for two symbols."""
    idx = pd.date_range(
        datetime(2023, 3, 1, 14, 30),  # 09:30 ET
        periods=390,
        freq="min",
        tz="UTC",
    )
    data = {
        "XOM_open": [100.0] * 390,
        "XOM_close": [100.1] * 390,
        "XOM_volume": [1_000_000] * 390,
        "XOP_open": [50.0] * 390,
        "XOP_close": [50.1] * 390,
        "XOP_volume": [500_000] * 390,
    }
    return pd.DataFrame(data, index=idx)


def test_write_creates_parquet_file(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """write() creates at least one parquet file on disk."""
    paths = store.write(sample_df)
    assert len(paths) >= 1
    for p in paths:
        assert p.exists()
        assert p.suffix == ".parquet"


def test_write_single_day_single_file(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """One day of data produces exactly one parquet file."""
    paths = store.write(sample_df)
    assert len(paths) == 1


def test_write_two_days_two_files(store: ParquetStore) -> None:
    """Two days of data produce two files."""
    idx1 = pd.date_range(datetime(2023, 3, 1, 14, 30), periods=390, freq="min", tz="UTC")
    idx2 = pd.date_range(datetime(2023, 3, 2, 14, 30), periods=390, freq="min", tz="UTC")
    idx = idx1.append(idx2)
    df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
    paths = store.write(df)
    assert len(paths) == 2


def test_read_returns_dataframe_with_utc_index(
    store: ParquetStore, sample_df: pd.DataFrame
) -> None:
    """read() returns DataFrame with UTC-aware DatetimeIndex."""
    store.write(sample_df)
    result = store.read()
    assert result is not None
    assert isinstance(result, pd.DataFrame)
    assert result.index.tz is not None
    assert str(result.index.tz) == "UTC"


def test_read_round_trip_equality(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """Written and read DataFrames have matching values (column order may differ)."""
    store.write(sample_df)
    result = store.read()
    assert result is not None
    assert result.index.equals(sample_df.index)
    assert result.columns.sort_values().equals(sample_df.columns.sort_values())
    pd.testing.assert_frame_equal(
        result[sorted(result.columns)],
        sample_df[sorted(sample_df.columns)],
        check_freq=False,
    )


def test_read_returns_none_when_empty(store: ParquetStore) -> None:
    """read() returns None when no data exists."""
    result = store.read()
    assert result is None


def test_read_filters_symbols(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """read(symbols=[\"XOM\"]) only returns XOM columns."""
    store.write(sample_df)
    result = store.read(symbols=["XOM"])
    assert result is not None
    for col in result.columns:
        assert col.startswith("XOM_")
    assert "XOP_close" not in result.columns


def test_read_filters_date_range(store: ParquetStore) -> None:
    """Date range filtering returns only bars within bounds."""
    idx = pd.date_range(datetime(2023, 3, 1, 14, 30), periods=780, freq="min", tz="UTC")
    df = pd.DataFrame({"XOM_close": [100.0] * len(idx)}, index=idx)
    store.write(df)

    # Last bar is at 2023-03-02 03:29 UTC — request a sub-range
    start = datetime(2023, 3, 2, 0, 0, tzinfo=UTC)
    end = datetime(2023, 3, 2, 1, 0, tzinfo=UTC)
    result = store.read(start=start, end=end)
    assert result is not None
    assert len(result) > 0
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    assert result.index.min() >= start_ts
    assert result.index.max() <= end_ts


def test_column_names_wide_format(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """Column names follow {SYM}_{field} convention."""
    store.write(sample_df)
    result = store.read()
    assert result is not None
    for col in result.columns:
        assert "_" in col, f"Column {col} does not follow SYM_field format"


def test_write_empty_dataframe(store: ParquetStore) -> None:
    """Writing an empty DataFrame returns empty list."""
    empty = pd.DataFrame()
    paths = store.write(empty)
    assert paths == []


def test_get_cached_ranges_after_write(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """get_cached_ranges returns correct ranges after writing."""
    store.write(sample_df)
    ranges = store.get_cached_ranges()
    assert len(ranges) >= 1
    start, end = ranges[0]
    assert start < end
    assert start.date() == date(2023, 3, 1)


def test_get_cached_ranges_empty(store: ParquetStore) -> None:
    """get_cached_ranges returns empty list when nothing cached."""
    ranges = store.get_cached_ranges()
    assert ranges == []


def test_find_missing_ranges_fully_cached(store: ParquetStore, sample_df: pd.DataFrame) -> None:
    """find_missing_ranges returns empty when entire range is cached."""
    store.write(sample_df)
    start = datetime(2023, 3, 1, 14, 30, tzinfo=UTC)
    end = datetime(2023, 3, 1, 15, 0, tzinfo=UTC)
    missing = store.find_missing_ranges(["XOM"], start, end)
    assert missing == []


def test_find_missing_ranges_nothing_cached(store: ParquetStore) -> None:
    """find_missing_ranges returns full range when nothing cached."""
    start = datetime(2023, 3, 1, 14, 30, tzinfo=UTC)
    end = datetime(2023, 3, 1, 15, 0, tzinfo=UTC)
    missing = store.find_missing_ranges(["XOM"], start, end)
    assert missing == [(start, end)]


def test_find_missing_ranges_partial(store: ParquetStore) -> None:
    """Partial cache returns correct missing sub-range."""
    # Write only the first day
    idx1 = pd.date_range(datetime(2023, 3, 1, 14, 30), periods=390, freq="min", tz="UTC")
    df1 = pd.DataFrame({"XOM_close": [100.0] * len(idx1)}, index=idx1)
    store.write(df1)

    start = datetime(2023, 3, 1, 14, 30, tzinfo=UTC)
    end = datetime(2023, 3, 3, 15, 0, tzinfo=UTC)
    missing = store.find_missing_ranges(["XOM"], start, end)

    assert len(missing) >= 1
    for ms, me in missing:
        assert ms > start or me < end


def test_incremental_write_merges_with_existing(store: ParquetStore) -> None:
    """Writing new data for a cached date merges without overwriting."""
    # Write first batch (first 200 bars)
    idx1 = pd.date_range(datetime(2023, 3, 1, 14, 30), periods=200, freq="min", tz="UTC")
    df1 = pd.DataFrame({"XOM_close": [100.0] * len(idx1)}, index=idx1)
    store.write(df1)

    # Write second batch (last 200 bars, overlapping + extending)
    idx2 = pd.date_range(datetime(2023, 3, 1, 15, 0), periods=200, freq="min", tz="UTC")
    df2 = pd.DataFrame({"XOM_close": [101.0] * len(idx2)}, index=idx2)
    store.write(df2)

    result = store.read()
    assert result is not None
    # 230 unique bars: 200 + 200 - 170 overlapping minutes
    # (no data loss despite two writes to the same date)
    assert len(result) == 230
    # Data from both batches present — overlap uses last-write-wins
    assert result.iloc[0]["XOM_close"] == 100.0   # from first batch
    assert result.iloc[-1]["XOM_close"] == 101.0   # from second batch


def test_importable_from_data_module() -> None:
    """ParquetStore is importable from orbust.data."""
    from orbust.data import ParquetStore

    assert ParquetStore is not None
