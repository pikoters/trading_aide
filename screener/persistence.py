"""Compatibility import for the PostgreSQL persistence adapter."""

import sys

from screener.infrastructure.postgres import repository as _implementation

sys.modules[__name__] = _implementation
