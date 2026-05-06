"""Configuration loading and validation.

Layered YAML config with Pydantic validation:

  1. System config:    config/system.yaml       (data paths, risk limits, GPU, broker)
  2. Strategy config:  strategies/{name}/config.yaml  (features, model, hyperparams)
  3. Run mode:         CLI argument             (backtest | paper | live)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

# ═══════════════════════════════════════════════════════════════
# System config — loaded from config/system.yaml
# ═══════════════════════════════════════════════════════════════


class DataPaths(BaseModel):
    data_dir: str = "data"
    model_dir: str = "models"
    log_dir: str = "logs"
    config_dir: str = "config"


class AlpacaConfig(BaseModel):
    key_id: str = ""
    secret_key: str = ""
    paper_endpoint: str = "https://paper-api.alpaca.markets"
    live_endpoint: str = "https://api.alpaca.markets"
    data_endpoint: str = "https://data.alpaca.markets"


class RiskLimits(BaseModel):
    max_total_exposure: float = 100_000.0
    max_position_per_symbol: float = 20_000.0
    max_daily_loss: float = 5_000.0
    max_open_positions: int = 10
    max_drawdown_pct: float = 0.15


class GpuConfig(BaseModel):
    device: Literal["auto", "cuda", "cpu"] = "auto"
    mixed_precision: bool = True
    memory_fraction: float = 0.8


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    refresh_interval_s: int = 5


class SystemConfig(BaseSettings):
    """Top-level system configuration.

    Loaded from config/system.yaml with optional env var overrides.
    """

    stage: Literal["supervised_paper", "autonomous_paper", "autonomous_live"] = "supervised_paper"

    data: DataPaths = DataPaths()
    alpaca: AlpacaConfig = AlpacaConfig()
    risk: RiskLimits = RiskLimits()
    gpu: GpuConfig = GpuConfig()
    dashboard: DashboardConfig = DashboardConfig()

    class Settings:
        env_prefix = "ORBUST_"
        env_nested_delimiter = "__"
        yaml_file: str = "config/system.yaml"

    @classmethod
    def load(cls, path: str | Path | None = None) -> SystemConfig:
        """Load config from YAML, overlay env vars, validate."""
        path = Path(path or "config/system.yaml")
        if path.exists():
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        return cls(**raw)


# ═══════════════════════════════════════════════════════════════
# Strategy config — loaded from strategies/{name}/config.yaml
# ═══════════════════════════════════════════════════════════════


class WalkForwardConfig(BaseModel):
    mode: Literal["expanding", "rolling"] = "expanding"
    min_train_days: int = 30
    validation_days: int = 5
    step_days: int = 5
    window_days: int | None = None


class CostModelConfig(BaseModel):
    spread_bps: float = 2.0
    commission_per_share: float = 0.0
    slippage_bps: float = 1.0


class FeatureConfig(BaseModel):
    """Feature selection for a strategy — references FeatureRegistry entries."""

    names: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ModelConfig(BaseModel):
    """Model hyperparameters — interpreted by the Strategy class."""

    architecture: str = "conv1d"
    hidden_dims: list[int] = Field(default_factory=lambda: [64, 64])
    dropout: float = 0.0
    learning_rate: float = 1e-3
    batch_size: int = 256
    max_epochs: int = 50
    patience: int = 5
    window_size: int = 15


class StrategyConfig(BaseModel):
    """Per-strategy configuration."""

    name: str = ""
    signal_type: Literal["classification", "regression", "ranking", "position"] = "classification"
    symbols: list[str] = Field(default_factory=list)
    features: FeatureConfig = FeatureConfig()
    model: ModelConfig = ModelConfig()
    walk_forward: WalkForwardConfig = WalkForwardConfig()
    cost_model: CostModelConfig = CostModelConfig()
    risk_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbols")
    @classmethod
    def check_symbols_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one symbol required")
        return v


# ═══════════════════════════════════════════════════════════════
# Convenience loader
# ═══════════════════════════════════════════════════════════════


def load_strategy_config(path: str | Path) -> StrategyConfig:
    """Load and validate a strategy YAML config."""
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return StrategyConfig(**raw)


def resolve_config(
    system_path: str | Path = "config/system.yaml",
    strategy_path: str | Path | None = None,
) -> tuple[SystemConfig, StrategyConfig | None]:
    """Load system config + optional strategy config in one call."""
    sys_cfg = SystemConfig.load(system_path)
    strat_cfg = load_strategy_config(strategy_path) if strategy_path else None
    return sys_cfg, strat_cfg
