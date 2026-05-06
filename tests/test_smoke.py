"""Smoke tests: verify core types, config loading, and logging."""

from __future__ import annotations

from orbust.config import StrategyConfig, SystemConfig
from orbust.log import get_logger
from orbust.types import (
    BarEvent,
    ProposedAction,
    Signal,
    SignalType,
    Timeframe,
)


def test_signal_creation() -> None:
    """Signal can be instantiated with required fields."""
    s = Signal(
        strategy_name="test",
        timestamp="2023-03-01",
        signal_type=SignalType.CLASSIFICATION,
        symbols=["XOM"],
        payload={},
    )
    assert s.strategy_name == "test"
    assert s.signal_type == SignalType.CLASSIFICATION


def test_bar_event_validation() -> None:
    """BarEvent raises on invalid low > high."""
    import datetime

    ts = datetime.datetime(2023, 3, 1, 14, 30)
    BarEvent(symbol="XOM", timestamp=ts, open=100, high=101, low=99, close=100, volume=1_000_000)

    import pytest

    with pytest.raises(ValueError, match=r"low.*>.*high"):
        BarEvent(symbol="XOM", timestamp=ts, open=100,
                 high=99, low=101, close=100, volume=1_000_000)


def test_proposed_action_defaults() -> None:
    """ProposedAction generates a unique action_id."""
    a1 = ProposedAction()
    a2 = ProposedAction()
    assert a1.action_id != a2.action_id
    assert a1.side.value == "hold"


def test_timeframe_values() -> None:
    """Timeframe enum maps to correct Alpaca strings."""
    assert Timeframe.MINUTE_1.value == "1Min"
    assert Timeframe.MINUTE_5.value == "5Min"
    assert Timeframe.DAY.value == "1Day"


def test_system_config_loads_from_yaml() -> None:
    """System config loads default values from config/system.yaml."""
    cfg = SystemConfig.load("config/system.yaml")
    assert cfg.stage == "supervised_paper"
    assert cfg.dashboard.port == 8080
    assert len(cfg.alpaca.key_id) == 0  # not set by default


def test_strategy_config_minimal() -> None:
    """StrategyConfig validates fields, rejects empty symbols."""
    import pytest

    with pytest.raises(ValueError, match="at least one symbol"):
        StrategyConfig(name="empty", symbols=[])

    cfg = StrategyConfig(name="test", symbols=["XOM"])
    assert cfg.name == "test"
    assert cfg.model.architecture == "conv1d"


def test_logger_creates_and_binds() -> None:
    """Logger creation and context binding works."""
    log = get_logger(pipeline_id="test_001")
    log.info("smoke_test", status="ok")
    # If we got here without exceptions, structlog is wired correctly
    assert True


def test_sample_fixtures(sample_bar_dataframe, energy_symbols) -> None:
    """Conftest fixtures are importable and produce expected shapes."""
    assert "XOMClose" in sample_bar_dataframe.columns
    assert "XOPClose" in sample_bar_dataframe.columns
    assert len(sample_bar_dataframe) == 390  # one RTH session
    assert "XLE" in energy_symbols
    assert len(energy_symbols) == 23
