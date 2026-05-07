"""Tests for AlpacaFetcher — pagination, rate limiting, error handling, data format."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from orbust.config import AlpacaConfig
from orbust.data.alpaca import (
    _FIELD_MAP,
    ALL_FIELDS,
    AlpacaFetcher,
    AlpacaFetchError,
    _RateLimiter,
)
from orbust.types import Timeframe

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def alpaca_config() -> AlpacaConfig:
    """Minimal AlpacaConfig for testing (no real credentials needed)."""
    return AlpacaConfig(
        key_id="test_key_id",
        secret_key="test_secret",
        data_endpoint="https://data.alpaca.markets",
    )


@pytest.fixture
def fetcher(alpaca_config: AlpacaConfig) -> AlpacaFetcher:
    """AlpacaFetcher with _request mocked to avoid real HTTP."""
    f = AlpacaFetcher(alpaca_config)
    # Ensure the rate limiter never actually blocks during tests
    f._rate_limiter = _RateLimiter(max_requests=10_000, window_seconds=0.001)
    yield f
    f.close()


def _make_bar(
    t: str,
    o: float = 100.0,
    h: float = 101.0,
    low_: float = 99.0,
    c: float = 100.5,
    v: float = 1_000_000,
    n: int = 5_000,
    vw: float = 100.3,
) -> dict[str, Any]:
    """Helper to create a single bar dict matching Alpaca's response format."""
    return {"t": t, "o": o, "h": h, "l": low_, "c": c, "v": v, "n": n, "vw": vw}


