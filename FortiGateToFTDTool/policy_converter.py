#!/usr/bin/env python3
"""
FortiGate Firewall Policy Converter Module
===========================================
This module handles the conversion of FortiGate firewall policies to 
Cisco FTD access rules.

WHAT THIS MODULE DOES:
    - Parses FortiGate 'firewall_policy' section from YAML
    - Extracts policy rules (source, destination, service, action)
    - Maps FortiGate actions to FTD actions (accept -> PERMIT, deny -> DENY)
    - Converts to FTD 'accessrule' format
    - Handles interfaces as security zones
    - Normalizes single values and lists

FORTIGATE YAML FORMAT:
    firewall_policy:
        - POLICY_ID:
            name: "Policy Name"
            uuid: xxxxx
            srcintf: "interface_name" or ["intf1", "intf2"]
            dstintf: "interface_name" or ["intf1", "intf2"]
            action: accept or deny
            srcaddr: "address_name" or ["addr1", "addr2"]
            dstaddr: "address_name" or ["addr1", "addr2"]
            schedule: "always"
            service: "service_name" or ["svc1", "svc2"]

FTD JSON OUTPUT FORMAT:
    {
        "name": "Policy Name",
        "ruleId": 1,
        "sourceZones": [
            {"name": "inside", "type": "securityzone"}
        ],
        "destinationZones": [
            {"name": "outside", "type": "securityzone"}
        ],
        "sourceNetworks": [
            {"name": "source_address", "type": "networkobject"}
        ],
        "destinationNetworks": [
            {"name": "dest_address", "type": "networkobject"}
        ],
        "destinationPorts": [
            {"name": "service_name", "type": "tcpportobject"}
        ],
        "ruleAction": "PERMIT",
        "eventLogAction": "LOG_BOTH",
        "logFiles": false,
        "type": "accessrule"
    }

IMPORTANT NOTES:
    - FortiGate 'srcintf' and 'dstintf' map to FTD 'sourceZones' and 'destinationZones'
    - FortiGate action 'accept' -> FTD 'PERMIT'
    - FortiGate action 'deny' -> FTD 'DENY'
    - Special handling for 'any' and 'all' keywords
    - ruleId is assigned sequentially starting from 1
"""

import re
from typing import Dict, List, Any, Set

def sanitize_name(name: str) -> str:
    """
    Sanitize object names for FTD compatibility.
    
    FTD only allows alphanumeric characters and underscores in object names.
    This function replaces any other character with an underscore.
    
    Args:
        name: Original object name (may contain spaces, dashes, etc.)
        
    Returns:
        Sanitized name with only alphanumeric characters and underscores
    """
    if name is None:
        return ""
    # Replace any character that isn't alphanumeric or underscore with underscore
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(name)).upper()




