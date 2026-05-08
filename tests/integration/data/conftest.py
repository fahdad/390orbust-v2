"""Shared fixtures for data pipeline integration tests.

Provides:
    - Mocked AlpacaFetcher (no real HTTP)
    - Temporary ParquetStore on real filesystem
    - Pre-configured AlpacaBarProvider
    - Quality check helpers
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from orbust.config import AlpacaConfig, DataPaths, SystemConfig
from orbust.data.alpaca import AlpacaBarProvider
from orbust.data.store import ParquetStore
from orbust.types import Timeframe

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

WINTER_START = datetime(2023, 3, 2, 14, 30, tzinfo=UTC)  # 09:30 ET
SUMMER_START = datetime(2023, 6, 15, 13, 30, tzinfo=UTC)  # 09:30 ET

RTH_BARS_PER_DAY = 390
TEST_BARS_PER_DAY = 60


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def alpaca_fixture_data() -> dict:
    """Load the static Alpaca mock response fixture."""
    path = Path(__file__).parents[2] / "fixtures" / "alpaca_response_sample.json"
    return json.loads(path.read_text())


@pytest.fixture
def temp_system_config(tmp_path) -> SystemConfig:
    """SystemConfig pointing at a temporary data directory."""
    return SystemConfig(
        alpaca=AlpacaConfig(key_id="test", secret_key="test"),
        data=DataPaths(data_dir=str(tmp_path / "data")),
    )


@pytest.fixture
def provider(temp_system_config) -> AlpacaBarProvider:
    """AlpacaBarProvider with RTH filtering disabled and temp data dir."""
    return AlpacaBarProvider(temp_system_config, rth_only=False)


@pytest.fixture
def provider_rth(temp_system_config) -> AlpacaBarProvider:
    """AlpacaBarProvider with RTH filtering enabled and temp data dir."""
    return AlpacaBarProvider(temp_system_config, rth_only=True)


@pytest.fixture
def temp_store(temp_system_config) -> ParquetStore:
    """Empty ParquetStore for direct cache manipulation."""
    return ParquetStore(temp_system_config.data.data_dir, Timeframe.MINUTE_1)


def _make_bars_df(
    symbols: list[str],
    start: datetime,
    periods: int,
) -> pd.DataFrame:
    """Create a wide-format bar DataFrame for testing."""
    idx = pd.date_range(start, periods=periods, freq="min", tz="UTC")
    idx.name = "timestamp"
    data: dict[str, list[float]] = {}
    base_price = 100.0
    for sym in symbols:
        for field in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
            data[f"{sym}_{field}"] = [base_price] * periods
        base_price += 50.0
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def mock_fetch_multi_symbol() -> pd.DataFrame:
    """Pre-built multi-symbol DataFrame for mock fetch responses."""
    return _make_bars_df(["XOM", "CVX"], WINTER_START, TEST_BARS_PER_DAY)


@pytest.fixture
def mock_fetch_extended_hours() -> pd.DataFrame:
    """Data spanning pre-market + RTH + after-hours."""
    start = datetime(2023, 3, 2, 13, 0, tzinfo=UTC)  # 08:00 ET
    return _make_bars_df(["XOM"], start, 540)  # 9 hours
