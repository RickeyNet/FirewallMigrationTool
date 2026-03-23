#!/usr/bin/env python3
"""
Cisco ASA to Palo Alto PAN-OS Configuration Converter
=======================================================
Converts a Cisco ASA running-config text file to PAN-OS JSON files that
are compatible with the existing panos_api_importer.

OUTPUT FILES (same schema as the FortiGate→PAN-OS converter):
    {basename}_interfaces.json
    {basename}_address_objects.json
    {basename}_address_groups.json
    {basename}_service_objects.json
    {basename}_service_groups.json
    {basename}_security_rules.json
    {basename}_static_routes.json
    {basename}_zones.json
    {basename}_nat_rules.json        (ASA NAT — for manual review)
    {basename}_metadata.json
    {basename}_summary.json

HOW TO RUN:
    python asa_converter.py Cisco_ASA_config.txt
    python asa_converter.py Cisco_ASA_config.txt -o pa_config --pretty
    python asa_converter.py Cisco_ASA_config.txt --target-model pa-440
"""

import argparse
import json
import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure sibling packages are importable
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_PA_DIR = os.path.join(os.path.dirname(_SELF_DIR), "FortiGateToPaloAltoTool")
for _d in (_SELF_DIR, _PA_DIR):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

from asa_parser import ASAParser  # noqa: E402
from pa_common import sanitize_name, netmask_to_cidr  # noqa: E402
from pa_interface_converter import PA_MODELS, print_supported_models  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# Helper utilities
# ═══════════════════════════════════════════════════════════════════════════

