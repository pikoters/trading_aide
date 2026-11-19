"""Compatibility import for domain trade-plan calculations."""

import sys

from screener.domain import trade_plans as _implementation

sys.modules[__name__] = _implementation
