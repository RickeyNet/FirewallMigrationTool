#!/usr/bin/env python3
"""
Cisco FTD to FortiGate Configuration Converter — Main Script
=============================================================
Connects to a Cisco FTD device via the Firepower Device Manager (FDM)
REST API, reads the running configuration, and converts it to a single
FortiGate CLI .conf file.

OUTPUT FILE:
    {output_base}.conf    — FortiGate CLI configuration

SECTIONS GENERATED (in order):
    1. config system interface    — Physical and EtherChannel interfaces
    2. config system zone         — Security zones (with member interfaces)
    3. config firewall address    — Address objects
    4. config firewall addrgrp    — Address groups
    5. config firewall service custom  — TCP/UDP service objects
    6. config firewall service group   — Service groups
    7. config firewall policy     — Security policies (from access rules)
    8. config router static       — Static routes

HOW TO RUN:
    python fg_ftd_converter.py --host 192.168.1.1 --username admin --password P@ss
    python fg_ftd_converter.py --host 192.168.1.1 -o fg_migration --no-ssl-verify

NOTE:
    Direct API import to FortiGate is not currently supported.
    Apply the generated .conf file via the FortiGate CLI or:
        System > Configuration > Restore
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Path setup — allow importing from sibling tool directories
# ---------------------------------------------------------------------------
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_FTD_DIR = os.path.join(os.path.dirname(_SELF_DIR), "FortiGateToFTDTool")
_PA_FG_DIR = os.path.join(os.path.dirname(_SELF_DIR), "PaloAltoToFortiGateTool")

for _d in (_SELF_DIR, _FTD_DIR, _PA_FG_DIR):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

try:
    from ftd_reader import FTDReader
    from fg_common import (
        cidr_to_netmask,
        split_cidr,
        sanitize_fg_name,
        fg_members_str,
        map_any_address,
    )
except ImportError as e:
    print("\n" + "=" * 60)
    print("ERROR: Missing module!")
    print("=" * 60)
    print(f"\nDetails: {e}")
    print("\nMake sure these directories are present:")
    print("  - FortiGateToFTDTool/ftd_api_base.py")
    print("  - CiscoFTDToFortiGateTool/ftd_reader.py")
    print("  - PaloAltoToFortiGateTool/fg_common.py")
    print("\n" + "=" * 60)
    raise


# ---------------------------------------------------------------------------
# FTD built-in object names that map to FortiGate "all" / "ALL"
# ---------------------------------------------------------------------------
_FTD_ANY_ADDRESSES: frozenset = frozenset({
    "any", "any-ipv4", "any-ipv6", "any_ipv4", "any_ipv6",
    "ipv4-any", "ipv4_any", "ipv4 any",
})
_FTD_ANY_SERVICES: frozenset = frozenset({"any", "any-ipv4"})


def _is_ftd_any_addr(name: str) -> bool:
    return name.strip().lower() in _FTD_ANY_ADDRESSES


def _is_ftd_any_svc(name: str) -> bool:
    return name.strip().lower() in _FTD_ANY_SERVICES


def _fg_intf_name(ftd_hw_name: str, ftd_ifname: str) -> str:
    """Return the FortiGate interface name for an FTD interface.

    Prefers the logical name (ifname / nameif equivalent) when available,
    falling back to a sanitized hardware name.
    """
    if ftd_ifname:
        return sanitize_fg_name(ftd_ifname)
    # Replace characters that are invalid in FG interface names
    sanitized = ftd_hw_name.replace("/", "_").replace(".", "_")
    return sanitize_fg_name(sanitized)


def _ftd_port_str(raw: str) -> str:
    """Normalize an FTD port string for use in FortiGate portrange syntax.

    FTD uses '80' or '80-443'.  FortiGate uses the same format.
    """
    return raw.strip() if raw else ""


# ===========================================================================
# Phase 1: Interfaces
# ===========================================================================

def _convert_interfaces(
    interfaces: List[Dict],
    etherchannel_interfaces: List[Dict],
) -> Tuple[str, Dict[str, List[str]], Dict[str, str]]:
    """Convert FTD interfaces to a FortiGate 'config system interface' block.

    Returns:
        cli_block          — The FortiGate CLI text
        zone_to_intfs      — Mapping of zone name → [fg_intf_name, ...]
        hw_to_fg           — Mapping of FTD hardware name → fg_intf_name
                             (used when resolving static-route interface names)
    """
    lines = ["config system interface"]
    count = 0
    zone_to_intfs: Dict[str, List[str]] = {}
    hw_to_fg: Dict[str, str] = {}

    def _process_intf(obj: Dict, intf_type: str) -> None:
        nonlocal count
        hw_name = obj.get("hardwareName") or obj.get("name", "")
        ifname = obj.get("ifname", "")
        fg_name = _fg_intf_name(hw_name, ifname)
        if not fg_name:
            return

        hw_to_fg[hw_name] = fg_name

        lines.append(f'    edit "{fg_name}"')

        # Type
        if intf_type == "etherchannel":
            lines.append("        set type aggregate")
        elif obj.get("vlanId"):
            vlan_id = obj["vlanId"]
            parent_hw = obj.get("parentInterface", {}).get("hardwareName", "")
            parent_fg = hw_to_fg.get(parent_hw, sanitize_fg_name(parent_hw))
            lines.append("        set type vlan")
            lines.append(f"        set vlanid {vlan_id}")
            if parent_fg:
                lines.append(f'        set interface "{parent_fg}"')

        # Alias (logical name, if different from the fg_name we used)
        if ifname and ifname != fg_name:
            lines.append(f'        set alias "{sanitize_fg_name(ifname)}"')
        elif hw_name and hw_name != fg_name:
            lines.append(f'        set alias "{sanitize_fg_name(hw_name)}"')

        # IP address
        ipv4 = obj.get("ipv4") or {}
        ip_addr_obj = ipv4.get("ipAddress") or {}
        ip = ip_addr_obj.get("ipAddress", "")
        mask = ip_addr_obj.get("netmask", "")
        if ip and mask:
            lines.append(f"        set ip {ip} {mask}")
        elif ipv4.get("dhcp"):
            lines.append("        set mode dhcp")

        # Admin state
        if not obj.get("enabled", True):
            lines.append("        set status down")

        # Zone membership — record for later zone block generation
        zone_ref = obj.get("securityZone") or {}
        zone_name = zone_ref.get("name", "")
        if zone_name:
            zone_to_intfs.setdefault(zone_name, []).append(fg_name)

        lines.append("    next")
        count += 1
        print(f"    Converted: {hw_name} ({ifname or 'no ifname'}) → \"{fg_name}\"")

    for intf in interfaces:
        _process_intf(intf, "physical")

    for intf in etherchannel_interfaces:
        _process_intf(intf, "etherchannel")

    lines.append("end")
    print(f"  Result: {count} interfaces converted")
    return "\n".join(lines), zone_to_intfs, hw_to_fg


# ===========================================================================
# Phase 2: Zones
# ===========================================================================

def _convert_zones(
    security_zones: List[Dict],
    zone_to_intfs: Dict[str, List[str]],
) -> str:
    """Convert FTD security zones to a FortiGate 'config system zone' block."""
    lines = ["config system zone"]
    count = 0

    # Emit zones that have member interfaces first, then any remaining zones
    emitted: Set[str] = set()

    def _emit_zone(name: str, members: List[str]) -> None:
        nonlocal count
        fg_name = sanitize_fg_name(name)
        lines.append(f'    edit "{fg_name}"')
        if members:
            lines.append(f"        set interface {fg_members_str(members)}")
        lines.append("    next")
        count += 1
        emitted.add(name)

    for zone_name, intfs in zone_to_intfs.items():
        _emit_zone(zone_name, intfs)

    for zone in security_zones:
        name = zone.get("name", "")
        if not name or name in emitted:
            continue
        _emit_zone(name, [])

    lines.append("end")
    print(f"  Result: {count} zones converted")
    return "\n".join(lines)


# ===========================================================================
# Phase 3: Address objects
# ===========================================================================

def _convert_network_objects(network_objects: List[Dict]) -> Tuple[str, Set[str]]:
    """Convert FTD network objects to a FortiGate 'config firewall address' block.

    Returns (cli_block, set_of_fg_names).
    The name set is used by the group converter to detect literals that need
    inline address objects.
    """
    lines = ["config firewall address"]
    count = 0
    skipped = 0
    fg_names: Set[str] = set()

    for obj in network_objects:
        name = obj.get("name", "")
        if not name or _is_ftd_any_addr(name):
            continue

        fg_name = sanitize_fg_name(name)
        sub_type = obj.get("subType", "").upper()
        value = obj.get("value", "")
        description = obj.get("description", "")

        if sub_type == "HOST":
            lines.append(f'    edit "{fg_name}"')
            lines.append(f"        set subnet {value} 255.255.255.255")
            if description:
                lines.append(f'        set comment "{sanitize_fg_name(description)}"')
            lines.append("    next")
            count += 1
            fg_names.add(fg_name)

        elif sub_type == "NETWORK":
            ip, mask = split_cidr(value)
            lines.append(f'    edit "{fg_name}"')
            lines.append(f"        set subnet {ip} {mask}")
            if description:
                lines.append(f'        set comment "{sanitize_fg_name(description)}"')
            lines.append("    next")
            count += 1
            fg_names.add(fg_name)

        elif sub_type == "RANGE":
            if "-" in value:
                start, _, end = value.partition("-")
                lines.append(f'    edit "{fg_name}"')
                lines.append("        set type iprange")
                lines.append(f"        set start-ip {start.strip()}")
                lines.append(f"        set end-ip {end.strip()}")
                if description:
                    lines.append(f'        set comment "{sanitize_fg_name(description)}"')
                lines.append("    next")
                count += 1
                fg_names.add(fg_name)
            else:
                print(f"  Skipped: {name} (RANGE with no '-' in value: {value})")
                skipped += 1

        elif sub_type == "FQDN":
            lines.append(f'    edit "{fg_name}"')
            lines.append("        set type fqdn")
            lines.append(f'        set fqdn "{value}"')
            if description:
                lines.append(f'        set comment "{sanitize_fg_name(description)}"')
            lines.append("    next")
            count += 1
            fg_names.add(fg_name)

        else:
            print(f"  Skipped: {name} (unknown subType: '{sub_type}')")
            skipped += 1

    lines.append("end")
    print(f"  Result: {count} converted, {skipped} skipped")
    return "\n".join(lines), fg_names


# ===========================================================================
# Phase 4: Address groups
# ===========================================================================

def _make_inline_addr_block(inline_objects: List[Dict]) -> str:
    """Build a supplemental address block for literals discovered during group conversion."""
    if not inline_objects:
        return ""
    lines = ["config firewall address"]
    for obj in inline_objects:
        fg_name = obj["fg_name"]
        lines.append(f'    edit "{fg_name}"')
        if obj["type"] == "iprange":
            lines.append("        set type iprange")
            lines.append(f"        set start-ip {obj['start']}")
            lines.append(f"        set end-ip {obj['end']}")
        else:
            lines.append(f"        set subnet {obj['ip']} {obj['mask']}")
        lines.append(f'        set comment "Auto-created from group literal"')
        lines.append("    next")
    lines.append("end")
    return "\n".join(lines)


def _convert_network_groups(
    network_groups: List[Dict],
    known_fg_names: Set[str],
) -> Tuple[str, str]:
    """Convert FTD network groups to a FortiGate 'config firewall addrgrp' block.

    Returns (addrgrp_cli_block, supplemental_address_block).
    The supplemental block contains address objects auto-created from
    inline IP literals found inside groups.
    """
    lines = ["config firewall addrgrp"]
    count = 0
    skipped = 0
    inline_objects: List[Dict] = []

    def _literal_to_fg(lit: Dict, group_name: str) -> Optional[str]:
        """Create an inline address object from a literal and return its FG name."""
        value = lit.get("value", "")
        lit_type = lit.get("type", "")
        if not value:
            return None

        # Build a stable name from the value
        safe_val = value.replace("/", "_").replace(".", "_").replace("-", "_")
        fg_name = sanitize_fg_name(f"inline_{safe_val}")

        if fg_name in known_fg_names:
            return fg_name  # Already exists

        known_fg_names.add(fg_name)

        if lit_type == "host" or ("/" not in value and "-" not in value):
            inline_objects.append({
                "fg_name": fg_name,
                "type": "host",
                "ip": value,
                "mask": "255.255.255.255",
            })
        elif "-" in value and "/" not in value:
            start, _, end = value.partition("-")
            inline_objects.append({
                "fg_name": fg_name,
                "type": "iprange",
                "start": start.strip(),
                "end": end.strip(),
            })
        else:
            ip, mask = split_cidr(value)
            inline_objects.append({
                "fg_name": fg_name,
                "type": "subnet",
                "ip": ip,
                "mask": mask,
            })

        return fg_name

    for grp in network_groups:
        name = grp.get("name", "")
        if not name or _is_ftd_any_addr(name):
            continue

        fg_name = sanitize_fg_name(name)
        members: List[str] = []

        for obj_ref in grp.get("objects", []):
            ref_name = obj_ref.get("name", "")
            if ref_name and not _is_ftd_any_addr(ref_name):
                members.append(sanitize_fg_name(ref_name))

        for lit in grp.get("literals", []):
            lit_fg = _literal_to_fg(lit, name)
            if lit_fg:
                members.append(lit_fg)

        if not members:
            print(f"  Skipped: {name} (no members)")
            skipped += 1
            continue

        lines.append(f'    edit "{fg_name}"')
        lines.append(f"        set member {fg_members_str(members)}")
        lines.append("    next")
        count += 1

    lines.append("end")
    print(f"  Result: {count} converted, {skipped} skipped")
    return "\n".join(lines), _make_inline_addr_block(inline_objects)


# ===========================================================================
# Phase 5: Service objects
# ===========================================================================

def _convert_port_objects(
    tcp_ports: List[Dict],
    udp_ports: List[Dict],
) -> Tuple[str, Dict[str, str]]:
    """Convert FTD TCP/UDP port objects to 'config firewall service custom'.

    Detects _TCP/_UDP suffix pairs (produced by the FG→PA converter) and
    merges them back into single dual-protocol FortiGate service objects.

    Returns:
        cli_block        — FortiGate CLI text
        service_name_map — Mapping of original FTD port-object name → FG service name
                           (used by group and policy converters)
    """
    lines = ["config firewall service custom"]
    count = 0
    service_name_map: Dict[str, str] = {}

    tcp_map: Dict[str, str] = {}
    udp_map: Dict[str, str] = {}

    for obj in tcp_ports:
        n, p = obj.get("name", ""), obj.get("port", "")
        if n and p:
            tcp_map[n] = _ftd_port_str(p)

    for obj in udp_ports:
        n, p = obj.get("name", ""), obj.get("port", "")
        if n and p:
            udp_map[n] = _ftd_port_str(p)

    merged_ftd_names: Set[str] = set()

    # Detect and merge _TCP / _UDP companion pairs
    for tcp_name, tcp_port in sorted(tcp_map.items()):
        for suffix, alt_suffix in (("_TCP", "_UDP"), ("_tcp", "_udp")):
            if tcp_name.endswith(suffix):
                base = tcp_name[: -len(suffix)]
                udp_name = base + alt_suffix.upper()
                udp_name_alt = base + alt_suffix
                udp_port = udp_map.get(udp_name) or udp_map.get(udp_name_alt)
                if udp_port:
                    fg_merged = sanitize_fg_name(base)
                    lines.append(f'    edit "{fg_merged}"')
                    lines.append(f"        set tcp-portrange {tcp_port}")
                    lines.append(f"        set udp-portrange {udp_port}")
                    lines.append("    next")
                    count += 1
                    merged_ftd_names.add(tcp_name)
                    matched_udp = udp_name if udp_name in udp_map else udp_name_alt
                    merged_ftd_names.add(matched_udp)
                    service_name_map[tcp_name] = fg_merged
                    service_name_map[matched_udp] = fg_merged
                    print(f"    Merged: {tcp_name} + {matched_udp} → \"{fg_merged}\"")
                break

    # Remaining TCP port objects
    for tcp_name, tcp_port in sorted(tcp_map.items()):
        if tcp_name in merged_ftd_names:
            continue
        fg_name = sanitize_fg_name(tcp_name)
        lines.append(f'    edit "{fg_name}"')
        lines.append(f"        set tcp-portrange {tcp_port}")
        lines.append("    next")
        count += 1
        service_name_map[tcp_name] = fg_name

    # Remaining UDP port objects
    for udp_name, udp_port in sorted(udp_map.items()):
        if udp_name in merged_ftd_names:
            continue
        fg_name = sanitize_fg_name(udp_name)
        lines.append(f'    edit "{fg_name}"')
        lines.append(f"        set udp-portrange {udp_port}")
        lines.append("    next")
        count += 1
        service_name_map[udp_name] = fg_name

    lines.append("end")
    print(f"  Result: {count} service objects converted")
    return "\n".join(lines), service_name_map


# ===========================================================================
# Phase 6: Service groups
# ===========================================================================

def _convert_port_groups(
    port_groups: List[Dict],
    service_name_map: Dict[str, str],
) -> str:
    """Convert FTD port groups to 'config firewall service group'."""
    lines = ["config firewall service group"]
    count = 0
    skipped = 0

    for grp in port_groups:
        name = grp.get("name", "")
        if not name or _is_ftd_any_svc(name):
            continue

        fg_name = sanitize_fg_name(name)
        members: List[str] = []

        for obj_ref in grp.get("objects", []):
            ref_name = obj_ref.get("name", "")
            if ref_name and not _is_ftd_any_svc(ref_name):
                members.append(service_name_map.get(ref_name, sanitize_fg_name(ref_name)))

        if not members:
            print(f"  Skipped: {name} (no members)")
            skipped += 1
            continue

        lines.append(f'    edit "{fg_name}"')
        lines.append(f"        set member {fg_members_str(members)}")
        lines.append("    next")
        count += 1

    lines.append("end")
    print(f"  Result: {count} converted, {skipped} skipped")
    return "\n".join(lines)


# ===========================================================================
# Phase 7: Security policies (from access rules)
# ===========================================================================

def _resolve_network_refs(
    field: Any,
    inline_addr: List[Dict],
    known_fg_names: Set[str],
) -> List[str]:
    """Resolve FTD sourceNetworks / destinationNetworks to FG address names.

    FTD GET may return the field as:
      - A list of {name, type} dicts  (older FDM versions)
      - A dict with 'objects' and 'literals' keys  (newer FDM versions)
      - None / empty  (meaning "any")
    """
    if not field:
        return ["all"]

    objects: List[Dict] = []
    literals: List[Dict] = []

    if isinstance(field, list):
        objects = field
    elif isinstance(field, dict):
        objects = field.get("objects", [])
        literals = field.get("literals", [])

    result: List[str] = []

    for obj_ref in objects:
        ref_name = obj_ref.get("name", "")
        if not ref_name or _is_ftd_any_addr(ref_name):
            return ["all"]
        result.append(sanitize_fg_name(ref_name))

    for lit in literals:
        value = lit.get("value", "")
        lit_type = lit.get("type", "")
        if not value:
            continue
        safe_val = value.replace("/", "_").replace(".", "_").replace("-", "_")
        fg_name = sanitize_fg_name(f"inline_{safe_val}")
        if fg_name not in known_fg_names:
            known_fg_names.add(fg_name)
            if lit_type == "host" or "/" not in value:
                inline_addr.append({
                    "fg_name": fg_name,
                    "type": "host",
                    "ip": value,
                    "mask": "255.255.255.255",
                })
            else:
                ip, mask = split_cidr(value)
                inline_addr.append({
                    "fg_name": fg_name,
                    "type": "subnet",
                    "ip": ip,
                    "mask": mask,
                })
        result.append(fg_name)

    return result if result else ["all"]


def _resolve_service_refs(
    field: Any,
    service_name_map: Dict[str, str],
) -> List[str]:
    """Resolve FTD destinationPorts to FG service names.

    Returns ["ALL"] if the field is empty or contains "any".
    """
    if not field:
        return ["ALL"]

    if isinstance(field, list):
        objects = field
    elif isinstance(field, dict):
        objects = field.get("objects", [])
    else:
        return ["ALL"]

    result: List[str] = []
    for obj_ref in objects:
        ref_name = obj_ref.get("name", "")
        if not ref_name or _is_ftd_any_svc(ref_name):
            return ["ALL"]
        result.append(service_name_map.get(ref_name, sanitize_fg_name(ref_name)))

    return result if result else ["ALL"]


def _convert_access_rules(
    access_rules: List[Dict],
    service_name_map: Dict[str, str],
    known_fg_names: Set[str],
) -> Tuple[str, str]:
    """Convert FTD access rules to a FortiGate 'config firewall policy' block.

    Returns (policy_cli_block, supplemental_address_block) where the
    supplemental block holds any inline address objects discovered in rule
    network literals.
    """
    lines = ["config firewall policy"]
    count = 0
    skipped = 0
    inline_addr: List[Dict] = []
    policy_id = 1

    for rule in access_rules:
        name = rule.get("name", f"rule_{policy_id}")
        action_raw = rule.get("ruleAction", "DENY").upper()
        action = "accept" if action_raw == "PERMIT" else "deny"

        # Source zones → srcintf
        src_zones_raw = rule.get("sourceZones", [])
        if isinstance(src_zones_raw, dict):
            src_zones_raw = src_zones_raw.get("objects", [])
        src_intfs = [
            sanitize_fg_name(z.get("name", ""))
            for z in src_zones_raw
            if z.get("name")
        ]
        if not src_intfs:
            src_intfs = ["any"]

        # Destination zones → dstintf
        dst_zones_raw = rule.get("destinationZones", [])
        if isinstance(dst_zones_raw, dict):
            dst_zones_raw = dst_zones_raw.get("objects", [])
        dst_intfs = [
            sanitize_fg_name(z.get("name", ""))
            for z in dst_zones_raw
            if z.get("name")
        ]
        if not dst_intfs:
            dst_intfs = ["any"]

        # Source networks → srcaddr
        src_addrs = _resolve_network_refs(
            rule.get("sourceNetworks"), inline_addr, known_fg_names
        )

        # Destination networks → dstaddr
        dst_addrs = _resolve_network_refs(
            rule.get("destinationNetworks"), inline_addr, known_fg_names
        )

        # Destination ports → service
        services = _resolve_service_refs(
            rule.get("destinationPorts"), service_name_map
        )

        # Logging
        log_action = rule.get("eventLogAction", "")
        log_traffic = "all" if log_action and log_action not in ("LOG_NONE", "") else "disable"

        # Enabled/disabled
        enabled = rule.get("enabled", True)

        fg_rule_name = sanitize_fg_name(name)

        lines.append(f"    edit {policy_id}")
        lines.append(f'        set name "{fg_rule_name}"')
        lines.append(f"        set srcintf {fg_members_str(src_intfs)}")
        lines.append(f"        set dstintf {fg_members_str(dst_intfs)}")
        lines.append(f"        set srcaddr {fg_members_str(src_addrs)}")
        lines.append(f"        set dstaddr {fg_members_str(dst_addrs)}")
        lines.append(f"        set action {action}")
        lines.append('        set schedule "always"')
        lines.append(f"        set service {fg_members_str(services)}")
        lines.append(f"        set logtraffic {log_traffic}")
        if not enabled:
            lines.append("        set status disable")
        lines.append("    next")

        print(
            f"    Converted: {name} [{action.upper()}] "
            f"({', '.join(src_intfs)} → {', '.join(dst_intfs)})"
        )
        count += 1
        policy_id += 1

    lines.append("end")
    print(f"  Result: {count} policies converted, {skipped} skipped")
    return "\n".join(lines), _make_inline_addr_block(inline_addr)


# ===========================================================================
# Phase 8: Static routes
# ===========================================================================

def _convert_static_routes(
    static_routes: List[Dict],
    hw_to_fg: Dict[str, str],
) -> str:
    """Convert FTD static routes to a FortiGate 'config router static' block."""
    lines = ["config router static"]
    count = 0
    route_id = 1

    for route in static_routes:
        networks = route.get("networks", [])
        if not networks:
            continue

        for net_entry in networks:
            dest = net_entry.get("value", "")
            if not dest:
                continue

            ip, mask = split_cidr(dest)

            gw_obj = route.get("gateway") or {}
            nexthop = gw_obj.get("ipAddress", "")

            intf_obj = route.get("interface") or {}
            ftd_intf = intf_obj.get("hardwareName") or intf_obj.get("name", "")
            fg_intf = hw_to_fg.get(ftd_intf, sanitize_fg_name(ftd_intf))

            metric = route.get("metricValue", 1)

            if not nexthop and not fg_intf:
                print(f"  Skipped: {dest} (no nexthop and no interface)")
                continue

            lines.append(f"    edit {route_id}")
            lines.append(f"        set dst {ip} {mask}")
            if nexthop:
                lines.append(f"        set gateway {nexthop}")
            if fg_intf:
                lines.append(f'        set device "{fg_intf}"')
            lines.append(f"        set distance {metric}")
            lines.append("    next")
            count += 1
            route_id += 1

    lines.append("end")
    print(f"  Result: {count} static routes converted")
    return "\n".join(lines)


# ===========================================================================
# Output helpers
# ===========================================================================

_HEADER_TEMPLATE = """\
# ============================================================
# FortiGate CLI Configuration
# Generated by Firewall Migration Tool
# Source:    Cisco FTD ({host})
# Generated: {timestamp}
# ============================================================
#
# HOW TO APPLY:
#   Option A — CLI (granular, section by section):
#     Paste each config block into the FortiGate CLI shell.
#
#   Option B — Web UI restore (merges all sections at once):
#     System > Configuration > Restore  (select this .conf file)
#
# IMPORTANT:
#   Review interface names and physical port assignments before
#   applying.  FortiGate port naming (port1, port2, ...) may
#   differ from FTD hardware names.
# ============================================================
"""


def _write_conf(sections: List[str], output_path: str, host: str) -> None:
    """Write the assembled FortiGate .conf file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = _HEADER_TEMPLATE.format(host=host, timestamp=timestamp)
    body = "\n\n".join(s for s in sections if s.strip())
    content = header + "\n" + body + "\n"
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


