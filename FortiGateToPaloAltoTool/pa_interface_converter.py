#!/usr/bin/env python3
"""
FortiGate Interface Converter — Palo Alto PAN-OS Target
=========================================================
Converts FortiGate ``system_interface`` entries to PAN-OS interface and zone
configurations.

WHAT THIS MODULE DOES:
    - Parses FortiGate 'system_interface' section from YAML
    - Maps FortiGate ports to PAN-OS hardware interfaces
    - Converts physical interfaces with IP/netmask/MTU
    - Converts VLAN interfaces to PAN-OS subinterfaces
    - Converts aggregate interfaces to PAN-OS aggregate-ethernet (LACP)
    - Generates zone definitions from FortiGate zone/role info

FORTIGATE INTERFACE TYPES:
    - type: physical   → PAN-OS ethernet (layer3 with IP)
    - type: aggregate  → PAN-OS aggregate-ethernet (LACP)
    - VLAN (interface + vlanid) → PAN-OS subinterface (ethernet1/X.tag)
    - type: switch     → Skipped (no PAN-OS equivalent; use virtual-wire manually)
    - type: loopback/tunnel → Skipped

OUTPUT JSON (interfaces):
    {
        "name": "ethernet1/1",
        "type": "physical",
        "ip_address": "10.0.0.1/24",
        "comment": "LAN interface",
        "mtu": 1500,
        "enabled": true,
        "link_speed": "auto"
    }

OUTPUT JSON (zones):
    {
        "name": "trust",
        "interfaces": ["ethernet1/1", "ethernet1/2"]
    }

PA-440 hardware reference:
    - 8x 1G copper: ethernet1/1 through ethernet1/8
    - 1x mgmt port (separate, not in data plane)
"""

from typing import Any, Dict, List, Set

from pa_common import sanitize_name, netmask_to_cidr


# PA model definitions
PA_MODELS = {
    "pa-440": {
        "name": "Palo Alto PA-440",
        "total_ports": 8,
        "port_prefix": "ethernet1/",
        "management_port": "mgmt",
        "description": "8-port 1G copper desktop firewall (ethernet1/1 - ethernet1/8)",
    },
    "pa-450": {
        "name": "Palo Alto PA-450",
        "total_ports": 8,
        "port_prefix": "ethernet1/",
        "management_port": "mgmt",
        "description": "8-port desktop firewall (ethernet1/1 - ethernet1/8)",
    },
    "pa-460": {
        "name": "Palo Alto PA-460",
        "total_ports": 12,
        "port_prefix": "ethernet1/",
        "management_port": "mgmt",
        "description": "12-port desktop firewall with PoE",
    },
    "pa-3220": {
        "name": "Palo Alto PA-3220",
        "total_ports": 12,
        "port_prefix": "ethernet1/",
        "management_port": "mgmt",
        "description": "12-port 1U enterprise firewall",
    },
    "pa-3250": {
        "name": "Palo Alto PA-3250",
        "total_ports": 24,
        "port_prefix": "ethernet1/",
        "management_port": "mgmt",
        "description": "24-port 1U enterprise firewall",
    },
    "pa-5220": {
        "name": "Palo Alto PA-5220",
        "total_ports": 24,
        "port_prefix": "ethernet1/",
        "management_port": "mgmt",
        "description": "24-port 2U data center firewall",
    },
}


def get_supported_models() -> list:
    """Return list of supported PA model names."""
    return sorted(PA_MODELS.keys())


def print_supported_models():
    """Print a table of supported Palo Alto models."""
    print("\nSupported Palo Alto Models:")
    print("=" * 70)
    print(f"{'Model':<15} {'Name':<25} {'Ports':<8} {'Description'}")
    print("-" * 70)
    for model_id, info in sorted(PA_MODELS.items()):
        print(f"{model_id:<15} {info['name']:<25} {info['total_ports']:<8} {info['description']}")
    print("=" * 70)


