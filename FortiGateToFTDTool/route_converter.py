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