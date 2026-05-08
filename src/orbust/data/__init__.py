"""Data Provider Layer — fetch, cache, and serve market data.

Components:
    provider:   DataProvider ABC defining the interface
    alpaca:     AlpacaBarProvider implementation + AlpacaFetcher
    store:      Parquet/SQLite storage layer
    rth:        Regular Trading Hours filtering utility
    quality:    Gap detection, timestamp validation
    notebook:   Notebook-friendly helpers for quick data exploration
"""

from orbust.data.alpaca import AlpacaBarProvider as AlpacaBarProvider
from orbust.data.alpaca import AlpacaFetcher as AlpacaFetcher
from orbust.data.notebook import check as check
from orbust.data.notebook import quick_fetch as quick_fetch
from orbust.data.notebook import summarize as summarize
from orbust.data.provider import DataProvider as DataProvider
from orbust.data.quality import QualityReport as QualityReport
from orbust.data.quality import check_quality as check_quality
from orbust.data.rth import filter_rth as filter_rth
from orbust.data.rth import get_rth_minutes as get_rth_minutes
from orbust.data.rth import is_rth as is_rth
from orbust.data.store import ParquetStore as ParquetStore

__all__ = [
    "AlpacaBarProvider",
    "AlpacaFetcher",
    "DataProvider",
    "ParquetStore",
    "QualityReport",
    "check",
    "check_quality",
    "filter_rth",
    "get_rth_minutes",
    "is_rth",
    "quick_fetch",
    "summarize",
]
