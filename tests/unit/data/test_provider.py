"""Tests for DataProvider ABC — interface compliance and abstract enforcement."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pandas as pd
import pytest

from orbust.data.provider import DataProvider
from orbust.types import BarEvent, Timeframe


def test_abstract_class_cannot_be_instantiated() -> None:
    """DataProvider raises TypeError on direct instantiation."""
    with pytest.raises(TypeError):
        DataProvider()  # type: ignore[abstract]


def test_complete_subclass_can_be_instantiated() -> None:
    """A subclass implementing all three methods works."""

    class ConcreteProvider(DataProvider):
        def get_bars(
            self,
            symbols: list[str],
            start: datetime,
            end: datetime,
            timeframe: Timeframe,
        ) -> pd.DataFrame:
            return pd.DataFrame()

        def stream_bars(
            self,
            symbols: list[str],
            timeframe: Timeframe,
        ) -> Iterator[BarEvent]:
            return iter([])

        def available_fields(self) -> list[str]:
            return ["open", "high", "low", "close", "volume"]

    provider = ConcreteProvider()
    assert isinstance(provider, DataProvider)


def test_missing_get_bars_raises_type_error() -> None:
    """Subclass missing get_bars raises TypeError."""

    class MissingGetBars(DataProvider):  # type: ignore[abstract]
        def stream_bars(
            self,
            symbols: list[str],
            timeframe: Timeframe,
        ) -> Iterator[BarEvent]:
            return iter([])

        def available_fields(self) -> list[str]:
            return []

    with pytest.raises(TypeError):
        MissingGetBars()


def test_missing_stream_bars_raises_type_error() -> None:
    """Subclass missing stream_bars raises TypeError."""

    class MissingStream(DataProvider):  # type: ignore[abstract]
        def get_bars(
            self,
            symbols: list[str],
            start: datetime,
            end: datetime,
            timeframe: Timeframe,
        ) -> pd.DataFrame:
            return pd.DataFrame()

        def available_fields(self) -> list[str]:
            return []

    with pytest.raises(TypeError):
        MissingStream()


def test_missing_available_fields_raises_type_error() -> None:
    """Subclass missing available_fields raises TypeError."""

    class MissingFields(DataProvider):  # type: ignore[abstract]
        def get_bars(
            self,
            symbols: list[str],
            start: datetime,
            end: datetime,
            timeframe: Timeframe,
        ) -> pd.DataFrame:
            return pd.DataFrame()

        def stream_bars(
            self,
            symbols: list[str],
            timeframe: Timeframe,
        ) -> Iterator[BarEvent]:
            return iter([])

    with pytest.raises(TypeError):
        MissingFields()


def test_importable_from_data_module() -> None:
    """DataProvider is re-exported from orbust.data."""
    from orbust.data import DataProvider

    assert DataProvider is not None


class MockProviderForConformance(DataProvider):
    """Concrete mock used by downstream tests to verify interface."""

    def __init__(self) -> None:
        self._fields = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> pd.DataFrame:
        idx = pd.date_range(start, end, freq=timeframe.value, tz="UTC")
        data: dict[str, list[float]] = {}
        for sym in symbols:
            for field in self._fields:
                data[f"{sym}_{field}"] = [100.0] * len(idx)
        return pd.DataFrame(data, index=idx)

    def stream_bars(
        self,
        symbols: list[str],
        timeframe: Timeframe,
    ) -> Iterator[BarEvent]:
        return iter([])

    def available_fields(self) -> list[str]:
        return self._fields


def test_mock_provider_returns_wide_format() -> None:
    """MockProvider produces expected wide-format DataFrame."""
    provider = MockProviderForConformance()
    start = datetime(2023, 3, 1, 14, 30)
    end = datetime(2023, 3, 1, 15, 0)
    df = provider.get_bars(["XOM", "XOP"], start, end, Timeframe.MINUTE_1)

    assert isinstance(df, pd.DataFrame)
    assert "XOM_close" in df.columns
    assert "XOP_volume" in df.columns
    assert df.index.tz is not None  # UTC-aware


def test_mock_provider_fields_match_contract() -> None:
    """MockProvider returns expected field names."""
    provider = MockProviderForConformance()
    fields = provider.available_fields()
    assert "open" in fields
    assert "volume" in fields
    assert "vwap" in fields
