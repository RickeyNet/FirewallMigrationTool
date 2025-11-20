#!/usr/bin/env python3
"""
FortiGate Service Port Object Converter Module
===============================================
This module handles the conversion of FortiGate service custom objects to 
Cisco FTD port objects (TCP and UDP).

CRITICAL RULE: TCP and UDP Must Be Separated
    - Cisco FTD does NOT allow combining TCP and UDP in the same port object
    - If a FortiGate service has both tcp-portrange AND udp-portrange,
      we create TWO separate FTD port objects:
      1. One TCP port object (name with _TCP suffix)
      2. One UDP port object (name with _UDP suffix)

WHAT THIS MODULE DOES:
    - Parses FortiGate 'firewall_service_custom' section from YAML
    - Extracts service objects (TCP ports, UDP ports, or both)
    - Splits services with both TCP and UDP into two separate objects
    - Converts to FTD 'tcpportobject' and 'udpportobject' formats
    - Handles various port formats (single, range, multiple ranges)

FORTIGATE YAML FORMAT:
    firewall_service_custom:
        - SERVICE_NAME:
            uuid: xxxxx
            protocol: IP  # Can be IP, TCP/UDP/SCTP
            tcp-portrange: 80  # TCP ports (optional)
            udp-portrange: 53  # UDP ports (optional)
            category: "Web Access"  # Optional
            color: 13  # Optional

PORT FORMATS:
    - Single port: tcp-portrange: 80
    - Port range: tcp-portrange: 49152-65535
    - Multiple ranges: tcp-portrange: 49152-65535:1024-2048

FTD JSON OUTPUT FORMAT:
    {
        "name": "HTTP_TCP",
        "isSystemDefined": false,
        "port": "80",
        "type": "tcpportobject"
    }
    {
        "name": "DNS_UDP",
        "isSystemDefined": false,
        "port": "53",
        "type": "udpportobject"
    }
"""

from typing import Dict, List, Any, Tuple