def write_json_file(path: str, data: object, pretty: bool = False) -> None:
    """Write JSON data to a file."""
    with open(path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(data, f, indent=2)
        else:
            json.dump(data, f, separators=(",", ":"))


# ═══════════════════════════════════════════════════════════════════════════
# Conversion functions — each mirrors the PAN-OS JSON output schema
# ═══════════════════════════════════════════════════════════════════════════

def convert_interfaces(
    parsed: Dict[str, Any], target_model: str
) -> Tuple[List[Dict], List[Dict], Dict[str, str], Dict[str, str]]:
    """Convert ASA interfaces to PAN-OS interface + zone format.

    Returns:
        (pa_interfaces, pa_zones, interface_name_mapping, zone_mapping)

    interface_name_mapping: ASA nameif → PAN-OS ethernet name
    zone_mapping:           ASA nameif → PAN-OS zone name
    """
    model_info = PA_MODELS.get(target_model, PA_MODELS["pa-440"])
    total_ports = model_info["total_ports"]

    pa_interfaces: List[Dict] = []
    zone_to_members: Dict[str, List[str]] = {}
    intf_map: Dict[str, str] = {}   # nameif → ethernet name
    zone_map: Dict[str, str] = {}   # nameif → zone name

    port_index = 1

    for intf in parsed["interfaces"]:
        nameif = intf.get("nameif", "")
        if not nameif:
            continue

        # Skip management-only interfaces from data plane assignment
        if intf.get("management_only"):
            print(f"    Skipped data-plane mapping: {intf['hw_id']} "
                  f"(management-only)")
            # Still create a zone for management
            zone_name = sanitize_name(nameif)
            zone_map[nameif] = zone_name
            continue

        if port_index > total_ports:
            print(f"    WARNING: No more ports on {target_model} for "
                  f"{intf['hw_id']} ({nameif})")
            continue

        pa_name = f"ethernet1/{port_index}"
        port_index += 1

        # Build IP in CIDR format
        ip_cidr = ""
        if intf["ip_address"] and intf["netmask"]:
            cidr = netmask_to_cidr(intf["netmask"])
            ip_cidr = f"{intf['ip_address']}/{cidr}"

        pa_intf: Dict[str, Any] = {
            "name": pa_name,
            "type": "physical",
            "ip_address": ip_cidr,
            "comment": intf.get("description", ""),
            "enabled": not intf.get("shutdown", True),
            "link_speed": "auto",
        }
        pa_interfaces.append(pa_intf)

        # Map ASA nameif to PAN-OS interface and zone
        zone_name = sanitize_name(nameif)
        intf_map[nameif] = pa_name
        zone_map[nameif] = zone_name

        zone_to_members.setdefault(zone_name, []).append(pa_name)

        print(f"  Mapped: {intf['hw_id']} ({nameif}) → {pa_name} "
              f"[zone: {zone_name}] {ip_cidr}")

    # Build zone list
    pa_zones = [
        {"name": z, "interfaces": members}
        for z, members in sorted(zone_to_members.items())
    ]

    return pa_interfaces, pa_zones, intf_map, zone_map


def convert_address_objects(
    parsed: Dict[str, Any],
    inline_hosts: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Convert ASA network objects to PAN-OS address objects.

    Also includes any ad-hoc host objects created from inline ACL references.
    """
    results: List[Dict] = []
    used_names: Set[str] = set()

    for obj_name, obj in parsed["network_objects"].items():
        sanitized = sanitize_name(obj_name)
        sanitized = _dedup_name(sanitized, used_names)

        obj_type = obj.get("type", "")
        description = obj.get("description", "")

        if obj_type == "host":
            pa_obj = {
                "name": sanitized,
                "type": "ip-netmask",
                "value": f"{obj['value']}/32",
                "description": description,
            }
        elif obj_type == "subnet":
            cidr = netmask_to_cidr(obj.get("netmask", "255.255.255.255"))
            pa_obj = {
                "name": sanitized,
                "type": "ip-netmask",
                "value": f"{obj['value']}/{cidr}",
                "description": description,
            }
        elif obj_type == "range":
            pa_obj = {
                "name": sanitized,
                "type": "ip-range",
                "value": f"{obj['value']}-{obj.get('end_value', '')}",
                "description": description,
            }
        elif obj_type == "fqdn":
            pa_obj = {
                "name": sanitized,
                "type": "fqdn",
                "value": obj.get("fqdn", ""),
                "description": description,
            }
        else:
            print(f"  Skipped: {obj_name} (unknown type '{obj_type}')")
            continue

        results.append(pa_obj)
        print(f"  Converted: {obj_name} → {sanitized} [{pa_obj['type']}] "
              f"({pa_obj['value']})")

    # Add ad-hoc host objects for inline ACL/group references
    if inline_hosts:
        for host_name, ip in inline_hosts.items():
            if host_name in used_names:
                continue
            used_names.add(host_name)
            results.append({
                "name": host_name,
                "type": "ip-netmask",
                "value": f"{ip}/32",
                "description": "Auto-created from inline reference",
            })
            print(f"  Auto-created: {host_name} → {ip}/32")

    return results


def convert_address_groups(
    parsed: Dict[str, Any],
    inline_hosts: Dict[str, str],
) -> List[Dict]:
    """Convert ASA network object-groups to PAN-OS address groups."""
    results: List[Dict] = []
    used_names: Set[str] = set()

    for grp_name, grp in parsed["network_object_groups"].items():
        sanitized = sanitize_name(grp_name)
        sanitized = _dedup_name(sanitized, used_names)

        members: List[str] = []

        for member in grp.get("members", []):
            mtype = member.get("type", "")
            if mtype == "object":
                members.append(sanitize_name(member["name"]))
            elif mtype == "group":
                members.append(sanitize_name(member["name"]))
            elif mtype == "host":
                # Create an ad-hoc host object
                host_name = f"host_{member['value'].replace('.', '_')}"
                host_name = sanitize_name(host_name)
                inline_hosts[host_name] = member["value"]
                members.append(host_name)
            elif mtype == "subnet":
                ip = member.get("value", "")
                mask = member.get("netmask", "")
                cidr = netmask_to_cidr(mask)
                subnet_name = sanitize_name(
                    f"net_{ip.replace('.', '_')}_{cidr}"
                )
                inline_hosts[subnet_name] = f"{ip}/{cidr}"
                members.append(subnet_name)

        if not members:
            print(f"  Skipped: {grp_name} (no members)")
            continue

        results.append({
            "name": sanitized,
            "members": members,
            "description": "",
        })
        print(f"  Converted: {grp_name} → {sanitized} "
              f"({len(members)} members)")

    return results


def convert_service_objects(
    parsed: Dict[str, Any],
    inline_services: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Convert ASA service objects to PAN-OS service objects."""
    results: List[Dict] = []
    used_names: Set[str] = set()

    for svc_name, svc in parsed["service_objects"].items():
        protocol = svc.get("protocol", "")
        dst_port = svc.get("dst_port", "")

        if not protocol or protocol in ("icmp", "icmp6", "ip"):
            print(f"  Skipped: {svc_name} (protocol '{protocol}' — "
                  f"no PAN-OS service equivalent)")
            continue

        if not dst_port:
            print(f"  Skipped: {svc_name} (no destination port)")
            continue

        sanitized = sanitize_name(svc_name)
        sanitized = _dedup_name(sanitized, used_names)

        port_value = dst_port
        if svc.get("dst_port_end"):
            port_value = f"{dst_port}-{svc['dst_port_end']}"

        results.append({
            "name": sanitized,
            "protocol": protocol,
            "port": port_value,
        })
        print(f"  Converted: {svc_name} → {sanitized} "
              f"[{protocol.upper()}] (port {port_value})")

    # Add ad-hoc service objects from inline ACL port specs
    if inline_services:
        for svc_name, svc_info in inline_services.items():
            if svc_name in used_names:
                continue
            used_names.add(svc_name)
            results.append({
                "name": svc_name,
                "protocol": svc_info["protocol"],
                "port": svc_info["port"],
            })
            print(f"  Auto-created: {svc_name} [{svc_info['protocol'].upper()}] "
                  f"(port {svc_info['port']})")

    return results


def convert_service_groups(
    parsed: Dict[str, Any],
    inline_services: Dict[str, Dict],
) -> List[Dict]:
    """Convert ASA service object-groups to PAN-OS service groups.

    For port-based groups (object-group service <name> tcp), each member
    port becomes an individual PAN-OS service object, and the group
    references them.
    """
    results: List[Dict] = []
    used_names: Set[str] = set()

    for grp_name, grp in parsed["service_object_groups"].items():
        sanitized = sanitize_name(grp_name)
        sanitized = _dedup_name(sanitized, used_names)
        protocol = grp.get("protocol", "tcp")
        port_members = grp.get("members", [])
        svc_refs = grp.get("service_refs", [])

        member_names: List[str] = []

        # Create service objects for each port in the group
        for port_val in port_members:
            svc_obj_name = sanitize_name(f"{protocol}_{port_val}")
            if svc_obj_name not in inline_services:
                inline_services[svc_obj_name] = {
                    "protocol": protocol,
                    "port": port_val,
                }
            member_names.append(svc_obj_name)

        # Handle service-object and group-object references
        for ref in svc_refs:
            if ref["type"] == "object":
                member_names.append(sanitize_name(ref["name"]))
            elif ref["type"] == "group":
                member_names.append(sanitize_name(ref["name"]))
            elif ref["type"] == "inline":
                proto = ref.get("protocol", "tcp")
                port = ref.get("port", "")
                svc_obj_name = sanitize_name(f"{proto}_{port}")
                if svc_obj_name not in inline_services:
                    inline_services[svc_obj_name] = {
                        "protocol": proto,
                        "port": port,
                    }
                member_names.append(svc_obj_name)

        if not member_names:
            print(f"  Skipped: {grp_name} (no resolvable members)")
            continue

        results.append({
            "name": sanitized,
            "members": member_names,
        })
        print(f"  Converted: {grp_name} → {sanitized} "
              f"({len(member_names)} members)")

    return results


def convert_static_routes(
    parsed: Dict[str, Any],
    intf_map: Dict[str, str],
) -> List[Dict]:
    """Convert ASA static routes to PAN-OS static routes."""
    results: List[Dict] = []
    used_names: Set[str] = set()

    for route in parsed["routes"]:
        dest = route["destination"]
        mask = route["netmask"]
        cidr = netmask_to_cidr(mask)
        dest_cidr = f"{dest}/{cidr}"
        gateway = route["gateway"]
        metric = route.get("metric", 1)

        # Build a descriptive route name
        if dest == "0.0.0.0" and cidr == 0:
            base_name = "default_route"
        else:
            base_name = f"route_{dest.replace('.', '_')}_{cidr}"
        route_name = sanitize_name(base_name)
        route_name = _dedup_name(route_name, used_names)

        # Map ASA interface nameif to PAN-OS interface
        asa_intf = route["interface"]
        pa_intf = intf_map.get(asa_intf, "")

        pa_route: Dict[str, Any] = {
            "name": route_name,
            "destination": dest_cidr,
        }
        if gateway and gateway != "0.0.0.0":
            pa_route["nexthop"] = gateway
        if pa_intf:
            pa_route["interface"] = pa_intf
        pa_route["metric"] = metric

        results.append(pa_route)
        gw_display = gateway if gateway else "connected"
        intf_display = pa_intf if pa_intf else asa_intf
        print(f"  Converted: {route_name} → {dest_cidr} via {gw_display} "
              f"{intf_display} (metric {metric})")

    return results


def convert_security_rules(
    parsed: Dict[str, Any],
    zone_map: Dict[str, str],
    inline_hosts: Dict[str, str],
    inline_services: Dict[str, Dict],
) -> List[Dict]:
    """Convert ASA access-lists to PAN-OS security rules.

    Uses access-group bindings to determine the from-zone for each ACL.
    """
    results: List[Dict] = []
    used_names: Set[str] = set()
    access_groups = parsed.get("access_groups", {})

    for acl_name, aces in parsed.get("access_lists", {}).items():
        # Determine the interface / zone this ACL is bound to
        binding = access_groups.get(acl_name)
        from_zone = ""
        if binding:
            asa_intf = binding.get("interface", "")
            from_zone = zone_map.get(asa_intf, sanitize_name(asa_intf))

        for idx, ace in enumerate(aces, start=1):
            action = ace.get("action", "deny")
            pa_action = "allow" if action == "permit" else "deny"

            # Rule name
            base_name = f"{sanitize_name(acl_name)}_rule_{idx}"
            rule_name = _dedup_name(base_name, used_names)

            # Zones
            from_zones = [from_zone] if from_zone else ["any"]
            to_zones = ["any"]

            # Source
            sources = _resolve_ace_address(
                ace.get("source", {}), inline_hosts, parsed
            )
            if not sources:
                sources = ["any"]

            # Destination
            destinations = _resolve_ace_address(
                ace.get("destination", {}), inline_hosts, parsed
            )
            if not destinations:
                destinations = ["any"]

            # Service
            services = _resolve_ace_service(
                ace, parsed, inline_services
            )
            if not services:
                services = ["any"]

            # Description
            protocol = ace.get("protocol", "")
            desc_parts = [f"ASA ACL: {acl_name}"]
            if protocol == "icmp":
                desc_parts.append("(ICMP — review application setting)")
            description = " ".join(desc_parts)

            rule: Dict[str, Any] = {
                "name": rule_name,
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
            print(f"  Converted: {rule_name} [{pa_action.upper()}] "
                  f"({', '.join(from_zones)} → {', '.join(to_zones)})")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# ACE resolution helpers
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_ace_address(
    addr_spec: Dict[str, str],
    inline_hosts: Dict[str, str],
    parsed: Dict[str, Any],
) -> List[str]:
    """Resolve an ACE address specifier to PAN-OS address reference(s)."""
    addr_type = addr_spec.get("type", "any")

    if addr_type == "any":
        return ["any"]
    elif addr_type == "host":
        ip = addr_spec.get("value", "")
        host_name = sanitize_name(f"host_{ip.replace('.', '_')}")
        inline_hosts[host_name] = ip
        return [host_name]
    elif addr_type == "object":
        return [sanitize_name(addr_spec.get("name", ""))]
    elif addr_type == "object-group":
        return [sanitize_name(addr_spec.get("name", ""))]
    elif addr_type == "subnet":
        ip = addr_spec.get("value", "")
        mask = addr_spec.get("netmask", "")
        cidr = netmask_to_cidr(mask)
        net_name = sanitize_name(f"net_{ip.replace('.', '_')}_{cidr}")
        inline_hosts[net_name] = f"{ip}/{cidr}"
        return [net_name]

    return ["any"]


def _resolve_ace_service(
    ace: Dict[str, Any],
    parsed: Dict[str, Any],
    inline_services: Dict[str, Dict],
) -> List[str]:
    """Resolve the service/port from an ACE to PAN-OS service reference(s)."""
    protocol = ace.get("protocol", "")

    # Protocol is a service object or group reference
    if ace.get("protocol_ref_type") in ("object", "object-group"):
        return [sanitize_name(ace["protocol_ref_name"])]

    # IP = any protocol → PAN-OS "any"
    if protocol in ("ip", ""):
        return ["any"]

    # ICMP — no port-based service object
    if protocol in ("icmp", "icmp6"):
        return ["any"]

    # TCP / UDP with destination port
    dest_port = ace.get("dest_port")
    if dest_port:
        return _resolve_port_spec(dest_port, protocol, inline_services)

    # TCP / UDP without port → any
    return ["any"]


def _resolve_port_spec(
    port_spec: Dict[str, str],
    protocol: str,
    inline_services: Dict[str, Dict],
) -> List[str]:
    """Resolve a port specification to PAN-OS service object name(s)."""
    ptype = port_spec.get("type", "")

    if ptype == "eq":
        port = port_spec.get("port", "")
        svc_name = sanitize_name(f"{protocol}_{port}")
        if svc_name not in inline_services:
            inline_services[svc_name] = {
                "protocol": protocol,
                "port": port,
            }
        return [svc_name]
    elif ptype == "range":
        start = port_spec.get("start", "")
        end = port_spec.get("end", "")
        port_val = f"{start}-{end}"
        svc_name = sanitize_name(f"{protocol}_{start}_{end}")
        if svc_name not in inline_services:
            inline_services[svc_name] = {
                "protocol": protocol,
                "port": port_val,
            }
        return [svc_name]
    elif ptype == "object-group":
        return [sanitize_name(port_spec.get("name", ""))]
    elif ptype in ("gt", "lt", "neq"):
        port = port_spec.get("port", "")
        if ptype == "gt":
            port_val = f"{int(port) + 1}-65535" if port.isdigit() else port
        elif ptype == "lt":
            port_val = f"1-{int(port) - 1}" if port.isdigit() else port
        else:
            port_val = port  # neq — approximate
        svc_name = sanitize_name(f"{protocol}_{ptype}_{port}")
        if svc_name not in inline_services:
            inline_services[svc_name] = {
                "protocol": protocol,
                "port": port_val,
            }
        return [svc_name]

    return ["any"]


# ═══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════

def _dedup_name(name: str, used: Set[str]) -> str:
    """Return a unique name by appending _N if already used."""
    if name not in used:
        used.add(name)
        return name
    counter = 2
    while f"{name}_{counter}" in used:
        counter += 1
    unique = f"{name}_{counter}"
    used.add(unique)
    return unique


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def main(argv=None):
    """Main function — parse ASA config and produce PAN-OS JSON files."""

    parser = argparse.ArgumentParser(
        description="Convert Cisco ASA configuration to Palo Alto PAN-OS format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python asa_converter.py Cisco_ASA_config.txt
  python asa_converter.py Cisco_ASA_config.txt -o pa_config --pretty
  python asa_converter.py Cisco_ASA_config.txt --target-model pa-440
  python asa_converter.py Cisco_ASA_config.txt --list-models
        """,
    )

    parser.add_argument(
        "input_file",
        nargs="?",
        help="Path to Cisco ASA configuration file (.txt / .cfg)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Base name for output JSON files (default: pa_config)",
        default="pa_config",
    )
    parser.add_argument(
        "-p", "--pretty",
        action="store_true",
        help="Format JSON output with indentation for readability",
    )
    parser.add_argument(
        "-m", "--target-model",
        default="pa-440",
        help="Target Palo Alto model (default: pa-440). "
             "Use --list-models to see options.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List supported Palo Alto models and exit",
    )

    args = parser.parse_args(argv)

    if args.list_models:
        print_supported_models()
        return 0

    if not args.input_file:
        parser.error("input_file is required (unless using --list-models)")

    # ====================================================================
    # Banner
    # ====================================================================
    print("=" * 60)
    print("Cisco ASA to Palo Alto PAN-OS Configuration Converter")
    print("=" * 60)
    print(f"Target Model: {args.target_model}")

    # ====================================================================
    # Load and parse ASA config
    # ====================================================================
    print(f"\nLoading ASA configuration from: {args.input_file}")

    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            config_text = f.read()
    except FileNotFoundError:
        print(f"\n[ERROR] Input file '{args.input_file}' not found!")
        return 1
    except OSError as e:
        print(f"\n[ERROR] Could not read input file: {e}")
        return 1

    asa_parser = ASAParser()
    parsed = asa_parser.parse(config_text)

    hostname = parsed.get("hostname", "unknown")
    print(f"[OK] Parsed ASA config for hostname: {hostname}")
    print(f"  - Interfaces: {len(parsed['interfaces'])}")
    print(f"  - Network objects: {len(parsed['network_objects'])}")
    print(f"  - Network object-groups: {len(parsed['network_object_groups'])}")
    print(f"  - Service objects: {len(parsed['service_objects'])}")
    print(f"  - Service object-groups: {len(parsed['service_object_groups'])}")
    print(f"  - Access-lists: {len(parsed['access_lists'])} "
          f"({sum(len(v) for v in parsed['access_lists'].values())} ACEs)")
    print(f"  - Access-groups: {len(parsed['access_groups'])}")
    print(f"  - Static routes: {len(parsed['routes'])}")
    print(f"  - NAT rules: {len(parsed['nat_rules'])}")

    # Shared containers for ad-hoc objects created during conversion
    inline_hosts: Dict[str, str] = {}       # name → IP or CIDR
    inline_services: Dict[str, Dict] = {}   # name → {protocol, port}

    # ====================================================================
    # Convert interfaces & zones
    # ====================================================================
    print("\n" + "=" * 70)
    print("Converting Interfaces & Zones...")
    print("=" * 70)

    pa_interfaces, pa_zones, intf_map, zone_map = convert_interfaces(
        parsed, args.target_model
    )
    print(f"\n[OK] {len(pa_interfaces)} interfaces, "
          f"{len(pa_zones)} zones created")

    # ====================================================================
    # Convert address groups FIRST (to discover inline host objects)
    # ====================================================================
    print("\n" + "-" * 60)
    print("Converting Address Groups...")
    print("-" * 60)

    address_groups = convert_address_groups(parsed, inline_hosts)
    print(f"[OK] Converted {len(address_groups)} address groups")

    # ====================================================================
    # Convert service groups (to discover inline service objects)
    # ====================================================================
    print("\n" + "-" * 60)
    print("Converting Service Groups...")
    print("-" * 60)

    service_groups = convert_service_groups(parsed, inline_services)
    print(f"[OK] Converted {len(service_groups)} service groups")

    # ====================================================================
    # Convert security rules (may create more inline objects)
    # ====================================================================
    print("\n" + "-" * 60)
    print("Converting Security Rules (Access-Lists)...")
    print("-" * 60)

    security_rules = convert_security_rules(
        parsed, zone_map, inline_hosts, inline_services
    )

    allow_count = sum(1 for r in security_rules if r["action"] == "allow")
    deny_count = len(security_rules) - allow_count
    print(f"[OK] Converted {len(security_rules)} security rules "
          f"(allow: {allow_count}, deny: {deny_count})")

    # ====================================================================
    # Convert address objects (including inline hosts discovered above)
    # ====================================================================
    print("\n" + "-" * 60)
    print("Converting Address Objects...")
    print("-" * 60)

    address_objects = convert_address_objects(parsed, inline_hosts)
    print(f"[OK] Converted {len(address_objects)} address objects")

    # ====================================================================
    # Convert service objects (including inline services discovered above)
    # ====================================================================
    print("\n" + "-" * 60)
    print("Converting Service Objects...")
    print("-" * 60)

    service_objects = convert_service_objects(parsed, inline_services)

    tcp_count = sum(1 for s in service_objects if s.get("protocol") == "tcp")
    udp_count = sum(1 for s in service_objects if s.get("protocol") == "udp")
    print(f"[OK] Converted {len(service_objects)} service objects "
          f"(TCP: {tcp_count}, UDP: {udp_count})")

    # ====================================================================
    # Convert static routes
    # ====================================================================
    print("\n" + "-" * 60)
    print("Converting Static Routes...")
    print("-" * 60)

    static_routes = convert_static_routes(parsed, intf_map)
    print(f"[OK] Converted {len(static_routes)} static routes")

    # ====================================================================
    # Write output files
    # ====================================================================
    print(f"\n" + "-" * 60)
    print("Saving output files...")
    print("-" * 60)

    base = args.output
    file_map = {
        "interfaces": (f"{base}_interfaces.json", pa_interfaces),
        "zones": (f"{base}_zones.json", pa_zones),
        "address_objects": (f"{base}_address_objects.json", address_objects),
        "address_groups": (f"{base}_address_groups.json", address_groups),
        "service_objects": (f"{base}_service_objects.json", service_objects),
        "service_groups": (f"{base}_service_groups.json", service_groups),
        "security_rules": (f"{base}_security_rules.json", security_rules),
        "static_routes": (f"{base}_static_routes.json", static_routes),
    }

    # Metadata
    metadata = {
        "target_platform": "panos",
        "source_platform": "cisco_asa",
        "source_hostname": hostname,
        "target_model": args.target_model,
        "output_basename": args.output,
        "schema_version": 1,
    }
    write_json_file(f"{base}_metadata.json", metadata, pretty=args.pretty)
    print(f"[OK] Wrote metadata: {base}_metadata.json")

    try:
        for label, (path, data) in file_map.items():
            write_json_file(path, data, args.pretty)
            print(f"[OK] {label}: {path} ({len(data)} items)")

        # NAT rules (for manual review)
        nat_rules = parsed.get("nat_rules", [])
        if nat_rules:
            nat_path = f"{base}_nat_rules.json"
            nat_data = [
                {"original_rule": r, "note": "Manual review required"}
                for r in nat_rules
            ]
            write_json_file(nat_path, nat_data, pretty=True)
            print(f"[OK] NAT rules (manual review): {nat_path} "
                  f"({len(nat_data)} rules)")

        # Summary
        summary = {
            "conversion_summary": {
                "source_platform": "cisco_asa",
                "source_hostname": hostname,
                "target_platform": "panos",
                "target_model": args.target_model,
                "interfaces": len(pa_interfaces),
                "zones": len(pa_zones),
                "address_objects": len(address_objects),
                "address_groups": len(address_groups),
                "service_objects": {
                    "total": len(service_objects),
                    "tcp": tcp_count,
                    "udp": udp_count,
                },
                "service_groups": len(service_groups),
                "security_rules": {
                    "total": len(security_rules),
                    "allow": allow_count,
                    "deny": deny_count,
                },
                "static_routes": len(static_routes),
                "nat_rules_for_review": len(nat_rules),
            },
        }
        write_json_file(f"{base}_summary.json", summary, pretty=True)
        print(f"[OK] Summary: {base}_summary.json")

    except IOError as e:
        print(f"\n[ERROR] Could not write output files: {e}")
        return 1

    # ====================================================================
    # Final summary
    # ====================================================================
    print("\n" + "=" * 60)
    print("CONVERSION COMPLETE")
    print("=" * 60)
    print(f"\nSource: Cisco ASA ({hostname})")
    print(f"Target: Palo Alto {args.target_model}")
    print(f"\nOutput Files:")
    print(f"  1. {base}_interfaces.json      ({len(pa_interfaces)} interfaces)")
    print(f"  2. {base}_zones.json            ({len(pa_zones)} zones)")
    print(f"  3. {base}_address_objects.json  ({len(address_objects)} objects)")
    print(f"  4. {base}_address_groups.json   ({len(address_groups)} groups)")
    print(f"  5. {base}_service_objects.json  ({len(service_objects)} objects)")
    print(f"  6. {base}_service_groups.json   ({len(service_groups)} groups)")
    print(f"  7. {base}_security_rules.json   ({len(security_rules)} rules)")
    print(f"  8. {base}_static_routes.json    ({len(static_routes)} routes)")

    if nat_rules:
        print(f"\n  NOTE: {len(nat_rules)} NAT rule(s) saved to "
              f"{base}_nat_rules.json")
        print("        NAT requires manual review — PAN-OS NAT differs "
              "significantly from ASA.")

    print("\n" + "=" * 60)
    print("IMPORT ORDER FOR PAN-OS:")
    print("=" * 60)
    print("  1. Import interfaces first (layer3)")
    print("  2. Import zones")
    print("  3. Import address objects")
    print("  4. Import address groups")
    print("  5. Import service objects")
    print("  6. Import service groups")
    print("  7. Import static routes")
    print("  8. Import security rules last")
    print("  9. Commit configuration")
    print("  10. Configure NAT manually")
    print("\nThis order ensures referenced objects exist before importing")
    print("objects that reference them.")
    print("\n" + "=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
