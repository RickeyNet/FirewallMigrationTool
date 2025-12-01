#!/usr/bin/env python3
"""
FortiGate Address Group Converter Module
=========================================
This module handles the conversion of FortiGate address groups to 
Cisco FTD network object groups.

WHAT THIS MODULE DOES:
    - Parses FortiGate 'firewall_addrgrp' section from YAML
    - Extracts group name and member objects
    - Converts to FTD 'networkobjectgroup' format
    - Handles both single members and lists of members

FORTIGATE YAML FORMAT:
    firewall_addrgrp:
        - GROUP_NAME:
            uuid: xxxxx
            member: ["object1", "object2", "object3"]  # List of members
            color: 13  # Optional
        - ANOTHER_GROUP:
            member: "single_object"  # Single member (string, not list)

FTD JSON OUTPUT FORMAT:
    {
        "name": "GROUP_NAME",
        "isSystemDefined": false,
        "objects": [
            {"name": "object1", "type": "networkobject"},
            {"name": "object2", "type": "networkobject"}
        ],
        "type": "networkobjectgroup"
    }

IMPORTANT NOTES:
    - FortiGate 'member' can be either a STRING or a LIST
      Examples: member: "single_object" OR member: ["obj1", "obj2"]
    - We need to normalize this to always be a list for processing
    - FTD requires each member to be an object with 'name' and 'type' fields
    - The 'type' is always 'networkobject' for address group members
"""

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
    return str(name).replace(' ', '_')




class AddressGroupConverter:
    """
    Converter class for transforming FortiGate address groups to FTD network groups.
    
    This class is responsible for:
    1. Reading the 'firewall_addrgrp' section from FortiGate YAML
    2. Extracting group names and their member objects
    3. Converting to FTD's networkobjectgroup format
    4. Handling edge cases (empty groups, single vs multiple members)
    """
    
    def __init__(self, fortigate_config: Dict[str, Any]):
        """
        Initialize the converter with FortiGate configuration data.
        
        Args:
            fortigate_config: Dictionary containing the complete parsed FortiGate YAML
                             Expected to have a 'firewall_addrgrp' key with group data
        """
        # Store the entire FortiGate configuration
        # We'll extract what we need from this in the convert() method
        self.fg_config = fortigate_config
        
        # This will store the converted FTD network groups
        # Starts empty and gets populated by the convert() method
        self.ftd_network_groups = []
    
    def convert(self) -> List[Dict]:
        """
        Main conversion method - converts all FortiGate address groups to FTD format.
        
        CONVERSION PROCESS:
        1. Extract the 'firewall_addrgrp' list from FortiGate config
        2. Loop through each group entry
        3. Extract the group name (the dictionary key)
        4. Extract the group properties (uuid, member, color, etc.)
        5. Normalize the 'member' field to always be a list
        6. Create FTD networkobjectgroup structure
        7. Return the complete list of converted groups
        
        Returns:
            List of dictionaries, each representing an FTD network object group
        """
        # ====================================================================
        # STEP 1: Extract address groups from FortiGate configuration
        # ====================================================================
        # The .get() method safely retrieves the key, returning [] if not found
        # This prevents KeyError exceptions if the key doesn't exist
        address_groups = self.fg_config.get('firewall_addrgrp', [])
        
        # Check if we found any address groups
        if not address_groups:
            print("Warning: No address groups found in FortiGate configuration")
            print("  Expected key: 'firewall_addrgrp'")
            return []
        
        # This list will accumulate all converted groups
        network_groups = []
        
        # ====================================================================
        # STEP 2: Process each FortiGate address group
        # ====================================================================
        # Each group in the list looks like: {'GROUP_NAME': {properties}}
        for group_dict in address_groups:
            # ================================================================
            # STEP 2A: Extract the group name
            # ================================================================
            # The group name is the only key in the dictionary
            # Example: {'Blocked IPs': {uuid: ..., member: ...}}
            #          The group name is 'Blocked IPs'
            
            group_name = list(group_dict.keys())[0]
            
            # ================================================================
            # STEP 2B: Extract the group properties
            # ================================================================
            # Properties include: uuid, member, color, comment, etc.
            properties = group_dict[group_name]
            
            # ================================================================
            # STEP 2C: Extract and normalize the member list
            # ================================================================
            # FortiGate can store members as either:
            # 1. A single string: member: "object_name"
            # 2. A list of strings: member: ["obj1", "obj2", "obj3"]
            # We need to normalize this to ALWAYS be a list
            
            members_raw = properties.get('member', [])
            
            # Normalize to list format
            if isinstance(members_raw, str):
                # If it's a single string, convert to a list with one item
                # Example: "object1" becomes ["object1"]
                members_list = [members_raw]
            elif isinstance(members_raw, list):
                # If it's already a list, use it as-is
                # Example: ["obj1", "obj2"] stays ["obj1", "obj2"]
                members_list = members_raw
            else:
                # If it's some other type (shouldn't happen), default to empty list
                print(f"  Warning: Group '{group_name}' has unexpected member format")
                members_list = []
            
            # ================================================================
            # STEP 2D: Convert members to FTD object format
            # ================================================================
            # FTD expects each member to be an object with 'name' and 'type'
            # FortiGate: ["Server1", "Server2"]
            # FTD:       [{"name": "Server1", "type": "networkobject"},
            #             {"name": "Server2", "type": "networkobject"}]
            
            ftd_members = []
            for member_name in members_list:
                # Create an FTD member object
                member_obj = {
                    "name": sanitize_name(member_name),           # The object name
                    "type": "networkobject"        # Always 'networkobject' for address objects
                }
                ftd_members.append(member_obj)
            
            # ================================================================
            # STEP 2E: Create the FTD network group structure
            # ================================================================
            # This is the final format that FTD FDM API expects
            # Sanitize the group name
            sanitized_group_name = sanitize_name(group_name)
            
            ftd_group = {
                "name": sanitized_group_name,                    # Group name from FortiGate
                "isSystemDefined": False,              # Custom groups are not system-defined
                "objects": ftd_members,                # List of member objects
                "type": "networkobjectgroup"           # FTD type for address groups
            }
            
            # Add the converted group to our result list
            network_groups.append(ftd_group)
            
            # ================================================================
            # STEP 2F: Print conversion details for user feedback
            # ================================================================
            # This helps users see what's being converted in real-time
            member_count = len(ftd_members)
            if group_name != sanitized_group_name:
                print(f"  Converted: {group_name} -> {sanitized_group_name} ({member_count} members)")
            else:
                print(f"  Converted: {sanitized_group_name} ({member_count} members)")
            
            # Optional: Print the actual member names for debugging
            # Uncomment the next line if you want to see all members
            # print(f"    Members: {', '.join(members_list)}")
        
        # ====================================================================
        # STEP 3: Return all converted groups
        # ====================================================================
        return network_groups