# ===========================================================================
# main()
# ===========================================================================

def main(argv=None) -> int:
    """Entry point called by the GUI and CLI."""

    parser = argparse.ArgumentParser(
        description="Convert Cisco FTD configuration to FortiGate CLI format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fg_ftd_converter.py --host 192.168.1.1 --username admin --password P@ss
  python fg_ftd_converter.py --host 192.168.1.1 -o fg_migration
  python fg_ftd_converter.py --host 192.168.1.1 --no-ssl-verify
        """,
    )
    parser.add_argument(
        "--host",
        required=True,
        help="FTD management IP address or hostname",
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="FDM username (default: admin)",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="FDM password",
    )
    parser.add_argument(
        "-o", "--output",
        default="fg_config",
        help="Base name for output .conf file (default: fg_config)",
    )
    parser.add_argument(
        "--no-ssl-verify",
        action="store_true",
        help="Disable SSL certificate verification (for self-signed certs)",
    )

    args = parser.parse_args(argv)

    # ── Banner ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("Cisco FTD to FortiGate Configuration Converter")
    print("=" * 60)
    print(f"FTD Host:  {args.host}")
    print(f"Username:  {args.username}")
    print(f"Output:    {args.output}.conf")

    # ── Connect and authenticate ──────────────────────────────────────────
    reader = FTDReader(
        host=args.host,
        username=args.username,
        password=args.password,
        verify_ssl=not args.no_ssl_verify,
    )
    if not reader.authenticate():
        print("[ERROR] Authentication failed — check host, username, and password.")
        return 1

    # ── Read FTD configuration ────────────────────────────────────────────
    print("\n[Reading FTD configuration...]")
    ftd_config = reader.read_all()

    print(
        f"\n  Inventory: "
        f"{len(ftd_config['network_objects'])} address objects, "
        f"{len(ftd_config['network_groups'])} address groups, "
        f"{len(ftd_config['tcp_ports'])} TCP ports, "
        f"{len(ftd_config['udp_ports'])} UDP ports, "
        f"{len(ftd_config['port_groups'])} service groups, "
        f"{len(ftd_config['interfaces'])} interfaces, "
        f"{len(ftd_config['security_zones'])} zones, "
        f"{len(ftd_config['static_routes'])} routes, "
        f"{len(ftd_config['access_rules'])} access rules"
    )

    # ── Conversion phases ─────────────────────────────────────────────────
    output_sections: List[str] = []

    # Phase 1: Interfaces
    print("\n[Phase 1/8] Converting interfaces...")
    intf_block, zone_to_intfs, hw_to_fg = _convert_interfaces(
        ftd_config["interfaces"],
        ftd_config["etherchannel_interfaces"],
    )
    if intf_block:
        output_sections.append(intf_block)

    # Phase 2: Zones
    print("\n[Phase 2/8] Converting security zones...")
    zone_block = _convert_zones(ftd_config["security_zones"], zone_to_intfs)
    if zone_block:
        output_sections.append(zone_block)

    # Phase 3: Address objects
    print("\n[Phase 3/8] Converting address objects...")
    addr_block, known_fg_names = _convert_network_objects(ftd_config["network_objects"])
    if addr_block:
        output_sections.append(addr_block)

    # Phase 4: Address groups
    print("\n[Phase 4/8] Converting address groups...")
    addrgrp_block, inline_addr_block = _convert_network_groups(
        ftd_config["network_groups"], known_fg_names
    )
    # Prepend any auto-created inline address objects before the group block
    if inline_addr_block:
        output_sections.append(inline_addr_block)
    if addrgrp_block:
        output_sections.append(addrgrp_block)

    # Phase 5: Service objects
    print("\n[Phase 5/8] Converting service objects...")
    svc_block, service_name_map = _convert_port_objects(
        ftd_config["tcp_ports"], ftd_config["udp_ports"]
    )
    if svc_block:
        output_sections.append(svc_block)

    # Phase 6: Service groups
    print("\n[Phase 6/8] Converting service groups...")
    svcgrp_block = _convert_port_groups(ftd_config["port_groups"], service_name_map)
    if svcgrp_block:
        output_sections.append(svcgrp_block)

    # Phase 7: Policies
    print("\n[Phase 7/8] Converting access rules to policies...")
    policy_block, rule_inline_addr_block = _convert_access_rules(
        ftd_config["access_rules"], service_name_map, known_fg_names
    )
    if rule_inline_addr_block:
        # Insert before the policy block
        output_sections.append(rule_inline_addr_block)
    if policy_block:
        output_sections.append(policy_block)

    # Phase 8: Static routes
    print("\n[Phase 8/8] Converting static routes...")
    route_block = _convert_static_routes(ftd_config["static_routes"], hw_to_fg)
    if route_block:
        output_sections.append(route_block)

    # ── Write output ──────────────────────────────────────────────────────
    output_path = f"{args.output}.conf"
    print(f"\n[Writing output file: {output_path}]")
    try:
        _write_conf(output_sections, output_path, args.host)
    except OSError as exc:
        print(f"[ERROR] Could not write output file: {exc}")
        return 1

    print(f"\n{'='*60}")
    print(f"Conversion complete: {output_path}")
    print(
        f"Sections: {len(output_sections)} | "
        f"Apply via CLI paste or System > Configuration > Restore"
    )
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
