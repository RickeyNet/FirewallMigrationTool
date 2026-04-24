#!/usr/bin/env python3
"""PAN-OS Security Rule Converter — FortiGate Target
======================================================
Converts PAN-OS security rules to FortiGate ``firewall policy`` CLI config.

Key translation notes:
    - PAN-OS zones  -> FortiGate srcintf / dstintf (zone names are reused)
    - PAN-OS "any" zone      -> FortiGate "any" interface wildcard
    - PAN-OS "any" address   -> FortiGate "all" built-in address object
    - PAN-OS action allow    -> FortiGate action accept
    - PAN-OS action deny/drop/reset-* -> FortiGate action deny
    - PAN-OS log-end yes     -> FortiGate logtraffic all
    - PAN-OS disabled yes    -> FortiGate status disable
    - PAN-OS service "application-default" -> FortiGate service "ALL"

FortiGate policies use integer IDs.  Sequential IDs are assigned starting
from 1 in the order policies appear in the PAN-OS config.

FortiGate CLI output format:
    config firewall policy
        edit 1
            set name "Allow_Web"
            set srcintf "untrust"
            set dstintf "trust"
            set srcaddr "any_src"
            set dstaddr "webserver"
            set service "HTTP" "HTTPS"
            set action accept
            set logtraffic all
            set comments "Allow web traffic"
        next
    end
"""

from typing import Any, Dict, List

from fg_common import sanitize_fg_name, fg_members_str, map_any_address


# PA actions that map to FortiGate "deny"
_PA_DENY_ACTIONS = {"deny", "drop", "reset-client", "reset-server", "reset-both"}

# PA "application-default" service token -> use FortiGate's ANY service
_APP_DEFAULT = "application-default"


class FGPolicyConverter:
    """Convert PAN-OS security rules to FortiGate firewall policy format."""

    def __init__(
        self,
        pa_config: Dict[str, Any],
        service_name_map: Dict[str, str],
    ):
        self.pa_config = pa_config
        self._service_name_map = service_name_map
        self.failed_items: List[Dict] = []
        self._stats = {
            "total": 0,
            "allow": 0,
            "deny": 0,
            "disabled": 0,
        }

    def convert(self) -> str:
        """Convert all security rules and return FortiGate CLI block.

        Returns:
            A string containing the ``config firewall policy`` block,
            or an empty string if there are no rules.
        """
        rules = self.pa_config.get("security_rules", [])
        if not rules:
            print("  Warning: No security rules found in PAN-OS configuration")
            return ""

        entries: List[str] = []
        policy_id = 1

        for rule in rules:
            name = sanitize_fg_name(rule.get("name", f"Policy_{policy_id}"))
            if not name:
                name = f"Policy_{policy_id}"

            # --- Action ---
            pa_action = str(rule.get("action", "deny")).strip().lower()
            if pa_action in _PA_DENY_ACTIONS:
                fg_action = "deny"
                self._stats["deny"] += 1
            else:
                fg_action = "accept"
                self._stats["allow"] += 1

            # --- Source / destination zones -> srcintf / dstintf ---
            from_zones = self._resolve_zones(rule.get("from_zones", []))
            to_zones = self._resolve_zones(rule.get("to_zones", []))

            # --- Source / destination addresses ---
            sources = self._resolve_addresses(rule.get("sources", []))
            destinations = self._resolve_addresses(rule.get("destinations", []))

            # --- Services ---
            services = self._resolve_services(rule.get("services", []))

            # --- Logging ---
            log_end = rule.get("log_end", True)
            logtraffic = "all" if log_end else "disable"

            # --- Description ---
            description = str(rule.get("description", "")).strip()
            if not description:
                description = name

            # --- Disabled ---
            disabled = rule.get("disabled", False)
            if disabled:
                self._stats["disabled"] += 1

            lines = [f"    edit {policy_id}"]
            lines.append(f'        set name "{name}"')
            lines.append(f"        set srcintf {fg_members_str(from_zones)}")
            lines.append(f"        set dstintf {fg_members_str(to_zones)}")
            lines.append(f"        set srcaddr {fg_members_str(sources)}")
            lines.append(f"        set dstaddr {fg_members_str(destinations)}")
            lines.append(f"        set service {fg_members_str(services)}")
            lines.append(f"        set action {fg_action}")
            lines.append(f"        set logtraffic {logtraffic}")
            if disabled:
                lines.append("        set status disable")
            safe_comment = description.replace('"', "'")
            lines.append(f'        set comments "{safe_comment}"')
            lines.append("    next")

            entries.append("\n".join(lines))
            self._stats["total"] += 1
            policy_id += 1

            action_label = fg_action.upper()
            print(
                f"  Converted policy: [{policy_id - 1}] {name} "
                f"[{action_label}] "
                f"({', '.join(from_zones)} -> {', '.join(to_zones)})"
            )

        if not entries:
            return ""

        block = "config firewall policy\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_zones(self, zones: List) -> List[str]:
        """Sanitize zone names; keep 'any' as-is (FortiGate supports it)."""
        result: List[str] = []
        seen: set = set()
        for z in _to_list(zones):
            z_str = str(z).strip()
            if not z_str:
                continue
            fg_z = z_str  # FortiGate accepts "any" directly for interfaces
            if fg_z not in seen:
                result.append(fg_z)
                seen.add(fg_z)
        return result if result else ["any"]

    def _resolve_addresses(self, addrs: List) -> List[str]:
        """Map PAN-OS 'any' to FG 'all'; sanitize other names."""
        result: List[str] = []
        seen: set = set()
        for a in _to_list(addrs):
            a_str = str(a).strip()
            if not a_str:
                continue
            fg_a = map_any_address(sanitize_fg_name(a_str))
            if fg_a not in seen:
                result.append(fg_a)
                seen.add(fg_a)
        return result if result else ["all"]

    def _resolve_services(self, services: List) -> List[str]:
        """Resolve service names through the service name map.

        Handles:
          - 'any'                 -> 'ALL'
          - 'application-default' -> 'ALL'
          - merged service names  -> resolved FG name
        """
        result: List[str] = []
        seen: set = set()
        for s in _to_list(services):
            s_str = str(s).strip()
            if not s_str:
                continue
            if s_str.lower() in ("any", _APP_DEFAULT):
                fg_s = "ALL"
            else:
                sanitized = sanitize_fg_name(s_str)
                fg_s = self._service_name_map.get(sanitized, sanitized)
            if fg_s not in seen:
                result.append(fg_s)
                seen.add(fg_s)
        return result if result else ["ALL"]


def _to_list(value: Any) -> List:
    """Ensure value is a list."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
