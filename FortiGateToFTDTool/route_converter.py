#!/usr/bin/env python3
"""
FortiGate Static Route Converter Module
========================================
This module handles the conversion of FortiGate static routes to 
Cisco FTD static route entries.

WHAT THIS MODULE DOES:
    - Parses FortiGate 'router_static' section from YAML
    - Extracts route information (destination, gateway, interface, metric)
    - Converts destination subnet to network object reference
    - Converts gateway IP to network object reference
    - Maps FortiGate device/interface to FTD interface reference
    - Handles blackhole routes (routes with no gateway)
    - Converts to FTD 'staticrouteentry' format

FORTIGATE YAML FORMAT:
    router_static:
        - ROUTE_ID:
            dst: [10.0.20.0, 255.255.255.0]  # Destination network
            gateway: 10.0.222.18             # Gateway IP (optional)
            distance: 1                       # Metric/distance (optional)
            device: "port2"                  # Interface name (optional)
            comment: "Description"           # Optional comment
            blackhole: enable                # Blackhole route (optional)
            vrf: 0                           # VRF (optional)

FTD JSON OUTPUT FORMAT:
    {
        "name": "Route_Name",
        "iface": {
            "name": "interface_name",
            "type": "physicalinterface"
        },
        "networks": [
            {"name": "destination_network", "type": "networkobject"}
        ],
        "gateway": {
            "name": "gateway_ip",
            "type": "networkobject"
        },
        "metricValue": 1,
        "ipType": "IPv4",
        "type": "staticrouteentry"
    }

IMPORTANT NOTES:
    - FortiGate 'dst' (destination) becomes FTD 'networks' array
    - FortiGate 'gateway' becomes FTD 'gateway' object reference
    - FortiGate 'device' becomes FTD 'iface' reference
    - FortiGate 'distance' becomes FTD 'metricValue'
    - Blackhole routes are skipped (or handled specially)
    - Default routes (0.0.0.0/0) are converted to "any-ipv4" reference
"""

import re
from typing import Dict, List, Any, Optional

def sanitize_name(name: str) -> str:
    """
    Sanitize object names for FTD compatibility.
    
    FTD does not allow spaces in object names. This function replaces
    spaces with underscores to ensure compatibility.
    
    Args:
        name: Original object name (may contain spaces)
        
    Returns:
        Sanitized name with spaces replaced by underscores
    """
    if name is None:
        return ""
    # Convert to string in case it's not
    name = str(name)
    # Replace any non-alphanumeric character (except underscore) with underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    # Remove consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized




