#!/usr/bin/env python3
"""
FortiGate Service Group Converter Module
=========================================
This module handles the conversion of FortiGate service groups to 
Cisco FTD port object groups.

IMPORTANT CONSIDERATION:
    - When a FortiGate service group references a service that was split
      into TCP and UDP objects (like "DNS" -> "DNS_TCP" and "DNS_UDP"),
      the group must include BOTH the TCP and UDP versions
    - This module assumes all member names are provided as-is from FortiGate
    - The main script should handle resolving split services

WHAT THIS MODULE DOES:
    - Parses FortiGate 'firewall_service_group' section from YAML
    - Extracts group name and member services
    - Converts to FTD 'portobjectgroup' format
    - Handles both single members and lists of members

FORTIGATE YAML FORMAT:
    firewall_service_group:
        - GROUP_NAME:
            uuid: xxxxx
            member: ["HTTP", "HTTPS", "DNS"]  # List of service names
            color: 13  # Optional
        - ANOTHER_GROUP:
            member: "single_service"  # Single member (string, not list)

FTD JSON OUTPUT FORMAT:
    {
        "name": "Web_Access",
        "isSystemDefined": false,
        "objects": [
            {"name": "HTTP_TCP", "type": "tcpportobject"},
            {"name": "HTTPS_TCP", "type": "tcpportobject"},
            {"name": "DNS_TCP", "type": "tcpportobject"},
            {"name": "DNS_UDP", "type": "udpportobject"}
        ],
        "type": "portobjectgroup"
    }

NOTE ON MEMBER TYPES:
    - We don't know in advance if a member is TCP or UDP
    - We include the member name as-is from FortiGate
    - The type field is set generically (could be refined in post-processing)
"""

import re
from typing import Dict, List, Any, Set

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
    # Replace any character that isn't aplhanumeric or underscore with underscore
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(name))




