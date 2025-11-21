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

from typing import Dict, List, Any, Tuple


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

    def __init__(self, fortigate_config: Dict[str, Any]):
        """
        Initialize the converter with FortiGate configuration data.

        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                                Expected to have a 'router_static' key with route data
        """
        # Store the entire FortiGate configuration
        self.fg_config = fortigate_config

        # This will store the converted FTD static routes
        self.ftd_static_routes = []

        # Track statistics
        self.converted_count = 0
        self.blackhole_count = 0
        self.skipped_count = 0

    def conver(self) -> list[Dict]:
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

        returns:
            List of dictionaries, each representing an FTD static route entry
        """
        # ====================================================================
        # STEP 1: Extract static routes from FortiGate configuration
        # ====================================================================
        routes = self.fg_config.get('router_static', [])

        if not routes:
            print("Warning: No static routes found in FortiGate configuration")
            print(" Expected key: 'router_static'")
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
            
            # ================================================================
            # STEP 2H: Create the FTD static route entry structure
            # ================================================================
            ftd_route = {
                "name": route_name,
                "iface": {
                    "name": interface_name,
                    "type": "physicalinterface"  # Assume physical, could also be subinterface
                },
                "networks": [
                    {
                        "name": dst_name,
                        "type": "networkobject"
                    }
                ],
                "gateway": {
                    "name": gateway_name,
                    "type": "networkobject"
                },
                "metricValue": metric,
                "ipType": "IPv4",  # Assume IPv4 for now
                "type": "staticrouteentry"
            }
            
            