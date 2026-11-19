"""Compatibility import for the analysis application workflows."""

import sys

from screener.application import analysis_workflows as _implementation

sys.modules[__name__] = _implementation
