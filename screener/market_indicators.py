"""Compatibility import for domain indicator calculations."""

import sys

from screener.domain import indicators as _implementation

sys.modules[__name__] = _implementation