class RouteConverter:
    """
    Converter class for transforming FortiGate static routes to FTD route entries.
    
    This class is responsible for:
    1. Reading the 'router_static' section from FortiGate YAML
    2. Extracting route information (destination, gateway, interface, metric)
    3. Converting IP addresses to network object references
    4. Mapping FortiGate interfaces to FTD interfaces
    5. Converting to FTD's staticrouteentry format
    6. Handling special cases (blackhole routes, default routes)
    """
    
    def __init__(self, fortigate_config: Dict[str, Any], network_objects: List[Dict] = None, interface_name_mapping: Dict[str, str] = None, converted_interfaces: Dict[str, List[Dict]] = None, debug: bool = False): # pyright: ignore[reportArgumentType]
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'router_static' key with route data
            network_objects: List of already-converted FTD network objects
                           Used to match route destinations/gateways to existing objects
            interface_name_mapping: Dict mapping FortiGate interface names to FTD interface names
            converted_interfaces: Dict containing converted interface lists
                                 Keys: 'physical_interfaces', 'subinterfaces', 'etherchannels', 'bridge_groups'
            debug: Enable debug output
        """
        # Store the entire FortiGate configuration
        self.fg_config = fortigate_config
        
        # Store the list of network objects for lookup
        self.network_objects = network_objects or []

        # Store interface name mapping
        self.interface_name_mapping = interface_name_mapping or {}
        
        # Store debug flag
        self.debug = debug
        
        # Store converted interfaces
        self.converted_interfaces = converted_interfaces or {}
        
        # Build lookup dictionaries
        # Name -> full network object (for routes)
        self.name_to_network_object = {}
        self._build_network_object_lookup()
        
        # IP/CIDR -> network object name
        self.ip_to_network_object_name = {}
        self._build_ip_to_network_object_lookup()
        
        # Interface name -> full interface object
        self.name_to_interface_object = {}
        self._build_interface_object_lookup()
        
        # IP/network -> interface name (for determining which interface a network/gateway is on)
        self.ip_to_interface_name = {}
        self._build_ip_to_interface_name_lookup()
        
        # This will store the converted FTD static routes
        self.ftd_static_routes = []
        
        # Track routes that need network objects created
        self.missing_network_objects = []
        
        # Track statistics
        self.converted_count = 0
        self.blackhole_count = 0
        self.skipped_count = 0
        self.unmatched_count = 0  # Track routes with no matching address object

    def _build_network_object_lookup(self):
        """Build lookup from network object name to full object."""
        for obj in self.network_objects:
            name = obj.get('name')
            if name:
                self.name_to_network_object[name] = obj
    
    def _build_ip_to_network_object_lookup(self):
        """Build lookup from IP/CIDR to network object name."""
        for obj in self.network_objects:
            name = obj.get('name', '')
            value = obj.get('value', '')
            
            if value and name:
                # Store in lookup: "10.0.20.0/24" -> "Bull_net"
                self.ip_to_network_object_name[value] = name
                
                # Also store without CIDR for host addresses
                if '/' in value:
                    ip_only = value.split('/')[0]
                    if ip_only not in self.ip_to_network_object_name:
                        self.ip_to_network_object_name[ip_only] = name
    
    def _build_interface_object_lookup(self):
        """Build lookup from interface name to full interface object."""
        for interface_type in ['physical_interfaces', 'subinterfaces', 'etherchannels', 'bridge_groups']:
            interfaces = self.converted_interfaces.get(interface_type, [])
            
            for intf in interfaces:
                name = intf.get('name', '')
                if name:
                    self.name_to_interface_object[name] = intf


    def _build_ip_to_interface_name_lookup(self):
        """Build lookup from IP/network to interface name."""
        for interface_type in ['physical_interfaces', 'subinterfaces', 'etherchannels', 'bridge_groups']:
            interfaces = self.converted_interfaces.get(interface_type, [])
            
            for intf in interfaces:
                intf_name = intf.get('name', '')
                if not intf_name:
                    continue
                
                # Extract IPv4 address if present
                ipv4_config = intf.get('ipv4')
                if ipv4_config and isinstance(ipv4_config, dict):
                    ip_address_obj = ipv4_config.get('ipAddress', {})
                    
                    if isinstance(ip_address_obj, dict):
                        ip_addr = ip_address_obj.get('ipAddress')
                        netmask = ip_address_obj.get('netmask')
                        
                        if ip_addr and netmask:
                            # Calculate network address and CIDR
                            cidr = self._netmask_to_cidr(netmask)
                            network_addr = self._calculate_network_address(ip_addr, netmask)
                            network_cidr = f"{network_addr}/{cidr}"
                            
                            # Store mappings
                            self.ip_to_interface_name[ip_addr] = intf_name
                            self.ip_to_interface_name[f"{ip_addr}/32"] = intf_name
                            self.ip_to_interface_name[network_cidr] = intf_name
                            self.ip_to_interface_name[network_addr] = intf_name
    
    def _calculate_network_address(self, ip_addr: str, netmask: str) -> str:
        """Calculate the network address given an IP and netmask."""
        try:
            ip_octets = [int(o) for o in ip_addr.split('.')]
            mask_octets = [int(o) for o in netmask.split('.')]
            network_octets = [ip_octets[i] & mask_octets[i] for i in range(4)]
            return '.'.join(str(o) for o in network_octets)
        except Exception:
            return ip_addr
        

    def _get_network_object_for_destination(self, dst: List) -> Optional[Dict]:
        """
        Get the full network object for a route destination.
        
        Args:
            dst: List containing [IP_address, netmask]
            
        Returns:
            Full network object dict with id, version, name, type, or None
        """
        if len(dst) < 2:
            return None
        
        ip_addr = str(dst[0])
        netmask = str(dst[1])
        cidr = self._netmask_to_cidr(netmask)
        
        # Check if this is a default route
        if ip_addr == "0.0.0.0" and cidr == 0:
            # Return reference to "any-ipv4" built-in object
            return {
                "name": "any-ipv4",
                "type": "networkobject"
            }
        
        # Calculate network address
        network_addr = self._calculate_network_address(ip_addr, netmask)
        network_cidr = f"{network_addr}/{cidr}"
        
        # Try to find existing network object by CIDR
        if network_cidr in self.ip_to_network_object_name:
            obj_name = self.ip_to_network_object_name[network_cidr]
            if obj_name in self.name_to_network_object:
                return self.name_to_network_object[obj_name].copy()
        
        # Try by network address only
        if network_addr in self.ip_to_network_object_name:
            obj_name = self.ip_to_network_object_name[network_addr]
            if obj_name in self.name_to_network_object:
                return self.name_to_network_object[obj_name].copy()
        
        # Try by IP address
        if ip_addr in self.ip_to_network_object_name:
            obj_name = self.ip_to_network_object_name[ip_addr]
            if obj_name in self.name_to_network_object:
                return self.name_to_network_object[obj_name].copy()
        
        # No existing object found - need to create one
        self.unmatched_count += 1
        generated_name = f"Net_{network_addr.replace('.', '_')}_{cidr}"
        print(f"    Warning: No network object found for {network_cidr}")
        print(f"             You need to create network object: {generated_name} = {network_cidr}")
        
        # Track missing object
        self.missing_network_objects.append({
            "name": generated_name,
            "value": network_cidr,
            "type": "networkobject"
        })
        
        # Return reference (will need ID added during import)
        return {
            "name": generated_name,
            "type": "networkobject"
        }
    
    def _get_network_object_for_gateway(self, gateway_ip: str) -> Optional[Dict]:
        """
        Get the full network object for a gateway IP.
        
        Args:
            gateway_ip: Gateway IP address as string
            
        Returns:
            Full network object dict with id, version, name, type, or None
        """
        # Try with /32 CIDR notation first
        gateway_cidr = f"{gateway_ip}/32"
        if gateway_cidr in self.ip_to_network_object_name:
            obj_name = self.ip_to_network_object_name[gateway_cidr]
            if obj_name in self.name_to_network_object:
                return self.name_to_network_object[obj_name].copy()
        
        # Try without CIDR
        if gateway_ip in self.ip_to_network_object_name:
            obj_name = self.ip_to_network_object_name[gateway_ip]
            if obj_name in self.name_to_network_object:
                return self.name_to_network_object[obj_name].copy()
        
        # No existing object found - need to create one
        self.unmatched_count += 1
        generated_name = f"Gateway_{gateway_ip.replace('.', '_')}"
        print(f"    Warning: No network object found for gateway {gateway_ip}")
        print(f"             You need to create network object: {generated_name} = {gateway_ip}/32")
        
        # Track missing object
        self.missing_network_objects.append({
            "name": generated_name,
            "value": f"{gateway_ip}/32",
            "type": "networkobject"
        })
        
        # Return reference (will need ID added during import)
        return {
            "name": generated_name,
            "type": "networkobject"
        }
    
    def _get_interface_object(self, interface_name: str) -> Optional[Dict]:
        """
        Get the full interface object by name.
        
        Args:
            interface_name: FTD interface name
            
        Returns:
            Full interface object dict, or None
        """
        return self.name_to_interface_object.get(interface_name)
    
    
    def convert(self) -> List[Dict]:
        """
        Main conversion method - converts all FortiGate static routes to FTD format.
        
        CONVERSION PROCESS:
        1. Extract the 'router_static' list from FortiGate config
        2. Loop through each route entry
        3. Extract the route ID and properties
        4. Check if it's a blackhole route (skip or handle specially)
        5. Extract destination network and convert to CIDR
        6. Extract gateway IP
        7. Extract interface name
        8. Extract metric/distance
        9. Create FTD staticrouteentry structure
        10. Return the complete list of converted routes
        
        Returns:
            List of dictionaries, each representing an FTD static route entry
        """
        # ====================================================================
        # STEP 1: Extract static routes from FortiGate configuration
        # ====================================================================
        routes = self.fg_config.get('router_static', [])
        
        if not routes:
            print("Warning: No static routes found in FortiGate configuration")
            print("  Expected key: 'router_static'")
            return []
        
        # This list will accumulate all converted routes
        static_routes = []
        
        # ====================================================================
        # STEP 2: Process each FortiGate static route
        # ====================================================================
        for route_dict in routes:
            # ================================================================
            # STEP 2A: Extract the route ID and properties
            # ================================================================
            # Each route looks like: {64: {dst: ..., gateway: ...}}
            # The route ID is the key (e.g., 64)
            route_id = list(route_dict.keys())[0]
            properties = route_dict[route_id]
            
            # ================================================================
            # STEP 2B: Check if this is a blackhole route
            # ================================================================
            # Blackhole routes drop traffic - they may not be needed in FTD
            if properties.get('blackhole') == 'enable':
                self.blackhole_count += 1
                print(f"  Skipped: Route [{route_id}] - Blackhole route")
                continue
            
            # ================================================================
            # STEP 2C: Extract destination network
            # ================================================================
            dst = properties.get('dst', [])
            if not dst or len(dst) < 2:
                print(f"  Skipped: Route [{route_id}] - No destination specified")
                self.skipped_count += 1
                continue
            
            # Convert destination to CIDR format
            dst_network = self._format_destination(dst)
            
            # ================================================================
            # STEP 2D: Get destination network object
            # ================================================================
            dst_network_obj = self._get_network_object_for_destination(dst)
            if not dst_network_obj:
                print(f"  Skipped: Route [{route_id}] - Could not resolve destination network object")
                self.skipped_count += 1
                continue
            
            # ================================================================
            # STEP 2E: Extract gateway and get network object
            # ================================================================
            gateway_ip = properties.get('gateway', None)
            if not gateway_ip:
                print(f"  Skipped: Route [{route_id}] - No gateway specified")
                self.skipped_count += 1
                continue
            
            gateway_obj = self._get_network_object_for_gateway(gateway_ip)
            if not gateway_obj:
                print(f"  Skipped: Route [{route_id}] - Could not resolve gateway network object")
                self.skipped_count += 1
                continue
            
            # ================================================================
            # STEP 2F: Extract interface/device and get interface object
            # ================================================================
            fg_interface_name = properties.get('device', 'unknown')
            
            # Map FortiGate interface name to FTD interface name
            if fg_interface_name in self.interface_name_mapping:
                ftd_interface_name = self.interface_name_mapping[fg_interface_name]
            else:
                ftd_interface_name = self.interface_name_mapping.get(
                    fg_interface_name, 
                    fg_interface_name.lower().replace('-', '_')
                )
            
            # Get the full interface object
            interface_obj = self._get_interface_object(ftd_interface_name) # type: ignore
            if not interface_obj:
                print(f"  Warning: Route [{route_id}] - Could not find interface object for {ftd_interface_name}")
                print(f"           Using basic interface reference")
                # Create basic interface reference as fallback
                interface_obj = {
                    "name": ftd_interface_name,
                    "type": "physicalinterface"
                }
            
            # ================================================================
            # STEP 2G: Extract metric/distance
            # ================================================================
            metric = properties.get('distance', 1)
            
            # ================================================================
            # STEP 2H: Extract comment for route name
            # ================================================================
            comment = properties.get('comment', '')
            if comment:
                route_name = sanitize_name(comment)
            else:
                dst_obj_name = dst_network_obj.get('name', 'unknown')
                route_name = f"Route_{route_id}_{sanitize_name(dst_obj_name)}"
            
            # ================================================================
            # STEP 2I: Create the FTD static route entry structure
            # ================================================================
            ftd_route = {
                "name": route_name,
                "iface": interface_obj,  # Full interface object with id, version, etc.
                "networks": [dst_network_obj],  # Full network object with id, version
                "gateway": gateway_obj,  # Full network object with id, version
                "metricValue": metric,
                "ipType": "IPv4",
                "type": "staticrouteentry"
            }
            
            # Add the converted route to our result list
            static_routes.append(ftd_route)
            self.converted_count += 1
            
            # ================================================================
            # STEP 2J: Print conversion details for user feedback
            # ================================================================
            dst_obj_name = dst_network_obj.get('name', 'unknown')
            gateway_obj_name = gateway_obj.get('name', 'unknown')
            interface_obj_name = interface_obj.get('name', 'unknown')
            
            print(f"  Converted: [{route_id}] {route_name}")
            print(f"    Destination: {dst_obj_name} ({dst_network})")
            print(f"    Gateway: {gateway_obj_name}")
            print(f"    Interface: {interface_obj_name}")
            print(f"    Metric: {metric}")
        
        # ====================================================================
        # STEP 3: Store results and return
        # ====================================================================
        self.ftd_static_routes = static_routes
        return static_routes
    
    def _format_destination(self, dst: List) -> str:
        """
        Convert FortiGate destination format to CIDR notation.
        
        FortiGate format: [IP, NETMASK]
        FTD format: IP/CIDR
        
        Args:
            dst: List containing [IP_address, netmask]
            
        Returns:
            String in CIDR format (e.g., "10.0.20.0/24")
        """
        if len(dst) < 2:
            return ""
        
        ip_addr = str(dst[0])
        netmask = str(dst[1])
        
        # Convert netmask to CIDR notation
        cidr = self._netmask_to_cidr(netmask)
        
        return f"{ip_addr}/{cidr}"
    
    def _netmask_to_cidr(self, netmask: str) -> int:
        """
        Convert subnet mask to CIDR prefix length.
        
        This is the same method used in the address converter.
        
        Args:
            netmask: Subnet mask in dotted decimal format (e.g., "255.255.255.0")
            
        Returns:
            Integer representing CIDR prefix length (e.g., 24)
        """
        try:
            # Split the netmask into individual octets
            octets = netmask.split('.')
            
            # Convert each octet to binary and concatenate
            binary_str = ''
            for octet in octets:
                # Convert to binary and pad to 8 bits
                binary_octet = bin(int(octet))[2:].zfill(8)
                binary_str += binary_octet
            
            # Count the number of '1' bits
            cidr_prefix = binary_str.count('1')
            
            return cidr_prefix
            
        except Exception as e:
            # If conversion fails, default to /32
            print(f"    Warning: Could not convert netmask '{netmask}' to CIDR")
            return 32
    
    def _create_network_name(self, dst: List) -> str:
        """
        Find the interface name for the destination network.
        
        This method looks up the destination IP/network to find which interface
        it's configured on, then returns that interface name.
        
        This allows FTD routes to reference interface names as the network object.
        
        Args:
            dst: List containing [IP_address, netmask]
            
        Returns:
            String name of the interface where this network exists, or a generated name if no match
        """
        if len(dst) < 2:
            return "Unknown_Network"
        
        ip_addr = str(dst[0])
        netmask = str(dst[1])
        cidr = self._netmask_to_cidr(netmask)
        
        # Check if this is a default route (0.0.0.0/0)
        if ip_addr == "0.0.0.0" and cidr == 0:
            return "any-ipv4"
        
        # Calculate network address
        network_addr = self._calculate_network_address(ip_addr, netmask)
        network_cidr = f"{network_addr}/{cidr}"
        
        if self.debug:
            print(f"\n    [DEBUG] Looking up network: {network_cidr}")
        
        # Try to find the interface by network CIDR
        if network_cidr in self.ip_to_interface: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_interface[network_cidr] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found interface by network CIDR: {result}")
            return result
        
        # Try to find by network address only
        if network_addr in self.ip_to_interface: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_interface[network_addr] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found interface by network address: {result}")
            return result
        
        # Try to find by IP address (in case it's a host route)
        if ip_addr in self.ip_to_interface: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_interface[ip_addr] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found interface by IP address: {result}")
            return result
        
        if self.debug:
            print(f"    [DEBUG] No interface found, trying address objects...")
        
        # FALLBACK: Try legacy address object lookup
        cidr_notation = f"{ip_addr}/{cidr}"
        
        # Try to find the address object by exact CIDR match
        if cidr_notation in self.ip_to_name: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_name[cidr_notation] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found address object by CIDR: {result}")
            return result
        
        # Try to find by IP only (for host addresses)
        if ip_addr in self.ip_to_name: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_name[ip_addr] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found address object by IP: {result}")
            return result
        
        # No match found - generate a name and warn the user
        self.unmatched_count += 1
        generated_name = f"Net_{ip_addr.replace('.', '_')}_{cidr}"
        print(f"    Warning: No interface or address object found for {cidr_notation}, using generated name: {generated_name}")
        
        return generated_name
    
    def _create_gateway_name(self, gateway_ip: str, properties: Dict) -> str:
        """
        Find the interface name for the gateway IP.
        
        This method looks up the gateway IP to find which interface network
        it belongs to, then returns that interface name.
        
        This allows FTD routes to reference interface names as the gateway object.
        
        Args:
            gateway_ip: Gateway IP address as string
            properties: Route properties dictionary (for comment field)
            
        Returns:
            String name of the interface where this gateway exists, or a generated name if no match
        """
        if self.debug:
            print(f"\n    [DEBUG] Looking up gateway: {gateway_ip}")
        
        # Try to find the interface by gateway IP
        # The gateway is typically an IP address on a directly connected network
        
        # First try exact IP match
        if gateway_ip in self.ip_to_interface: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_interface[gateway_ip] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found interface by IP: {result}")
            return result
        
        # Try with /32 CIDR notation
        gateway_cidr = f"{gateway_ip}/32"
        if gateway_cidr in self.ip_to_interface: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_interface[gateway_cidr] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found interface by CIDR: {result}")
            return result
        
        if self.debug:
            print(f"    [DEBUG] No interface found, trying address objects...")
        
        # FALLBACK: Try legacy address object lookup
        if gateway_cidr in self.ip_to_name: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_name[gateway_cidr] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found address object by CIDR: {result}")
            return result
        
        if gateway_ip in self.ip_to_name: # pyright: ignore[reportAttributeAccessIssue]
            result = self.ip_to_name[gateway_ip] # pyright: ignore[reportAttributeAccessIssue]
            if self.debug:
                print(f"    [DEBUG] Found address object by IP: {result}")
            return result
        
        # No match found - generate a name and warn the user
        self.unmatched_count += 1
        generated_name = f"Gateway_{gateway_ip.replace('.', '_')}"
        print(f"    Warning: No interface or address object found for gateway {gateway_ip}, using generated name: {generated_name}")
        
        return generated_name
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get conversion statistics for reporting.
        
        Returns:
            Dictionary with counts of converted, blackhole, and skipped routes
        """
        return {
            "total_routes": len(self.ftd_static_routes),
            "converted": self.converted_count,
            "blackhole_skipped": self.blackhole_count,
            "other_skipped": self.skipped_count,
            "unmatched_objects": self.unmatched_count
        }
    

    def get_missing_network_objects(self) -> List[Dict]:
        """
        Get list of network objects that need to be created for routes.
        
        Returns:
            List of network object dictionaries that should be created
        """
        return self.missing_network_objects


