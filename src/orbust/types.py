"""Core type definitions for the orbust trading platform.

All shared dataclasses, enums, and type aliases live here.
This module has zero dependencies outside stdlib + pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════


class Timeframe(Enum):
    MINUTE_1 = "1Min"
    MINUTE_5 = "5Min"
    MINUTE_15 = "15Min"
    DAY = "1Day"


class Side(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalType(Enum):
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    RANKING = "ranking"
    POSITION = "position"


class WFMode(Enum):
    """Walk-forward mode: expanding window or fixed rolling window."""

    EXPANDING = "expanding"
    ROLLING = "rolling"


class Stage(Enum):
    """Deployment stage — maps to approval policy + broker endpoint."""

    SUPERVISED_PAPER = "supervised_paper"
    AUTONOMOUS_PAPER = "autonomous_paper"
    AUTONOMOUS_LIVE = "autonomous_live"


class RiskDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ═══════════════════════════════════════════════════════════════
# Data layer types
# ═══════════════════════════════════════════════════════════════


@dataclass
class BarEvent:
    """A single minute bar from the data provider."""

    symbol: str
    timestamp: datetime  # UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int | None = None
    vwap: float | None = None

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(
                f"low ({self.low}) > high ({self.high}) for {self.symbol} at {self.timestamp}"
            )


# ═══════════════════════════════════════════════════════════════
# Signal & action types
# ═══════════════════════════════════════════════════════════════


@dataclass
class Signal:
    """Output of a Strategy — pure prediction, no position sizing."""

    strategy_name: str
    timestamp: datetime  # bar timestamp that produced this signal
    signal_type: SignalType
    symbols: list[str]
    payload: dict[str, Any]  # type-specific content; see module docstring for schema
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ProposedAction:
    """A concrete proposed order, produced by the SignalInterpreter."""

    action_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    strategy_name: str = ""
    symbol: str = ""
    side: Side = Side.HOLD
    quantity: int = 0
    rationale: str = ""
    confidence: float = 0.0
    proposed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


@dataclass
class RiskEvaluation:
    """Result of running an action through the risk gate."""

    decision: RiskDecision = RiskDecision.REJECTED
    reason: str = ""
    modified_action: ProposedAction | None = None


# ═══════════════════════════════════════════════════════════════
# Order & position types
# ═══════════════════════════════════════════════════════════════


@dataclass
class Order:
    """A placed order tracked by the execution layer."""

    order_id: str = ""
    strategy_name: str = ""
    symbol: str = ""
    side: Side = Side.HOLD
    quantity: int = 0
    filled_quantity: int = 0
    price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    filled_at: datetime | None = None


@dataclass
class Position:
    """Current position in a single symbol for a strategy book."""

    symbol: str
    quantity: int = 0
    avg_entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class StrategyBook:
    """A strategy's allocated book — capital, positions, orders, PnL."""

    strategy_name: str
    allocated_capital: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    pending_orders: list[Order] = field(default_factory=list)
    order_history: list[Order] = field(default_factory=list)
    daily_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class PortfolioState:
    """Snapshot of the full portfolio across all strategy books."""

    books: dict[str, StrategyBook] = field(default_factory=dict)
    total_capital: float = 0.0
    total_exposure: float = 0.0
    total_daily_pnl: float = 0.0


# ═══════════════════════════════════════════════════════════════
# Backtesting & evaluation types
# ═══════════════════════════════════════════════════════════════


@dataclass
class WalkForwardPolicy:
    """Configuration for walk-forward cross-validation."""

    mode: WFMode = WFMode.EXPANDING
    min_train_size: timedelta = timedelta(days=30)
    validation_size: timedelta = timedelta(days=5)
    step_size: timedelta = timedelta(days=5)
    window_size: timedelta | None = None  # ROLLING only


@dataclass
class CostModel:
    """Transaction cost model for backtesting."""

    spread_bps: float = 2.0  # bid-ask spread in basis points
    commission_per_share: float = 0.0
    slippage_bps: float = 1.0  # market impact estimate
    min_cost: float = 0.0


@dataclass
class FoldMetrics:
    """Metrics for a single walk-forward fold."""

    fold_index: int = 0
    train_start: datetime | None = None
    train_end: datetime | None = None
    val_start: datetime | None = None
    val_end: datetime | None = None
    accuracy: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0


@dataclass
class BacktestResult:
    """Aggregate backtest results across all folds."""

    strategy_name: str = ""
    fold_metrics: list[FoldMetrics] = field(default_factory=list)
    total_trades: int = 0
    sharpe_mean: float = 0.0
    sharpe_std: float = 0.0
    sortino_mean: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_gross_pnl: float = 0.0
    total_net_pnl: float = 0.0


@dataclass
class TrainResult:
    """Result of a strategy training run."""

    strategy_name: str = ""
    run_id: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    epochs_trained: int = 0
    model_path: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: str = "running"