class ServiceConverter:
    """
    Converter class for transforming FortiGate service objects to FTD port objects.
    
    This class is responsible for:
    1. Reading the 'firewall_service_custom' section from FortiGate YAML
    2. Identifying TCP and UDP port ranges
    3. Splitting services with both TCP and UDP into separate objects
    4. Formatting ports for FTD API compatibility
    5. Handling special protocols (IP, ICMP, etc.)
    """
    
    def __init__(self, fortigate_config: Dict[str, Any]):
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'firewall_service_custom' key
        """
        # Store the entire FortiGate configuration
        self.fg_config = fortigate_config
        
        # This will store the converted FTD port objects
        # Both TCP and UDP objects will be stored here
        self.ftd_port_objects = []
        
        # Track statistics for reporting
        self.tcp_count = 0
        self.udp_count = 0
        self.split_count = 0  # Services that were split into TCP and UDP
        self.skipped_count = 0  # Services that couldn't be converted
    
    def convert(self) -> List[Dict]:
        """
        Main conversion method - converts all FortiGate services to FTD port objects.
        
        CONVERSION PROCESS:
        1. Extract the 'firewall_service_custom' list from FortiGate config
        2. Loop through each service entry
        3. Extract the service name and properties
        4. Check if service has TCP ports, UDP ports, or both
        5. Create separate FTD port objects for TCP and UDP
        6. Handle special protocols (IP, ICMP) - skip or note them
        7. Return the complete list of converted port objects
        
        Returns:
            List of dictionaries, each representing an FTD port object
        """
        # ====================================================================
        # STEP 1: Extract service objects from FortiGate configuration
        # ====================================================================
        services = self.fg_config.get('firewall_service_custom', [])
        
        if not services:
            print("Warning: No service objects found in FortiGate configuration")
            print("  Expected key: 'firewall_service_custom'")
            return []
        
        # This list will accumulate all converted port objects
        port_objects = []
        
        # ====================================================================
        # STEP 2: Process each FortiGate service object
        # ====================================================================
        for service_dict in services:
            # ================================================================
            # STEP 2A: Extract the service name and properties
            # ================================================================
            # Each service looks like: {'SERVICE_NAME': {properties}}
            service_name = list(service_dict.keys())[0]
            properties = service_dict[service_name]
            
            # ================================================================
            # STEP 2B: Check the protocol type
            # ================================================================
            protocol = properties.get('protocol', '').upper()
            
            # Skip non-TCP/UDP protocols (IP, ICMP, etc.)
            # These need special handling or may not be supported as port objects
            if protocol in ['IP', 'ICMP', 'ICMP6']:
                print(f"  Skipped: {service_name} (Protocol: {protocol} - not a port-based service)")
                self.skipped_count += 1
                continue
            
            # ================================================================
            # STEP 2C: Extract TCP and UDP port ranges
            # ================================================================
            tcp_ports = properties.get('tcp-portrange', None)
            udp_ports = properties.get('udp-portrange', None)
            
            # ================================================================
            # STEP 2D: Determine what port objects to create
            # ================================================================
            # CASE 1: Service has BOTH TCP and UDP ports
            if tcp_ports and udp_ports:
                # We MUST create TWO separate objects
                # FTD does not allow combining TCP and UDP in one object
                
                # Create TCP port object with _TCP suffix
                tcp_obj = self._create_port_object(
                    name=f"{service_name}_TCP",
                    port_value=tcp_ports,
                    protocol_type="tcp",
                    properties=properties
                )
                port_objects.append(tcp_obj)
                self.tcp_count += 1
                
                # Create UDP port object with _UDP suffix
                udp_obj = self._create_port_object(
                    name=f"{service_name}_UDP",
                    port_value=udp_ports,
                    protocol_type="udp",
                    properties=properties
                )
                port_objects.append(udp_obj)
                self.udp_count += 1
                
                self.split_count += 1
                print(f"  Split: {service_name} -> {service_name}_TCP and {service_name}_UDP")
            
            # CASE 2: Service has ONLY TCP ports
            elif tcp_ports:
                tcp_obj = self._create_port_object(
                    name=service_name,
                    port_value=tcp_ports,
                    protocol_type="tcp",
                    properties=properties
                )
                port_objects.append(tcp_obj)
                self.tcp_count += 1
                print(f"  Converted: {service_name} -> TCP port {tcp_ports}")
            
            # CASE 3: Service has ONLY UDP ports
            elif udp_ports:
                udp_obj = self._create_port_object(
                    name=service_name,
                    port_value=udp_ports,
                    protocol_type="udp",
                    properties=properties
                )
                port_objects.append(udp_obj)
                self.udp_count += 1
                print(f"  Converted: {service_name} -> UDP port {udp_ports}")
            
            # CASE 4: Service has neither TCP nor UDP ports
            else:
                print(f"  Skipped: {service_name} (No TCP or UDP ports defined)")
                self.skipped_count += 1
        
        # ====================================================================
        # STEP 3: Store results and return
        # ====================================================================
        self.ftd_port_objects = port_objects
        return port_objects
    
    def _create_port_object(self, name: str, port_value: Any, 
                           protocol_type: str, properties: Dict) -> Dict:
        """
        Create a single FTD port object from FortiGate service data.
        
        This method constructs the JSON structure that FTD expects for port objects.
        
        Args:
            name: Name for the port object (may include _TCP or _UDP suffix)
            port_value: Port number or range (e.g., "80", "1024-2048", "80:443")
            protocol_type: Either "tcp" or "udp"
            properties: Original FortiGate service properties (for comments, etc.)
            
        Returns:
            Dictionary representing an FTD port object
        """
        # ====================================================================
        # STEP 1: Format the port value for FTD
        # ====================================================================
        # FortiGate can use colons to separate multiple ranges: "80:443:8080"
        # FTD expects comma-separated ranges: "80,443,8080"
        # Also handle the case where it's already an integer
        if isinstance(port_value, int):
            formatted_port = str(port_value)
        else:
            # Convert port_value to string and replace colons with commas
            # Example: "49152-65535:1024-2048" becomes "49152-65535,1024-2048"
            formatted_port = str(port_value).replace(':', ',')
        
        # ====================================================================
        # STEP 2: Determine the FTD type
        # ====================================================================
        # FTD uses different types for TCP vs UDP port objects
        if protocol_type.lower() == "tcp":
            ftd_type = "tcpportobject"
        elif protocol_type.lower() == "udp":
            ftd_type = "udpportobject"
        else:
            # Fallback (shouldn't happen)
            ftd_type = "tcpportobject"
        
        # ====================================================================
        # STEP 3: Build the FTD port object structure
        # ====================================================================
        # This matches the format that FTD FDM API expects
        port_object = {
            "name": name,                              # Port object name
            "isSystemDefined": False,                  # Custom objects are not system-defined
            "port": formatted_port,                    # Port number or range
            "type": ftd_type                           # tcpportobject or udpportobject
        }
        
        # Optional: Add description if FortiGate had a comment or category
        # Uncomment the following lines if you want to include descriptions
        # description_parts = []
        # if 'comment' in properties:
        #     description_parts.append(properties['comment'])
        # if 'category' in properties:
        #     description_parts.append(f"Category: {properties['category']}")
        # if description_parts:
        #     port_object['description'] = ' | '.join(description_parts)
        
        return port_object
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get conversion statistics for reporting.
        
        Returns:
            Dictionary with counts of TCP, UDP, split, and skipped services
        """
        return {
            "total_objects": len(self.ftd_port_objects),
            "tcp_objects": self.tcp_count,
            "udp_objects": self.udp_count,
            "split_services": self.split_count,
            "skipped_services": self.skipped_count
        }


# =============================================================================
# TESTING CODE (for standalone testing of this module)
# =============================================================================

if __name__ == '__main__':
    """
    This code only runs when you execute this file directly.
    It's useful for testing the converter without running the main script.
    
    To test this module standalone:
        python service_converter.py
    """
    
    # Sample FortiGate configuration for testing
    test_config = {
        'firewall_service_custom': [
            {
                'ALL': {
                    'uuid': '11111111-2222-3333-8888-000000000014',
                    'category': 'General',
                    'protocol': 'IP',
                    'color': 1
                }
            },
            {
                'HTTP': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'category': 'Web Access',
                    'color': 13,
                    'tcp-portrange': 80
                }
            },
            {
                'DNS': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'category': 'Network Services',
                    'color': 13,
                    'tcp-portrange': 53,
                    'udp-portrange': 53
                }
            },
            {
                'HTTPS': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'category': 'Web Access',
                    'color': 13,
                    'tcp-portrange': 443,
                    'udp-portrange': 443
                }
            },
            {
                'Big Ports 2008': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'tcp-portrange': '49152-65535:49152-65535'
                }
            }
        ]
    }
    
    # Create converter instance
    converter = ServiceConverter(test_config)
    
    # Run conversion
    print("Testing Service Converter...")
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