class PolicyConverter:
    """
    Converter class for transforming FortiGate firewall policies to FTD access rules.
    
    This class is responsible for:
    1. Reading the 'firewall_policy' section from FortiGate YAML
    2. Extracting policy information (source, dest, service, action)
    3. Mapping interfaces to security zones
    4. Mapping actions (accept/deny to PERMIT/DENY)
    5. Normalizing lists vs single values
    6. Converting to FTD's accessrule format
    """
    
    def __init__(self, fortigate_config: Dict[str, Any], 
                 split_services: Set[str] = None): # pyright: ignore[reportArgumentType]
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'firewall_policy' key
            split_services: Set of service names that were split into TCP and UDP
                          (e.g., {"DNS", "HTTPS"} if these had both TCP and UDP)
        """
        # Store the entire FortiGate configuration
        self.fg_config = fortigate_config
        
        # Store the set of services that were split into TCP and UDP
        self.split_services = split_services or set()
        
        # This will store the converted FTD access rules
        self.ftd_access_rules = []
        
        # Track statistics
        self.permit_count = 0
        self.deny_count = 0
    
    def convert(self) -> List[Dict]:
        """
        Main conversion method - converts all FortiGate policies to FTD access rules.
        
        CONVERSION PROCESS:
        1. Extract the 'firewall_policy' list from FortiGate config
        2. Loop through each policy entry
        3. Extract the policy ID and properties
        4. Normalize all fields (convert single values to lists where needed)
        5. Map FortiGate action to FTD action
        6. Create FTD accessrule structure
        7. Assign sequential ruleId
        8. Return the complete list of converted rules
        
        Returns:
            List of dictionaries, each representing an FTD access rule
        """
        # ====================================================================
        # STEP 1: Extract firewall policies from FortiGate configuration
        # ====================================================================
        policies = self.fg_config.get('firewall_policy', [])
        
        if not policies:
            print("Warning: No firewall policies found in FortiGate configuration")
            print("  Expected key: 'firewall_policy'")
            return []
        
        # This list will accumulate all converted access rules
        access_rules = []
        
        # ruleId counter - FTD assigns sequential IDs to rules
        rule_id_counter = 1
        
        # ====================================================================
        # STEP 2: Process each FortiGate firewall policy
        # ====================================================================
        for policy_dict in policies:
            # ================================================================
            # STEP 2A: Extract the policy ID and properties
            # ================================================================
            # Each policy looks like: {161: {name: ..., action: ...}}
            # The policy ID is the key (e.g., 161)
            policy_id = list(policy_dict.keys())[0]
            properties = policy_dict[policy_id]
            
            # ================================================================
            # STEP 2B: Extract basic policy information
            # ================================================================
            policy_name = properties.get('name', f'Policy_{policy_id}')
            action = properties.get('action', 'deny')
            
            # ================================================================
            # STEP 2C: Map FortiGate action to FTD action
            # ================================================================
            ftd_action = self._map_action(action)
            
            # Track statistics
            if ftd_action == 'PERMIT':
                self.permit_count += 1
            else:
                self.deny_count += 1
            
            # ================================================================
            # STEP 2D: Extract and normalize source/destination interfaces
            # ================================================================
            # FortiGate interfaces map to FTD security zones
            source_zones = self._normalize_to_list(properties.get('srcintf', []))
            dest_zones = self._normalize_to_list(properties.get('dstintf', []))
            
            # Convert to FTD zone format
            ftd_source_zones = self._create_zone_objects(source_zones)
            ftd_dest_zones = self._create_zone_objects(dest_zones)
            
            # ================================================================
            # STEP 2E: Extract and normalize source/destination addresses
            # ================================================================
            source_addrs = self._normalize_to_list(properties.get('srcaddr', []))
            dest_addrs = self._normalize_to_list(properties.get('dstaddr', []))
            
            # Convert to FTD network object format
            ftd_source_networks = self._create_network_objects(source_addrs)
            ftd_dest_networks = self._create_network_objects(dest_addrs)
            
            # ================================================================
            # STEP 2F: Extract and normalize services
            # ================================================================
            services = self._normalize_to_list(properties.get('service', []))
            
            # Expand services that were split into TCP and UDP
            expanded_services = self._expand_services(services)
            
            # Convert to FTD port object format
            ftd_dest_ports = self._create_port_objects(expanded_services)
            
            # ================================================================
            # STEP 2G: Create the FTD access rule structure
            # ================================================================
            # Sanitize the policy name to replace spaces with underscores
            sanitized_policy_name = sanitize_name(policy_name)
            
            ftd_rule = {
                "name": sanitized_policy_name,
                "ruleId": rule_id_counter,
                "sourceZones": ftd_source_zones,
                "destinationZones": ftd_dest_zones,
                "sourceNetworks": ftd_source_networks,
                "destinationNetworks": ftd_dest_networks,
                "destinationPorts": ftd_dest_ports,
                "ruleAction": ftd_action,
                "eventLogAction": "LOG_BOTH",  # Can be customized
                "logFiles": False,
                "type": "accessrule"
            }
            
            # Add the converted rule to our result list
            access_rules.append(ftd_rule)
            
            # Increment rule ID for next rule
            rule_id_counter += 1
            
            # ================================================================
            # STEP 2H: Print conversion details for user feedback
            # ================================================================
            src_count = len(ftd_source_networks)
            dst_count = len(ftd_dest_networks)
            svc_count = len(ftd_dest_ports)
            if policy_name != sanitized_policy_name:
                print(f"  Converted: [{policy_id}] {policy_name} -> {sanitized_policy_name} [{ftd_action}] "
                      f"(Src:{src_count} Dst:{dst_count} Svc:{svc_count})")
            else:
                print(f"  Converted: [{policy_id}] {sanitized_policy_name} -> {ftd_action} "
                      f"(Src:{src_count} Dst:{dst_count} Svc:{svc_count})")
        
        # ====================================================================
        # STEP 3: Store results and return
        # ====================================================================
        self.ftd_access_rules = access_rules
        return access_rules
    
    def _map_action(self, fg_action: str) -> str:
        """
        Map FortiGate action to FTD action.
        
        FortiGate actions:
        - accept, allow -> FTD PERMIT
        - deny, reject -> FTD DENY
        
        Args:
            fg_action: FortiGate action string
            
        Returns:
            FTD action string ('PERMIT' or 'DENY')
        """
        action_lower = fg_action.lower()
        
        if action_lower in ['accept', 'allow']:
            return 'PERMIT'
        elif action_lower in ['deny', 'reject']:
            return 'DENY'
        else:
            # Default to DENY for safety
            print(f"    Warning: Unknown action '{fg_action}', defaulting to DENY")
            return 'DENY'
    
    def _normalize_to_list(self, value: Any) -> List[str]:
        """
        Normalize a value to always be a list.
        
        FortiGate can store values as:
        - Single string: "value"
        - List: ["value1", "value2"]
        - None/empty
        
        This method normalizes all to a list format.
        
        Args:
            value: The value to normalize (string, list, or None)
            
        Returns:
            List of strings
        """
        if value is None or value == '':
            return []
        elif isinstance(value, str):
            return [value]
        elif isinstance(value, list):
            return value
        else:
            return [str(value)]
    
    def _create_zone_objects(self, zone_names: List[str]) -> List[Dict]:
        """
        Create FTD security zone objects from FortiGate interface names.
        
        Args:
            zone_names: List of FortiGate interface names
            
        Returns:
            List of FTD zone object dictionaries
        """
        zone_objects = []
        
        for zone_name in zone_names:
            # Skip 'any' as it means no zone restriction
            if zone_name.lower() == 'any':
                continue
            
            zone_obj = {
                "name": sanitize_name(zone_name),
                "type": "securityzone"
            }
            zone_objects.append(zone_obj)
        
        return zone_objects
    
    def _create_network_objects(self, addr_names: List[str]) -> List[Dict]:
        """
        Create FTD network object references from FortiGate address names.
        
        Args:
            addr_names: List of FortiGate address object names
            
        Returns:
            List of FTD network object reference dictionaries
        """
        network_objects = []
        
        for addr_name in addr_names:
            # Skip 'all' and 'any' as they mean no address restriction
            if addr_name.lower() in ['all', 'any']:
                continue
            
            # Determine if this is likely a group or single object
            # In a real implementation, you might look this up
            # For now, we'll assume it could be either
            network_obj = {
                "name": sanitize_name(addr_name),
                "type": "networkobject"  # Could also be "networkobjectgroup"
            }
            network_objects.append(network_obj)
        
        return network_objects
    
    def _expand_services(self, services: List[str]) -> List[str]:
        """
        Expand services that were split into TCP and UDP versions.
        
        If a service in the list was split (has both TCP and UDP ports),
        replace it with both the _TCP and _UDP versions.
        
        Args:
            services: List of FortiGate service names
            
        Returns:
            List of expanded service names
        """
        expanded = []
        
        for service in services:
            # Skip 'ALL' and 'any' as they mean no service restriction
            if service.upper() in ['ALL', 'ANY']:
                continue
            
            # Sanitize the service name
            sanitized_service = sanitize_name(service)
            
            if service in self.split_services:
                # This service was split, add both versions with sanitized name
                expanded.append(f"{sanitized_service}_TCP")
                expanded.append(f"{sanitized_service}_UDP")
            else:
                # Service was not split, use sanitized name
                expanded.append(sanitized_service)
        
        return expanded
    
    def _create_port_objects(self, service_names: List[str]) -> List[Dict]:
        """
        Create FTD port object references from FortiGate service names.
        
        Args:
            service_names: List of FortiGate service names (possibly expanded)
            
        Returns:
            List of FTD port object reference dictionaries
        """
        port_objects = []
        
        for service_name in service_names:
            # Determine type based on naming convention
            if service_name.endswith('_TCP'):
                port_type = "tcpportobject"
            elif service_name.endswith('_UDP'):
                port_type = "udpportobject"
            else:
                # Unknown - could be either or a group, default to tcpportobject
                port_type = "tcpportobject"
            
            port_obj = {
                "name": service_name,
                "type": port_type
            }
            port_objects.append(port_obj)
        
        return port_objects
    
    def set_split_services(self, split_services: Set[str]):
        """
        Update the set of services that were split into TCP and UDP.
        
        Args:
            split_services: Set of service names that have both TCP and UDP versions
        """
        self.split_services = split_services
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get conversion statistics for reporting.
        
        Returns:
            Dictionary with counts of rules and actions
        """
        return {
            "total_rules": len(self.ftd_access_rules),
            "permit_rules": self.permit_count,
            "deny_rules": self.deny_count
        }


