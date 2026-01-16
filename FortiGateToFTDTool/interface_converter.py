#!/usr/bin/env python3
"""
FortiGate Interface Converter Module
=====================================
This module handles the conversion of FortiGate interfaces to 
Cisco FTD interface configurations.

WHAT THIS MODULE DOES:
    - Parses FortiGate 'system_interface' section from YAML
    - Maps FortiGate ports to FTD hardware interfaces
    - Converts physical interfaces (generates PUT payloads)
    - Converts aggregate interfaces to EtherChannels
    - Converts switch interfaces to Bridge Groups
    - Converts VLAN interfaces to Subinterfaces
    - Ensures all interface names are lowercase (FTD requirement)

FORTIGATE INTERFACE TYPES:
    - type: physical → FTD physicalinterface (PUT to update)
    - type: aggregate → FTD etherchannelinterface (POST to create)
    - type: switch → FTD bridgegroupinterface (POST to create)
    - VLAN (has interface: and vlanid:) → FTD subinterface (POST to create)

FTD INTERFACE NAME RULES:
    - Must be lowercase
    - Only alphanumeric and underscores allowed
    - Cannot start with a number
"""

import re
from typing import Dict, List, Any, Set, Tuple, Optional


def sanitize_interface_name(name: str) -> str:
    """
    Sanitize interface names for FTD compatibility.
    
    FTD interface names must be:
    - Lowercase
    - Alphanumeric and underscores only
    - Cannot start with a number
    
    Args:
        name: Original interface name
        
    Returns:
        Sanitized lowercase name
    """
    if name is None:
        return ""
    
    # Convert to string and lowercase
    name = str(name).lower()
    
    # Replace any non-alphanumeric character (except underscore) with underscore
    sanitized = re.sub(r'[^a-z0-9_]', '_', name)
    
    # Remove consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    
    return sanitized


