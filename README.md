# 390OrBust v2 — Modular Algorithmic Trading Platform

**Mission**: Build a modular, event-driven algorithmic trading platform that supports the full lifecycle from signal research to autonomous live execution — one box, one operator, multiple strategies.

The number 390 refers to the minutes in a US Regular Trading Session (6.5 h x 60 min). The name carries conviction: predict the next 390 minutes' movement, or go bust trying.

---

## Staged Deployment

| Stage | Authority | Target |
|-------|-----------|--------|
| Supervised Paper | Human approves every action | Alpaca paper |
| Autonomous Paper | System executes, human monitors | Alpaca paper |
| Autonomous Live | System executes with risk guardrails | Alpaca live |

Stage transitions are config changes, not rewrites.

---

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐
│ Data Provider │──▶│ Feature      │──▶│ Strategy Engine      │
│ Layer         │   │ Registry     │   │ (pluggable strategies)│
└──────┬───────┘   └──────────────┘   └──────────┬───────────┘
       │                                         │
       │          ┌──────────────┐               │
       └─────────▶│ Data Store   │◀──────────────┘
                  │ (Parquet/    │
                  │  SQLite)     │   ┌──────────────────────┐
                  └──────────────┘   │ Signal Interpreter   │
                                     │ + Risk Layer         │
┌──────────────┐                     └──────────┬──────────┘
│ Walk-Forward │                                │
│ Engine       │   ┌──────────────┐   ┌─────────▼──────────┐
│ + Backtester │   │ Dashboard    │◀─▶│ Execution Layer     │
└──────────────┘   └──────────────┘   └─────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Experiment Ledger & Model Store                              │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ Logging & Observability (structlog, structured JSON)         │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# Clone and enter
git clone <repo-url> 390orbust-v2
cd 390orbust-v2

# Create venv and install deps
uv sync --group dev

# Verify
uv run python -c "from orbust.types import Signal; print('ok')"

# Run tests
uv run pytest
```

---

## Project Structure

```
390orbust-v2/
├── config/
│   └── system.yaml              # System-level configuration
├── src/
│   └── orbust/                  # The orbust package
│       ├── types.py             # Core dataclasses: Signal, Position, Order, enums
│       ├── config.py            # Pydantic-validated config loader
│       ├── log.py               # structlog setup with correlation IDs
│       ├── data/                # Data Provider Layer, Parquet/SQLite store
│       ├── features/            # Feature Registry, built-in feature library
│       ├── strategy/            # Strategy ABC, engine, training harness
│       ├── evaluation/          # Walk-forward engine, backtester, metrics
│       ├── execution/           # Signal interpreter, risk gate, broker adapter
│       ├── dashboard/           # FastAPI + SSE web interface
│       ├── ledger/              # Experiment tracking, model store
│       └── service.py           # Main event loop
├── strategies/                  # Strategy definitions (one dir each)
│   └── energy_conv1d/           # v1 energy Conv1D port
├── notebooks/                   # Research notebooks (marimo)
├── tests/                       # Test suite
├── models/                      # Trained model artifacts (gitignored)
├── data/                        # Market data cache (gitignored)
└── logs/                        # Structured JSON logs (gitignored)
```

---

## Tech Stack

| Concern | Choice |
|---|---|
| Package manager | uv |
| ML framework | PyTorch 2.x (torch.compile, CUDA graphs, AMP) |
| Config | Pydantic + PyYAML |
| Logging | structlog with correlation IDs |
| Linting/formatting | ruff |
| Type checking | mypy (strict) |
| Testing | pytest + hypothesis |
| Notebooks | marimo (.py-native, git-diffable) |
| Dashboard | FastAPI + Jinja2 + htmx + SSE |
| CLI | typer |
| Data | pandas, pyarrow, parquet |
| State | SQLite |

---

## Documentation

The architectural blueprint lives at `~/WorkPlans/390v2/390OrBust_v2_Kickstart.md`. This README is the entry point; the kickstart document is the single source of truth for all architectural decisions.

v1 reference repository: `~/code/390minsv1/` — preserved as-is for feature engineering and model reference.
