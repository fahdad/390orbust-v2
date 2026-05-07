# 390OrBust v2 — Architectural Kickstart Plan

**Generated**: 2026-05-04
**Method**: Structured decision-tree interview → architectural blueprint
**Purpose**: Master reference for all future build sessions. Every component, interface, dependency, and phase is defined here.

---

## 1. Mission & End-State

**Mission**: Build a modular, event-driven algorithmic trading platform that supports the full lifecycle from signal research to autonomous live execution.

**Staged deployment model**:

| Stage | Description | Decision Authority | Infrastructure |
|-------|-------------|-------------------|----------------|
| **Stage 1**: Supervised Paper | Strategies emit signals, human approves every action via dashboard | Human click required | Alpaca paper endpoint |
| **Stage 2**: Autonomous Paper | Strategies execute automatically against paper account, human monitors | System (risk-gated) | Alpaca paper endpoint |
| **Stage 3**: Autonomous Live | Strategies execute against real capital with system risk guardrails | System (risk-gated) | Alpaca live endpoint |

The architecture must support all three stages without structural changes — stage transitions are configuration changes (approval policy, endpoint target), not rewrites.

---

## 2. Foundational Decisions

These are the resolved architectural decisions. They are not negotiable within v2 scope.

**Runtime model**: Long-running event-driven service. Backtesting and training run as batch processes sharing the same libraries.

**Architecture style**: Well-structured monolith. Component boundaries are module interfaces (function signatures, typed objects), not network boundaries. All components run in-process on a single box.

**Deployment target**: Bare-metal Ubuntu, Ryzen 5 5600X, 48GB RAM, RTX 3090 (24GB VRAM). No containers in the hot path. Systemd for process management. Minimal layers between code and silicon.

**Language & framework**: Python. PyTorch for all ML. CUDA-aware throughout — assume GPU is always present. Mixed precision (FP16/TF32) available. Models stay GPU-resident during live inference.

**Data format & storage**:

| Store | Technology | Purpose |
|-------|-----------|---------|
| Operational state | SQLite | Positions, orders, strategy configs, experiment ledger, run history |
| Market data | Parquet files | Bars, feature matrices, backtest results |
| Model artifacts | Filesystem (.pt) | Trained model weights, optimizer state |
| Logs | Structured JSON files (structlog) | Rotated, queryable, full causal chain |
| Analytics (future) | DuckDB | Labeled seam — bring in when data volume demands it |
| Time-series DB (future) | QuestDB | Labeled seam — bring in with L2 data |

**Configuration**: Layered YAML with Pydantic validation.

| Layer | File | Contents |
|-------|------|----------|
| System | `config/system.yaml` | Data paths, Alpaca creds ref, system risk limits, GPU settings, dashboard port |
| Strategy | `strategies/{name}/config.yaml` | Features, model def, hyperparams, walk-forward policy, risk overrides, signal type |
| Run mode | CLI argument | `--mode backtest|paper|live` — invocation choice, not config |

Every experiment run snapshots the full resolved config into the experiment ledger for reproducibility.

**Codebase**: Clean start, new repository. v1 preserved as-is for reference. v1 energy-sector strategy ported as a validation task after infrastructure is complete.

**Development workflow**: Notebooks for exploratory research (importing infrastructure libraries). Strategy class for production. Training harness only accepts formal Strategy classes — notebooks are drafts, not deployable artifacts.

---

## 3. Component Architecture

The system decomposes into eight modules. Each module has a defined responsibility, a clear interface boundary, and explicit dependencies.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         390OrBust v2                                │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ Data Provider │───▶│ Feature      │───▶│ Strategy Engine      │  │
│  │ Layer         │    │ Registry     │    │ (pluggable strategies)│  │
│  └──────┬───────┘    └──────────────┘    └──────────┬───────────┘  │
│         │                                           │               │
│         │            ┌──────────────┐               │               │
│         └───────────▶│ Data Store   │◀──────────────┘               │
│                      │ (Parquet/    │                                │
│                      │  SQLite)     │    ┌──────────────────────┐   │
│                      └──────────────┘    │ Signal Interpreter   │   │
│                                          │ + Risk Layer         │   │
│  ┌──────────────┐                        └──────────┬──────────┘   │
│  │ Walk-Forward │                                   │              │
│  │ Engine       │    ┌──────────────┐    ┌──────────▼──────────┐   │
│  │ + Backtester │    │ Dashboard    │◀──▶│ Execution Layer     │   │
│  └──────────────┘    └──────────────┘    └─────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Experiment Ledger & Model Store                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Logging & Observability (structlog, structured JSON)         │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 3.1 Data Provider Layer

