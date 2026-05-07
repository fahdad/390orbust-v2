"""Data Provider Layer — fetch, cache, and serve market data.

Components:
    provider:   DataProvider ABC defining the interface
    alpaca:     AlpacaBarProvider implementation
    store:      Parquet/SQLite storage layer
    quality:    Gap detection, timestamp validation
"""

from orbust.data.provider import DataProvider as DataProvider

__all__ = ["DataProvider"]
