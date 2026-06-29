"""Pytest path setup.

Loaded by pytest before any test module is imported, so the per-tool source
directories are on sys.path regardless of how imports are ordered inside the
individual test files. This keeps the suite robust against auto-formatters
that reorder imports relative to in-file sys.path manipulation.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Tool source directories that tests import modules from.
_TOOL_DIRS = (
    "FortiGateToFTDTool",
    "FortiGateToPaloAltoTool",
)

for _sub in _TOOL_DIRS:
    _path = str(ROOT / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