**Responsibility**: Fetch, normalize, and cache market data from external sources. Present a uniform time-indexed data interface to all downstream consumers.

**Interface**:
```python
class DataProvider(ABC):
    def get_bars(self, symbols: list[str], start: datetime, end: datetime,
                 timeframe: Timeframe) -> pd.DataFrame:
        """Returns wide-format DataFrame: UTC DatetimeIndex, columns {SYM}_{field}"""
        ...

    def stream_bars(self, symbols: list[str], timeframe: Timeframe) -> Iterator[BarEvent]:
        """Yields BarEvent objects as new bars arrive (live/paper mode)"""
        ...

    def available_fields(self) -> list[str]:
        """Returns list of fields this provider offers (open, high, low, close, volume, etc.)"""
        ...
```

**v2 implementation**: `AlpacaBarProvider` — fetches 1-minute bars via `alpaca-py` SDK. Handles pagination, rate limiting, RTH filtering (09:30–16:00 ET, Mon–Fri), and caching to Parquet.

**Design constraints**:
- All timestamps are UTC-aware `DatetimeIndex`
- Wide format: `{SYM}_{field}` columns (consistent with v1 schema)
- Provider caches fetched data to Parquet automatically — re-fetches only missing ranges
- RTH filtering is a provider-level config, not consumer responsibility
- Temporal alignment guarantee: all bars for a given timestamp represent the same wall-clock minute

**Future seams**: L2 order book provider, alternative data providers (VIX, oil futures, sentiment). Each is a new class implementing `DataProvider` with additional fields.

**Dependencies**: External (Alpaca API), Internal (Data Store for caching)

---

### 3.2 Feature Registry

**Responsibility**: Define, compute, cache, and serve engineered features. Enforce leakage control centrally. Provide composable feature definitions that strategies select from via config.

**Interface**:
```python
class FeatureRegistry:
    def register(self, name: str, compute_fn: Callable, params: dict,
                 dependencies: list[str]) -> None:
        """Register a new feature definition"""
        ...

    def compute(self, feature_names: list[str], bars: pd.DataFrame,
                shift: int = 1) -> pd.DataFrame:
        """Compute requested features from bar data, applying leakage shift"""
        ...

    def available_features(self) -> list[FeatureDefinition]:
        """List all registered features with their parameter schemas"""
        ...
```

