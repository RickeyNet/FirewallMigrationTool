#!/usr/bin/env python3
"""Shared utilities for converter modules."""

import re
from typing import Any, Dict, List, Optional

_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_]")


def sanitize_name(name: str) -> str:
    """Return an FTD-safe name with only alphanumerics/underscores."""
    if name is None:
        return ""
    sanitized = _SANITIZE_PATTERN.sub("_", str(name))
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized


# ---------------------------------------------------------------------------
# Group-flattening helpers (used by address_group_converter & service_group_converter)
# ---------------------------------------------------------------------------

def build_group_lookup(group_entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Build a mapping of sanitized group name -> sanitized member names.

    Args:
        group_entries: List of single-key dicts as produced by the FortiGate
            YAML parser for ``firewall_addrgrp`` or ``firewall_service_group``.

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

        lookup[sanitize_name(group_name)] = [sanitize_name(m) for m in members_list]
    return lookup


def flatten_group_members(
    members: List[str],
    group_lookup: Dict[str, List[str]],
    visited: Optional[set] = None,
) -> List[str]:
    """Recursively flatten *members*, expanding any nested groups.

    Args:
        members: Member names (may include group names).
        group_lookup: Mapping returned by :func:`build_group_lookup`.
        visited: Already-visited group names (circular-reference guard).

    Returns:
        Deduplicated list of individual object names (order-preserving).
    """
    if visited is None:
        visited = set()

    flattened: List[str] = []

    for member in members:
        if member in group_lookup:
            if member in visited:
                print(f"    Warning: Circular reference detected for group '{member}', skipping")
                continue

            visited.add(member)

            nested_members = group_lookup.get(member, [])
            expanded = flatten_group_members(nested_members, group_lookup, visited)

            print(f"    Flattening nested group '{member}' -> {len(expanded)} objects")
            flattened.extend(expanded)
        else:
            flattened.append(member)

    # Remove duplicates while preserving order
    seen: set = set()
    unique: List[str] = []
    for item in flattened:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    return unique
