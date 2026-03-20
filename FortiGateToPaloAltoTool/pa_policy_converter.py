#!/usr/bin/env python3
"""
FortiGate Policy Converter — Palo Alto PAN-OS Target
=====================================================
Converts FortiGate ``firewall_policy`` entries to PAN-OS security rules.

PAN-OS security rule fields:
    - from/to       : source/destination zones
    - source/dest   : address objects or groups
    - service       : service objects, groups, "any", or "application-default"
    - application   : always "any" for migration (app-id can be tuned later)
    - action        : allow / deny / drop / reset-*
    - log-end       : yes/no

Output JSON:
    {
        "name": "Allow_Web",
        "from_zones": ["untrust"],
        "to_zones": ["trust"],
        "sources": ["any"],
        "destinations": ["webserver"],
        "services": ["tcp_80", "tcp_443"],
        "application": ["any"],
        "action": "allow",
        "log_end": "yes",
        "description": "Allow web traffic",
        "disabled": "no"
    }
"""

from typing import Any, Dict, List, Set, Tuple

from pa_common import sanitize_name


class PAPolicyConverter:
    """Convert FortiGate firewall policies to PAN-OS security rules."""

    def __init__(self, fortigate_config: Dict[str, Any]):
        self.fg_config = fortigate_config
        self.pa_security_rules: List[Dict] = []
        self.failed_items: List[Dict] = []

        # Set by the orchestrator after service/address conversion
        self._split_services: Set[str] = set()
        self._service_name_mapping: Dict[str, List[Tuple[str, str]]] = {}
        self._skipped_services: Set[str] = set()
        self._address_groups: Set[str] = set()
        self._service_groups: Set[str] = set()
        self._interface_name_mapping: Dict[str, str] = {}

        # Statistics
        self._stats = {
            "total_rules": 0,
            "allow_rules": 0,
            "deny_rules": 0,
        }

    def set_split_services(
        self,
        split_services: Set[str],
        service_name_mapping: Dict[str, List[Tuple[str, str]]],
        skipped_services: Set[str],
        address_groups: Set[str],
        service_groups: Set[str],
        interface_name_mapping: Dict[str, str],
    ) -> None:
        """Provide context from prior converters (called before convert)."""
        self._split_services = split_services
        self._service_name_mapping = service_name_mapping
        self._skipped_services = skipped_services
        self._address_groups = address_groups
        self._service_groups = service_groups
        self._interface_name_mapping = interface_name_mapping

    def convert(self) -> List[Dict]:
        """Convert all FortiGate policies to PAN-OS security rules.

        Returns:
            List of dicts, each representing a PAN-OS security rule.
        """
        policies = self.fg_config.get("firewall_policy", [])
        if not policies:
            print("Warning: No firewall policies found in FortiGate configuration")
            return []

        results: List[Dict] = []
        used_names: Dict[str, int] = {}

        for policy_dict in policies:
            policy_id = list(policy_dict.keys())[0]
            properties = policy_dict[policy_id]

            # Build rule name from policy name or ID
            rule_name = str(properties.get("name", f"Policy_{policy_id}")).strip()
            if not rule_name or rule_name.lower() == "none":
                rule_name = f"Policy_{policy_id}"

            sanitized = sanitize_name(rule_name)
            if not sanitized:
                sanitized = f"Policy_{policy_id}"

            if sanitized in used_names:
                used_names[sanitized] += 1
                sanitized = f"{sanitized}_{used_names[sanitized]}"
            else:
                used_names[sanitized] = 1

            # --- Action ---
            fg_action = str(properties.get("action", "deny")).strip().lower()
            if fg_action in ("accept", "allow"):
                pa_action = "allow"
            else:
                pa_action = "deny"

            # --- Zones ---
            from_zones = self._resolve_zones(properties.get("srcintf", []))
            to_zones = self._resolve_zones(properties.get("dstintf", []))

            # PAN-OS requires at least one zone; use "any" as fallback
            if not from_zones:
                from_zones = ["any"]
            if not to_zones:
                to_zones = ["any"]

            # --- Source addresses ---
            sources = self._resolve_addresses(properties.get("srcaddr", []))
            if not sources:
                sources = ["any"]

            # --- Destination addresses ---
            destinations = self._resolve_addresses(properties.get("dstaddr", []))
            if not destinations:
                destinations = ["any"]

            # --- Services ---
            services = self._resolve_services(properties.get("service", []))
            if not services:
                services = ["any"]

            # --- Description ---
            description = str(properties.get("comments", "")).strip()
            if not description:
                description = str(properties.get("name", "")).strip()

            # --- Build rule ---
            rule = {
                "name": sanitized,
                "from_zones": from_zones,
                "to_zones": to_zones,
                "sources": sources,
                "destinations": destinations,
                "services": services,
                "application": ["any"],
                "action": pa_action,
                "log_end": "yes",
                "description": description,
                "disabled": "no",
            }
            results.append(rule)

            # Update stats
            if pa_action == "allow":
                self._stats["allow_rules"] += 1
            else:
                self._stats["deny_rules"] += 1

            print(f"  Converted: {sanitized} [{pa_action.upper()}] "
                  f"({', '.join(from_zones)} -> {', '.join(to_zones)})")

        self._stats["total_rules"] = len(results)
        self.pa_security_rules = results
        return results

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_zones(self, raw) -> List[str]:
        """Map FortiGate interface names to PAN-OS zone names."""
        items = _to_list(raw)
        zones: List[str] = []
        for item in items:
            item_str = str(item).strip()
            if item_str.lower() in ("any", "all", ""):
                continue

            # Try interface mapping first
            zone_name = self._find_zone(item_str)
            if zone_name and zone_name not in zones:
                zones.append(zone_name)

        return zones

    def _find_zone(self, interface_name: str) -> str:
        """Look up zone name for a FortiGate interface."""
        # Direct match
        if interface_name in self._interface_name_mapping:
            return self._interface_name_mapping[interface_name]

        # Lowercase match
        lower = interface_name.lower()
        for fg_name, pa_zone in self._interface_name_mapping.items():
            if fg_name.lower() == lower:
                return pa_zone

        # VLAN ID suffix match (e.g., "551" matches zone for VLAN 551)
        for fg_name, pa_zone in self._interface_name_mapping.items():
            if fg_name.endswith(interface_name) or interface_name.endswith(fg_name):
                return pa_zone

        # Fallback: use sanitized interface name as zone name
        return sanitize_name(interface_name)

    def _resolve_addresses(self, raw) -> List[str]:
        """Resolve FortiGate address references to PAN-OS names."""
        items = _to_list(raw)
        addresses: List[str] = []
        for item in items:
            item_str = str(item).strip()
            if item_str.lower() in ("any", "all", ""):
                # "any" is explicit in PAN-OS
                if "any" not in addresses:
                    addresses.append("any")
                continue

            sanitized = sanitize_name(item_str)
            if sanitized and sanitized not in addresses:
                addresses.append(sanitized)

        return addresses

    def _resolve_services(self, raw) -> List[str]:
        """Resolve FortiGate service references to PAN-OS service names."""
        items = _to_list(raw)
        services: List[str] = []

        for item in items:
            item_str = str(item).strip()
            if item_str.lower() in ("all", "any", ""):
                if "any" not in services:
                    services.append("any")
                continue

            sanitized = sanitize_name(item_str)

            # Skip protocols that have no PAN-OS equivalent
            if sanitized in self._skipped_services:
                continue

            # If this service was split into multiple PAN-OS objects
            if sanitized in self._service_name_mapping:
                for pa_name, _proto in self._service_name_mapping[sanitized]:
                    if pa_name not in services:
                        services.append(pa_name)
            elif sanitized in self._service_groups:
                # Service group reference
                if sanitized not in services:
                    services.append(sanitized)
            else:
                # Direct service reference
                if sanitized not in services:
                    services.append(sanitized)

        return services


def _to_list(raw) -> List:
    """Normalize raw value to a list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return raw
    return [raw]
