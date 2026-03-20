#!/usr/bin/env python3
"""
FortiGate Address Object Converter — Palo Alto PAN-OS Target
=============================================================
Converts FortiGate ``firewall_address`` entries to PAN-OS address objects.

PAN-OS address types:
    ip-netmask  — Host (/32) or subnet (10.0.0.0/24)
    ip-range    — 10.0.0.1-10.0.0.10
    fqdn        — dns.google

Output JSON (later converted to XML by the importer):
    {
        "name": "webserver",
        "type": "ip-netmask",
        "value": "10.10.20.100/32",
        "description": "Web server"
    }
"""

from typing import Any, Dict, List

from pa_common import sanitize_name, netmask_to_cidr


class PAAddressConverter:
    """Convert FortiGate address objects to PAN-OS address format."""

    def __init__(self, fortigate_config: Dict[str, Any]):
        self.fg_config = fortigate_config
        self.pa_address_objects: List[Dict] = []
        self.failed_items: List[Dict] = []

    def convert(self) -> List[Dict]:
        """Convert all FortiGate address objects to PAN-OS format.

        Returns:
            List of dicts, each representing a PAN-OS address object.
        """
        addresses = self.fg_config.get("firewall_address", [])
        if not addresses:
            print("Warning: No address objects found in FortiGate configuration")
            return []

        results: List[Dict] = []
        used_names: Dict[str, int] = {}

        for addr_dict in addresses:
            object_name = list(addr_dict.keys())[0]
            properties = addr_dict[object_name]

            # Skip objects named "none"
            if object_name.lower() == "none":
                print(f"  Skipped: {object_name} (name is 'none')")
                self.failed_items.append({
                    "name": object_name,
                    "reason": "name is 'none'",
                    "config": properties,
                })
                continue

            # Determine PAN-OS type and value
            pa_type = self._determine_type(properties)
            pa_value = self._extract_value(properties, pa_type)

            if not pa_value or pa_value.strip() == "":
                print(f"  Skipped: {object_name} (empty value)")
                self.failed_items.append({
                    "name": object_name,
                    "reason": "empty value",
                    "config": properties,
                })
                continue

            # Validate non-FQDN values
            if pa_type != "fqdn" and not self._is_valid_address(pa_value):
                print(f"  Skipped: {object_name} (invalid value: {pa_value})")
                self.failed_items.append({
                    "name": object_name,
                    "reason": f"invalid value: {pa_value}",
                    "config": properties,
                })
                continue

            # Sanitize and deduplicate name
            sanitized = sanitize_name(object_name)
            if sanitized in used_names:
                used_names[sanitized] += 1
                sanitized = f"{sanitized}_{used_names[sanitized]}"
            else:
                used_names[sanitized] = 1

            pa_object = {
                "name": sanitized,
                "type": pa_type,
                "value": pa_value,
                "description": str(properties.get("comment", "")),
            }
            results.append(pa_object)

            if object_name != sanitized:
                print(f"  Converted: {object_name} -> {sanitized} [{pa_type}] ({pa_value})")
            else:
                print(f"  Converted: {sanitized} -> {pa_type} ({pa_value})")

        self.pa_address_objects = results
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _determine_type(self, properties: Dict) -> str:
        """Map FortiGate address properties to PAN-OS address type."""

        if properties.get("type") == "iprange":
            start_ip = str(properties.get("start-ip", ""))
            end_ip = str(properties.get("end-ip", ""))
            if start_ip and end_ip and start_ip == end_ip:
                return "ip-netmask"  # single host
            return "ip-range"

        if properties.get("type") == "fqdn":
            return "fqdn"

        if "subnet" in properties:
            subnet = properties["subnet"]
            if isinstance(subnet, list) and len(subnet) >= 2:
                netmask = str(subnet[1])
                # All subnet-based addresses use ip-netmask in PAN-OS
                return "ip-netmask"
            return "ip-netmask"

        # Default: treat as host
        return "ip-netmask"

    def _extract_value(self, properties: Dict, pa_type: str) -> str:
        """Extract and format the address value for PAN-OS."""

        if pa_type == "ip-range":
            start_ip = str(properties.get("start-ip", "")).strip()
            end_ip = str(properties.get("end-ip", "")).strip()
            if start_ip and end_ip:
                if start_ip == end_ip:
                    return f"{start_ip}/32"
                return f"{start_ip}-{end_ip}"
            return ""

        if pa_type == "fqdn":
            fqdn = properties.get("fqdn", "")
            if not fqdn:
                fqdn = properties.get("comment", "")
            return str(fqdn).strip().strip('"').strip("'")

        # ip-netmask type
        if "subnet" in properties:
            subnet = properties["subnet"]
            if isinstance(subnet, list) and len(subnet) >= 2:
                ip_addr = str(subnet[0]).strip()
                netmask = str(subnet[1]).strip()
                cidr = netmask_to_cidr(netmask)
                # PAN-OS always uses CIDR notation, including /32 for hosts
                return f"{ip_addr}/{cidr}"
            elif isinstance(subnet, str):
                return subnet.strip()
        return ""

    @staticmethod
    def _is_valid_address(value: str) -> bool:
        """Basic validation for ip-netmask and ip-range values."""
        if not value:
            return False
        # ip-range: two IPs separated by dash
        if "-" in value and "/" not in value:
            parts = value.split("-")
            return len(parts) == 2 and all(_looks_like_ip(p.strip()) for p in parts)
        # ip-netmask: IP/CIDR
        if "/" in value:
            parts = value.split("/")
            return len(parts) == 2 and _looks_like_ip(parts[0])
        # Bare IP
        return _looks_like_ip(value)


def _looks_like_ip(s: str) -> bool:
    """Quick check if string looks like an IPv4 address."""
    parts = s.strip().split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
