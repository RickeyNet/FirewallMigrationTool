#!/usr/bin/env python3
"""PAN-OS Interface and Zone Converter - FortiGate Target
==========================================================
Converts PAN-OS interfaces and zones to FortiGate ``system interface``
and ``system zone`` CLI config.

PAN-OS interface names (ethernet1/1, ethernet1/2, …) are preserved as-is
in FortiGate because FortiGate allows arbitrary interface names.  The
physical port assignments must be reviewed and adjusted by the network
administrator after applying the config.

PAN-OS zones map directly to FortiGate ``config system zone`` entries,
preserving the same zone name and interface membership.

FortiGate CLI output format:
    config system interface
        edit "ethernet1/1"
            set ip 10.0.0.1 255.255.255.0
            set description "LAN interface"
            set type physical
        next
        edit "ethernet1/1.100"
            set ip 192.168.100.1 255.255.255.0
            set type vlan
            set vlanid 100
            set interface "ethernet1/1"
        next
    end

    config system zone
        edit "trust"
            set interface "ethernet1/1" "ethernet1/2"
        next
    end
"""

from typing import Any, Dict, List

from fg_common import sanitize_fg_name, fg_members_str, split_cidr


class FGInterfaceConverter:
    """Convert PAN-OS interfaces and zones to FortiGate format."""

    def __init__(self, pa_config: Dict[str, Any]):
        self.pa_config = pa_config
        self.failed_items: List[Dict] = []
        self._stats = {
            "interfaces": 0,
            "zones": 0,
        }

    def convert_interfaces(self) -> str:
        """Convert all interfaces and return FortiGate ``system interface`` block.

        Returns an empty string if no interface data is present (interface
        config is optional - policies can reference zone names instead).
        """
        interfaces = self.pa_config.get("interfaces", [])
        if not interfaces:
            return ""

        entries: List[str] = []

        for intf in interfaces:
            name = intf.get("name", "").strip()
            if not name:
                continue

            fg_name = sanitize_fg_name(name)
            intf_type = intf.get("type", "physical")
            ip_cidr = intf.get("ip", "").strip()
            description = intf.get("description", "").strip()
            vlan = intf.get("vlan", "").strip()
            parent = intf.get("parent", "").strip()

            lines = [f'    edit "{fg_name}"']

            if ip_cidr:
                ip, netmask = split_cidr(ip_cidr)
                lines.append(f"        set ip {ip} {netmask}")

            if intf_type == "vlan":
                lines.append("        set type vlan")
                if vlan:
                    lines.append(f"        set vlanid {vlan}")
                if parent:
                    fg_parent = sanitize_fg_name(parent)
                    lines.append(f'        set interface "{fg_parent}"')
            elif intf_type == "loopback":
                lines.append("        set type loopback")
            else:
                lines.append("        set type physical")

            if description:
                safe_desc = description.replace('"', "'")
                lines.append(f'        set description "{safe_desc}"')

            lines.append("    next")
            entries.append("\n".join(lines))
            self._stats["interfaces"] += 1
            print(f"  Converted interface: {fg_name} ({intf_type})")

        if not entries:
            return ""

        block = "config system interface\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def convert_zones(self) -> str:
        """Convert all zones and return FortiGate ``system zone`` block.

        Returns an empty string if no zone data is present.
        """
        zones = self.pa_config.get("zones", [])
        if not zones:
            return ""

        entries: List[str] = []

        for zone in zones:
            name = zone.get("name", "").strip()
            if not name:
                continue

            fg_name = sanitize_fg_name(name)
            interfaces = [sanitize_fg_name(i) for i in zone.get("interfaces", []) if i]

            lines = [f'    edit "{fg_name}"']
            if interfaces:
                lines.append(f"        set interface {fg_members_str(interfaces)}")
            lines.append("    next")

            entries.append("\n".join(lines))
            self._stats["zones"] += 1
            members_display = ", ".join(interfaces) if interfaces else "(no interfaces)"
            print(f"  Converted zone: {fg_name} [{members_display}]")

        if not entries:
            return ""

        block = "config system zone\n"
        block += "\n".join(entries)
        block += "\nend\n"
        return block

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)
