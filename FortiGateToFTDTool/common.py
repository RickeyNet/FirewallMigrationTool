#!/usr/bin/env python3
"""Shared utilities for converter modules."""

import re

_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_]")


def sanitize_name(name: str) -> str:
    """Return an FTD-safe name with only alphanumerics/underscores."""
    if name is None:
        return ""
    sanitized = _SANITIZE_PATTERN.sub("_", str(name))
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized
