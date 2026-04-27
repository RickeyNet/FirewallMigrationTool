#!/usr/bin/env python3
"""PAN-OS Address Group Converter - FortiGate Target
======================================================
Converts PAN-OS address groups to FortiGate ``firewall addrgrp`` CLI config.

PAN-OS supports nested address groups natively, as does FortiGate - no
flattening is required (unlike the FTD converter which must flatten).

FortiGate CLI output format:
    config firewall addrgrp
        edit "web-servers"
            set member "web1" "web2" "app1"
            set comment "All web servers"
        next
    end
"""

from typing import Any, Dict, List

from fg_common import sanitize_fg_name, fg_members_str


class FGAddressGroupConverter:
    """Convert PAN-OS address groups to FortiGate addrgrp format."""

    def __init__(self, pa_config: Dict[str, Any]):
        self.pa_config = pa_config
        self.failed_items: List[Dict] = []
        self._stats = {"total": 0, "skipped": 0}

    def convert(self) -> str:
        """Convert all address groups and return FortiGate CLI block.

        Returns:
            A string containing the ``config firewall addrgrp`` block,
            or an empty string if there are no groups.
        """
        groups = self.pa_config.get("address_groups", [])
        if not groups:
            return ""

        entries: List[str] = []
        used_names: Dict[str, int] = {}

        for grp in groups:
            name = sanitize_fg_name(grp.get("name", ""))
            if not name:
                continue

            if name in used_names:
                used_names[name] += 1
                name = f"{name}_{used_names[name]}"
            else:
                used_names[name] = 1

            raw_members = grp.get("members", [])
            members = [sanitize_fg_name(m) for m in raw_members if m]

            if not members:
                self._record_failure(grp, "no members")
                continue

            description = grp.get("description", "").strip()

            lines = [
                f'    edit "{name}"',
                f"        set member {fg_members_str(members)}",
            ]
            if description:
                safe_comment = description.replace('"', "'")
                lines.append(f'        set comment "{safe_comment}"')
            lines.append("    next")

            entries.append("\n".join(lines))
            self._stats["total"] += 1
            print(f"  Converted address group: {name} ({len(members)} members)")

        if not entries:
            return ""

        block = "config firewall addrgrp\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)

    def _record_failure(self, grp: Dict, reason: str) -> None:
        name = grp.get("name", "unknown")
        print(f"  Skipped address group: {name} ({reason})")
        self.failed_items.append({"name": name, "reason": reason})
        self._stats["skipped"] += 1
