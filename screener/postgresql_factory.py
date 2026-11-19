"""Compatibility import for the PostgreSQL connection factory."""

import sys

from screener.infrastructure.postgres import connection_factory as _implementation

sys.modules[__name__] = _implementation
