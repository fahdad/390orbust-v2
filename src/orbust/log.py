"""Structured logging setup with structlog.

Provides:
  - JSON output to stdout (for systemd/journal) + file rotation
  - Correlation IDs (pipeline_id) for tracing bar → signal → order chains
  - Timestamps in ISO-8601 UTC
  - Configurable log level via env var ORBUST_LOG_LEVEL
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import cast

import structlog


def setup_logging(
    *,
    log_dir: str | Path | None = None,
    level: str | None = None,
    json: bool = True,
) -> None:
    """Configure structlog once at application startup."""
    level = level or os.environ.get("ORBUST_LOG_LEVEL", "INFO").upper()

    processors: list[object] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers through structlog
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Keep third-party loggers at WARN to avoid noise
    for logger_name in ("alpaca-py", "urllib3", "httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # File handler if log_dir provided
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path / "orbust.log"),
            maxBytes=100 * 1024 * 1024,  # 100 MB
            backupCount=5,
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root_logger.addHandler(file_handler)


def get_logger(**initial_kwargs: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with optional initial context bindings.

    Usage:
        log = get_logger()
        log.info("bar_received", symbol_count=23)

        # With correlation ID for pipeline tracing:
        log = get_logger(pipeline_id="2026-05-06T09:30:00_abc123")
        log.info("signal_emitted", confidence=0.62)
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(**initial_kwargs))