# =============================================================================
# ADDITIONAL HELPER METHODS (if needed in the future)
# =============================================================================

    def _validate_group(self, group_name: str, properties: Dict) -> bool:
        """
        Validate that a group has all required fields.
        This is an optional validation method that could be called before conversion.
        
        Args:
            group_name: Name of the group being validated
            properties: Dictionary of group properties
            
        Returns:
            True if valid, False otherwise
        """
        # Check if the group has members
        if 'member' not in properties:
            print(f"  Warning: Group '{group_name}' has no members")
            return False
        
        members = properties['member']
        
        # Check if members is empty
        if isinstance(members, list) and len(members) == 0:
            print(f"  Warning: Group '{group_name}' has empty member list")
            return False
        
        if isinstance(members, str) and members.strip() == '':
            print(f"  Warning: Group '{group_name}' has empty member string")
            return False
        
        return True
    
    def get_group_count(self) -> int:
        """
        Get the number of address groups that were converted.
        
        Returns:
            Integer count of converted groups
        """
        return len(self.ftd_network_groups)
    
    def get_member_count(self, group_name: str) -> int:
        """
        Get the number of members in a specific converted group.
        
        Args:
            group_name: Name of the group to check
            
        Returns:
            Integer count of members, or -1 if group not found
        """
        # Search through converted groups to find the matching name
        for group in self.ftd_network_groups:
            if group['name'] == group_name:
                return len(group['objects'])
        
        # Group not found
        return -1


# =============================================================================
# TESTING CODE (for standalone testing of this module)
# =============================================================================

if __name__ == '__main__':
    """
    This code only runs when you execute this file directly.
    It's useful for testing the converter without running the main script.
    
    To test this module standalone:
        python address_group_converter.py
    """
    
    # Sample FortiGate configuration for testing
    test_config = {
        'firewall_addrgrp': [
            {
                'Blocked IPs': {
                    'uuid': '11111111-2222-3333-8888-000000000005',
                    'member': ["1.0.0.1", "149.112.112.122", "208.67.222.222"]
                }
            },
            {
                'Switches': {
                    'uuid': '11111111-2222-3333-8888-000000000006',
                    'member': ["Switch1", "Switch2", "Switch3"]
                }
            },
            {
                'Single_Member_Group': {
                    'uuid': '11111111-2222-3333-8888-000000000007',
                    'member': "SingleObject"  # Test single string member
                }
            }
        ]
    }
    
    # Create converter instance
    converter = AddressGroupConverter(test_config)
    
    # Run conversion
    print("Testing Address Group Converter...")
    print("="*60)
    result = converter.convert()
    
    # Display results
    print("\nConversion Results:")
    print("="*60)
    import json
    print(json.dumps(result, indent=2))
    print("\n" + "="*60)
    print(f"Total groups converted: {len(result)}")