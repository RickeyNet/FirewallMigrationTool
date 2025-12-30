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
from typing import Dict, List, Any

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
    
    def __init__(self, fortigate_config: Dict[str, Any], network_objects: List[Dict] = None): # pyright: ignore[reportArgumentType]
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'router_static' key with route data
            network_objects: List of already-converted FTD network objects
                           Used to match route destinations/gateways to existing objects
        """
        # Store the entire FortiGate configuration
        self.fg_config = fortigate_config
        
        # Store the list of network objects for lookup
        self.network_objects = network_objects or []
        
        # Build a lookup dictionary: IP/CIDR -> object name
        # This allows us to quickly find the object name for a given IP
        self.ip_to_name = {}
        self._build_ip_lookup()
        
        # This will store the converted FTD static routes
        self.ftd_static_routes = []
        
        # Track statistics
        self.converted_count = 0
        self.blackhole_count = 0
        self.skipped_count = 0
        self.unmatched_count = 0  # Track routes with no matching address object

    def _build_ip_lookup(self):
        """
        Build a lookup dictionary mapping IP addresses/CIDRs to object names.
        
        This allows us to find the correct address object name when we have
        a destination or gateway IP from the route.
        
        The lookup handles:
        - Exact IP matches (e.g., 10.0.20.5 -> "Server1")
        - Network matches (e.g., 10.0.20.0/24 -> "Bull_net")
        - Gateway IPs that are hosts (/32)
        """
        for obj in self.network_objects:
            # Get the object name
            name = obj.get('name', '')
            
            # Get the value (IP or network in CIDR format)
            value = obj.get('value', '')
            
            if value and name:
                # Store in lookup: "10.0.20.0/24" -> "Bull_net"
                self.ip_to_name[value] = name
                
                # Also store without CIDR for host addresses
                # "10.0.20.5/32" -> also indexed as "10.0.20.5"
                if '/' in value:
                    ip_only = value.split('/')[0]
                    # Only add if not already present (prefer the CIDR version)
                    if ip_only not in self.ip_to_name:
                        self.ip_to_name[ip_only] = name
    
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
            dst_name = self._create_network_name(dst)
            
            # ================================================================
            # STEP 2D: Extract gateway
            # ================================================================
            gateway_ip = properties.get('gateway', None)
            if not gateway_ip:
                print(f"  Skipped: Route [{route_id}] - No gateway specified")
                self.skipped_count += 1
                continue
            
            # Create a name for the gateway object
            gateway_name = self._create_gateway_name(gateway_ip, properties)
            
            # ================================================================
            # STEP 2E: Extract interface/device
            # ================================================================
            interface_name = properties.get('device', 'unknown')
            
            # ================================================================
            # STEP 2F: Extract metric/distance
            # ================================================================
            metric = properties.get('distance', 1)  # Default to 1 if not specified
            
            # ================================================================
            # STEP 2G: Extract comment for route name
            # ================================================================
            comment = properties.get('comment', '')
            if comment:
                route_name = comment
            else:
                route_name = f"Route_{route_id}_{dst_name}"
            
            # Sanitize all names to replace spaces with underscores
            sanitized_route_name = sanitize_name(route_name)
            sanitized_interface_name = sanitize_name(interface_name)
            sanitized_dst_name = sanitize_name(dst_name)
            sanitized_gateway_name = sanitize_name(gateway_name)
            
            # ================================================================
            # STEP 2H: Create the FTD static route entry structure
            # ================================================================
            ftd_route = {
                "name": sanitized_route_name,
                "iface": {
                    "name": sanitized_interface_name,
                    "type": "physicalinterface"  # Assume physical, could also be subinterface
                },
                "networks": [
                    {
                        "name": sanitized_dst_name,
                        "type": "networkobject"
                    }
                ],
                "gateway": {
                    "name": sanitized_gateway_name,
                    "type": "networkobject"
                },
                "metricValue": metric,
                "ipType": "IPv4",  # Assume IPv4 for now
                "type": "staticrouteentry"
            }
            
            # Add the converted route to our result list
            static_routes.append(ftd_route)
            self.converted_count += 1
            
            # ================================================================
            # STEP 2I: Print conversion details for user feedback
            # ================================================================
            if route_name != sanitized_route_name:
                print(f"  Converted: [{route_id}] {route_name} -> {sanitized_route_name}")
            else:
                print(f"  Converted: [{route_id}] {sanitized_route_name}")
            print(f"    Destination: {sanitized_dst_name} ({dst_network})")
            print(f"    Gateway: {sanitized_gateway_name}")
            print(f"    Interface: {sanitized_interface_name}")
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
        Find the actual address object name for the destination network.
        
        This method looks up the destination IP/network in our address objects
        to find the real object name that exists in FTD.
        
        Args:
            dst: List containing [IP_address, netmask]
            
        Returns:
            String name of the matching address object, or a generated name if no match
        """
        if len(dst) < 2:
            return "Unknown_Network"
        
        ip_addr = str(dst[0])
        netmask = str(dst[1])
        cidr = self._netmask_to_cidr(netmask)
        
        # Check if this is a default route (0.0.0.0/0)
        if ip_addr == "0.0.0.0" and cidr == 0:
            return "any-ipv4"
        
        # Format as CIDR for lookup
        cidr_notation = f"{ip_addr}/{cidr}"
        
        # Try to find the address object by exact CIDR match
        if cidr_notation in self.ip_to_name:
            return self.ip_to_name[cidr_notation]
        
        # Try to find by IP only (for host addresses)
        if ip_addr in self.ip_to_name:
            return self.ip_to_name[ip_addr]
        
        # No match found - generate a name and warn the user
        self.unmatched_count += 1
        generated_name = f"Net_{ip_addr.replace('.', '_')}_{cidr}"
        print(f"    Warning: No address object found for {cidr_notation}, using generated name: {generated_name}")
        
        return generated_name
    
    def _create_gateway_name(self, gateway_ip: str, properties: Dict) -> str:
        """
        Find the actual address object name for the gateway IP.
        
        This method looks up the gateway IP in our address objects
        to find the real object name that exists in FTD.
        
        Args:
            gateway_ip: Gateway IP address as string
            properties: Route properties dictionary (for comment field)
            
        Returns:
            String name of the matching address object, or a generated name if no match
        """
        # Try to find the address object by IP
        # Gateways are usually host addresses (/32)
        
        # First try with /32 CIDR notation
        gateway_cidr = f"{gateway_ip}/32"
        if gateway_cidr in self.ip_to_name:
            return self.ip_to_name[gateway_cidr]
        
        # Try without CIDR
        if gateway_ip in self.ip_to_name:
            return self.ip_to_name[gateway_ip]
        
        # No match found - generate a name and warn the user
        self.unmatched_count += 1
        generated_name = f"Gateway_{gateway_ip.replace('.', '_')}"
        print(f"    Warning: No address object found for gateway {gateway_ip}, using generated name: {generated_name}")
        
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