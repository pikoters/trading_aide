"""Compatibility import for market-backed strategy analysis."""

import sys

from screener.market_data import strategy_analysis as _implementation

sys.modules[__name__] = _implementation