def _mock_response(status_code: int, json_data: dict[str, Any]) -> MagicMock:
    """Create a mock HTTP response with the given status code and JSON body."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = str(json_data)
    mock.json.return_value = json_data
    mock.headers = {}
    return mock


# ═══════════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════════


class TestConstruction:
    def test_accepts_config(self, alpaca_config: AlpacaConfig) -> None:
        """Can instantiate with an AlpacaConfig."""
        f = AlpacaFetcher(alpaca_config)
        assert f._config is alpaca_config

    def test_base_url_from_data_endpoint(self, alpaca_config: AlpacaConfig) -> None:
        """Base URL is derived from the data endpoint."""
        f = AlpacaFetcher(alpaca_config)
        assert f._base_url == "https://data.alpaca.markets"

    def test_strips_trailing_slash(self) -> None:
        """Trailing slash on endpoint is stripped."""
        config = AlpacaConfig(data_endpoint="https://data.alpaca.markets/")
        f = AlpacaFetcher(config)
        assert f._base_url == "https://data.alpaca.markets"


# ═══════════════════════════════════════════════════════════════
# _request — retry + error handling
# ═══════════════════════════════════════════════════════════════

# Important: we patch fetcher._client.request directly since _request
# delegates to it. This tests the retry/error logic around the HTTP call.


class TestRequest:
    """All HTTP calls go through _request — test retry, backoff, errors."""

    def test_returns_json_on_success(self, fetcher: AlpacaFetcher) -> None:
        """Successful response returns parsed JSON."""
        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.return_value = _mock_response(200, {"bars": []})

            result = fetcher._request("GET", "/test")

            assert result == {"bars": []}
            mock_client.assert_called_once()

    def test_429_retries_then_succeeds(self, fetcher: AlpacaFetcher) -> None:
        """A single 429 is retried and succeeds on the second attempt."""
        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.side_effect = [
                _mock_response(429, {}),
                _mock_response(200, {"bars": [1]}),
            ]

            with patch("time.sleep") as mock_sleep:
                result = fetcher._request("GET", "/test")

            assert result == {"bars": [1]}
            assert mock_client.call_count == 2
            mock_sleep.assert_called_once()

    def test_429_exhausts_retries(self, fetcher: AlpacaFetcher) -> None:
        """Persistent 429 raises AlpacaFetchError after all retries."""
        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.return_value = _mock_response(429, {})
            mock_client.side_effect = None  # unset side_effect

            # Override the return_value for all calls
            mock_client.return_value = _mock_response(429, {})

            with patch("time.sleep"), pytest.raises(AlpacaFetchError) as excinfo:
                fetcher._request("GET", "/test")

            assert "Rate limited" in str(excinfo.value)
            assert excinfo.value.status_code == 429
            # 5 retries = 1 initial + 4 retries = 5 calls total (then raise)
            assert mock_client.call_count == 5

    def test_400_raises_immediately(self, fetcher: AlpacaFetcher) -> None:
        """4xx errors raise AlpacaFetchError immediately (no retry)."""
        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.return_value = _mock_response(400, {"message": "Bad Request"})

            with pytest.raises(AlpacaFetchError) as excinfo:
                fetcher._request("GET", "/test")

            assert excinfo.value.status_code == 400
            assert mock_client.call_count == 1  # no retry

    def test_500_retries_then_fails(self, fetcher: AlpacaFetcher) -> None:
        """5xx errors are retried with backoff, then raise AlpacaFetchError."""
        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.return_value = _mock_response(500, {"message": "Server Error"})

            with patch("time.sleep"), pytest.raises(AlpacaFetchError) as excinfo:
                fetcher._request("GET", "/test")

            assert excinfo.value.status_code == 500
            assert mock_client.call_count == 5  # retried 4 times, then failed

    def test_retry_backoff_progression(self, fetcher: AlpacaFetcher) -> None:
        """429 retries use increasing backoff: 2^attempt seconds."""
        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.return_value = _mock_response(429, {})

            with patch("time.sleep") as mock_sleep, pytest.raises(AlpacaFetchError):
                fetcher._request("GET", "/test")

            # 5 calls total: 1 initial + 4 retries. Sleeps before retries 1-4.
            # Backoff: 2^0, 2^1, 2^2, 2^3 = 1.0, 2.0, 4.0, 8.0
            expected_sleeps = [1.0, 2.0, 4.0, 8.0]
            actual_sleeps = [args[0][0] for args in mock_sleep.call_args_list]
            assert actual_sleeps == expected_sleeps

    def test_backoff_capped_at_30s(self) -> None:
        """Exponential backoff caps at 30 seconds."""
        from orbust.data.alpaca import _BACKOFF_CAP

        f = AlpacaFetcher(AlpacaConfig())
        assert f._backoff(10) == _BACKOFF_CAP  # 2^10 = 1024, capped at 30

    def test_connect_error_retries_then_succeeds(self, fetcher: AlpacaFetcher) -> None:
        """Transient ConnectError is retried and succeeds on second attempt."""
        import httpx

        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.side_effect = [
                httpx.ConnectError("connection refused"),
                _mock_response(200, {"bars": []}),
            ]

            with patch("time.sleep"):
                result = fetcher._request("GET", "/test")

            assert result == {"bars": []}
            assert mock_client.call_count == 2

    def test_connect_error_exhausts_retries(self, fetcher: AlpacaFetcher) -> None:
        """Persistent ConnectError raises AlpacaFetchError after all retries."""
        import httpx

        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.side_effect = httpx.ConnectError("connection refused")

            with patch("time.sleep"), pytest.raises(AlpacaFetchError) as excinfo:
                fetcher._request("GET", "/test")

            assert "Network error" in str(excinfo.value)
            assert mock_client.call_count == 5

    def test_non_retryable_http_error_raises_immediately(self, fetcher: AlpacaFetcher) -> None:
        """Non-retryable HTTPError (e.g., InvalidURL) raises immediately."""
        import httpx

        with patch.object(fetcher._client, "request") as mock_client:
            mock_client.side_effect = httpx.InvalidURL("invalid url")

            with pytest.raises(AlpacaFetchError):
                fetcher._request("GET", "/test")

            assert mock_client.call_count == 1  # no retry


# ═══════════════════════════════════════════════════════════════
# _paginate — single + multi-page responses
# ═══════════════════════════════════════════════════════════════


class TestPaginate:
    """_paginate iterates pages until next_page_token is absent."""

    def test_single_page(self, fetcher: AlpacaFetcher) -> None:
        """A single page with no next_page_token works."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {
                "bars": [_make_bar("2023-03-01T14:30:00Z")],
                "next_page_token": None,
                "symbol": "XOM",
            }

            result = fetcher._paginate(
                "XOM",
                datetime(2023, 3, 1, 14, 30),
                datetime(2023, 3, 1, 15, 0),
                "1Min",
            )

            assert len(result) == 1
            mock_request.assert_called_once()

    def test_multiple_pages(self, fetcher: AlpacaFetcher) -> None:
        """Multiple pages via next_page_token are concatenated."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.side_effect = [
                {
                    "bars": [_make_bar("2023-03-01T14:30:00Z")],
                    "next_page_token": "token_abc",
                    "symbol": "XOM",
                },
                {
                    "bars": [_make_bar("2023-03-01T14:31:00Z")],
                    "next_page_token": None,
                    "symbol": "XOM",
                },
            ]

            result = fetcher._paginate(
                "XOM",
                datetime(2023, 3, 1, 14, 30),
                datetime(2023, 3, 1, 15, 0),
                "1Min",
            )

            assert len(result) == 2
            assert mock_request.call_count == 2
            # Second call should include page_token param
            _, kwargs = mock_request.call_args_list[1]
            params = kwargs.get("params", {})
            assert params.get("page_token") == "token_abc"

    def test_three_pages(self, fetcher: AlpacaFetcher) -> None:
        """Three pages are concatenated correctly."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.side_effect = [
                {"bars": [_make_bar("t1")], "next_page_token": "t1"},
                {"bars": [_make_bar("t2")], "next_page_token": "t2"},
                {"bars": [_make_bar("t3")], "next_page_token": None},
            ]

            result = fetcher._paginate(
                "XOM",
                datetime(2023, 3, 1, 14, 30),
                datetime(2023, 3, 1, 15, 0),
                "1Min",
            )

            assert len(result) == 3

    def test_empty_response(self, fetcher: AlpacaFetcher) -> None:
        """Empty bars list returns empty list."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {
                "bars": [],
                "next_page_token": None,
                "symbol": "XOM",
            }

            result = fetcher._paginate(
                "XOM",
                datetime(2023, 3, 1, 14, 30),
                datetime(2023, 3, 1, 15, 0),
                "1Min",
            )

            assert result == []

    def test_missing_bars_key(self, fetcher: AlpacaFetcher) -> None:
        """Response missing 'bars' key defaults to empty list (safety)."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {"symbol": "XOM"}

            result = fetcher._paginate(
                "XOM",
                datetime(2023, 3, 1, 14, 30),
                datetime(2023, 3, 1, 15, 0),
                "1Min",
            )

            assert result == []


