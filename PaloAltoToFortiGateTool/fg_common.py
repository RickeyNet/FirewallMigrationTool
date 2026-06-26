#!/usr/bin/env python3
"""Shared utilities for Palo Alto → FortiGate converter modules.

FortiGate CLI naming rules:
- Object names are enclosed in double-quotes in CLI commands
- Double-quotes and backslashes within names must be avoided
- Maximum name length is ~64 characters for most object types
- FortiGate uses the built-in address object "all" where PAN-OS uses "any"
"""

import re
from typing import List, Tuple, Union

# Max name length for FortiGate objects
FG_NAME_MAX_LENGTH = 64

# PAN-OS "any" translates to FortiGate's built-in "all" address object
PA_ANY_TO_FG_ALL = "all"


def cidr_to_netmask(prefix_len: Union[int, str]) -> str:
    """Convert a CIDR prefix length to a dotted-decimal netmask.

    Example: 24 -> '255.255.255.0'
    """
    try:
        prefix_len = int(prefix_len)
        if prefix_len < 0 or prefix_len > 32:
            return "255.255.255.255"
        if prefix_len == 0:
            return "0.0.0.0"
        bits = 0xFFFFFFFF ^ ((1 << (32 - prefix_len)) - 1)
        return ".".join([str((bits >> (8 * i)) & 0xFF) for i in [3, 2, 1, 0]])
    except (ValueError, TypeError):
        return "255.255.255.255"


def split_cidr(cidr: str) -> Tuple[str, str]:
    """Split CIDR notation into an (ip, netmask) pair.

    Examples:
        '10.0.0.0/24' -> ('10.0.0.0', '255.255.255.0')
        '10.0.0.1/32' -> ('10.0.0.1', '255.255.255.255')
        '10.0.0.1'    -> ('10.0.0.1', '255.255.255.255')
    """
    cidr = str(cidr).strip()
    if "/" in cidr:
        ip, prefix = cidr.split("/", 1)
        return ip.strip(), cidr_to_netmask(prefix.strip())
    return cidr, "255.255.255.255"


def sanitize_fg_name(name: str) -> str:
    """Return a FortiGate-safe object name.

    Strips surrounding whitespace, replaces characters that cause issues
    in FortiGate CLI (double-quotes, backslashes, control characters) with
    underscores, and truncates to the maximum allowed length.
    """
    if not name:
        return ""
    sanitized = re.sub(r'["\\\x00-\x1f\x7f]', "_", str(name).strip())
    return sanitized[:FG_NAME_MAX_LENGTH]


def fg_members_str(members: List[str]) -> str:
    """Format a list of member names as a FortiGate CLI member string.

    Example: ['web1', 'web2'] -> '"web1" "web2"'
    """
    return " ".join(f'"{m}"' for m in members if m)


def map_any_address(name: str) -> str:
    """Map PAN-OS 'any' address to FortiGate's 'all' built-in object."""
    if str(name).strip().lower() == "any":
        return PA_ANY_TO_FG_ALL
    return name
