"""Data provider abstract interface.

All data sources (Alpaca, file, future L2/vendor providers) implement this
contract. Consumers write against DataProvider, not concrete implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime

import pandas as pd

from orbust.types import BarEvent, Timeframe


class DataProvider(ABC):
    """Abstract interface for market data access.

    Every provider returns data in a uniform wide format:
    - UTC-aware ``pd.DatetimeIndex``
    - Columns named ``{SYM}_{field}`` (e.g. ``XOM_close``, ``XOM_volume``)
    """

    @abstractmethod
    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> pd.DataFrame:
        """Fetch historical bars for one or more symbols.

        Args:
            symbols: List of ticker symbols.
            start: Start of the query window (UTC, inclusive).
            end: End of the query window (UTC, inclusive).
            timeframe: Bar aggregation period.

        Returns:
            Wide-format DataFrame with UTC DatetimeIndex and
            ``{SYM}_{field}`` columns.
        """
        ...

    @abstractmethod
    def stream_bars(
        self,
        symbols: list[str],
        timeframe: Timeframe,
    ) -> Iterator[BarEvent]:
        """Stream live/paper bars as they arrive.

        Args:
            symbols: List of ticker symbols to subscribe to.
            timeframe: Bar aggregation period.

        Yields:
            :class:`BarEvent` instances as new bars arrive.
        """
        ...

    @abstractmethod
    def available_fields(self) -> list[str]:
        """Return the field names this provider supplies.

        Returns:
            List of field names (e.g. ``open``, ``high``, ``low``,
            ``close``, ``volume``, ``trade_count``, ``vwap``).
        """
        ...
