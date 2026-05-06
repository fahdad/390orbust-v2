"""Shared test fixtures for orbust."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_bar_dataframe() -> pd.DataFrame:
    """Small synthetic DataFrame mimicking the v1 wide-format bar data.

    Columns use the {SYM}_{field} convention.
    """
    periods = 390  # one full RTH session
    now = datetime(2023, 3, 1, 14, 30)  # 09:30 ET = 14:30 UTC
    idx = pd.date_range(now, periods=periods, freq="min", tz="UTC")

    data = {}
    for sym in ("XOM", "XOP"):
        close = np.cumsum(np.random.randn(periods) * 0.01) + 100.0
        data[f"{sym}Open"] = close - np.random.rand(periods) * 0.02
        data[f"{sym}High"] = close + np.random.rand(periods) * 0.03
        data[f"{sym}Low"] = close - np.random.rand(periods) * 0.03
        data[f"{sym}Close"] = close
        data[f"{sym}Volume"] = np.random.randint(100_000, 5_000_000, periods)
        data[f"{sym}Trades"] = np.random.randint(500, 10_000, periods)
        data[f"{sym}VWAP"] = close + np.random.randn(periods) * 0.01

    data["day_of_year"] = idx.dayofyear
    data["minute_of_day"] = idx.hour * 60 + idx.minute

    return pd.DataFrame(data, index=idx)


@pytest.fixture
def sample_bar_events() -> list[dict]:
    """List of synthetic BarEvent-compatible dicts."""
    now = datetime(2023, 3, 1, 14, 30)
    events = []
    for i in range(10):
        ts = now + timedelta(minutes=i)
        events.append(
            {
                "symbol": "XOM",
                "timestamp": ts,
                "open": 100.0 + i * 0.1,
                "high": 100.5 + i * 0.1,
                "low": 99.5 + i * 0.1,
                "close": 100.2 + i * 0.1,
                "volume": 1_000_000 + i * 10_000,
                "trade_count": 5000 + i * 50,
                "vwap": 100.1 + i * 0.1,
            }
        )
    return events


@pytest.fixture
def temp_data_dir(tmp_path):
    """Temporary directory for test artifacts (parquet, sqlite)."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def energy_symbols() -> list[str]:
    """The v1 23-symbol XLE universe."""
    return [
        "XLE",
        "XOM",
        "CVX",
        "COP",
        "WMB",
        "EOG",
        "MPC",
        "KMI",
        "PSX",
        "SLB",
        "VLO",
        "BKR",
        "OKE",
        "TRGP",
        "EQT",
        "OXY",
        "FANG",
        "EXE",
        "DVN",
        "HAL",
        "TPL",
        "CTRA",
        "APA",
    ]