class PAInterfaceConverter:
    """Convert FortiGate interfaces to PAN-OS interface and zone configs.

    Produces two outputs:
        1. Interface configurations (physical, subinterface, aggregate-ethernet)
        2. Zone definitions (groups of interfaces)

    Also builds mappings consumed by route and policy converters:
        - interface_name_mapping: FortiGate name -> PAN-OS interface name
        - zone_mapping: FortiGate name -> PAN-OS zone name
    """

    # FortiGate interface names to always skip
    _SKIP_NAMES = frozenset([
        "ha", "mgmt", "modem", "naf.root", "l2t.root", "ssl.root",
        "fortilink", "npu0_vlink0", "npu0_vlink1",
    ])

    def __init__(
        self,
        fortigate_config: Dict[str, Any],
        target_model: str = "pa-440",
    ):
        self.fg_config = fortigate_config
        self.target_model = target_model
        self.model_info = PA_MODELS.get(target_model, PA_MODELS["pa-440"])
        self.total_ports = self.model_info["total_ports"]

        # Outputs
        self.pa_interfaces: List[Dict] = []  # Physical + aggregate + subinterface configs
        self.pa_zones: List[Dict] = []
        self.failed_items: List[Dict] = []

        # FortiGate interface name -> PAN-OS interface name (e.g. "port1" -> "ethernet1/1")
        self.interface_name_mapping: Dict[str, str] = {}

        # FortiGate interface name -> PAN-OS zone name (e.g. "port1" -> "trust")
        self.zone_mapping: Dict[str, str] = {}

        # Zone name -> list of PAN-OS interface names
        self._zone_members: Dict[str, List[str]] = {}

        # Track port assignment
        self._next_port: int = 1
        self._used_ports: Set[int] = set()

        # Track aggregate-ethernet IDs
        self._next_ae_id: int = 1

        # Statistics
        self._stats = {
            "total_interfaces": 0,
            "physical_interfaces": 0,
            "subinterfaces": 0,
            "aggregate_interfaces": 0,
            "zones_created": 0,
            "mapped_interfaces": 0,
            "skipped": 0,
        }

    def convert(self) -> List[Dict]:
        """Convert FortiGate interfaces to PAN-OS zone definitions.

        Also populates self.pa_interfaces with full interface configs.

        Returns:
            List of zone dicts (for backward compatibility).
        """
        interfaces = self.fg_config.get("system_interface", [])
        if not interfaces:
            print("Warning: No interfaces found in FortiGate configuration")
            return []

        # Build FortiGate zone lookup from system_zone
        fg_zones = self.fg_config.get("system_zone", [])
        zone_lookup = self._build_zone_lookup(fg_zones)

        # Categorize interfaces by type
        physical_ports = []
        aggregate_ports = []
        vlan_interfaces = []

        for intf_dict in interfaces:
            intf_key = list(intf_dict.keys())[0]
            properties = intf_dict[intf_key]
            intf_name = str(intf_key)
            self._stats["total_interfaces"] += 1

            if not isinstance(properties, dict):
                self._stats["skipped"] += 1
                continue

            # Skip system/virtual interfaces
            if intf_name in self._SKIP_NAMES:
                print(f"    Skipped: {intf_name} (system/virtual interface)")
                self._stats["skipped"] += 1
                continue

            # Skip special FortiGate interfaces
            if intf_name.startswith("vw") or (intf_name.startswith("s") and len(intf_name) <= 2):
                print(f"    Skipped: {intf_name} (special port)")
                self._stats["skipped"] += 1
                continue

            intf_type = str(properties.get("type", "")).strip().lower()

            # Skip loopback and tunnel
            if intf_type in ("loopback", "tunnel"):
                print(f"    Skipped: {intf_name} (type: {intf_type})")
                self._stats["skipped"] += 1
                continue

            # Categorize
            if "interface" in properties and "vlanid" in properties:
                vlan_interfaces.append((intf_name, properties))
            elif intf_type == "aggregate":
                aggregate_ports.append((intf_name, properties))
            elif intf_type in ("physical", "hard-switch", "") or not intf_type:
                physical_ports.append((intf_name, properties))
            elif intf_type == "switch":
                # PAN-OS doesn't have bridge groups
                print(f"    Skipped: {intf_name} (switch/bridge group — not supported on PAN-OS)")
                self.failed_items.append({
                    "name": intf_name,
                    "reason": "switch/bridge group not supported on PAN-OS",
                    "config": properties,
                })
                self._stats["skipped"] += 1
            else:
                print(f"    Skipped: {intf_name} (type: {intf_type})")
                self._stats["skipped"] += 1

        # --- Phase 1: Identify which physical ports are aggregate members ---
        aggregate_member_set: Set[str] = set()
        for _, props in aggregate_ports:
            members = props.get("member", [])
            if isinstance(members, str):
                members = [members]
            for m in members:
                aggregate_member_set.add(str(m).strip())

        # --- Phase 2: Identify which physical ports have subinterfaces ---
        parent_interface_set: Set[str] = set()
        for _, props in vlan_interfaces:
            parent = str(props.get("interface", "")).strip()
            if parent:
                parent_interface_set.add(parent)

        # --- Phase 3: Convert aggregate interfaces first (need member ports) ---
        for fg_name, props in aggregate_ports:
            self._convert_aggregate(fg_name, props, zone_lookup)

        # --- Phase 4: Convert physical interfaces ---
        for fg_name, props in physical_ports:
            if fg_name in aggregate_member_set:
                # Already assigned as aggregate member — skip standalone conversion
                # but still need the port mapped for reference
                continue
            self._convert_physical(fg_name, props, zone_lookup)

        # --- Phase 5: Convert VLAN subinterfaces ---
        for fg_name, props in vlan_interfaces:
            self._convert_subinterface(fg_name, props, zone_lookup)

        # --- Phase 6: Build zone output ---
        results: List[Dict] = []
        for zone_name, members in sorted(self._zone_members.items()):
            zone = {
                "name": zone_name,
                "interfaces": members,
            }
            results.append(zone)
            self._stats["zones_created"] += 1
            print(f"  Zone: {zone_name} ({', '.join(members)})")

        self.pa_zones = results
        return results

    def get_interfaces(self) -> List[Dict]:
        """Return the full interface configuration list."""
        return list(self.pa_interfaces)

    def get_interface_mapping(self) -> Dict[str, str]:
        """Return FortiGate name -> PAN-OS interface name mapping.

        Used by route converter for the 'interface' field in static routes.
        """
        return dict(self.interface_name_mapping)

    def get_zone_mapping(self) -> Dict[str, str]:
        """Return FortiGate name -> PAN-OS zone name mapping.

        Used by policy converter for from_zones/to_zones in security rules.
        """
        return dict(self.zone_mapping)

    def get_statistics(self) -> Dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Conversion methods
    # ------------------------------------------------------------------

    def _convert_physical(
        self, fg_name: str, properties: Dict, zone_lookup: Dict[str, str]
    ) -> None:
        """Convert a FortiGate physical interface to PAN-OS layer3 config."""
        pa_interface = self._assign_pa_port(fg_name)
        if not pa_interface:
            return

        # Zone
        zone_name = self._determine_zone(fg_name, properties, zone_lookup)
        self.interface_name_mapping[fg_name] = pa_interface
        self.zone_mapping[fg_name] = zone_name

        # Also map alias if present
        alias = str(properties.get("alias", "")).strip()
        if alias and alias != fg_name:
            self.interface_name_mapping[alias] = pa_interface
            self.zone_mapping[alias] = zone_name

        self._add_to_zone(zone_name, pa_interface)
        self._stats["physical_interfaces"] += 1
        self._stats["mapped_interfaces"] += 1

        # Build interface config
        intf_config: Dict[str, Any] = {
            "name": pa_interface,
            "type": "physical",
            "mode": "layer3",
            "enabled": properties.get("status", "up") != "down",
        }

        # IP address
        ip_cidr = self._extract_ip_cidr(properties)
        if ip_cidr:
            intf_config["ip_address"] = ip_cidr

        # DHCP
        mode = str(properties.get("mode", "")).strip().lower()
        if mode == "dhcp":
            intf_config["dhcp"] = True

        # Comment / description
        desc = properties.get("description") or properties.get("alias") or fg_name
        intf_config["comment"] = str(desc)

        # MTU
        if properties.get("mtu-override") == "enable":
            mtu = self._parse_int(properties.get("mtu"), 1500)
            if mtu > 9216:
                mtu = 9216  # PAN-OS max jumbo frame
            intf_config["mtu"] = mtu

        # Link speed (auto by default on PAN-OS)
        speed = str(properties.get("speed", "")).strip().lower()
        intf_config["link_speed"] = speed if speed else "auto"

        self.pa_interfaces.append(intf_config)
        ip_display = ip_cidr if ip_cidr else ("DHCP" if mode == "dhcp" else "no IP")
        print(f"    Converted: {fg_name} -> {pa_interface} ({ip_display}, zone: {zone_name})")

    def _convert_subinterface(
        self, fg_name: str, properties: Dict, zone_lookup: Dict[str, str]
    ) -> None:
        """Convert a FortiGate VLAN interface to PAN-OS subinterface."""
        parent_fg = str(properties.get("interface", "")).strip()
        vlan_id = properties.get("vlanid")

        if not parent_fg or not vlan_id:
            print(f"    Skipped: {fg_name} (missing parent or VLAN ID)")
            self._stats["skipped"] += 1
            self.failed_items.append({
                "name": fg_name,
                "reason": "missing parent interface or VLAN ID",
                "config": properties,
            })
            return

        vlan_id = int(vlan_id)

        # Find the PAN-OS parent interface name
        parent_pa = self.interface_name_mapping.get(parent_fg)
        if not parent_pa:
            # Parent hasn't been mapped yet — assign a port for it
            parent_pa = self._assign_pa_port(parent_fg)
            if not parent_pa:
                print(f"    Skipped: {fg_name} (parent {parent_fg} has no available port)")
                self._stats["skipped"] += 1
                self.failed_items.append({
                    "name": fg_name,
                    "reason": f"parent {parent_fg} could not be mapped",
                    "config": properties,
                })
                return
            self.interface_name_mapping[parent_fg] = parent_pa

        # PAN-OS subinterface name: ethernet1/1.100
        pa_name = f"{parent_pa}.{vlan_id}"

        # Zone
        zone_name = self._determine_zone(fg_name, properties, zone_lookup)
        self.interface_name_mapping[fg_name] = pa_name
        self.zone_mapping[fg_name] = zone_name

        alias = str(properties.get("alias", "")).strip()
        if alias and alias != fg_name:
            self.interface_name_mapping[alias] = pa_name
            self.zone_mapping[alias] = zone_name

        self._add_to_zone(zone_name, pa_name)
        self._stats["subinterfaces"] += 1
        self._stats["mapped_interfaces"] += 1

        # Build subinterface config
        intf_config: Dict[str, Any] = {
            "name": pa_name,
            "type": "subinterface",
            "parent": parent_pa,
            "tag": vlan_id,
            "enabled": properties.get("status", "up") != "down",
        }

        ip_cidr = self._extract_ip_cidr(properties)
        if ip_cidr:
            intf_config["ip_address"] = ip_cidr

        mode = str(properties.get("mode", "")).strip().lower()
        if mode == "dhcp":
            intf_config["dhcp"] = True

        desc = properties.get("description") or properties.get("alias") or fg_name
        intf_config["comment"] = str(desc)

        if properties.get("mtu-override") == "enable":
            mtu = self._parse_int(properties.get("mtu"), 1500)
            if mtu > 9216:
                mtu = 9216
            intf_config["mtu"] = mtu

        self.pa_interfaces.append(intf_config)
        ip_display = ip_cidr if ip_cidr else ("DHCP" if mode == "dhcp" else "no IP")
        print(f"    Converted: {fg_name} -> {pa_name} (VLAN {vlan_id}, {ip_display}, zone: {zone_name})")

    def _convert_aggregate(
        self, fg_name: str, properties: Dict, zone_lookup: Dict[str, str]
    ) -> None:
        """Convert a FortiGate aggregate interface to PAN-OS aggregate-ethernet."""
        members_raw = properties.get("member", [])
        if isinstance(members_raw, str):
            members_raw = [members_raw]

        if not members_raw:
            print(f"    Skipped: {fg_name} (aggregate with no members)")
            self._stats["skipped"] += 1
            self.failed_items.append({
                "name": fg_name,
                "reason": "aggregate with no members",
                "config": properties,
            })
            return

        ae_id = self._next_ae_id
        self._next_ae_id += 1
        ae_name = f"ae{ae_id}"

        # Assign PAN-OS ports to each member
        member_pa_names = []
        member_configs = []
        for member_fg in members_raw:
            member_fg = str(member_fg).strip()
            pa_port = self._assign_pa_port(member_fg)
            if pa_port:
                member_pa_names.append(pa_port)
                self.interface_name_mapping[member_fg] = pa_port

                # Build member physical interface config (set aggregate-group)
                member_configs.append({
                    "name": pa_port,
                    "type": "aggregate-member",
                    "aggregate_group": ae_name,
                    "enabled": True,
                    "comment": f"Member of {ae_name} (FortiGate: {fg_name})",
                })
            else:
                self.failed_items.append({
                    "name": member_fg,
                    "reason": f"no port available for aggregate member of {fg_name}",
                    "config": {},
                })

        if not member_pa_names:
            print(f"    Skipped: {fg_name} (no ports available for members)")
            self._stats["skipped"] += 1
            return

        # Zone
        zone_name = self._determine_zone(fg_name, properties, zone_lookup)
        self.interface_name_mapping[fg_name] = ae_name
        self.zone_mapping[fg_name] = zone_name

        alias = str(properties.get("alias", "")).strip()
        if alias and alias != fg_name:
            self.interface_name_mapping[alias] = ae_name
            self.zone_mapping[alias] = zone_name

        self._add_to_zone(zone_name, ae_name)
        self._stats["aggregate_interfaces"] += 1
        self._stats["mapped_interfaces"] += 1

        # Build aggregate-ethernet config
        intf_config: Dict[str, Any] = {
            "name": ae_name,
            "type": "aggregate-ethernet",
            "mode": "layer3",
            "members": member_pa_names,
            "lacp_mode": "active",
            "enabled": properties.get("status", "up") != "down",
        }

        ip_cidr = self._extract_ip_cidr(properties)
        if ip_cidr:
            intf_config["ip_address"] = ip_cidr

        mode = str(properties.get("mode", "")).strip().lower()
        if mode == "dhcp":
            intf_config["dhcp"] = True

        desc = properties.get("description") or properties.get("alias") or fg_name
        intf_config["comment"] = str(desc)

        if properties.get("mtu-override") == "enable":
            mtu = self._parse_int(properties.get("mtu"), 1500)
            if mtu > 9216:
                mtu = 9216
            intf_config["mtu"] = mtu

        # Add member configs first (they need to be configured before the AE)
        self.pa_interfaces.extend(member_configs)
        self.pa_interfaces.append(intf_config)

        members_display = ", ".join(member_pa_names)
        ip_display = ip_cidr if ip_cidr else ("DHCP" if mode == "dhcp" else "no IP")
        print(f"    Converted: {fg_name} -> {ae_name} (LACP, members: [{members_display}], "
              f"{ip_display}, zone: {zone_name})")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assign_pa_port(self, fg_name: str) -> str:
        """Assign the next available PAN-OS port to a FortiGate interface."""
        port = self._get_next_port()
        if port:
            return f"{self.model_info['port_prefix']}{port}"
        self.failed_items.append({
            "name": fg_name,
            "reason": f"no available ports on {self.target_model} "
                      f"({self.total_ports} total)",
            "config": {},
        })
        return ""

    def _get_next_port(self) -> int:
        """Get the next available port number on the target model."""
        while self._next_port <= self.total_ports:
            port = self._next_port
            self._next_port += 1
            if port not in self._used_ports:
                self._used_ports.add(port)
                return port
        return 0

    def _build_zone_lookup(self, fg_zones: List) -> Dict[str, str]:
        """Build interface -> zone name mapping from FortiGate system_zone."""
        lookup: Dict[str, str] = {}
        if not fg_zones:
            return lookup
        for zone_dict in fg_zones:
            zone_name = list(zone_dict.keys())[0]
            properties = zone_dict[zone_name]
            interfaces = properties.get("interface", [])
            if isinstance(interfaces, str):
                interfaces = [interfaces]
            for intf in interfaces:
                lookup[str(intf).strip()] = sanitize_name(zone_name)
        return lookup

    def _determine_zone(
        self, intf_name: str, properties: Dict, zone_lookup: Dict[str, str]
    ) -> str:
        """Determine PAN-OS zone name for a FortiGate interface."""
        # 1. Explicit zone assignment from system_zone
        if intf_name in zone_lookup:
            return zone_lookup[intf_name]

        # 2. Use FortiGate 'alias' or 'description' as zone name
        alias = str(properties.get("alias", "")).strip()
        if alias:
            return sanitize_name(alias)

        # 3. Use FortiGate 'role' hint
        role = str(properties.get("role", "")).strip().lower()
        if role in ("lan", "dmz", "wan"):
            return role
        if role == "undefined":
            return sanitize_name(intf_name)

        # 4. Fallback: use sanitized interface name
        return sanitize_name(intf_name)

    def _add_to_zone(self, zone_name: str, pa_interface: str) -> None:
        """Add a PAN-OS interface to a zone."""
        if zone_name not in self._zone_members:
            self._zone_members[zone_name] = []
        if pa_interface not in self._zone_members[zone_name]:
            self._zone_members[zone_name].append(pa_interface)

    def _extract_ip_cidr(self, properties: Dict) -> str:
        """Extract IP address in CIDR notation from FortiGate interface properties.

        FortiGate stores IP as: [ip, netmask] e.g. [10.0.0.1, 255.255.255.0]
        PAN-OS uses CIDR: 10.0.0.1/24
        """
        ip_config = properties.get("ip")
        if not ip_config:
            return ""

        if isinstance(ip_config, list) and len(ip_config) >= 2:
            ip_addr = str(ip_config[0]).strip()
            netmask = str(ip_config[1]).strip()
            if ip_addr and ip_addr != "0.0.0.0":
                cidr = netmask_to_cidr(netmask)
                return f"{ip_addr}/{cidr}"

        if isinstance(ip_config, str):
            ip_str = ip_config.strip()
            if "/" in ip_str:
                return ip_str
            parts = ip_str.split()
            if len(parts) == 2 and parts[0] != "0.0.0.0":
                cidr = netmask_to_cidr(parts[1])
                return f"{parts[0]}/{cidr}"

        return ""

    @staticmethod
    def _parse_int(value: Any, default: int = 0) -> int:
        """Safely parse an integer value."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