# =============================================================================
# TESTING CODE (for standalone testing of this module)
# =============================================================================

if __name__ == '__main__':
    """
    This code only runs when you execute this file directly.
    It's useful for testing the converter without running the main script.
    
    To test this module standalone:
        python policy_converter.py
    """
    
    # Sample FortiGate configuration for testing
    test_config = {
        'firewall_policy': [
            {
                161: {
                    'name': '3120_EAST_FW_TO_ALL',
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'srcintf': 'any',
                    'dstintf': 'any',
                    'action': 'accept',
                    'srcaddr': ['3120_EAST_MASTER', '3120_EAST_SLAVE'],
                    'dstaddr': 'all',
                    'schedule': 'always',
                    'service': 'ALL'
                }
            },
            {
                466: {
                    'name': 'BGP2',
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'srcintf': 'lock',
                    'dstintf': 'open',
                    'action': 'accept',
                    'srcaddr': 'Lock_add_2',
                    'dstaddr': 'open_less_1',
                    'schedule': 'always',
                    'service': 'ALL'
                }
            }
        ]
    }
    
    # Simulate that DNS and HTTPS were split
    split_services = {"DNS", "HTTPS"}
    
    # Create converter instance
    converter = PolicyConverter(test_config, split_services)
    
    # Run conversion
    print("Testing Policy Converter...")
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