# ═══════════════════════════════════════════════════════════════
# fetch_bars — end-to-end
# ═══════════════════════════════════════════════════════════════


class TestFetchBars:
    def test_single_symbol(self, fetcher: AlpacaFetcher) -> None:
        """fetch_bars returns wide-format DataFrame for one symbol."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {
                "bars": [
                    _make_bar("2023-03-01T14:30:00Z", c=100.0),
                    _make_bar("2023-03-01T14:31:00Z", c=100.5),
                ],
                "next_page_token": None,
                "symbol": "XOM",
            }

            df = fetcher.fetch_bars(
                ["XOM"],
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 15, 0, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

            assert isinstance(df, pd.DataFrame)
            assert "XOM_close" in df.columns
            assert "XOM_open" in df.columns
            assert "XOM_volume" in df.columns
            assert df.index.tz is not None
            assert str(df.index.tz) == "UTC"
            assert len(df) == 2

    def test_multiple_symbols(self, fetcher: AlpacaFetcher) -> None:
        """fetch_bars returns combined DataFrame for multiple symbols."""
        # _paginate is called once per symbol — mock _paginate directly
        with patch.object(fetcher, "_paginate") as mock_paginate:
            mock_paginate.side_effect = [
                [
                    _make_bar("2023-03-01T14:30:00Z", c=100.0),
                    _make_bar("2023-03-01T14:31:00Z", c=100.5),
                ],
                [
                    _make_bar("2023-03-01T14:30:00Z", c=50.0),
                    _make_bar("2023-03-01T14:31:00Z", c=50.5),
                ],
            ]

            df = fetcher.fetch_bars(
                ["XOM", "XOP"],
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 15, 0, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

            assert isinstance(df, pd.DataFrame)
            assert "XOM_close" in df.columns
            assert "XOP_close" in df.columns
            assert df.index.tz is not None
            assert len(df) == 2
            assert mock_paginate.call_count == 2

    def test_empty_response(self, fetcher: AlpacaFetcher) -> None:
        """Empty API response returns empty DataFrame with no error."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {
                "bars": [],
                "next_page_token": None,
                "symbol": "XOM",
            }

            df = fetcher.fetch_bars(
                ["XOM"],
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 15, 0, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 0

    def test_partial_data(self, fetcher: AlpacaFetcher) -> None:
        """One symbol has data, another has none — still returns a valid DataFrame."""
        with patch.object(fetcher, "_paginate") as mock_paginate:
            mock_paginate.side_effect = [
                [
                    _make_bar("2023-03-01T14:30:00Z", c=100.0),
                ],
                [],  # XOP has no data
            ]

            df = fetcher.fetch_bars(
                ["XOM", "XOP"],
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 15, 0, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

            assert isinstance(df, pd.DataFrame)
            assert "XOM_close" in df.columns
            assert len(df) == 1

    def test_column_naming_convention(self, fetcher: AlpacaFetcher) -> None:
        """Columns follow {SYM}_{field} naming."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {
                "bars": [_make_bar("2023-03-01T14:30:00Z")],
                "next_page_token": None,
                "symbol": "XOM",
            }

            df = fetcher.fetch_bars(
                ["XOM"],
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 15, 0, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

            for col in df.columns:
                assert col.startswith("XOM_")
                assert "_" in col

    def test_null_timestamp_bars_are_skipped(self, fetcher: AlpacaFetcher) -> None:
        """Bars with null/unparseable timestamps are silently skipped (no data corruption)."""
        with patch.object(fetcher, "_request") as mock_request:
            mock_request.return_value = {
                "bars": [
                    _make_bar("2023-03-01T14:30:00Z", c=100.0),
                    {"t": None, "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 100, "n": 10, "vw": 1.5},
                    _make_bar("2023-03-01T14:31:00Z", c=100.5),
                ],
                "next_page_token": None,
                "symbol": "XOM",
            }

            df = fetcher.fetch_bars(
                ["XOM"],
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 15, 0, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

            assert len(df) == 2  # null-timestamp bar skipped
            assert "XOM_close" in df.columns
            assert df["XOM_close"].iloc[0] == 100.0
            assert df["XOM_close"].iloc[1] == 100.5

    def test_rejects_naive_datetimes(self, fetcher: AlpacaFetcher) -> None:
        """fetch_bars rejects naive (non-timezone-aware) datetimes."""
        with pytest.raises(ValueError, match="timezone-aware"):
            fetcher.fetch_bars(
                ["XOM"],
                datetime(2023, 3, 1, 14, 30),  # no tzinfo
                datetime(2023, 3, 1, 15, 0),  # no tzinfo
                Timeframe.MINUTE_1,
            )

    def test_rejects_start_after_end(self, fetcher: AlpacaFetcher) -> None:
        """fetch_bars rejects start >= end."""
        with pytest.raises(ValueError, match="must be before"):
            fetcher.fetch_bars(
                ["XOM"],
                datetime(2023, 3, 2, 14, 30, tzinfo=UTC),
                datetime(2023, 3, 1, 14, 30, tzinfo=UTC),
                Timeframe.MINUTE_1,
            )

    def test_context_manager_closes_client(self, alpaca_config: AlpacaConfig) -> None:
        """Context manager closes the httpx client on exit."""
        fetcher = AlpacaFetcher(alpaca_config)
        with patch.object(fetcher._client, "close") as mock_close:
            with fetcher:
                pass
            mock_close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Timeframe mapping
# ═══════════════════════════════════════════════════════════════


class TestTimeframeMapping:
    def test_all_timeframes_map(self) -> None:
        """All Timeframe enum values map to valid Alpaca strings."""
        from orbust.data.alpaca import ALPACA_TIMEFRAMES

        for tf in Timeframe:
            assert tf in ALPACA_TIMEFRAMES
            assert isinstance(ALPACA_TIMEFRAMES[tf], str)

    def test_resolve_valid_timeframe(self) -> None:
        """_resolve_timeframe returns correct Alpaca string."""
        assert AlpacaFetcher._resolve_timeframe(Timeframe.MINUTE_1) == "1Min"
        assert AlpacaFetcher._resolve_timeframe(Timeframe.MINUTE_5) == "5Min"
        assert AlpacaFetcher._resolve_timeframe(Timeframe.MINUTE_15) == "15Min"
        assert AlpacaFetcher._resolve_timeframe(Timeframe.DAY) == "1Day"


# ═══════════════════════════════════════════════════════════════
# Data format helpers
# ═══════════════════════════════════════════════════════════════


class TestFieldMapping:
    def test_field_map_keys_match_alpaca(self) -> None:
        """_FIELD_MAP covers all expected Alpaca response bar keys."""
        expected_keys = {"o", "h", "l", "c", "v", "n", "vw"}
        assert set(_FIELD_MAP.keys()) == expected_keys

    def test_all_fields_matches_field_map_values(self) -> None:
        """ALL_FIELDS covers all field suffixes from the map (order-preserving)."""
        assert set(ALL_FIELDS) == set(_FIELD_MAP.values())
        assert len(ALL_FIELDS) == len(_FIELD_MAP)
        assert ALL_FIELDS[0] == "open"  # first in dict insertion order
        assert ALL_FIELDS[-1] == "vwap"  # last in dict insertion order

    def test_parse_alpaca_timestamp_iso(self) -> None:
        """ISO-8601 string is parsed to UTC-aware datetime."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        dt = _parse_alpaca_timestamp("2023-03-01T14:30:00Z")
        assert dt is not None
        assert dt.year == 2023
        assert dt.month == 3
        assert dt.day == 1
        assert dt.hour == 14
        assert dt.minute == 30
        assert dt.tzinfo is not None

    def test_parse_alpaca_timestamp_offset(self) -> None:
        """ISO-8601 with offset is parsed correctly."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        dt = _parse_alpaca_timestamp("2023-03-01T09:30:00-05:00")
        assert dt is not None
        # -05:00 offset means 09:30 ET = 14:30 UTC
        assert dt.hour == 14

    def test_parse_alpaca_timestamp_none(self) -> None:
        """None returns None."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        assert _parse_alpaca_timestamp(None) is None

    def test_parse_alpaca_timestamp_epoch_ns(self) -> None:
        """Epoch nanoseconds (int) is parsed correctly."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        # 2023-03-01T14:30:00Z in epoch nanoseconds: 1677681000 seconds * 1e9
        dt = _parse_alpaca_timestamp(1677681000000000000)
        assert dt is not None
        assert dt.year == 2023
        assert dt.month == 3
        assert dt.day == 1
        assert dt.hour == 14
        assert dt.minute == 30
        assert dt.tzinfo is not None

    def test_parse_alpaca_timestamp_epoch_float(self) -> None:
        """Epoch nanoseconds (float) is parsed correctly."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        dt = _parse_alpaca_timestamp(1677681000000000000.0)
        assert dt is not None
        assert dt.hour == 14

    def test_parse_alpaca_timestamp_invalid_string(self) -> None:
        """Invalid ISO string returns None."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        assert _parse_alpaca_timestamp("not-a-date") is None

    def test_parse_alpaca_timestamp_invalid_type(self) -> None:
        """Unsupported type (e.g., list) returns None."""
        from orbust.data.alpaca import _parse_alpaca_timestamp

        assert _parse_alpaca_timestamp([]) is None


# ═══════════════════════════════════════════════════════════════
# Rate limiter
# ═══════════════════════════════════════════════════════════════


class TestRateLimiter:
    def test_single_request_passes(self) -> None:
        """A single request does not block."""
        limiter = _RateLimiter(max_requests=200, window_seconds=60.0)
        start = time.monotonic()
        limiter.wait_if_needed()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # should not block

    def test_tracks_request_timestamps(self) -> None:
        """After N requests, N timestamps are tracked."""
        limiter = _RateLimiter(max_requests=200, window_seconds=60.0)
        for _ in range(3):
            limiter.wait_if_needed()
        assert len(limiter._timestamps) == 3

    def test_prunes_expired_timestamps(self) -> None:
        """Timestamps older than window_seconds are pruned."""
        limiter = _RateLimiter(max_requests=2, window_seconds=0.01)

        limiter.wait_if_needed()
        limiter.wait_if_needed()
        assert len(limiter._timestamps) == 2

        time.sleep(0.015)

        # Next call should prune old timestamps
        limiter.wait_if_needed()
        assert len(limiter._timestamps) == 1  # old 2 pruned, 1 new


# ═══════════════════════════════════════════════════════════════
# Import verification
# ═══════════════════════════════════════════════════════════════


def test_importable() -> None:
    """AlpacaFetcher and AlpacaFetchError are importable."""
    from orbust.data.alpaca import AlpacaFetcher, AlpacaFetchError

    assert AlpacaFetcher is not None
    assert AlpacaFetchError is not None


def test_error_has_attributes() -> None:
    """AlpacaFetchError carries symbol, status_code, response_body."""
    err = AlpacaFetchError(
        "test error",
        symbol="XOM",
        status_code=429,
        response_body='{"message":"rate limit"}',
    )
    assert err.symbol == "XOM"
    assert err.status_code == 429
    assert err.response_body is not None
    assert "rate limit" in err.response_body
