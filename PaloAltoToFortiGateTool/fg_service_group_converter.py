#!/usr/bin/env python3
"""PAN-OS Service Group Converter — FortiGate Target
======================================================
Converts PAN-OS service groups to FortiGate ``firewall service group``
CLI config.

If the service converter merged TCP+UDP companion objects (e.g.
``DNS_TCP`` + ``DNS_UDP`` → ``DNS``), member references in groups are
automatically updated using the name map from the service converter.

FortiGate CLI output format:
    config firewall service group
        edit "web-services"
            set member "HTTP" "HTTPS" "HTTP_8080"
        next
    end
"""

from typing import Any, Dict, List

from fg_common import sanitize_fg_name, fg_members_str


class FGServiceGroupConverter:
    """Convert PAN-OS service groups to FortiGate service group format."""

    def __init__(
        self,
        pa_config: Dict[str, Any],
        service_name_map: Dict[str, str],
    ):
        self.pa_config = pa_config
        self._name_map = service_name_map
        self.failed_items: List[Dict] = []
        self._stats = {"total": 0, "skipped": 0}

    def convert(self) -> str:
        """Convert all service groups and return FortiGate CLI block.

        Returns:
            A string containing the ``config firewall service group`` block,
            or an empty string if there are no service groups.
        """
        groups = self.pa_config.get("service_groups", [])
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
            members: List[str] = []
            seen: set = set()
            for m in raw_members:
                sanitized_m = sanitize_fg_name(m)
                # Resolve through name map (handles merged TCP+UDP pairs)
                resolved = self._name_map.get(sanitized_m, sanitized_m)
                if resolved and resolved not in seen:
                    members.append(resolved)
                    seen.add(resolved)

            if not members:
                self._record_failure(grp, "no resolvable members")
                continue

            lines = [
                f'    edit "{name}"',
                f"        set member {fg_members_str(members)}",
                "    next",
            ]
            entries.append("\n".join(lines))
            self._stats["total"] += 1
            print(f"  Converted service group: {name} ({len(members)} members)")

        if not entries:
            return ""

        block = "config firewall service group\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)

    def _record_failure(self, grp: Dict, reason: str) -> None:
        name = grp.get("name", "unknown")
        print(f"  Skipped service group: {name} ({reason})")
        self.failed_items.append({"name": name, "reason": reason})
        self._stats["skipped"] += 1
