"""Alpaca Markets data fetching — raw HTTP, no SDK dependency.

Provides:
    AlpacaFetchError: Descriptive exception for API failures.
    AlpacaFetcher: Historical bar fetcher with pagination and rate limiting.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd
from structlog.stdlib import BoundLogger

from orbust.config import AlpacaConfig
from orbust.log import get_logger
from orbust.types import Timeframe

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

ALPACA_TIMEFRAMES: dict[Timeframe, str] = {
    Timeframe.MINUTE_1: "1Min",
    Timeframe.MINUTE_5: "5Min",
    Timeframe.MINUTE_15: "15Min",
    Timeframe.DAY: "1Day",
}

# Alpaca v2 stock bars endpoint: /v2/stocks/{symbol}/bars
_BARS_ENDPOINT = "/v2/stocks/{symbol}/bars"

# Default API page size — 10_000 is the max Alpaca allows per page
_PAGE_SIZE = 10_000

# Rate limit: 200 requests per 60-second window
_MAX_REQUESTS = 200
_WINDOW_SECONDS = 60.0

# Valid US equity symbol pattern (1-5 uppercase letters, optionally . followed by letters)
_VALID_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,5})?$")

# Retry backoff: 2^attempt seconds, capped at 30s
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 30.0

# Request timeout
_TIMEOUT_SECONDS = 30.0

# Field mapping from Alpaca JSON keys to our column suffixes
_FIELD_MAP: dict[str, str] = {
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "n": "trade_count",
    "vw": "vwap",
}

# All expected fields in the output DataFrame
ALL_FIELDS = list(_FIELD_MAP.values())


# ═══════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════


class AlpacaFetchError(Exception):
    """Raised when an Alpaca API request fails after all retries."""

    def __init__(
        self,
        message: str,
        *,
        symbol: str = "",
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        self.symbol = symbol
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


# ═══════════════════════════════════════════════════════════════
# Rate limiter
# ═══════════════════════════════════════════════════════════════


class _RateLimiter:
    """Sliding-window rate limiter for Alpaca API requests.

    Thread-safe via internal lock.
    """

    def __init__(
        self,
        max_requests: int = _MAX_REQUESTS,
        window_seconds: float = _WINDOW_SECONDS,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def wait_if_needed(self) -> None:
        """Block until a request slot is available."""
        while True:
            now = time.monotonic()

            with self._lock:
                # Prune expired timestamps
                while self._timestamps and self._timestamps[0] <= now - self._window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) >= self._max_requests:
                    need_sleep = self._timestamps[0] + self._window_seconds - now
                else:
                    self._timestamps.append(time.monotonic())
                    return

            # Sleep without the lock held so other threads can prune/register
            if need_sleep > 0:
                time.sleep(need_sleep)

            # Loop back to re-check under lock — other threads may have filled the gap


# ═══════════════════════════════════════════════════════════════
# AlpacaFetcher
# ═══════════════════════════════════════════════════════════════


class AlpacaFetcher:
    """Fetch historical bars from the Alpaca Markets v2 API.

    Handles pagination, rate limiting, and retry with exponential backoff.
    All HTTP calls go through ``_request()`` for easy mocking in tests.

    Args:
        config: Alpaca API credentials and endpoint configuration.
        logger: Optional structlog logger. Creates one with component= if not provided.
    """

    def __init__(
        self,
        config: AlpacaConfig,
        logger: BoundLogger | None = None,
    ) -> None:
        self._config = config
        self._logger = logger or get_logger(component="alpaca_fetcher")

        self._rate_limiter = _RateLimiter()

        # Build base URL from the data endpoint
        base = config.data_endpoint.rstrip("/")
        self._base_url = base

        # Shared httpx client (connection pooling, keep-alive)
        # Alpaca v2 API uses custom headers, not HTTP Basic Auth
        self._client = httpx.Client(
            base_url=base,
            headers={
                "APCA-API-KEY-ID": config.key_id,
                "APCA-API-SECRET-KEY": config.secret_key,
            },
            timeout=_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        """Close the underlying HTTP client, releasing connections."""
        self._client.close()

    def __enter__(self) -> AlpacaFetcher:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Public API ────────────────────────────────────────────

    def fetch_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> pd.DataFrame:
        """Fetch historical bars for one or more symbols.

        Args:
            symbols: List of ticker symbols.
            start: Start of query window (UTC, inclusive).
            end: End of query window (UTC, inclusive).
            timeframe: Bar aggregation period.

        Returns:
            Wide-format DataFrame with UTC DatetimeIndex and ``{SYM}_{field}`` columns.
            Returns an empty DataFrame with correct columns if no data is returned.
        """
        timeframe_str = self._resolve_timeframe(timeframe)

        # Deduplicate symbols to avoid redundant API calls
        symbols = list(dict.fromkeys(symbols))

        # Validate inputs
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware datetimes")
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("start and end must have a UTC offset")

        if start.utcoffset() != timedelta(0):
            raise ValueError(f"start must be in UTC, got offset {start.utcoffset()}")
        if end.utcoffset() != timedelta(0):
            raise ValueError(f"end must be in UTC, got offset {end.utcoffset()}")
        if start >= end:
            raise ValueError(f"start ({start.isoformat()}) must be before end ({end.isoformat()})")
        if not symbols:
            raise ValueError("at least one symbol required")
        for sym in symbols:
            if not _VALID_SYMBOL_RE.match(sym):
                raise ValueError(f"invalid ticker symbol: {sym!r}")

        self._logger.info(
            "fetch_bars_start",
            symbols=symbols,
            start=start.isoformat(),
            end=end.isoformat(),
            timeframe=timeframe_str,
        )

        all_symbol_bars: dict[str, list[dict[str, Any]]] = {}
        total_bars = 0

        for symbol in symbols:
            raw_bars = self._paginate(symbol, start, end, timeframe_str)
            all_symbol_bars[symbol] = raw_bars
            total_bars += len(raw_bars)

        df = self._to_wide_dataframe(all_symbol_bars, symbols)

        self._logger.info(
            "fetch_bars_complete",
            symbols=symbols,
            total_rows=len(df),
            total_bars=total_bars,
        )

        return df

    # ── Pagination ────────────────────────────────────────────

    def _paginate(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe_str: str,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of bar data for a single symbol.

        Args:
            symbol: Ticker symbol.
            start: Start datetime (UTC).
            end: End datetime (UTC).
            timeframe_str: Alpaca timeframe string (e.g. ``"1Min"``).

        Returns:
            List of raw bar dicts from Alpaca.
        """
        all_bars: list[dict[str, Any]] = []
        page_token: str | None = None
        page_count = 0

        while True:
            params = self._build_params(
                start=start,
                end=end,
                timeframe=timeframe_str,
                limit=_PAGE_SIZE,
                feed=self._config.feed,
                page_token=page_token,
            )

            data = self._request(
                "GET",
                _BARS_ENDPOINT.format(symbol=symbol),
                params=params,
            )

            bars = data.get("bars", [])
            all_bars.extend(bars)
            page_count += 1

            page_token = data.get("next_page_token")
            if not page_token:
                break

        self._logger.debug(
            "paginate_done",
            symbol=symbol,
            bars=len(all_bars),
            pages=page_count,
        )

        return all_bars

    # ── Single HTTP request (retry + rate limit) ──────────────

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a single HTTP request with rate limiting and retry.

        This is the single mockable point for all Alpaca HTTP calls.

        Args:
            method: HTTP method (``"GET"``, etc.).
            path: URL path (e.g. ``/v2/stocks/XOM/bars``).
            **kwargs: Extra arguments for ``httpx.Client.request``.

        Returns:
            Parsed JSON response.

        Raises:
            AlpacaFetchError: If the request fails after all retries.
        """
        for attempt in range(_MAX_RETRIES):
            self._rate_limiter.wait_if_needed()

            try:
                response = self._client.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = self._backoff(attempt)
                    self._logger.warning(
                        "request_retry_network",
                        attempt=attempt + 1,
                        path=path,
                        error=str(e),
                        backoff=sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue
                raise AlpacaFetchError(
                    f"Network error after {_MAX_RETRIES} retries: {e}",
                ) from e
            except httpx.InvalidURL as e:
                raise AlpacaFetchError(
                    f"Invalid URL: {e}",
                ) from e
            except httpx.HTTPError as e:
                # Non-retryable HTTP errors
                raise AlpacaFetchError(
                    f"HTTP client error: {e}",
                ) from e

            if response.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    # Respect Retry-After header if provided by Alpaca
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            sleep_time = float(retry_after)
                        except (ValueError, TypeError):
                            sleep_time = self._backoff(attempt)
                    else:
                        sleep_time = self._backoff(attempt)
                    self._logger.warning(
                        "request_retry_429",
                        attempt=attempt + 1,
                        path=path,
                        backoff=sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue
                raise AlpacaFetchError(
                    f"Rate limited after {_MAX_RETRIES} retries",
                    status_code=429,
                    response_body=response.text[:500],
                )

            # Retry transient server errors (5xx) with backoff
            if 500 <= response.status_code < 600:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = self._backoff(attempt)
                    self._logger.warning(
                        "request_retry_5xx",
                        attempt=attempt + 1,
                        path=path,
                        status_code=response.status_code,
                        backoff=sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue
                raise AlpacaFetchError(
                    f"HTTP {response.status_code} after"
                    f" {_MAX_RETRIES} retries: {response.text[:500]}",
                    status_code=response.status_code,
                    response_body=response.text[:500],
                )

            if response.status_code >= 400:
                raise AlpacaFetchError(
                    f"HTTP {response.status_code}: {response.text[:500]}",
                    status_code=response.status_code,
                    response_body=response.text[:500],
                )

            try:
                return response.json()
            except (ValueError, TypeError) as e:
                raise AlpacaFetchError(
                    f"Failed to parse JSON (HTTP {response.status_code}): {e}",
                    status_code=response.status_code,
                    response_body=response.text[:500],
                ) from e

        # Should not reach here, but satisfy type checker
        raise AlpacaFetchError("Unexpected error in _request")

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _resolve_timeframe(timeframe: Timeframe) -> str:
        """Convert Timeframe enum to Alpaca API string."""
        if timeframe not in ALPACA_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe: {timeframe}. Supported: {list(ALPACA_TIMEFRAMES.keys())}"
            )
        return ALPACA_TIMEFRAMES[timeframe]

    @staticmethod
    def _build_params(
        start: datetime,
        end: datetime,
        timeframe: str,
        limit: int,
        feed: str = "sip",
        page_token: str | None = None,
    ) -> dict[str, str]:
        """Build query parameters for the bars endpoint."""
        params: dict[str, str] = {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeframe": timeframe,
            "limit": str(limit),
            "adjustment": "raw",  # no split/dividend adjustment
            "feed": feed,
        }
        if page_token:
            params["page_token"] = page_token
        return params

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff: 2^attempt seconds, capped."""
        return min(_BACKOFF_BASE**attempt, _BACKOFF_CAP)

    @staticmethod
    def _to_wide_dataframe(
        symbol_bars: dict[str, list[dict[str, Any]]],
        symbols: list[str],
    ) -> pd.DataFrame:
        """Convert per-symbol raw bar lists into a wide-format DataFrame.

        Each bar dict from Alpaca has keys:
            t (timestamp), o, h, l, c, v, n, vw

        Returns a DataFrame with:
            - UTC DatetimeIndex (sorted)
            - Columns named ``{SYM}_{field}`` (e.g. ``XOM_open``),
              ordered by symbol then OHLCV convention
            - Missing bar fields represented as NaN (not 0.0)
            - All requested symbols present as columns, even if no data returned
        """
        # Canonical column list: {SYM1}_open, {SYM1}_high, ..., {SYM2}_open, ...
        expected_columns = [f"{sym}_{field}" for sym in symbols for field in ALL_FIELDS]

        all_dfs: list[pd.DataFrame] = []

        for symbol, bars in symbol_bars.items():
            if not bars:
                continue

            # Collect (timestamp, bar) pairs, filtering out unparseable timestamps
            valid_pairs: list[tuple[datetime, dict[str, Any]]] = []
            for bar in bars:
                ts = _parse_alpaca_timestamp(bar.get("t"))
                if ts is not None:
                    valid_pairs.append((ts, bar))

            if not valid_pairs:
                continue

            # Deduplicate by timestamp — keep first occurrence
            seen_ts: set[datetime] = set()
            unique_pairs: list[tuple[datetime, dict[str, Any]]] = []
            for ts, bar in valid_pairs:
                if ts not in seen_ts:
                    seen_ts.add(ts)
                    unique_pairs.append((ts, bar))

            timestamps = [ts for ts, _ in unique_pairs]
            records: dict[str, list[float]] = {f: [] for f in ALL_FIELDS}

            for _, bar in unique_pairs:
                for alpaca_key, field_name in _FIELD_MAP.items():
                    val = bar.get(alpaca_key)
                    # Use NaN for missing values — 0.0 would corrupt downstream indicators
                    records[field_name].append(float(val) if val is not None else float("nan"))

            # Create per-symbol DataFrame for cleaner concatenation
            symbol_df = pd.DataFrame(records, index=timestamps)
            symbol_df.columns = [f"{symbol}_{f}" for f in ALL_FIELDS]
            all_dfs.append(symbol_df)

        if not all_dfs:
            return pd.DataFrame(
                index=pd.DatetimeIndex([], tz=UTC, name="timestamp"),
                columns=expected_columns,
                dtype=float,
            )

        df = pd.concat(all_dfs, axis=1)
        df.index.name = "timestamp"
        df.index = pd.DatetimeIndex(df.index, tz=UTC)
        df = df.sort_index()

        # Reindex ensures all requested symbols are present and in expected order
        df = df.reindex(columns=expected_columns)

        return df


# ═══════════════════════════════════════════════════════════════
# Module-level helpers
# ═══════════════════════════════════════════════════════════════


def _parse_alpaca_timestamp(raw: Any) -> datetime | None:
    """Parse an Alpaca bar timestamp into a UTC-aware datetime.

    Alpaca returns timestamps as ISO-8601 strings (e.g. ``"2023-03-01T14:30:00Z"``)
    or as epoch nanoseconds (int). Converts any timezone offset to UTC.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        # Parse ISO string — handle 'Z' suffix and timezone offsets
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            # Convert any timezone offset to UTC
            return dt.astimezone(UTC)
        except (ValueError, TypeError):
            return None
    if isinstance(raw, (int, float)):
        # Assume epoch nanoseconds. Defensive against nan/inf/extreme values.
        try:
            return datetime.fromtimestamp(raw / 1_000_000_000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None
