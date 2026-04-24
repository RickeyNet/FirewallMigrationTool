#!/usr/bin/env python3
"""
Palo Alto PAN-OS to FortiGate Configuration Converter — Main Script
====================================================================
Orchestrates the conversion of a PAN-OS XML running configuration to
FortiGate CLI config format.

The output is a single ``.conf`` file containing FortiGate CLI commands
that can be pasted directly into the FortiGate CLI or restored via:
    System > Configuration > Restore (select the .conf file)

OUTPUT FILE:
    {output_base}.conf    — FortiGate CLI configuration

SECTIONS GENERATED (in order):
    1. config system interface   — Physical and VLAN interfaces
    2. config system zone        — Security zones
    3. config firewall address   — Address objects
    4. config firewall addrgrp   — Address groups
    5. config firewall service custom  — Service objects
    6. config firewall service group   — Service groups
    7. config firewall policy    — Security policies
    8. config router static      — Static routes

HOW TO RUN:
    python fg_converter.py panos_running.xml
    python fg_converter.py panos_running.xml -o fg_migration
    python fg_converter.py panos_running.xml --vsys vsys1

NOTE:
    Direct API import to FortiGate is not currently supported.
    Apply the generated .conf file using the FortiGate CLI or
    the web UI backup/restore feature.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

try:
    from fg_pa_parser import parse_panos_xml
    from fg_address_converter import FGAddressConverter
    from fg_address_group_converter import FGAddressGroupConverter
    from fg_service_converter import FGServiceConverter
    from fg_service_group_converter import FGServiceGroupConverter
    from fg_policy_converter import FGPolicyConverter
    from fg_route_converter import FGRouteConverter
    from fg_interface_converter import FGInterfaceConverter
except ImportError as e:
    print("\n" + "=" * 60)
    print("ERROR: Missing converter module files!")
    print("=" * 60)
    print(f"\nDetails: {e}")
    print("\nMake sure these files are in the same folder as this script:")
    print("  - fg_common.py")
    print("  - fg_pa_parser.py")
    print("  - fg_address_converter.py")
    print("  - fg_address_group_converter.py")
    print("  - fg_service_converter.py")
    print("  - fg_service_group_converter.py")
    print("  - fg_policy_converter.py")
    print("  - fg_route_converter.py")
    print("  - fg_interface_converter.py")
    print("\n" + "=" * 60)
    raise


def main(argv=None):
    """Main function that orchestrates the entire conversion process."""

    # ====================================================================
    # STEP 1: Parse command-line arguments
    # ====================================================================
    parser = argparse.ArgumentParser(
        description=(
            "Convert Palo Alto PAN-OS XML configuration to FortiGate CLI format"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fg_converter.py panos_running.xml
  python fg_converter.py panos_running.xml -o fg_migration
  python fg_converter.py panos_running.xml --vsys vsys2
        """,
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Path to PAN-OS XML configuration file",
    )
    parser.add_argument(
        "-o", "--output",
        help="Base name for output .conf file (default: fg_config)",
        default="fg_config",
    )
    parser.add_argument(
        "--vsys",
        help="Target vsys to parse (default: vsys1)",
        default="vsys1",
    )

    args = parser.parse_args(argv)

    if not args.input_file:
        parser.error("input_file is required")

    # ====================================================================
    # STEP 2: Display welcome banner
    # ====================================================================
    print("=" * 60)
    print("Palo Alto PAN-OS to FortiGate Configuration Converter")
    print("=" * 60)
    print(f"Input:  {args.input_file}")

    # ====================================================================
    # STEP 3: Parse PAN-OS XML
    # ====================================================================
    print(f"\nLoading PAN-OS XML configuration from: {args.input_file}")
    try:
        pa_config = parse_panos_xml(args.input_file)
        print("[OK] PAN-OS XML parsed successfully")
    except Exception as exc:
        print(f"[ERROR] Failed to parse XML: {exc}")
        return 1

    # Print quick inventory
    print(
        f"  Found: "
        f"{len(pa_config.get('addresses', []))} addresses, "
        f"{len(pa_config.get('address_groups', []))} address groups, "
        f"{len(pa_config.get('services', []))} services, "
        f"{len(pa_config.get('service_groups', []))} service groups, "
        f"{len(pa_config.get('security_rules', []))} rules, "
        f"{len(pa_config.get('static_routes', []))} routes, "
        f"{len(pa_config.get('zones', []))} zones, "
        f"{len(pa_config.get('interfaces', []))} interfaces"
    )

    # ====================================================================
    # STEP 4: Run conversion phases
    # ====================================================================
    output_sections = []

    # ------------------------------------------------------------------ #
    # Phase 1: Interfaces                                                  #
    # ------------------------------------------------------------------ #
    print("\n[Phase 1/7] Converting interfaces and zones...")
    intf_converter = FGInterfaceConverter(pa_config)
    intf_block = intf_converter.convert_interfaces()
    zone_block = intf_converter.convert_zones()
    if intf_block:
        output_sections.append(intf_block)
    if zone_block:
        output_sections.append(zone_block)
    stats = intf_converter.get_statistics()
    print(
        f"  Result: {stats['interfaces']} interfaces, "
        f"{stats['zones']} zones"
    )

    # ------------------------------------------------------------------ #
    # Phase 2: Address objects                                             #
    # ------------------------------------------------------------------ #
    print("\n[Phase 2/7] Converting address objects...")
    addr_converter = FGAddressConverter(pa_config)
    addr_block = addr_converter.convert()
    if addr_block:
        output_sections.append(addr_block)
    stats = addr_converter.get_statistics()
    print(
        f"  Result: {stats['total']} converted "
        f"({stats['subnet']} subnets, {stats['iprange']} ranges, "
        f"{stats['fqdn']} FQDNs), {stats['skipped']} skipped"
    )

    # ------------------------------------------------------------------ #
    # Phase 3: Address groups                                              #
    # ------------------------------------------------------------------ #
    print("\n[Phase 3/7] Converting address groups...")
    addrgrp_converter = FGAddressGroupConverter(pa_config)
    addrgrp_block = addrgrp_converter.convert()
    if addrgrp_block:
        output_sections.append(addrgrp_block)
    stats = addrgrp_converter.get_statistics()
    print(f"  Result: {stats['total']} converted, {stats['skipped']} skipped")

    # ------------------------------------------------------------------ #
    # Phase 4: Service objects                                             #
    # ------------------------------------------------------------------ #
    print("\n[Phase 4/7] Converting service objects...")
    svc_converter = FGServiceConverter(pa_config)
    svc_block = svc_converter.convert()
    if svc_block:
        output_sections.append(svc_block)
    service_name_map = svc_converter.get_name_map()
    stats = svc_converter.get_statistics()
    print(
        f"  Result: {stats['total']} converted "
        f"({stats['tcp_only']} TCP-only, {stats['udp_only']} UDP-only, "
        f"{stats['merged_tcp_udp']} TCP+UDP merged), "
        f"{stats['skipped']} skipped"
    )

    # ------------------------------------------------------------------ #
    # Phase 5: Service groups                                              #
    # ------------------------------------------------------------------ #
    print("\n[Phase 5/7] Converting service groups...")
    svcgrp_converter = FGServiceGroupConverter(pa_config, service_name_map)
    svcgrp_block = svcgrp_converter.convert()
    if svcgrp_block:
        output_sections.append(svcgrp_block)
    stats = svcgrp_converter.get_statistics()
    print(f"  Result: {stats['total']} converted, {stats['skipped']} skipped")

    # ------------------------------------------------------------------ #
    # Phase 6: Security policies                                           #
    # ------------------------------------------------------------------ #
    print("\n[Phase 6/7] Converting security policies...")
    policy_converter = FGPolicyConverter(pa_config, service_name_map)
    policy_block = policy_converter.convert()
    if policy_block:
        output_sections.append(policy_block)
    stats = policy_converter.get_statistics()
    print(
        f"  Result: {stats['total']} converted "
        f"({stats['allow']} allow, {stats['deny']} deny, "
        f"{stats['disabled']} disabled)"
    )

    # ------------------------------------------------------------------ #
    # Phase 7: Static routes                                               #
    # ------------------------------------------------------------------ #
    print("\n[Phase 7/7] Converting static routes...")
    route_converter = FGRouteConverter(pa_config)
    route_block = route_converter.convert()
    if route_block:
        output_sections.append(route_block)
    stats = route_converter.get_statistics()
    print(
        f"  Result: {stats['converted']} converted, "
        f"{stats['skipped']} skipped"
    )

    # ====================================================================
    # STEP 5: Write output file
    # ====================================================================
    output_path = Path(f"{args.output}.conf")
    print(f"\nWriting FortiGate config to: {output_path}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"# FortiGate CLI Configuration\n"
        f"# Generated by Firewall Migration Tool\n"
        f"# Source: {args.input_file}\n"
        f"# Generated: {timestamp}\n"
        f"#\n"
        f"# IMPORTANT: Review all settings before applying.\n"
        f"# Interface-to-port assignments must be verified manually.\n"
        f"# Apply via FortiGate CLI or: System > Configuration > Restore\n"
        f"#\n\n"
    )

    output_content = header + "\n".join(output_sections)

    try:
        output_path.write_text(output_content, encoding="utf-8")
        print(f"[OK] Configuration written: {output_path}")
    except OSError as exc:
        print(f"[ERROR] Failed to write output file: {exc}")
        return 1

    # ====================================================================
    # STEP 6: Summary
    # ====================================================================
    print("\n" + "=" * 60)
    print("Conversion Complete")
    print("=" * 60)
    print(f"Output file: {output_path.resolve()}")
    print(
        "\nNext steps:\n"
        "  1. Review the generated .conf file carefully\n"
        "  2. Verify interface names match your FortiGate hardware ports\n"
        "  3. Apply via FortiGate CLI or web UI (System > Configuration > Restore)\n"
        "  4. Test all firewall policies and routing after applying"
    )
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
