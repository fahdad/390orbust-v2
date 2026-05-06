"""Main event loop for live/paper trading.

Orchestrates the pipeline: bar arrival → features → strategy → signal
→ interpreter → risk → approval → execution.

Run with:
    python -m orbust.service --mode paper
"""

from __future__ import annotations

import signal
import time

import typer

from orbust.config import resolve_config
from orbust.log import get_logger, setup_logging

app = typer.Typer()
log = get_logger()


@app.command()
def run(
    mode: str = typer.Option("paper", help="backtest | paper | live"),
    config: str = typer.Option("config/system.yaml", help="Path to system config YAML"),
    strategy: str | None = typer.Option(None, help="Strategy name to load (for paper/live)"),
) -> None:
    """Start the trading service."""
    setup_logging(log_dir="logs")
    sys_cfg, _ = resolve_config(config)

    log.info(
        "service_starting",
        mode=mode,
        stage=sys_cfg.stage,
        strategy=strategy,
    )

    # ── Phase 1: Init components ──────────────────────────────
    # data_provider = AlpacaBarProvider(sys_cfg)
    # feature_registry = FeatureRegistry()
    # strategy_engine = ... (warm up, load models)
    # interpreter = SignalInterpreter()
    # risk_gate = RiskGate(sys_cfg.risk)
    # execution = ExecutionLayer(sys_cfg, broker_adapter)

    # ── Phase 2: Main loop ────────────────────────────────────
    running = True

    def shutdown(signum: int, _frame: object) -> None:
        nonlocal running
        log.warning("shutdown_signal_received", signal=signum)
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    tick_count = 0
    while running:
        tick_count += 1

        # TODO: Implement per-component pipeline
        # 1. Poll data provider for new bars
        # 2. Compute features via registry
        # 3. Run strategy predict() → Signal
        # 4. Interpret signal → ProposedAction
        # 5. Risk gate evaluation
        # 6. If approved, place order via broker
        # 7. Log everything with pipeline_id

        # Sleep until next bar (50s to stay ahead of the 60s clock)
        time.sleep(50)

    log.info("service_stopped", ticks=tick_count)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
