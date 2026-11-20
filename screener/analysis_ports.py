"""Compatibility import for analysis application contracts."""

import sys

from screener.application import analysis_ports as _implementation

sys.modules[__name__] = _implementation
