#!/usr/bin/env python3
"""
FortiGate Address Group Converter — Palo Alto PAN-OS Target
============================================================
Converts FortiGate ``firewall_addrgrp`` entries to PAN-OS address groups.

PAN-OS supports nested address groups natively, so no flattening is needed
(unlike FTD).

Output JSON:
    {
        "name": "web_servers",
        "members": ["webserver1", "webserver2"],
        "description": "Web server group"
    }
"""

from typing import Any, Dict, List

from pa_common import sanitize_name


class PAAddressGroupConverter:
    """Convert FortiGate address groups to PAN-OS address-group format."""

    def __init__(self, fortigate_config: Dict[str, Any]):
        self.fg_config = fortigate_config
        self.pa_address_groups: List[Dict] = []
        self.failed_items: List[Dict] = []

    def convert(self) -> List[Dict]:
        """Convert all FortiGate address groups to PAN-OS format.

        Returns:
            List of dicts, each representing a PAN-OS address group.
        """
        groups = self.fg_config.get("firewall_addrgrp", [])
        if not groups:
            print("Warning: No address groups found in FortiGate configuration")
            return []

        results: List[Dict] = []
        used_names: Dict[str, int] = {}

        for group_dict in groups:
            group_name = list(group_dict.keys())[0]
            properties = group_dict[group_name]

            # Extract members (can be string or list)
            members_raw = properties.get("member", [])
            if isinstance(members_raw, str):
                members_list = [members_raw]
            elif isinstance(members_raw, list):
                members_list = members_raw
            else:
                members_list = []

            if not members_list:
                print(f"  Skipped: {group_name} (no members)")
                self.failed_items.append({
                    "name": group_name,
                    "reason": "no members",
                    "config": properties,
                })
                continue

            # Sanitize group name (deduplicate)
            sanitized = sanitize_name(group_name)
            if sanitized in used_names:
                used_names[sanitized] += 1
                sanitized = f"{sanitized}_{used_names[sanitized]}"
            else:
                used_names[sanitized] = 1

            # Sanitize member names
            # PAN-OS supports nested groups, so we keep group references as-is
            sanitized_members = [sanitize_name(m) for m in members_list]

            pa_group = {
                "name": sanitized,
                "members": sanitized_members,
                "description": str(properties.get("comment", "")),
            }
            results.append(pa_group)

            if group_name != sanitized:
                print(f"  Converted: {group_name} -> {sanitized} ({len(sanitized_members)} members)")
            else:
                print(f"  Converted: {sanitized} ({len(sanitized_members)} members)")

        self.pa_address_groups = results
        return results
