#!/usr/bin/env python3
"""Shared utilities for Palo Alto converter modules.

PAN-OS naming rules differ from FTD:
- Max 63 characters
- Allowed: alphanumeric, underscore, hyphen, period
- First character must be alphanumeric or underscore
- Case-sensitive
"""

import re
from typing import Any, Dict, List

# PAN-OS allows alphanumeric, underscore, hyphen, and period
_PA_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_.\-]")

# Max object name length in PAN-OS
PA_NAME_MAX_LENGTH = 63


# ---------------------------------------------------------------------------
# FortiGate factory-default objects
# ---------------------------------------------------------------------------
# These objects ship on every FortiGate appliance regardless of customer
# configuration. They are not meaningful to migrate to the target firewall, so
# they are silently ignored during conversion instead of being reported as
# skipped/failed items that need attention. Names are matched case-insensitively.
DEFAULT_FORTIGATE_ADDRESS_OBJECTS = frozenset({
    "all",
    "none",
    "fabric_device",
    "firewall_auth_portal_address",
    "sslvpn_tunnel_addr1",
    "sslvpn_tunnel_ipv6_addr1",
    "ems_all_unmanageable_clients",
    "ems_all_unknown_clients",
})

DEFAULT_FORTIGATE_SERVICE_OBJECTS = frozenset({
    "all",
    "all_icmp",
    "all_icmp6",
    "all_icmp_type",
})


def is_default_fortigate_address(name: str) -> bool:
    """Return True if *name* is a FortiGate factory-default address object."""
    return name is not None and str(name).strip().lower() in DEFAULT_FORTIGATE_ADDRESS_OBJECTS


def is_default_fortigate_service(name: str) -> bool:
    """Return True if *name* is a FortiGate factory-default service object."""
    return name is not None and str(name).strip().lower() in DEFAULT_FORTIGATE_SERVICE_OBJECTS


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