class ServiceGroupConverter:
    """
    Converter class for transforming FortiGate service groups to FTD port groups.
    
    This class is responsible for:
    1. Reading the 'firewall_service_group' section from FortiGate YAML
    2. Extracting group names and their member services
    3. Converting to FTD's portobjectgroup format
    4. Handling edge cases (empty groups, single vs multiple members)
    5. Tracking which services need to be expanded (if they were split)
    """
    
    def __init__(self, fortigate_config: Dict[str, Any], 
                 split_services: Set[str] = None): # pyright: ignore[reportArgumentType]
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'firewall_service_group' key
            split_services: Set of service names that were split into TCP and UDP
                          (e.g., {"DNS", "HTTPS"} if these had both TCP and UDP)
        """
        # Store the entire FortiGate configuration
        self.fg_config = fortigate_config
        
        # Store the set of services that were split into TCP and UDP
        # This helps us know which members need to be expanded
        self.split_services = split_services or set()
        
        # This will store the converted FTD port groups
        self.ftd_port_groups = []
    
    def convert(self) -> List[Dict]:
        """
        Main conversion method - converts all FortiGate service groups to FTD format.
        
        CONVERSION PROCESS:
        1. Extract the 'firewall_service_group' list from FortiGate config
        2. Loop through each group entry
        3. Extract the group name (the dictionary key)
        4. Extract the group properties (uuid, member, color, etc.)
        5. Normalize the 'member' field to always be a list
        6. Expand members that were split (add both _TCP and _UDP versions)
        7. Create FTD portobjectgroup structure
        8. Return the complete list of converted groups
        
        Returns:
            List of dictionaries, each representing an FTD port object group
        """
        # ====================================================================
        # STEP 1: Extract service groups from FortiGate configuration
        # ====================================================================
        service_groups = self.fg_config.get('firewall_service_group', [])
        
        if not service_groups:
            print("Warning: No service groups found in FortiGate configuration")
            print("  Expected key: 'firewall_service_group'")
            return []
        
        # This list will accumulate all converted groups
        port_groups = []
        
        # ====================================================================
        # STEP 2: Process each FortiGate service group
        # ====================================================================
        for group_dict in service_groups:
            # ================================================================
            # STEP 2A: Extract the group name
            # ================================================================
            # The group name is the only key in the dictionary
            # Example: {'Email Access': {uuid: ..., member: ...}}
            group_name = list(group_dict.keys())[0]
            
            # ================================================================
            # STEP 2B: Extract the group properties
            # ================================================================
            properties = group_dict[group_name]
            
            # ================================================================
            # STEP 2C: Extract and normalize the member list
            # ================================================================
            # FortiGate can store members as either:
            # 1. A single string: member: "service_name"
            # 2. A list of strings: member: ["svc1", "svc2", "svc3"]
            # We need to normalize this to ALWAYS be a list
            
            members_raw = properties.get('member', [])
            
            # Normalize to list format
            if isinstance(members_raw, str):
                # Single string -> list with one item
                members_list = [members_raw]
            elif isinstance(members_raw, list):
                # Already a list
                members_list = members_raw
            else:
                # Unexpected format
                print(f"  Warning: Group '{group_name}' has unexpected member format")
                members_list = []
            
            # ================================================================
            # STEP 2D: Expand members that were split into TCP and UDP
            # ================================================================
            # If a member service was split (had both TCP and UDP ports),
            # we need to include BOTH versions in the group
            expanded_members = []
            
            for member_name in members_list:
                # Sanitize the member name first
                sanitized_member = sanitize_name(member_name)
                
                if member_name in self.split_services:
                    # This service was split, so add both TCP and UDP versions
                    expanded_members.append(f"{sanitized_member}_TCP")
                    expanded_members.append(f"{sanitized_member}_UDP")
                    print(f"    Expanded: {member_name} -> {sanitized_member}_TCP, {sanitized_member}_UDP")
                else:
                    # This service was not split, use sanitized name
                    expanded_members.append(sanitized_member)
            
            # ================================================================
            # STEP 2E: Convert members to FTD object format
            # ================================================================
            # FTD expects each member to be an object with 'name' and 'type'
            # IMPORTANT: FTD only needs the NAME - it will look up the object by name
            # Do NOT include UUIDs, IDs, or other fields - only name and type
            # FortiGate: ["HTTP", "HTTPS"]
            # FTD:       [{"name": "HTTP", "type": "tcpportobject"},
            #             {"name": "HTTPS", "type": "tcpportobject"}]
            
            # Note: We don't know the exact type (tcp vs udp) without looking up
            # each service, so we use a generic approach or set a placeholder
            ftd_members = []
            for member_name in expanded_members:
                # Determine type based on naming convention
                # If name ends with _TCP or _UDP, we can infer the type
                if member_name.endswith('_TCP'):
                    member_type = "tcpportobject"
                elif member_name.endswith('_UDP'):
                    member_type = "udpportobject"
                else:
                    # Unknown - could be either, default to tcpportobject
                    # In a real implementation, you might look this up
                    member_type = "tcpportobject"
                
                # Create member object with ONLY name and type
                # FTD will use the name to find the actual object in its database
                member_obj = {
                    "name": member_name,
                    "type": member_type
                }
                # DO NOT add: id, uuid, version, or any other fields
                # FTD resolves the reference by name only
                ftd_members.append(member_obj)
            
            # ================================================================
            # STEP 2F: Create the FTD port group structure
            # ================================================================
            # This is the final format that FTD FDM API expects
            # Sanitize the group name
            sanitized_group_name = sanitize_name(group_name)
            
            ftd_group = {
                "name": sanitized_group_name,                    # Group name from FortiGate
                "isSystemDefined": False,              # Custom groups are not system-defined
                "objects": ftd_members,                # List of member port objects
                "type": "portobjectgroup"              # FTD type for port groups
            }
            
            # Add the converted group to our result list
            port_groups.append(ftd_group)
            
            # ================================================================
            # STEP 2G: Print conversion details for user feedback
            # ================================================================
            member_count = len(ftd_members)
            if group_name != sanitized_group_name:
                print(f"  Converted: {group_name} -> {sanitized_group_name} ({member_count} members)")
            else:
                print(f"  Converted: {sanitized_group_name} ({member_count} members)")
        
        # ====================================================================
        # STEP 3: Store results and return
        # ====================================================================
        self.ftd_port_groups = port_groups
        return port_groups
    
    def set_split_services(self, split_services: Set[str]):
        """
        Update the set of services that were split into TCP and UDP.
        
        This should be called by the main script after converting service objects,
        so the group converter knows which members need to be expanded.
        
        Args:
            split_services: Set of service names that have both TCP and UDP versions
        """
        self.split_services = split_services
    
    def get_group_count(self) -> int:
        """
        Get the number of service groups that were converted.
        
        Returns:
            Integer count of converted groups
        """
        return len(self.ftd_port_groups)


# =============================================================================
# TESTING CODE (for standalone testing of this module)
# =============================================================================

if __name__ == '__main__':
    """
    This code only runs when you execute this file directly.
    It's useful for testing the converter without running the main script.
    
    To test this module standalone:
        python service_group_converter.py
    """
    
    # Sample FortiGate configuration for testing
    test_config = {
        'firewall_service_group': [
            {
                'Email Access': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'member': ["DNS", "IMAP", "IMAPS", "POP3", "POP3S", "SMTP"]
                }
            },
            {
                'Web Access': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'member': ["DNS", "HTTP", "HTTPS"]
                }
            },
            {
                'Windows AD': {
                    'uuid': '11111111-2222-3333-8888-000000000013',
                    'member': ["DNS", "Kerberos", "SAMBA", "SMB"]
                }
            }
        ]
    }
    
    # Simulate that DNS and HTTPS were split into TCP and UDP
    split_services = {"DNS", "HTTPS"}
    
    # Create converter instance
    converter = ServiceGroupConverter(test_config, split_services)
    
    # Run conversion
    print("Testing Service Group Converter...")
    print("="*60)
    result = converter.convert()
    
    # Display results
    print("\nConversion Results:")
    print("="*60)
    import json
    print(json.dumps(result, indent=2))
    print("\n" + "="*60)
    print(f"Total groups converted: {len(result)}")