"""Compatibility import for Yahoo Finance market-context retrieval."""

import sys

from screener.market_data import context as _implementation

sys.modules[__name__] = _implementation
