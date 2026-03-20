#!/usr/bin/env python3
"""Shared utilities for Palo Alto converter modules.

PAN-OS naming rules differ from FTD:
- Max 63 characters
- Allowed: alphanumeric, underscore, hyphen, period
- First character must be alphanumeric or underscore
- Case-sensitive
"""

import re
from typing import Any, Dict, List, Optional

# PAN-OS allows alphanumeric, underscore, hyphen, and period
_PA_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_.\-]")

# Max object name length in PAN-OS
PA_NAME_MAX_LENGTH = 63


def sanitize_name(name: str) -> str:
    """Return a PAN-OS-safe object name.

    Replaces disallowed characters with underscores, collapses runs of
    underscores, ensures the first character is valid, and truncates to
    63 characters.
    """
    if name is None:
        return ""
    sanitized = _PA_SANITIZE_PATTERN.sub("_", str(name))
    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # First character must be alphanumeric or underscore
    if sanitized and not (sanitized[0].isalnum() or sanitized[0] == "_"):
        sanitized = "_" + sanitized
    # Truncate to max length
    if len(sanitized) > PA_NAME_MAX_LENGTH:
        sanitized = sanitized[:PA_NAME_MAX_LENGTH]
    return sanitized


def netmask_to_cidr(netmask: str) -> int:
    """Convert a dotted-decimal netmask to CIDR prefix length.

    Example: '255.255.255.0' -> 24
    """
    try:
        parts = netmask.split(".")
        binary = "".join(f"{int(p):08b}" for p in parts)
        return binary.count("1")
    except (ValueError, AttributeError):
        return 32


def build_group_lookup(
    group_entries: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Build a mapping of sanitized group name -> sanitized member names.

    Args:
        group_entries: List of single-key dicts from the FortiGate
            YAML parser (``firewall_addrgrp`` or ``firewall_service_group``).

    Returns:
        ``{group_name: [member1, member2, ...]}`` with all names sanitized.
    """
    lookup: Dict[str, List[str]] = {}
    for group_dict in group_entries:
        group_name = list(group_dict.keys())[0]
        properties = group_dict[group_name]

        members_raw = properties.get("member", [])
        if isinstance(members_raw, str):
            members_list = [members_raw]
        elif isinstance(members_raw, list):
            members_list = members_raw
        else:
            members_list = []

        lookup[sanitize_name(group_name)] = [
            sanitize_name(m) for m in members_list
        ]
    return lookup