class InterfaceConverter:
    """
    Converter class for transforming FortiGate interfaces to FTD format.
    """
    
    # Default port mapping - FortiGate port name -> FTD hardware name
    # This can be customized via set_port_mapping()
    DEFAULT_PORT_MAPPING = {
        # Explicit mappings (user-specified)
        'port2': 'Ethernet1/1',
        'port6': 'Ethernet1/3',
        'port5': 'Ethernet1/13',
        'port7': 'Ethernet1/14',
        'x1': 'Ethernet1/15',
        'x2': 'Ethernet1/16',
    }
    
    # Ports to skip (reserved for other purposes)
    SKIP_FTD_PORTS = {'Ethernet1/2'}  # Reserved for HA
    
    def __init__(self, fortigate_config: Dict[str, Any]):
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'system_interface' key
        """
        self.fg_config = fortigate_config
        
        # Port mapping - can be customized
        self.port_mapping = self.DEFAULT_PORT_MAPPING.copy()
        self.skip_ftd_ports = self.SKIP_FTD_PORTS.copy()
        
        # Track which FTD ports have been assigned
        self.assigned_ftd_ports = set(self.port_mapping.values())
        self.assigned_ftd_ports.update(self.skip_ftd_ports)
        
        # Available FTD ports for auto-assignment (in order)
        # RJ45: Ethernet1/1-8, SFP: Ethernet1/9-16
        self.available_ftd_ports = []
        for i in range(1, 17):
            port = f"Ethernet1/{i}"
            if port not in self.assigned_ftd_ports:
                self.available_ftd_ports.append(port)
        
        # Store converted interfaces
        self.physical_interfaces = []      # PUT requests
        self.subinterfaces = []            # POST requests
        self.etherchannels = []            # POST requests
        self.bridge_groups = []            # POST requests
        
        # Interface name mapping: FortiGate name -> FTD name (for routes/policies)
        self.interface_name_mapping = {}
        
        # Track statistics
        self.stats = {
            'physical_updated': 0,
            'subinterfaces_created': 0,
            'etherchannels_created': 0,
            'bridge_groups_created': 0,
            'skipped': 0
        }
    
    def set_port_mapping(self, mapping: Dict[str, str]):
        """
        Set custom port mapping.
        
        Args:
            mapping: Dict of FortiGate port name -> FTD hardware name
        """
        self.port_mapping.update(mapping)
        self.assigned_ftd_ports = set(self.port_mapping.values())
        self.assigned_ftd_ports.update(self.skip_ftd_ports)
        
        # Rebuild available ports list
        self.available_ftd_ports = []
        for i in range(1, 17):
            port = f"Ethernet1/{i}"
            if port not in self.assigned_ftd_ports:
                self.available_ftd_ports.append(port)
    
    def set_skip_ports(self, ports: Set[str]):
        """
        Set FTD ports to skip (e.g., reserved for HA).
        
        Args:
            ports: Set of FTD hardware names to skip
        """
        self.skip_ftd_ports = ports
        self.assigned_ftd_ports.update(ports)
        
        # Rebuild available ports list
        self.available_ftd_ports = []
        for i in range(1, 17):
            port = f"Ethernet1/{i}"
            if port not in self.assigned_ftd_ports:
                self.available_ftd_ports.append(port)
    
    def _get_ftd_hardware_name(self, fg_port: str) -> Optional[str]:
        """
        Get the FTD hardware name for a FortiGate port.
        
        Args:
            fg_port: FortiGate port name (e.g., 'port1', 'x1')
            
        Returns:
            FTD hardware name (e.g., 'Ethernet1/1') or None if not available
        """
        # Check explicit mapping first
        if fg_port in self.port_mapping:
            return self.port_mapping[fg_port]
        
        # Auto-assign from available ports
        if self.available_ftd_ports:
            ftd_port = self.available_ftd_ports.pop(0)
            self.port_mapping[fg_port] = ftd_port
            self.assigned_ftd_ports.add(ftd_port)
            return ftd_port
        
        # No ports available
        return None
    
    def _netmask_to_cidr(self, netmask: str) -> int:
        """Convert subnet mask to CIDR prefix length."""
        try:
            octets = netmask.split('.')
            binary_str = ''.join(bin(int(octet))[2:].zfill(8) for octet in octets)
            return binary_str.count('1')
        except:
            return 24  # Default
    
    def convert(self) -> Dict[str, List[Dict]]:
        """
        Main conversion method - converts all FortiGate interfaces to FTD format.
        
        Returns:
            Dictionary with keys:
            - 'physical_interfaces': List of PUT payloads for physical interfaces
            - 'subinterfaces': List of POST payloads for subinterfaces
            - 'etherchannels': List of POST payloads for etherchannels
            - 'bridge_groups': List of POST payloads for bridge groups
        """
        interfaces = self.fg_config.get('system_interface', [])
        
        if not interfaces:
            print("Warning: No interfaces found in FortiGate configuration")
            print("  Expected key: 'system_interface'")
            return {
                'physical_interfaces': [],
                'subinterfaces': [],
                'etherchannels': [],
                'bridge_groups': []
            }
        
        # First pass: identify interface types and build mappings
        physical_ports = []
        aggregate_ports = []
        switch_ports = []
        vlan_interfaces = []
        
        for intf_dict in interfaces:
            intf_name = list(intf_dict.keys())[0]
            properties = intf_dict[intf_name]
            
            # Skip non-dict entries
            if not isinstance(properties, dict):
                continue
            
            intf_type = properties.get('type', 'physical')
            
            # Check if this is a VLAN interface (has 'interface' and 'vlanid')
            if 'interface' in properties and 'vlanid' in properties:
                vlan_interfaces.append((intf_name, properties))
            elif intf_type == 'aggregate':
                aggregate_ports.append((intf_name, properties))
            elif intf_type == 'switch':
                switch_ports.append((intf_name, properties))
            elif intf_type == 'physical':
                physical_ports.append((intf_name, properties))
            # Skip tunnel, etc.
        
        # Second pass: Convert each type
        
        # 1. Convert physical interfaces
        print("\n  Converting Physical Interfaces...")
        for fg_name, properties in physical_ports:
            self._convert_physical_interface(fg_name, properties)
        
        # 2. Convert aggregate interfaces (EtherChannels)
        print("\n  Converting Aggregate Interfaces (EtherChannels)...")
        for fg_name, properties in aggregate_ports:
            self._convert_aggregate_interface(fg_name, properties)
        
        # 3. Convert switch interfaces (Bridge Groups)
        print("\n  Converting Switch Interfaces (Bridge Groups)...")
        for fg_name, properties in switch_ports:
            self._convert_switch_interface(fg_name, properties)
        
        # 4. Convert VLAN interfaces (Subinterfaces)
        print("\n  Converting VLAN Interfaces (Subinterfaces)...")
        for fg_name, properties in vlan_interfaces:
            self._convert_vlan_interface(fg_name, properties)
        
        return {
            'physical_interfaces': self.physical_interfaces,
            'subinterfaces': self.subinterfaces,
            'etherchannels': self.etherchannels,
            'bridge_groups': self.bridge_groups
        }
    
    def _convert_physical_interface(self, fg_name: str, properties: Dict):
        """Convert a FortiGate physical interface to FTD format."""
        
        # Skip certain interfaces
        if fg_name in ['ha', 'mgmt', 'modem', 'naf.root', 'l2t.root', 'ssl.root']:
            print(f"    Skipped: {fg_name} (system/virtual interface)")
            self.stats['skipped'] += 1
            return
        
        # Skip interfaces that start with s, vw (special FortiGate ports)
        if fg_name.startswith('s') and len(fg_name) <= 2:
            print(f"    Skipped: {fg_name} (special port - no FTD equivalent)")
            self.stats['skipped'] += 1
            return
        if fg_name.startswith('vw'):
            print(f"    Skipped: {fg_name} (virtual wire port)")
            self.stats['skipped'] += 1
            return
        
        # Get FTD hardware name
        ftd_hardware = self._get_ftd_hardware_name(fg_name)
        if not ftd_hardware:
            print(f"    Skipped: {fg_name} (no available FTD port)")
            self.stats['skipped'] += 1
            return
        
        # Check if this FTD port should be skipped
        if ftd_hardware in self.skip_ftd_ports:
            print(f"    Skipped: {fg_name} -> {ftd_hardware} (reserved port)")
            self.stats['skipped'] += 1
            return
        
        # Get interface name (use alias if available, otherwise port name)
        alias = properties.get('alias', fg_name)
        ftd_name = sanitize_interface_name(alias)
        
        # Get description
        description = properties.get('description', alias)
        
        # Store the mapping
        self.interface_name_mapping[fg_name] = ftd_name
        self.interface_name_mapping[alias] = ftd_name
        
        # Build FTD physical interface payload (for PUT)
        ftd_interface = {
            "name": ftd_name,
            "hardwareName": ftd_hardware,
            "description": description,
            "enabled": properties.get('status', 'up') != 'down',
            "mode": "ROUTED",
            "type": "physicalinterface"
        }
        
        # Add IP address if present
        ip_config = properties.get('ip')
        if ip_config and isinstance(ip_config, list) and len(ip_config) >= 2:
            ip_addr = str(ip_config[0])
            netmask = str(ip_config[1])
            
            # Skip if IP is 0.0.0.0
            if ip_addr != '0.0.0.0':
                ftd_interface["ipv4"] = {
                    "ipType": "STATIC",
                    "defaultRouteUsingDHCP": False,
                    "ipAddress": {
                        "ipAddress": ip_addr,
                        "netmask": netmask,
                        "type": "haipv4address"
                    },
                    "dhcp": False,
                    "addressNull": False,
                    "type": "interfaceipv4"
                }
        
        # Add MTU if overridden
        if properties.get('mtu-override') == 'enable':
            mtu = properties.get('mtu', 1500)
            ftd_interface["mtu"] = mtu
        
        self.physical_interfaces.append(ftd_interface)
        self.stats['physical_updated'] += 1
        
        print(f"    Converted: {fg_name} -> {ftd_name} ({ftd_hardware})")
    
    def _convert_aggregate_interface(self, fg_name: str, properties: Dict):
        """Convert a FortiGate aggregate interface to FTD EtherChannel."""
        
        # Get interface name
        alias = properties.get('alias', fg_name)
        ftd_name = sanitize_interface_name(alias)
        
        # Store the mapping
        self.interface_name_mapping[fg_name] = ftd_name
        self.interface_name_mapping[alias] = ftd_name
        
        # Get member interfaces
        members = properties.get('member', [])
        if isinstance(members, str):
            members = [members]
        
        # Map member names to FTD hardware names
        ftd_members = []
        for member in members:
            ftd_hardware = self._get_ftd_hardware_name(member)
            if ftd_hardware:
                ftd_members.append({
                    "hardwareName": ftd_hardware,
                    "type": "physicalinterface"
                })
        
        if not ftd_members:
            print(f"    Skipped: {fg_name} (no valid member interfaces)")
            self.stats['skipped'] += 1
            return
        
        # Determine EtherChannel ID (extract from existing or assign new)
        # For simplicity, use 1 for first etherchannel, 2 for second, etc.
        etherchannel_id = len(self.etherchannels) + 1
        
        # Build FTD EtherChannel payload
        ftd_interface = {
            "name": ftd_name,
            "hardwareName": f"Port-channel{etherchannel_id}",
            "description": properties.get('description', alias),
            "enabled": properties.get('status', 'up') != 'down',
            "mode": "ROUTED",
            "etherChannelID": etherchannel_id,
            "memberInterfaces": ftd_members,
            "lacpMode": "ACTIVE",
            "type": "etherchannelinterface"
        }
        
        # Add MTU if overridden
        if properties.get('mtu-override') == 'enable':
            mtu = properties.get('mtu', 1500)
            ftd_interface["mtu"] = mtu
        
        self.etherchannels.append(ftd_interface)
        self.stats['etherchannels_created'] += 1
        
        member_str = ', '.join([m['hardwareName'] for m in ftd_members])
        print(f"    Converted: {fg_name} -> {ftd_name} (Port-channel{etherchannel_id}) members: [{member_str}]")
    
    def _convert_switch_interface(self, fg_name: str, properties: Dict):
        """Convert a FortiGate switch interface to FTD Bridge Group."""
        
        # Get interface name
        ftd_name = sanitize_interface_name(fg_name)
        
        # Store the mapping
        self.interface_name_mapping[fg_name] = ftd_name
        
        # For bridge groups, we need to identify member interfaces
        # In FortiGate, switch interfaces aggregate physical ports
        # We'll need to determine which physical ports belong to this switch
        
        # Bridge Group ID
        bridge_group_id = len(self.bridge_groups) + 1
        
        # Build FTD Bridge Group payload
        ftd_interface = {
            "name": ftd_name,
            "bridgeGroupId": bridge_group_id,
            "description": properties.get('description', fg_name),
            "enabled": properties.get('status', 'up') != 'down',
            "type": "bridgegroupinterface"
        }
        
        # Add IP address if present
        ip_config = properties.get('ip')
        if ip_config and isinstance(ip_config, list) and len(ip_config) >= 2:
            ip_addr = str(ip_config[0])
            netmask = str(ip_config[1])
            
            if ip_addr != '0.0.0.0':
                ftd_interface["ipv4"] = {
                    "ipType": "STATIC",
                    "defaultRouteUsingDHCP": False,
                    "ipAddress": {
                        "ipAddress": ip_addr,
                        "netmask": netmask,
                        "type": "haipv4address"
                    },
                    "dhcp": False,
                    "addressNull": False,
                    "type": "interfaceipv4"
                }
        
        # Add MTU if overridden
        if properties.get('mtu-override') == 'enable':
            mtu = properties.get('mtu', 1500)
            ftd_interface["mtu"] = mtu
        
        self.bridge_groups.append(ftd_interface)
        self.stats['bridge_groups_created'] += 1
        
        print(f"    Converted: {fg_name} -> {ftd_name} (BVI{bridge_group_id})")
    
    def _convert_vlan_interface(self, fg_name: str, properties: Dict):
        """Convert a FortiGate VLAN interface to FTD Subinterface."""
        
        # Get parent interface and VLAN ID
        parent_fg_name = properties.get('interface')
        vlan_id = properties.get('vlanid')
        
        if not parent_fg_name or not vlan_id:
            print(f"    Skipped: {fg_name} (missing parent interface or VLAN ID)")
            self.stats['skipped'] += 1
            return
        
        # Get interface name (use alias if available)
        alias = properties.get('alias', fg_name)
        ftd_name = sanitize_interface_name(alias)
        
        # Store the mapping
        self.interface_name_mapping[fg_name] = ftd_name
        self.interface_name_mapping[alias] = ftd_name
        
        # Determine parent FTD interface
        # Could be physical or etherchannel
        parent_ftd_name = self.interface_name_mapping.get(parent_fg_name)
        
        # Determine hardware name based on parent type
        if parent_fg_name in ['ether_trunk'] or parent_fg_name in [e.get('name', '') for e in self.etherchannels]:
            # Parent is an etherchannel
            # Find the etherchannel to get its hardware name
            for ec in self.etherchannels:
                if self.interface_name_mapping.get(parent_fg_name) == ec.get('name'):
                    parent_hardware = ec.get('hardwareName', 'Port-channel1')
                    break
            else:
                parent_hardware = 'Port-channel1'  # Default
        else:
            # Parent is a physical interface
            parent_hardware = self.port_mapping.get(parent_fg_name, f"Ethernet1/1")
        
        hardware_name = f"{parent_hardware}.{vlan_id}"
        
        # Build FTD Subinterface payload
        ftd_interface = {
            "name": ftd_name,
            "hardwareName": hardware_name,
            "description": properties.get('description', alias),
            "enabled": properties.get('status', 'up') != 'down',
            "mode": "ROUTED",
            "subIntfId": int(vlan_id),
            "vlanId": int(vlan_id),
            "type": "subinterface"
        }
        
        # Add IP address if present
        ip_config = properties.get('ip')
        if ip_config and isinstance(ip_config, list) and len(ip_config) >= 2:
            ip_addr = str(ip_config[0])
            netmask = str(ip_config[1])
            
            if ip_addr != '0.0.0.0':
                ftd_interface["ipv4"] = {
                    "ipType": "STATIC",
                    "defaultRouteUsingDHCP": False,
                    "ipAddress": {
                        "ipAddress": ip_addr,
                        "netmask": netmask,
                        "type": "haipv4address"
                    },
                    "dhcp": False,
                    "addressNull": False,
                    "type": "interfaceipv4"
                }
        
        # Add MTU if overridden
        if properties.get('mtu-override') == 'enable':
            mtu = properties.get('mtu', 1500)
            ftd_interface["mtu"] = mtu
        
        self.subinterfaces.append(ftd_interface)
        self.stats['subinterfaces_created'] += 1
        
        print(f"    Converted: {fg_name} -> {ftd_name} ({hardware_name}) VLAN {vlan_id}")
    
    def get_interface_mapping(self) -> Dict[str, str]:
        """
        Get the mapping of FortiGate interface names to FTD interface names.
        
        This is used by route and policy converters to update interface references.
        
        Returns:
            Dict mapping FortiGate names to FTD names
        """
        return self.interface_name_mapping.copy()
    
    def get_statistics(self) -> Dict[str, int]:
        """Get conversion statistics."""
        return self.stats.copy()


# =============================================================================
# TESTING CODE
# =============================================================================

if __name__ == '__main__':
    """Test the interface converter."""
    
    # Sample FortiGate configuration
    test_config = {
        'system_interface': [
            {
                'port2': {
                    'vdom': 'root',
                    'ip': ['10.0.0.6', '255.255.255.252'],
                    'type': 'physical',
                    'alias': 'IP-KVM',
                    'description': 'Connection to KVM'
                }
            },
            {
                'port6': {
                    'vdom': 'root',
                    'ip': ['10.0.0.10', '255.255.255.252'],
                    'type': 'physical',
                    'alias': 'L3_NTP'
                }
            },
            {
                'ether_trunk': {
                    'vdom': 'root',
                    'type': 'aggregate',
                    'member': ['x1', 'x2'],
                    'alias': 'UTB',
                    'mtu-override': 'enable',
                    'mtu': 9216
                }
            },
            {
                'whitebox': {
                    'vdom': 'root',
                    'ip': ['10.10.255.1', '255.255.255.0'],
                    'type': 'switch',
                    'description': 'Bridge Group'
                }
            },
            {
                '551': {
                    'vdom': 'root',
                    'ip': ['10.1.70.1', '255.255.255.0'],
                    'alias': 'L-slap',
                    'interface': 'ether_trunk',
                    'vlanid': 551
                }
            }
        ]
    }
    
    converter = InterfaceConverter(test_config)
    
    print("Testing Interface Converter...")
    print("="*60)
    result = converter.convert()
    
    print("\n" + "="*60)
    print("Results:")
    print("="*60)
    
    import json
    
    print("\nPhysical Interfaces (PUT):")
    print(json.dumps(result['physical_interfaces'], indent=2))
    
    print("\nEtherChannels (POST):")
    print(json.dumps(result['etherchannels'], indent=2))
    
    print("\nBridge Groups (POST):")
    print(json.dumps(result['bridge_groups'], indent=2))
    
    print("\nSubinterfaces (POST):")
    print(json.dumps(result['subinterfaces'], indent=2))
    
    print("\nInterface Name Mapping:")
    print(json.dumps(converter.get_interface_mapping(), indent=2))
    
    print("\nStatistics:")
    print(json.dumps(converter.get_statistics(), indent=2))