# =============================================================================
# TESTING CODE (for standalone testing of this module)
# =============================================================================

if __name__ == '__main__':
    """
    This code only runs when you execute this file directly.
    It's useful for testing the converter without running the main script.
    
    To test this module standalone:
        python route_converter.py
    """
    
    # Sample FortiGate configuration for testing
    test_config = {
        'router_static': [
            {
                64: {
                    'dst': ['10.0.20.0', '255.255.255.0'],
                    'gateway': '10.0.222.18',
                    'distance': 1,
                    'device': 'port2',
                    'comment': 'P5 Bear'
                }
            },
            {
                88: {
                    'dst': ['10.0.0.0', '255.252.0.0'],
                    'blackhole': 'enable',
                    'vrf': 0
                }
            },
            {
                118: {
                    'dst': ['10.0.22.0', '255.255.255.0'],
                    'gateway': '15.0.2.130',
                    'device': '20_Bull'
                }
            },
            {
                122: {
                    'dst': ['10.0.0.0', '255.0.0.0'],
                    'blackhole': 'enable',
                    'vrf': 0
                }
            }
        ]
    }
    
    # Create converter instance
    converter = RouteConverter(test_config)
    
    # Run conversion
    print("Testing Route Converter...")
    print("="*60)
    result = converter.convert()
    
    # Display results
    print("\nConversion Results:")
    print("="*60)
    import json
    print(json.dumps(result, indent=2))
    
    # Display statistics
    print("\nStatistics:")
    print("="*60)
    stats = converter.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")