**Built-in feature library** (ported from v1's 785-feature suite):

| Category | Features | Parameters |
|----------|----------|------------|
| Returns | Log returns at horizons | lags: [1, 5, 15] |
| Rolling stats | Mean, std of returns | windows: [5, 20, 60] |
| Moving averages | MA, EMA, price-over-MA ratios | MA: [5, 20, 60, 120], EMA: [12, 26] |
| Momentum | RSI | period: 14 |
| Volatility | True range, ATR | period: 14 |
| Liquidity | Volume z-score, volume ROC, trades z-score | windows: [10, 30, 60] |
| Price-VWAP | Price-VWAP spread | — |
| Cross-sectional | Equal-weight market return, CS z-scores (close, volume) | — |
| Calendar | Time-of-day (sin/cos), day-of-week (one-hot) | — |

**Design constraints**:
- Leakage control: the registry applies `shift` (default +1 bar) to the entire computed frame before returning. Strategies never see unshifted features.
- NaN policy: configurable per feature (forward-fill, drop, or impute). Default: `min_periods` enforcement on rolling computations.
- Caching: computed feature matrices are cached to Parquet keyed by (feature set hash, data range, shift). Recompute only on config change.
- Custom features: strategies can register additional features. Custom features go through the same leakage/NaN pipeline.
- All computation uses vectorized numpy/pandas operations. No Python for-loops over bars.

**Dependencies**: Data Provider Layer (raw bars)

---

### 3.3 Strategy Engine

**Responsibility**: Define the contract that all strategies implement. Manage strategy lifecycle (load, train, predict, save). Route data and features to strategies.

**Strategy interface contract**:
```python
class Strategy(ABC):
    @property
    def name(self) -> str: ...

    @property
    def signal_type(self) -> SignalType: ...
        # SignalType.CLASSIFICATION | REGRESSION | RANKING | POSITION

    @property
    def feature_dependencies(self) -> list[str]: ...
        # List of feature names from the registry

    @property
    def config_schema(self) -> type[BaseModel]: ...
        # Pydantic model defining this strategy's config

    def build_model(self, config: BaseModel) -> nn.Module: ...
        # Construct the PyTorch model

    def train(self, features: torch.Tensor, targets: torch.Tensor,
              config: BaseModel) -> TrainResult: ...
        # Train the model, return metrics + trained state

    def predict(self, features: torch.Tensor) -> Signal: ...
        # Emit a signal from current features

    def save(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...
```

**Signal object**:
```python
@dataclass
class Signal:
    strategy_name: str
    timestamp: datetime          # bar timestamp that produced this signal
    signal_type: SignalType
    symbols: list[str]
    payload: dict                # type-specific content:
    # CLASSIFICATION: {symbol: {class_label: str, confidence: dict[str, float]}}
    # REGRESSION:     {symbol: {forecast: float, ci_lower: float, ci_upper: float}}
    # RANKING:        {ranked_symbols: list[tuple[str, float]]}
    # POSITION:       {symbol: {target_shares: int, target_weight: float}}
    metadata: dict               # strategy-specific context for dashboard display
    created_at: datetime         # wall clock when signal was computed (for staleness)
```

**Design constraints**:
- Strategies are pure prediction units. They do not size positions, manage risk, or place orders.
- Strategies declare their feature dependencies; the engine materializes the feature matrix via the registry.
- The engine manages GPU memory: loads model to GPU for inference, handles batch sizing.
- Strategy config is frozen at training time and snapshotted in the experiment ledger.

**Dependencies**: Feature Registry, Data Store (model persistence)

---

### 3.4 Signal Interpreter & Risk Layer

**Responsibility**: Convert strategy signals into proposed portfolio actions. Enforce risk limits. Gate actions for human approval (in supervised mode).

**Two sub-components**:

#### 3.4a Signal Interpreter

Converts typed signals into concrete proposed actions:

```python
@dataclass
class ProposedAction:
    strategy_name: str
    signal: Signal
    symbol: str
    side: Side                   # BUY | SELL | HOLD
    quantity: int                # shares
    rationale: str               # human-readable explanation
    confidence: float            # interpreter's confidence in this action
    proposed_at: datetime
    expires_at: datetime         # signal staleness deadline
```

Interpretation policies (configurable per signal type):
- Classification: "if 'up' confidence > threshold → BUY quantity based on Kelly/fixed fraction"
- Regression: "if forecast > threshold → BUY, size by volatility-scaled target"
- Ranking: "long top N, short bottom N (if enabled)"
- Position: "pass through target directly"

#### 3.4b Risk Layer

Two tiers, enforced as a gate in the action pipeline:

| Tier | Scope | Examples | Override behavior |
|------|-------|----------|-------------------|
| System | All strategies, all books | Max total exposure, max drawdown, daily loss limit, max open positions | **Cannot be overridden** |
| Strategy | Per-strategy book | Max position size per symbol, max concentration, stop-loss per trade | Strategy can **tighten** below system limits, never loosen |

```python
class RiskGate:
    def evaluate(self, action: ProposedAction,
                 portfolio_state: PortfolioState) -> RiskDecision:
        """Returns APPROVED, REJECTED (with reason), or MODIFIED (with adjusted action)"""
        ...
```

The risk gate sits between the signal interpreter and the execution layer. It can reject or modify actions. It logs every decision with full reasoning.

**Dependencies**: Strategy Engine (signals), Execution Layer (portfolio state), Data Store (risk config)

---

### 3.5 Execution Layer

**Responsibility**: Manage portfolio state, place orders, track fills, reconcile with broker. Handle the approval workflow for human-in-the-loop mode.

**Core state**:
```python
@dataclass
class StrategyBook:
    strategy_name: str
    allocated_capital: float
    positions: dict[str, Position]     # symbol → Position
    pending_orders: list[Order]
    order_history: list[Order]
    daily_pnl: float
    realized_pnl: float
    unrealized_pnl: float
```

**Approval workflow**:

| Mode | Behavior |
|------|----------|
| Supervised | ProposedAction → dashboard queue → human approve/reject → execute or discard |
| Autonomous | ProposedAction → risk gate → execute immediately |

In supervised mode, unapproved actions expire at `expires_at` (configurable, default: next bar). No action executes without explicit human approval. Ever.

**Broker interface**:
```python
class BrokerAdapter(ABC):
    def place_order(self, order: Order) -> OrderResult: ...
    def cancel_order(self, order_id: str) -> CancelResult: ...
    def get_positions(self) -> dict[str, Position]: ...
    def get_account(self) -> AccountInfo: ...
```

**v2 implementation**: `AlpacaBrokerAdapter` — wraps `alpaca-py` trading client. Same adapter class for paper and live; endpoint URL is the only difference (config-driven).

**Crash recovery**: On restart, the service loads state from SQLite, calls `get_positions()` from Alpaca to reconcile (in case fills arrived while service was down), and resumes.

**Dependencies**: Risk Layer (approved actions), Data Store (SQLite for state), Broker API (Alpaca)

---

### 3.6 Walk-Forward Engine & Backtester

**Responsibility**: Evaluate strategy performance across time. Provide temporal cross-validation with configurable windowing policies. Simulate trading with cost models.

**Walk-forward policies** (strategy-configured):
```python
@dataclass
class WalkForwardPolicy:
    mode: WFMode                  # EXPANDING | ROLLING
    min_train_size: timedelta     # e.g., 5 days
    validation_size: timedelta    # e.g., 1 day
    step_size: timedelta          # e.g., 1 day (how far to slide)
    window_size: timedelta | None # ROLLING only: fixed training window
```

**Infrastructure-enforced invariants**:
- Strategy never sees future data within a fold
- Feature scaler (StandardScaler/imputer) is refit on each training fold
- Train/validation boundaries respect temporal ordering
- Per-fold metrics are recorded individually (not just averaged)

**Backtest engine** (Level 2):
```python
@dataclass
class CostModel:
    spread_bps: float           # bid-ask spread in basis points
    commission_per_share: float # fixed cost per share
    slippage_bps: float         # market impact estimate

class Backtester:
    def run(self, strategy: Strategy, data: pd.DataFrame,
            cost_model: CostModel, walk_forward: WalkForwardPolicy
            ) -> BacktestResult:
        """Run full walk-forward backtest, return per-fold and aggregate metrics"""
        ...
```

**BacktestResult** includes per-fold: accuracy, Sharpe, Sortino, max drawdown, PnL curve, win rate, profit factor. Aggregate: same metrics across all folds, plus stability metrics (variance of Sharpe across folds).

**Dependencies**: Strategy Engine, Feature Registry, Data Provider, Data Store (results)

---

### 3.7 Dashboard

**Responsibility**: Unified web interface for research review and live operations.

**Two modes, one interface**:

| Mode | Capabilities |
|------|-------------|
| Research | Experiment history browser, backtest result comparison, per-fold drill-down, feature importance visualization, strategy performance over time |
| Operations | Live signal feed with approve/reject, position monitor per strategy book, risk utilization gauges, PnL curves, temporal context visualization |

**Temporal context visualization** (key differentiator):
A timeline strip showing: bar arrival time → feature computation complete → signal emitted → current wall clock → next bar expected. Gives the operator an intuitive staleness read and processing-latency diagnostic.

**Technology**: Lightweight Python web framework (FastAPI + server-sent events for live updates, simple HTML/JS frontend). Served from the box. No SPA framework overhead — this is an operational tool, not a product.

**Dependencies**: All other components (reads from Data Store, Experiment Ledger, Execution Layer state)

---

### 3.8 Experiment Ledger & Model Store

**Responsibility**: Track every training run, store model artifacts, enable comparison and reproduction.

**Ledger schema** (SQLite):
```sql
CREATE TABLE experiment_runs (
    run_id          TEXT PRIMARY KEY,    -- UUID
    strategy_name   TEXT NOT NULL,
    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    status          TEXT,               -- running | completed | failed
    config_snapshot TEXT,               -- full YAML as JSON string
    feature_set     TEXT,               -- JSON list of feature names
    walk_forward    TEXT,               -- JSON WalkForwardPolicy
    model_path      TEXT,               -- path to saved .pt file
    metrics         TEXT,               -- JSON: per-fold + aggregate metrics
    notes           TEXT                -- human annotations
);
```

**Model store layout**:
```
models/
  {strategy_name}/
    {run_id}/
      model.pt                  # trained weights
      optimizer.pt              # optimizer state (for resume)
      config.yaml               # frozen config snapshot
      metrics.json              # full results
```

**Dependencies**: Strategy Engine (produces runs), Data Store (SQLite)

---

### 3.9 Logging & Observability

**Responsibility**: Structured logging across all components. Full causal chain from data arrival to position change.

**Implementation**: `structlog` with JSON output. Rotated daily log files.

**Every decision point logs its inputs and outputs**:

| Event | Logged Fields |
|-------|--------------|
| Bar received | timestamp, symbol_count, source, latency_ms |
| Features computed | timestamp, feature_count, nan_count, compute_ms |
| Signal emitted | timestamp, strategy, signal_type, symbols, payload_summary |
| Risk evaluation | action_id, tier, decision (approved/rejected/modified), reason |
| Human decision | action_id, decision (approved/rejected), latency_ms |
| Order placed | order_id, symbol, side, quantity, order_type, target_price |
| Fill received | order_id, fill_price, expected_price, slippage_bps |
| System event | event_type, details (startup, shutdown, crash_recovery, config_reload) |

**Correlation**: Every pipeline pass (bar → features → signal → action → order) shares a `pipeline_id` so the full chain can be reconstructed from logs.

---

## 4. Dependency Graph

Build order is constrained by these dependencies:

```
Phase 1 (Foundation):
  Logging ──────────────────────── (no deps, needed by everything)
  Config System ────────────────── (no deps, needed by everything)
  Data Store Schemas ───────────── (SQLite tables, Parquet schemas)

Phase 2 (Data):
  Data Provider Layer ──────────── depends on: Config, Logging, Data Store
  Feature Registry ─────────────── depends on: Data Provider, Config, Logging

Phase 3 (Strategy):
  Strategy Engine ──────────────── depends on: Feature Registry, Config, Logging
  Signal Interpreter ───────────── depends on: Strategy Engine, Config
  Risk Layer ───────────────────── depends on: Config, Logging

Phase 4 (Execution):
  Execution Layer ──────────────── depends on: Risk Layer, Signal Interpreter, Data Store
  Walk-Forward Engine ──────────── depends on: Strategy Engine, Feature Registry, Data Store
  Backtester ───────────────────── depends on: Walk-Forward Engine, Signal Interpreter

Phase 5 (Interface):
  Dashboard ────────────────────── depends on: all above (read-only consumer)
  Experiment Ledger integration ── depends on: Strategy Engine, Walk-Forward Engine

Phase 6 (Validation):
  Port v1 strategy ─────────────── depends on: all infrastructure complete
```

---

## 5. Phased Build Plan

### Phase 1: Foundation (Sessions 1–3)

**Goal**: Project skeleton, logging, config, storage schemas. Nothing runs yet, but the bones are right.

**Deliverables**:
- Repository structure with package layout
- `structlog` configuration with JSON output, rotation, correlation IDs
- Pydantic models for system config and strategy config
- YAML loading + validation pipeline
- SQLite schema creation (experiment_runs, positions, orders, strategy_books)
- Parquet schema definitions (bar data, feature matrices)
- Shared type definitions: `Signal`, `ProposedAction`, `BarEvent`, `Position`, `Order`, enums

**Validation**: Config loads and validates. SQLite tables create. Logger outputs structured JSON. Types import cleanly.

---

### Phase 2: Data Pipeline (Sessions 4–6)

**Goal**: Fetch Alpaca data, store it, serve it through the provider interface.

**Deliverables**:
- `DataProvider` abstract base class
- `AlpacaBarProvider` implementation (fetch, paginate, rate-limit, cache)
- RTH filtering (09:30–16:00 ET, Mon–Fri)
- Wide-format Parquet writer/reader
- Data quality checks: gap detection, duplicate bars, timestamp validation
- Notebook helper: `from infra.data import get_bars` works in Jupyter

**Validation**: Fetch 23 energy symbols for a date range. Verify Parquet output matches v1 schema. Verify RTH filtering. Verify gap detection catches known market holidays.

---

### Phase 3: Feature Engineering (Sessions 7–10)

**Goal**: Feature registry with the full v1 feature suite, config-driven, leakage-controlled.

**Deliverables**:
- `FeatureRegistry` class with register/compute/list interface
- All v1 features ported as registry entries (returns, rolling stats, MA/EMA, RSI, ATR, volume z-scores, price-VWAP, cross-sectional, calendar)
- Config-driven feature selection: strategy config lists feature names + params
- Leakage shift (+1 bar) applied centrally
- NaN handling: `min_periods` on rolling, configurable imputation
- Feature caching to Parquet (keyed by feature set hash + data range)
- Custom feature registration API
- Notebook helper: `from infra.features import registry; F = registry.compute(["rsi_14", "atr_14"], bars)`

**Validation**: Compute features for energy universe. Verify output matches v1 `F_model` numerically (or document any intentional differences). Verify shift is applied. Verify NaN counts.

---

### Phase 4: Strategy Framework (Sessions 11–14)

**Goal**: Strategy interface, signal types, training harness, experiment ledger.

**Deliverables**:
- `Strategy` ABC with full contract (name, signal_type, feature_deps, build_model, train, predict, save, load)
- `Signal` dataclass with type-tagged payloads
- `TrainResult` with metrics
- Training harness: loads strategy class, materializes features, runs training loop, saves model + logs to experiment ledger
- Experiment ledger: SQLite writes, config snapshots, metric storage
- Model store: directory layout, save/load with PyTorch state_dict
- GPU management: model-to-device, mixed precision context, memory cleanup
- CLI: `python -m infra.train --strategy energy_conv1d --mode backtest`

**Validation**: Create a trivial "always predict up" strategy. Verify it loads, trains (no-op), emits a signal, saves/loads, and appears in the experiment ledger.

---

### Phase 5: Backtesting & Walk-Forward (Sessions 15–18)

**Goal**: Walk-forward engine with configurable policies, backtester with cost model.

**Deliverables**:
- `WalkForwardPolicy` config (expanding/rolling, window sizes, step size)
- Walk-forward engine: iterates folds, retrains per fold, refits scaler per fold, collects per-fold metrics
- `CostModel` (spread, commission, slippage)
- `Backtester`: runs walk-forward, applies cost model, computes PnL curves
- `BacktestResult`: per-fold metrics (accuracy, Sharpe, Sortino, max drawdown, win rate, profit factor) + aggregate + stability
- Leakage audit: automated check that no future data is accessible within any fold
- CLI: `python -m infra.backtest --strategy energy_conv1d --walk-forward expanding --cost-spread 2`

**Validation**: Run walk-forward on the trivial strategy. Verify fold boundaries are correct. Verify scaler is refit. Inject a "cheating" strategy that peeks at future data and verify the leakage audit catches it.

---

### Phase 6: Signal Interpretation & Risk (Sessions 19–21)

**Goal**: Convert signals to proposed actions, enforce risk limits.

**Deliverables**:
- `SignalInterpreter` with per-type interpretation policies
- `ProposedAction` generation with position sizing logic
- `RiskGate` with system-tier and strategy-tier evaluation
- Risk config in YAML (system limits, strategy overrides that tighten only)
- Action pipeline: Signal → Interpreter → ProposedAction → RiskGate → approved/rejected/modified
- Full structured logging of every risk decision

**Validation**: Feed signals of each type through the pipeline. Verify classification signal produces correct buy/sell. Verify system risk limits block over-sized positions. Verify strategy can tighten but not loosen limits.

---

### Phase 7: Execution Layer (Sessions 22–25)

**Goal**: Portfolio management, order placement, approval workflow, broker integration.

**Deliverables**:
- `StrategyBook` state management (positions, PnL, order tracking)
- `BrokerAdapter` ABC
- `AlpacaBrokerAdapter` (paper + live via config)
- Order lifecycle: place → pending → filled/cancelled
- Approval workflow: supervised mode queues actions, expiry logic
- Crash recovery: SQLite state reload + Alpaca position reconciliation
- Event loop: bar arrives → features → strategy → signal → interpreter → risk → approve → execute

**Validation**: Run the full pipeline end-to-end against Alpaca paper with the trivial strategy. Verify orders appear in Alpaca dashboard. Verify crash recovery: kill process, restart, verify state is consistent.

---

### Phase 8: Dashboard (Sessions 26–30)

**Goal**: Web interface for research review and live operations.

**Deliverables**:
- FastAPI backend serving dashboard data
- Server-sent events for live signal/position updates
- Research mode: experiment browser, backtest comparison, per-fold drill-down
- Operations mode: signal feed with approve/reject buttons, position monitor, risk gauges
- Temporal context visualization: bar arrival → signal computation → current time → next bar
- PnL curves (per strategy book, daily, cumulative)
- Staleness indicator on pending signals

**Validation**: Run a paper trading session. Verify signals appear in dashboard, approve one, verify order executes. Verify backtest results from Phase 5 are browsable and comparable.

---

### Phase 9: v1 Strategy Port (Sessions 31–33)

**Goal**: Port the v1 Conv1D energy-sector strategy into the new architecture. This is the acid test.

**Deliverables**:
- `EnergyConv1DStrategy` class implementing `Strategy` interface
- Strategy config YAML (23 energy symbols, feature set matching v1, Conv1D architecture, walk-forward policy)
- Feature dependencies declared, computed via registry
- Training run through the harness, logged in experiment ledger
- Walk-forward backtest with cost model
- Results compared against v1's 51% accuracy baseline
- Document any gaps found in the infrastructure during porting

**Validation**: If this strategy can be expressed cleanly as a Strategy class consuming registry features and evaluated through the walk-forward engine — the architecture works. If it can't, the gap report drives a targeted fix cycle before building new strategies.

---

### Phase 10: Architecture Search Track (Sessions 34+)

**Goal**: Explore the model zoo that v1 defined but never trained.

**Candidates** (from v1, all defined but never executed):
- TCN + Squeeze-Excitation (dilated causal residual blocks)
- Transformer with causal masking and learned positional encoding
- Conv2D (time × features as image)
- Attention-augmented LSTM (with gradient clipping, which v1 missed)

**Additional research directions**:
- Volatility-scaled targets (returns ÷ recent rolling std)
- Multi-asset models (strategy consumes all 23 symbols jointly)
- Alternative data integration (VIX, oil futures — requires new data providers)
- Class imbalance handling (Focal Loss, class weights for the underrepresented "flat" class)
- Hyperparameter optimization (Optuna, integrated with experiment ledger)

Each of these is an independent strategy experiment using the shared infrastructure. They can run in parallel, be compared in the dashboard, and the best performers promoted to paper trading.

---

## 6. Known Traps & Mitigations

These are common failure modes in quant platform development. The architecture addresses each.

| Trap | How it kills you | Mitigation in this architecture |
|------|-----------------|-------------------------------|
| **Lookahead bias** | Features or backtest see future data; results look great, live performance is random | Feature registry enforces +1 bar shift centrally. Walk-forward engine refits scaler per fold. Leakage audit as automated test. |
| **Overfitting to backtest** | Strategy works on historical data, fails live | Walk-forward with per-fold metrics exposes instability. Cost model separates "predictive" from "tradeable." |
| **Survivorship bias** | Only testing on symbols that still exist today | Universe config should document inclusion criteria. Not a v2 blocker but a research discipline. |
| **Transaction costs ignored** | 51% accuracy looks profitable until you subtract spreads | CostModel is required in every backtest. No "gross" results without "net" alongside. |
| **Regime change** | Model trained on 2023 data fails in 2024 market regime | Rolling window walk-forward + per-fold Sharpe variance detects this. Volatility-scaled targets reduce regime sensitivity. |
| **GPU memory leaks** | Long-running service slowly consumes VRAM | Explicit `torch.cuda.empty_cache()` after training. Models pinned to specific device. Memory monitoring in observability. |
| **Notebook-to-production drift** | Notebook prototype doesn't match deployed code | Shared library imports. Training harness only accepts Strategy classes. Notebooks are research drafts, never production. |
| **Config drift** | "What settings produced this result?" becomes unanswerable | Full config snapshot in experiment ledger for every run. Immutable after training completes. |
| **Silent data quality issues** | Missing bars, bad prints, duplicate timestamps corrupt features | Data quality checks in provider layer. Gap detection. Timestamp validation. NaN monitoring in feature computation. |
| **Correlated multi-horizon labels** | Multi-horizon classification learns a shortcut (predict same direction for all) | Monitor per-horizon accuracy independently. Consider volatility-scaled targets. Consider auxiliary losses that decorrelate horizon predictions. |

---

## 7. Repository Structure

```
390orbust-v2/
├── config/
│   ├── system.yaml
│   └── system_schema.py          # Pydantic models
├── src/
│   └── infra/
│       ├── __init__.py
│       ├── types.py              # Signal, ProposedAction, BarEvent, Position, Order, enums
│       ├── config.py             # YAML loading, validation, merge logic
│       ├── logging.py            # structlog setup, correlation IDs
│       ├── data/
│       │   ├── __init__.py
│       │   ├── provider.py       # DataProvider ABC
│       │   ├── alpaca.py         # AlpacaBarProvider
│       │   ├── store.py          # Parquet read/write, SQLite connection
│       │   └── quality.py        # Gap detection, validation
│       ├── features/
│       │   ├── __init__.py
│       │   ├── registry.py       # FeatureRegistry
│       │   ├── builtins.py       # All v1 features as registry entries
│       │   └── leakage.py        # Shift logic, audit tools
│       ├── strategy/
│       │   ├── __init__.py
│       │   ├── base.py           # Strategy ABC
│       │   ├── engine.py         # Strategy loading, GPU management
│       │   ├── training.py       # Training harness
│       │   └── signals.py        # Signal types, serialization
│       ├── evaluation/
│       │   ├── __init__.py
│       │   ├── walk_forward.py   # Walk-forward engine
│       │   ├── backtester.py     # Cost model, PnL simulation
│       │   └── metrics.py        # Sharpe, Sortino, drawdown, etc.
│       ├── execution/
│       │   ├── __init__.py
│       │   ├── interpreter.py    # Signal → ProposedAction
│       │   ├── risk.py           # RiskGate (system + strategy tiers)
│       │   ├── broker.py         # BrokerAdapter ABC
│       │   ├── alpaca_broker.py  # AlpacaBrokerAdapter
│       │   ├── portfolio.py      # StrategyBook, position tracking
│       │   └── approval.py       # Human-in-the-loop workflow
│       ├── dashboard/
│       │   ├── __init__.py
│       │   ├── app.py            # FastAPI application
│       │   ├── events.py         # SSE for live updates
│       │   └── static/           # HTML/JS/CSS
│       ├── ledger/
│       │   ├── __init__.py
│       │   └── experiments.py    # Experiment tracking, model store
│       └── service.py            # Main event loop (long-running service)
├── strategies/
│   └── energy_conv1d/
│       ├── __init__.py
│       ├── strategy.py           # EnergyConv1DStrategy class
│       └── config.yaml
├── models/                       # Trained model artifacts (gitignored)
├── data/                         # Market data cache (gitignored)
├── logs/                         # Structured JSON logs (gitignored)
├── notebooks/                    # Research notebooks
├── tests/
│   ├── test_data_provider.py
│   ├── test_feature_registry.py
│   ├── test_strategy_contract.py
│   ├── test_risk_gate.py
│   ├── test_walk_forward.py
│   └── test_leakage_audit.py
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## 8. What This Document Does NOT Cover

Explicitly named to prevent scope creep:

- **Multi-user access** — Single operator. No auth on the dashboard.
- **Multi-box deployment** — Single machine. No distributed compute.
- **Kubernetes/Docker** — Not in v2. Bare metal.
- **Options/futures trading** — Equities only via Alpaca.
- **High-frequency (sub-second)** — Designed to evolve toward it, but v2 is minute-bar.
- **Portfolio optimization across strategies** — Human is the optimizer in v2. Multi-strategy packages are a labeled future seam.
- **DuckDB integration** — Future seam. Pandas handles v2 analytical queries.
- **L2 order book data** — Future seam. Provider abstraction supports it. No adapter built.
- **Mobile/notifications** — Dashboard is a desktop browser tool. Operator is at the screen during market hours.

---

*This document is the single source of truth for 390OrBust v2 architecture. Every future build session should begin by referencing the relevant phase and component specification herein. Deviations should be deliberate, documented, and reflected back into this document.*
