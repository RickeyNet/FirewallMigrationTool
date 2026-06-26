#!/usr/bin/env python3
"""PAN-OS Address Object Converter - FortiGate Target
======================================================
Converts PAN-OS address objects to FortiGate ``firewall address`` CLI config.

PAN-OS address types and their FortiGate equivalents:
    ip-netmask  -> set type subnet / set subnet <ip> <mask>
    ip-range    -> set type iprange / set start-ip / set end-ip
    fqdn        -> set type fqdn / set fqdn <domain>

FortiGate CLI output format:
    config firewall address
        edit "webserver"
            set subnet 10.10.20.100 255.255.255.255
            set comment "Web server"
        next
        edit "branch_range"
            set type iprange
            set start-ip 10.0.0.1
            set end-ip 10.0.0.10
        next
        edit "update_server"
            set type fqdn
            set fqdn "updates.example.com"
        next
    end
"""

from typing import Any, Dict, List

from fg_common import sanitize_fg_name, split_cidr


class FGAddressConverter:
    """Convert PAN-OS address objects to FortiGate address format."""

    def __init__(self, pa_config: Dict[str, Any]) -> None:
        self.pa_config = pa_config
        self.failed_items: List[Dict] = []
        self._stats = {
            "total": 0,
            "subnet": 0,
            "iprange": 0,
            "fqdn": 0,
            "skipped": 0,
        }

    def convert(self) -> str:
        """Convert all address objects and return FortiGate CLI block.

        Returns:
            A string containing the ``config firewall address`` block,
            or an empty string if there are no address objects.
        """
        addresses = self.pa_config.get("addresses", [])
        if not addresses:
            print("  Warning: No address objects found in PAN-OS configuration")
            return ""

        entries: List[str] = []
        used_names: Dict[str, int] = {}

        for addr in addresses:
            name = sanitize_fg_name(addr.get("name", ""))
            if not name:
                continue

            # Deduplicate names
            if name in used_names:
                used_names[name] += 1
                name = f"{name}_{used_names[name]}"
            else:
                used_names[name] = 1

            addr_type = addr.get("type", "")
            value = addr.get("value", "").strip()
            description = addr.get("description", "").strip()

            lines: List[str] = [f'    edit "{name}"']

            if addr_type == "ip-netmask":
                ip, netmask = split_cidr(value)
                if not ip:
                    self._record_failure(addr, "empty ip-netmask value")
                    continue
                lines.append(f"        set subnet {ip} {netmask}")
                self._stats["subnet"] += 1

            elif addr_type == "ip-range":
                # Format: "10.0.0.1-10.0.0.10"
                if "-" in value:
                    parts = value.split("-", 1)
                    start_ip = parts[0].strip()
                    end_ip = parts[1].strip()
                else:
                    self._record_failure(addr, f"unrecognized ip-range format: {value}")
                    continue
                lines.append("        set type iprange")
                lines.append(f"        set start-ip {start_ip}")
                lines.append(f"        set end-ip {end_ip}")
                self._stats["iprange"] += 1

            elif addr_type == "fqdn":
                if not value:
                    self._record_failure(addr, "empty fqdn value")
                    continue
                lines.append("        set type fqdn")
                lines.append(f'        set fqdn "{value}"')
                self._stats["fqdn"] += 1

            else:
                self._record_failure(addr, f"unsupported address type: {addr_type}")
                continue

            if description:
                # Escape any single quotes in comments
                safe_comment = description.replace('"', "'")
                lines.append(f'        set comment "{safe_comment}"')

            lines.append("    next")
            entries.append("\n".join(lines))
            self._stats["total"] += 1
            print(f"  Converted address: {name} ({addr_type})")

        if not entries:
            return ""

        block = "config firewall address\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)

    def _record_failure(self, addr: Dict, reason: str) -> None:
        name = addr.get("name", "unknown")
        print(f"  Skipped address: {name} ({reason})")
        self.failed_items.append({"name": name, "reason": reason})
        self._stats["skipped"] += 1
