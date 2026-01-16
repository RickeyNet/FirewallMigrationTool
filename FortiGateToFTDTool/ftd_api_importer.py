#!/usr/bin/env python3
"""
Cisco FTD FDM API Importer
===========================
This script imports converted FortiGate configurations into Cisco FTD
using the Firewall Device Manager (FDM) API.

REQUIREMENTS:
    - Python 3.6 or higher
    - requests library (install with: pip install requests)
    - urllib3 library (install with: pip install urllib3)

SUPPORTED FTD VERSIONS:
    - FTD 7.4.x with FDM (tested on 7.4.2.4-9)
    - Local management via FDM

WHAT THIS SCRIPT DOES:
    1. Authenticates to FTD FDM API
    2. Imports address objects
    3. Imports address groups
    4. Imports port objects
    5. Imports port groups
    6. Imports static routes
    7. Imports access rules
    8. Deploys the configuration changes
    9. Provides detailed progress and error reporting

HOW TO RUN:
    python ftd_api_importer.py --host 192.168.1.1 --username admin --password YourPassword

IMPORTANT NOTES:
    - SSL certificate verification is disabled by default (self-signed certs)
    - Always test on a non-production firewall first
    - Back up your FTD configuration before running
    - The script uses the /api/fdm/latest/ endpoint
    - Objects are imported in the correct dependency order
"""

import requests
import json
import argparse
import sys
import time
import getpass
import urllib3
from typing import Dict, List, Optional, Tuple


# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FTDAPIClient:
    """
    Client for interacting with Cisco FTD Firewall Device Manager (FDM) API.
    
    This class handles:
    - Authentication and token management
    - CRUD operations for network objects, services, routes, and policies
    - Deployment of configuration changes
    - Error handling and retry logic
    """
    
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        """
        Initialize the FTD API client.
        
        Args:
            host: FTD management IP address or hostname
            username: FDM username (typically 'admin')
            password: FDM password
            verify_ssl: Whether to verify SSL certificates (False for self-signed)
        """
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        
        # Base URL for FDM API
        self.base_url = f"https://{host}/api/fdm/latest"
        
        # Session for maintaining connection
        self.session = requests.Session()
        self.session.verify = verify_ssl
        
        # Authentication token (obtained after login)
        self.access_token = None
        self.refresh_token = None
        
        # Track statistics
        self.stats = {
            "address_objects_created": 0,
            "address_objects_failed": 0,
            "address_objects_skipped": 0,
            "address_groups_created": 0,
            "address_groups_failed": 0,
            "address_groups_skipped": 0,
            "port_objects_created": 0,
            "port_objects_failed": 0,
            "port_objects_skipped": 0,
            "port_groups_created": 0,
            "port_groups_failed": 0,
            "port_groups_skipped": 0,
            "routes_created": 0,
            "routes_failed": 0,
            "routes_skipped": 0,
            "rules_created": 0,
            "rules_failed": 0,
            "rules_skipped": 0,
            "physical_interfaces_updated": 0,
            "physical_interfaces_failed": 0,
            "physical_interfaces_skipped": 0,
            "subinterfaces_created": 0,
            "subinterfaces_failed": 0,
            "subinterfaces_skipped": 0,
            "etherchannels_created": 0,
            "etherchannels_failed": 0,
            "etherchannels_skipped": 0,
            "bridge_groups_created": 0,
            "bridge_groups_failed": 0,
            "bridge_groups_skipped": 0
        }
    
    def authenticate(self) -> bool:
        """
        Authenticate to the FTD FDM API and obtain access tokens.
        
        The FDM API uses OAuth 2.0 token-based authentication.
        After successful authentication, tokens are stored for subsequent requests.
        
        Returns:
            True if authentication successful, False otherwise
        """
        print(f"\n{'='*60}")
        print(f"Authenticating to FTD at {self.host}")
        print(f"{'='*60}")
        
        # Authentication endpoint
        auth_url = f"{self.base_url}/fdm/token"
        
        # OAuth 2.0 grant type for password-based authentication
        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            response = self.session.post(
                auth_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens.get("access_token")
                self.refresh_token = tokens.get("refresh_token")
                
                # Set the authorization header for all future requests
                self.session.headers.update({
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                })
                
                print("[OK] Authentication successful")
                return True
            else:
                print(f"[ERROR] Authentication failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Connection error: {e}")
            return False
    
    def _extract_error_message(self, response_or_data) -> str:
        """
        Extract a human-readable error message from an API response.
        
        Args:
            response_or_data: Either a requests.Response object or a dict of parsed JSON
            
        Returns:
            String containing the error message
        """
        try:
            # If it's a Response object, try to parse JSON
            if hasattr(response_or_data, 'json'):
                try:
                    data = response_or_data.json()
                except:
                    return response_or_data.text[:500] if response_or_data.text else "Unknown error"
            else:
                data = response_or_data
            
            # Try different error message formats that FTD API might return
            # Format 1: {"error": {"messages": [{"description": "..."}]}}
            if 'error' in data:
                error_obj = data['error']
                if 'messages' in error_obj and error_obj['messages']:
                    messages = []
                    for msg in error_obj['messages']:
                        if isinstance(msg, dict):
                            desc = msg.get('description', '')
                            code = msg.get('code', '')
                            if desc:
                                messages.append(f"{code}: {desc}" if code else desc)
                        elif isinstance(msg, str):
                            messages.append(msg)
                    if messages:
                        return " | ".join(messages)
                if 'message' in error_obj:
                    return error_obj['message']
            
            # Format 2: {"message": "..."}
            if 'message' in data:
                return data['message']
            
            # Format 3: {"description": "..."}
            if 'description' in data:
                return data['description']
            
            # Fallback: return the whole response as string (truncated)
            return str(data)[:500]
            
        except Exception as e:
            return f"Error parsing response: {str(e)}"
    
    def create_network_object(self, obj: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a network object (address object) in FTD.
        
        Args:
            obj: Dictionary containing network object data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        endpoint = f"{self.base_url}/object/networks"
        
        try:
            response = self.session.post(endpoint, json=obj, timeout=30)
            
            if response.status_code in [200, 201]:
                created_obj = response.json()
                self.stats["address_objects_created"] += 1
                return True, created_obj.get("id")
            elif response.status_code == 422:
                # 422 Unprocessable Entity - usually means object already exists
                error_data = response.json()
                error_msg = self._extract_error_message(error_data)
                
                # Check if it's a duplicate/already exists error
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["address_objects_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"  # Return True to indicate it's not a failure
                else:
                    self.stats["address_objects_failed"] += 1
                    return False, f"HTTP {response.status_code}: {error_msg}"
            else:
                self.stats["address_objects_failed"] += 1
                error_msg = self._extract_error_message(response)
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            self.stats["address_objects_failed"] += 1
            return False, f"Request error: {str(e)}"
    
    def create_network_group(self, group: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a network object group (address group) in FTD.
        
        Args:
            group: Dictionary containing network group data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        endpoint = f"{self.base_url}/object/networkgroups"
        
        try:
            response = self.session.post(endpoint, json=group, timeout=30)
            
            if response.status_code in [200, 201]:
                created_obj = response.json()
                self.stats["address_groups_created"] += 1
                return True, created_obj.get("id")
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = self._extract_error_message(error_data)
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["address_groups_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["address_groups_failed"] += 1
                    return False, f"HTTP {response.status_code}: {error_msg}"
            else:
                self.stats["address_groups_failed"] += 1
                error_msg = self._extract_error_message(response)
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            self.stats["address_groups_failed"] += 1
            return False, f"Request error: {str(e)}"
    
    def create_port_object(self, obj: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a port object (service object) in FTD.
        
        Args:
            obj: Dictionary containing port object data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        # Determine the correct endpoint based on protocol type
        obj_type = obj.get("type", "tcpportobject")
        
        if obj_type == "tcpportobject":
            endpoint = f"{self.base_url}/object/tcpports"
        elif obj_type == "udpportobject":
            endpoint = f"{self.base_url}/object/udpports"
        else:
            self.stats["port_objects_failed"] += 1
            return False, f"Unknown port type: {obj_type}"
        
        try:
            response = self.session.post(endpoint, json=obj, timeout=30)
            
            if response.status_code in [200, 201]:
                created_obj = response.json()
                self.stats["port_objects_created"] += 1
                return True, created_obj.get("id")
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = self._extract_error_message(error_data)
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["port_objects_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["port_objects_failed"] += 1
                    return False, f"HTTP {response.status_code}: {error_msg}"
            else:
                self.stats["port_objects_failed"] += 1
                error_msg = self._extract_error_message(response)
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            self.stats["port_objects_failed"] += 1
            return False, f"Request error: {str(e)}"
    
    def create_port_group(self, group: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a port object group (service group) in FTD.
        
        Args:
            group: Dictionary containing port group data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        endpoint = f"{self.base_url}/object/portgroups"
        
        try:
            response = self.session.post(endpoint, json=group, timeout=30)
            
            if response.status_code in [200, 201]:
                created_obj = response.json()
                self.stats["port_groups_created"] += 1
                return True, created_obj.get("id")
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = self._extract_error_message(error_data)
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["port_groups_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["port_groups_failed"] += 1
                    return False, f"HTTP {response.status_code}: {error_msg}"
            else:
                self.stats["port_groups_failed"] += 1
                error_msg = self._extract_error_message(response)
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            self.stats["port_groups_failed"] += 1
            return False, f"Request error: {str(e)}"
    
    def get_physical_interface(self, hardware_name: str) -> Tuple[bool, Optional[Dict]]:
        """
        Get a physical interface by hardware name to retrieve its ID.
        
        Args:
            hardware_name: Hardware name (e.g., 'Ethernet1/1')
            
        Returns:
            Tuple of (success: bool, interface dict or error message)
        """
        endpoint = f"{self.base_url}/devices/default/interfaces"
        
        # Normalize the hardware name for comparison (case-insensitive)
        search_name = hardware_name.lower().strip()
        
        try:
            # Use pagination to get all interfaces
            all_interfaces = []
            offset = 0
            limit = 100
            
            while True:
                params = {"offset": offset, "limit": limit}
                response = self.session.get(endpoint, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    interfaces = data.get('items', [])
                    
                    if not interfaces:
                        break
                    
                    all_interfaces.extend(interfaces)
                    
                    # Check pagination
                    paging = data.get('paging', {})
                    if not paging.get('next'):
                        break
                    
                    offset += limit
                else:
                    return False, f"HTTP {response.status_code}: {response.text}" # pyright: ignore[reportReturnType]
            
            # Search for the interface (case-insensitive)
            for intf in all_interfaces:
                intf_hardware = intf.get('hardwareName', '').lower().strip()
                if intf_hardware == search_name:
                    return True, intf
            
            # Interface not found - this might be because it's disabled/unconfigured
            return False, f"Interface {hardware_name} not found (may be disabled or not present on this device)" # pyright: ignore[reportReturnType]
                
        except requests.exceptions.RequestException as e:
            return False, str(e) # pyright: ignore[reportReturnType]
        
    def update_physical_interface(self, intf: Dict) -> Tuple[bool, Optional[str]]:
        """
        Update a physical interface in FTD (PUT request).
        
        Physical interfaces already exist in FTD - we update them with
        name, description, IP address, etc.
        
        IMPORTANT: This preserves existing hardware settings:
        - speed (e.g., "AUTO", "DETECT_SFP", "TEN_GIGABIT")
        - duplex (e.g., "FULL", "HALF", "AUTO")
        - fecMode (e.g., "AUTO", "CL74", "CL91")
        - autoNegotiation (True/False)
        
        Args:
            intf: Dictionary containing physical interface data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        hardware_name = intf.get('hardwareName')
        
        # First, get the existing interface to retrieve its ID and version
        success, existing = self.get_physical_interface(hardware_name) # pyright: ignore[reportArgumentType]
        if not success:
            # Interface not found - skip it instead of failing
            self.stats["physical_interfaces_skipped"] += 1
            return True, f"SKIPPED: {existing}"
        
        # Merge our updates with the existing interface
        intf_id = existing.get('id') # pyright: ignore[reportOptionalMemberAccess]
        intf_version = existing.get('version') # pyright: ignore[reportOptionalMemberAccess]
        
        # Start with the existing interface configuration
        # This preserves ALL existing settings including hardware config
        update_payload = existing.copy() # pyright: ignore[reportOptionalMemberAccess]
        
        # Only update the fields we want to change (logical config)
        # Name - only update if we have a name to set
        if intf.get('name'):
            update_payload['name'] = intf['name']
        
        # Description - only update if provided
        if 'description' in intf:
            update_payload['description'] = intf.get('description', '')
        
        # Enabled - only update if explicitly provided
        if 'enabled' in intf:
            update_payload['enabled'] = intf['enabled']
        
        # Update IPv4 if provided
        if 'ipv4' in intf and intf['ipv4'] is not None:
            update_payload['ipv4'] = intf['ipv4']
        
        # Update MTU if provided
        if 'mtu' in intf and intf['mtu'] is not None:
            update_payload['mtu'] = intf['mtu']
        
        # PRESERVE existing hardware settings - do NOT overwrite these
        # These are typically already configured correctly on the FTD
        # and should not be changed by the migration
        hardware_settings = ['speed', 'duplex', 'fecMode', 'autoNegotiation', 
                           'lacpMode', 'lacpPriority', 'flowControlSend', 
                           'flowControlReceive', 'managementOnly', 'nveOnly']
        
        for setting in hardware_settings:
            if setting in existing: # pyright: ignore[reportOperatorIssue]
                update_payload[setting] = existing[setting] # pyright: ignore[reportOptionalSubscript]
        
        endpoint = f"{self.base_url}/devices/default/interfaces/{intf_id}"
        
        try:
            response = self.session.put(endpoint, json=update_payload, timeout=30)
            
            if response.status_code in [200, 201]:
                updated_obj = response.json()
                self.stats["physical_interfaces_updated"] += 1
                return True, updated_obj.get("id")
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                self.stats["physical_interfaces_failed"] += 1
                return False, error_msg
            else:
                self.stats["physical_interfaces_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["physical_interfaces_failed"] += 1
            return False, str(e)
        
    def create_subinterface(self, intf: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a subinterface in FTD.
        
        Args:
            intf: Dictionary containing subinterface data
            
        Returns:
            Tuple of (success: bool, interface_id or error message)
        """
        endpoint = f"{self.base_url}/devices/default/subinterfaces"
        
        try:
            response = self.session.post(endpoint, json=intf, timeout=30)
            
            if response.status_code in [200, 201]:
                created = response.json()
                self.stats["subinterfaces_created"] += 1
                return True, created.get('id')
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower():
                    self.stats["subinterfaces_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["subinterfaces_failed"] += 1
                    return False, error_msg
            else:
                self.stats["subinterfaces_failed"] += 1
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except requests.exceptions.RequestException as e:
            self.stats["subinterfaces_failed"] += 1
            return False, str(e)
        
    def create_etherchannel(self, intf: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create an EtherChannel interface in FTD.
        
        Args:
            intf: Dictionary containing etherchannel data
            
        Returns:
            Tuple of (success: bool, interface_id or error message)
        """
        endpoint = f"{self.base_url}/devices/default/etherchannelinterfaces"
        
        # Need to resolve member interface IDs
        if 'memberInterfaces' in intf:
            resolved_members = []
            for member in intf['memberInterfaces']:
                hardware_name = member.get('hardwareName')
                if hardware_name:
                    success, existing = self.get_physical_interface(hardware_name)
                    if success:
                        resolved_members.append({
                            'id': existing.get('id'), # pyright: ignore[reportOptionalMemberAccess]
                            'type': 'physicalinterface'
                        })
            intf['memberInterfaces'] = resolved_members
        
        try:
            response = self.session.post(endpoint, json=intf, timeout=30)
            
            if response.status_code in [200, 201]:
                created = response.json()
                self.stats["etherchannels_created"] += 1
                return True, created.get('id')
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower():
                    self.stats["etherchannels_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["etherchannels_failed"] += 1
                    return False, error_msg
            else:
                self.stats["etherchannels_failed"] += 1
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except requests.exceptions.RequestException as e:
            self.stats["etherchannels_failed"] += 1
            return False, str(e)
        
    def create_bridge_group(self, intf: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a bridge group interface in FTD.
        
        Args:
            intf: Dictionary containing bridge group data
            
        Returns:
            Tuple of (success: bool, interface_id or error message)
        """
        endpoint = f"{self.base_url}/devices/default/bridgegroupinterfaces"
        
        try:
            response = self.session.post(endpoint, json=intf, timeout=30)
            
            if response.status_code in [200, 201]:
                created = response.json()
                self.stats["bridge_groups_created"] += 1
                return True, created.get('id')
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower():
                    self.stats["bridge_groups_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["bridge_groups_failed"] += 1
                    return False, error_msg
            else:
                self.stats["bridge_groups_failed"] += 1
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except requests.exceptions.RequestException as e:
            self.stats["bridge_groups_failed"] += 1
            return False, str(e)
    
    def create_static_route(self, route: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create a static route in FTD.
        
        Args:
            route: Dictionary containing static route data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        endpoint = f"{self.base_url}/devices/default/routing/staticrouteentries"
        
        try:
            response = self.session.post(endpoint, json=route, timeout=30)
            
            if response.status_code in [200, 201]:
                created_obj = response.json()
                self.stats["routes_created"] += 1
                return True, created_obj.get("id")
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = self._extract_error_message(error_data)
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["routes_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["routes_failed"] += 1
                    return False, f"HTTP {response.status_code}: {error_msg}"
            else:
                self.stats["routes_failed"] += 1
                error_msg = self._extract_error_message(response)
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            self.stats["routes_failed"] += 1
            return False, f"Request error: {str(e)}"
    
    def create_access_rule(self, rule: Dict) -> Tuple[bool, Optional[str]]:
        """
        Create an access rule (firewall policy) in FTD.
        
        Args:
            rule: Dictionary containing access rule data
            
        Returns:
            Tuple of (success: bool, object_id: str or error message)
        """
        endpoint = f"{self.base_url}/policy/accesspolicies/default/accessrules"
        
        try:
            response = self.session.post(endpoint, json=rule, timeout=30)
            
            if response.status_code in [200, 201]:
                created_obj = response.json()
                self.stats["rules_created"] += 1
                return True, created_obj.get("id")
            elif response.status_code == 422:
                error_data = response.json()
                error_msg = self._extract_error_message(error_data)
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["rules_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["rules_failed"] += 1
                    return False, f"HTTP {response.status_code}: {error_msg}"
            else:
                self.stats["rules_failed"] += 1
                error_msg = self._extract_error_message(response)
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            self.stats["rules_failed"] += 1
            return False, f"Request error: {str(e)}"
    
    def deploy_changes(self) -> bool:
        """
        Deploy pending configuration changes to the FTD device.
        
        After creating/modifying objects, changes must be deployed
        for them to take effect on the firewall.
        
        Returns:
            True if deployment initiated successfully, False otherwise
        """
        print(f"\n{'='*60}")
        print("Deploying configuration changes...")
        print(f"{'='*60}")
        
        endpoint = f"{self.base_url}/operational/deploy"
        
        try:
            response = self.session.post(endpoint, json={}, timeout=30)
            
            if response.status_code in [200, 201, 202]:
                print("[OK] Deployment initiated successfully")
                print("  Note: Deployment may take several minutes to complete")
                print("  Check FDM web interface for deployment status")
                return True
            else:
                print(f"[ERROR] Deployment failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Deployment error: {e}")
            return False
    
    def print_statistics(self):
        """
        Print a summary of import statistics.
        """
        print(f"\n{'='*60}")
        print("IMPORT STATISTICS")
        print(f"{'='*60}")
        print(f"\nAddress Objects:")
        print(f"  Created: {self.stats['address_objects_created']}")
        print(f"  Skipped: {self.stats['address_objects_skipped']} (already exist)")
        print(f"  Failed:  {self.stats['address_objects_failed']}")
        print(f"\nAddress Groups:")
        print(f"  Created: {self.stats['address_groups_created']}")
        print(f"  Skipped: {self.stats['address_groups_skipped']} (already exist)")
        print(f"  Failed:  {self.stats['address_groups_failed']}")
        print(f"\nPort Objects:")
        print(f"  Created: {self.stats['port_objects_created']}")
        print(f"  Skipped: {self.stats['port_objects_skipped']} (already exist)")
        print(f"  Failed:  {self.stats['port_objects_failed']}")
        print(f"\nPort Groups:")
        print(f"  Created: {self.stats['port_groups_created']}")
        print(f"  Skipped: {self.stats['port_groups_skipped']} (already exist)")
        print(f"  Failed:  {self.stats['port_groups_failed']}")
        print(f"\nPhysical Interfaces:")
        print(f"  Updated: {self.stats['physical_interfaces_updated']}")
        print(f"  Skipped: {self.stats['physical_interfaces_skipped']}")
        print(f"  Failed:  {self.stats['physical_interfaces_failed']}")
        print(f"\nEtherChannels:")
        print(f"  Created: {self.stats['etherchannels_created']}")
        print(f"  Skipped: {self.stats['etherchannels_skipped']}")
        print(f"  Failed:  {self.stats['etherchannels_failed']}")
        print(f"\nBridge Groups:")
        print(f"  Created: {self.stats['bridge_groups_created']}")
        print(f"  Skipped: {self.stats['bridge_groups_skipped']}")
        print(f"  Failed:  {self.stats['bridge_groups_failed']}")
        print(f"\nSubinterfaces:")
        print(f"  Created: {self.stats['subinterfaces_created']}")
        print(f"  Skipped: {self.stats['subinterfaces_skipped']}")
        print(f"  Failed:  {self.stats['subinterfaces_failed']}")
        print(f"\nStatic Routes:")
        print(f"  Created: {self.stats['routes_created']}")
        print(f"  Skipped: {self.stats['routes_skipped']} (already exist)")
        print(f"  Failed:  {self.stats['routes_failed']}")
        print(f"\nAccess Rules:")
        print(f"  Created: {self.stats['rules_created']}")
        print(f"  Skipped: {self.stats['rules_skipped']} (already exist)")
        print(f"  Failed:  {self.stats['rules_failed']}")
        print(f"\n{'='*60}")


def load_json_file(filename: str) -> Optional[List[Dict]]:
    """
    Load a JSON file containing configuration objects.
    
    Args:
        filename: Path to the JSON file
        
    Returns:
        List of objects from the file, or None if error
    """
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
            return data
    except FileNotFoundError:
        print(f"[ERROR] File not found: {filename}")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in {filename}: {e}")
        return None


def import_address_objects(client: FTDAPIClient, filename: str) -> bool:
    """
    Import address objects from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to address objects JSON file
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Importing Address Objects from {filename}")
    print(f"{'-'*60}")
    
    objects = load_json_file(filename)
    if objects is None:
        return False
    
    if not objects:
        print("  No objects to import")
        return True
    
    all_success = True
    for i, obj in enumerate(objects, 1):
        name = obj.get("name", "Unknown")
        print(f"  [{i}/{len(objects)}] Creating: {name}...", end=" ")
        
        success, result = client.create_network_object(obj)
        if success:
            if "SKIPPED" in str(result):
                print("(already exists)")
            else:
                print("[OK]")
        else:
            print(f"[ERROR]")
            print(f"      Error: {result}")
            all_success = False
        
        # Small delay to avoid overwhelming the API
        time.sleep(0.2)
    
    return all_success


def import_address_groups(client: FTDAPIClient, filename: str, debug: bool = False) -> bool:
    """
    Import address groups from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to address groups JSON file
        debug: If True, print the cleaned JSON before sending to API
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Importing Address Groups from {filename}")
    print(f"{'-'*60}")
    
    groups = load_json_file(filename)
    if groups is None:
        return False
    
    if not groups:
        print("  No groups to import")
        return True
    
    all_success = True
    for i, group in enumerate(groups, 1):
        name = group.get("name", "Unknown")
        
        # Clean the group object - remove FortiGate-specific fields like uuid
        # and ensure member objects only have name and type
        cleaned_group = clean_group_object(group, group_type="network")
        
        # Debug: show what we're sending to the API
        if debug:
            print(f"\n  [DEBUG] Cleaned group JSON for '{name}':")
            print(f"    {json.dumps(cleaned_group, indent=2)}")
        
        print(f"  [{i}/{len(groups)}] Creating: {name}...", end=" ")
        
        success, result = client.create_network_group(cleaned_group)
        if success:
            if "SKIPPED" in str(result):
                print("(already exists)")
            else:
                print("[OK]")
        else:
            print(f"[ERROR]")
            print(f"      Error: {result}")
            # On error, show what we tried to send
            print(f"      Sent: {json.dumps(cleaned_group)}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success


def clean_group_object(group: Dict, group_type: str = "network") -> Dict:
    """
    Clean a group object to ensure only FTD-compatible fields are included.
    
    FTD groups reference member objects by name only. This function removes
    any FortiGate-specific fields like UUIDs, colors, comments, and ensures
    member objects only have name and type.
    
    Args:
        group: Group object dictionary from the converted JSON
        group_type: Either "network" for address groups or "port" for service groups
        
    Returns:
        Cleaned group object with only FTD-compatible fields
    """
    # Start fresh with only the fields FTD needs
    cleaned = {}
    
    # Copy only the essential fields for FTD
    # Name is required
    if "name" in group:
        cleaned["name"] = group["name"]
    
    # isSystemDefined should be False for custom objects
    cleaned["isSystemDefined"] = group.get("isSystemDefined", False)
    
    # Type is required
    if group_type == "network":
        cleaned["type"] = "networkobjectgroup"
    else:
        cleaned["type"] = "portobjectgroup"
    
    # Clean the member objects - keep ONLY name and type
    if "objects" in group and isinstance(group["objects"], list):
        cleaned_members = []
        for member in group["objects"]:
            if isinstance(member, dict):
                member_name = member.get("name", "")
                
                # Determine the correct member type
                if group_type == "network":
                    member_type = "networkobject"
                else:
                    # For port groups, determine type from name or existing type
                    # Check for _TCP or _UDP anywhere in name (handles _TCP_1, _UDP_2, etc.)
                    if '_UDP' in str(member_name):
                        member_type = "udpportobject"
                    elif '_TCP' in str(member_name):
                        member_type = "tcpportobject"
                    else:
                        # Try to preserve existing type, default to TCP
                        member_type = member.get("type", "tcpportobject")
                
                # Keep ONLY name and type - remove everything else (uuid, id, version, etc.)
                cleaned_member = {
                    "name": member_name,
                    "type": member_type
                }
                cleaned_members.append(cleaned_member)
            elif isinstance(member, str):
                # If member is just a string, convert to proper format
                if group_type == "network":
                    cleaned_members.append({
                        "name": member,
                        "type": "networkobject"
                    })
                else:
                    # Determine type from name
                    if '_UDP' in member:
                        member_type = "udpportobject"
                    else:
                        member_type = "tcpportobject"
                    cleaned_members.append({
                        "name": member,
                        "type": member_type
                    })
        
        cleaned["objects"] = cleaned_members
    else:
        cleaned["objects"] = []
    
    # Note: We intentionally DO NOT copy these FortiGate-specific fields:
    # - uuid (FortiGate's internal identifier)
    # - id (FortiGate's internal identifier)  
    # - version (FortiGate versioning)
    # - color (FortiGate UI color coding)
    # - comment (could be added as description if needed)
    # - member (FortiGate format - we use "objects" instead)
    
    return cleaned


def import_service_objects(client: FTDAPIClient, filename: str) -> bool:
    """
    Import service port objects from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to service objects JSON file
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Importing Service Objects from {filename}")
    print(f"{'-'*60}")
    
    objects = load_json_file(filename)
    if objects is None:
        return False
    
    if not objects:
        print("  No objects to import")
        return True
    
    all_success = True
    for i, obj in enumerate(objects, 1):
        name = obj.get("name", "Unknown")
        obj_type = obj.get("type", "")
        print(f"  [{i}/{len(objects)}] Creating: {name} ({obj_type})...", end=" ")
        
        success, result = client.create_port_object(obj)
        if success:
            print("[OK]")
        else:
            print(f"[ERROR] {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success


def import_service_groups(client: FTDAPIClient, filename: str, debug: bool = False) -> bool:
    """
    Import service port groups from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to service groups JSON file
        debug: If True, print the cleaned JSON before sending to API
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Importing Service Groups from {filename}")
    print(f"{'-'*60}")
    
    groups = load_json_file(filename)
    if groups is None:
        return False
    
    if not groups:
        print("  No groups to import")
        return True
    
    all_success = True
    for i, group in enumerate(groups, 1):
        name = group.get("name", "Unknown")
        
        # Clean the group object - remove FortiGate-specific fields like uuid
        # and ensure member objects only have name and type
        cleaned_group = clean_group_object(group, group_type="port")
        
        # Debug: show what we're sending to the API
        if debug:
            print(f"\n  [DEBUG] Cleaned group JSON for '{name}':")
            print(f"    {json.dumps(cleaned_group, indent=2)}")
        
        print(f"  [{i}/{len(groups)}] Creating: {name}...", end=" ")
        
        success, result = client.create_port_group(cleaned_group)
        if success:
            if "SKIPPED" in str(result):
                print("(already exists)")
            else:
                print("[OK]")
        else:
            print(f"[ERROR]")
            print(f"      Error: {result}")
            # On error, show what we tried to send
            print(f"      Sent: {json.dumps(cleaned_group)}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success

def import_physical_interfaces(client: FTDAPIClient, filename: str) -> bool:
    """
    Import/update physical interfaces from JSON file to FTD.
    
    Physical interfaces already exist in FTD - this updates them with
    name, description, IP address configuration.
    
    NOTE: Interfaces that don't exist on the FTD (wrong model, disabled, etc.)
    will be skipped with a warning instead of failing.
    
    NOTE: Existing hardware settings (speed, duplex, FEC, auto-negotiation)
    are preserved and not overwritten.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to physical interfaces JSON file
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Updating Physical Interfaces from {filename}")
    print(f"{'-'*60}")
    print("  NOTE: Existing hardware settings (speed, duplex, FEC) will be preserved")
    print("  NOTE: Interfaces not found on FTD will be skipped")
    
    interfaces = load_json_file(filename)
    if interfaces is None:
        return False
    
    if not interfaces:
        print("  No physical interfaces to update")
        return True
    
    all_success = True
    skipped_count = 0
    updated_count = 0
    failed_count = 0
    
    for i, intf in enumerate(interfaces, 1):
        name = intf.get("name", "Unknown")
        hardware = intf.get("hardwareName", "Unknown")
        print(f"  [{i}/{len(interfaces)}] Updating: {name} ({hardware})...", end=" ")
        
        success, result = client.update_physical_interface(intf)
        if success:
            if "SKIPPED" in str(result):
                print(f"[SKIP] (not found on FTD)")
                skipped_count += 1
            else:
                print("[OK]")
                updated_count += 1
        else:
            print(f"[FAIL] {result}")
            failed_count += 1
            all_success = False
        
        time.sleep(0.2)
    
    # Print summary
    print(f"\n  Summary: {updated_count} updated, {skipped_count} skipped, {failed_count} failed")
    
    return all_success

def import_etherchannels(client: FTDAPIClient, filename: str) -> bool:
    """
    Import EtherChannel interfaces from JSON file to FTD.
    """
    print(f"\n{'-'*60}")
    print(f"Creating EtherChannels from {filename}")
    print(f"{'-'*60}")
    
    interfaces = load_json_file(filename)
    if interfaces is None:
        return False
    
    if not interfaces:
        print("  No etherchannels to create")
        return True
    
    all_success = True
    for i, intf in enumerate(interfaces, 1):
        name = intf.get("name", "Unknown")
        hardware = intf.get("hardwareName", "Unknown")
        print(f"  [{i}/{len(interfaces)}] Creating: {name} ({hardware})...", end=" ")
        
        success, result = client.create_etherchannel(intf)
        if success:
            if "SKIPPED" in str(result):
                print("[SKIP] (already exists)")
            else:
                print("[OK]")
        else:
            print(f"[FAIL] {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success

def import_bridge_groups(client: FTDAPIClient, filename: str) -> bool:
    """
    Import bridge group interfaces from JSON file to FTD.
    """
    print(f"\n{'-'*60}")
    print(f"Creating Bridge Groups from {filename}")
    print(f"{'-'*60}")
    
    interfaces = load_json_file(filename)
    if interfaces is None:
        return False
    
    if not interfaces:
        print("  No bridge groups to create")
        return True
    
    all_success = True
    for i, intf in enumerate(interfaces, 1):
        name = intf.get("name", "Unknown")
        print(f"  [{i}/{len(interfaces)}] Creating: {name}...", end=" ")
        
        success, result = client.create_bridge_group(intf)
        if success:
            if "SKIPPED" in str(result):
                print("[SKIP] (already exists)")
            else:
                print("[OK]")
        else:
            print(f"[FAIL] {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success

def import_subinterfaces(client: FTDAPIClient, filename: str) -> bool:
    """
    Import subinterfaces from JSON file to FTD.
    """
    print(f"\n{'-'*60}")
    print(f"Creating Subinterfaces from {filename}")
    print(f"{'-'*60}")
    
    interfaces = load_json_file(filename)
    if interfaces is None:
        return False
    
    if not interfaces:
        print("  No subinterfaces to create")
        return True
    
    all_success = True
    for i, intf in enumerate(interfaces, 1):
        name = intf.get("name", "Unknown")
        hardware = intf.get("hardwareName", "Unknown")
        vlan = intf.get("vlanId", "?")
        print(f"  [{i}/{len(interfaces)}] Creating: {name} ({hardware}) VLAN {vlan}...", end=" ")
        
        success, result = client.create_subinterface(intf)
        if success:
            if "SKIPPED" in str(result):
                print("[SKIP] (already exists)")
            else:
                print("[OK]")
        else:
            print(f"[FAIL] {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success

def import_static_routes(client: FTDAPIClient, filename: str) -> bool:
    """
    Import static routes from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to static routes JSON file
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Importing Static Routes from {filename}")
    print(f"{'-'*60}")
    
    routes = load_json_file(filename)
    if routes is None:
        return False
    
    if not routes:
        print("  No routes to import")
        return True
    
    all_success = True
    for i, route in enumerate(routes, 1):
        name = route.get("name", "Unknown")
        print(f"  [{i}/{len(routes)}] Creating: {name}...", end=" ")
        
        success, result = client.create_static_route(route)
        if success:
            print("[OK]")
        else:
            print(f"[ERROR] {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success


def import_access_rules(client: FTDAPIClient, filename: str) -> bool:
    """
    Import access rules from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to access rules JSON file
        
    Returns:
        True if all imports successful, False if any failed
    """
    print(f"\n{'-'*60}")
    print(f"Importing Access Rules from {filename}")
    print(f"{'-'*60}")
    
    rules = load_json_file(filename)
    if rules is None:
        return False
    
    if not rules:
        print("  No rules to import")
        return True
    
    all_success = True
    for i, rule in enumerate(rules, 1):
        name = rule.get("name", "Unknown")
        action = rule.get("ruleAction", "")
        print(f"  [{i}/{len(rules)}] Creating: {name} ({action})...", end=" ")
        
        success, result = client.create_access_rule(rule)
        if success:
            print("[OK]")
        else:
            print(f"[ERROR] {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success


def main():
    """
    Main function that orchestrates the import process.
    """
    parser = argparse.ArgumentParser(
        description='Import FortiGate converted configurations to Cisco FTD via FDM API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import everything (all files)
  python ftd_api_importer.py --host 192.168.1.1 --username admin --password MyPass123
  
  # Import only address objects
  python ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-objects
  
  # Import only service objects and groups
  python ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-objects --only-service-groups
  
  # Import a specific file
  python ftd_api_importer.py --host 192.168.1.1 -u admin --file my_addresses.json --type address-objects
  
  # Import and deploy
  python ftd_api_importer.py --host 192.168.1.1 -u admin --only-routes --deploy
        """
    )
    
    parser.add_argument('--host', required=True,
                       help='FTD management IP address or hostname')
    parser.add_argument('-u', '--username', required=True,
                       help='FDM username (typically "admin")')
    parser.add_argument('-p', '--password',
                       help='FDM password (will prompt if not provided)')
    parser.add_argument('--base', default='ftd_config',
                       help='Base name of converted JSON files (default: ftd_config)')
    parser.add_argument('--deploy', action='store_true',
                       help='Automatically deploy changes after import')
    parser.add_argument('--skip-verify', action='store_true', default=True,
                       help='Skip SSL certificate verification (default: True)')
    
    # Selective import options - allows importing only specific object types
    parser.add_argument('--only-address-objects', action='store_true',
                       help='Import only address objects')
    parser.add_argument('--only-address-groups', action='store_true',
                       help='Import only address groups')
    parser.add_argument('--only-service-objects', action='store_true',
                       help='Import only service objects')
    parser.add_argument('--only-service-groups', action='store_true',
                       help='Import only service groups')
    parser.add_argument('--only-physical-interfaces', action='store_true',
                       help='Import only physical interface updates')
    parser.add_argument('--only-etherchannels', action='store_true',
                       help='Import only etherchannels')
    parser.add_argument('--only-bridge-groups', action='store_true',
                       help='Import only bridge groups')
    parser.add_argument('--only-subinterfaces', action='store_true',
                       help='Import only subinterfaces')
    parser.add_argument('--only-routes', action='store_true',
                       help='Import only static routes')
    parser.add_argument('--only-rules', action='store_true',
                       help='Import only access rules')
    
    # Alternative: specify a single file directly
    parser.add_argument('--file', 
                       help='Import a specific JSON file (overrides --base and --only flags)')
    parser.add_argument('--type',
                       choices=['address-objects', 'address-groups', 'service-objects', 
                               'service-groups', 'routes', 'rules'],
                       help='Type of objects in the file (required with --file)')
    
    args = parser.parse_args()
    
    # Validate --file requires --type
    if args.file and not args.type:
        parser.error("--file requires --type to be specified")
    
    # Prompt for password if not provided
    if not args.password:
        args.password = getpass.getpass(f"Enter password for {args.username}: ")
    
    # Create API client
    client = FTDAPIClient(
        host=args.host,
        username=args.username,
        password=args.password,
        verify_ssl=not args.skip_verify
    )
    
    # Authenticate
    if not client.authenticate():
        print("\n[ERROR] Authentication failed. Exiting.")
        return 1
    
    # Determine what to import
    print(f"\n{'='*60}")
    print("Starting Import Process")
    print(f"{'='*60}")
    
    # Check if specific file is provided
    if args.file:
        print(f"\nImporting single file: {args.file}")
        print(f"Object type: {args.type}")
        
        # Import based on type
        if args.type == 'physical-interfaces':
            import_physical_interfaces(client, args.file)
        elif args.type == 'etherchannels':
            import_etherchannels(client, args.file)
        elif args.type == 'bridge-groups':
            import_bridge_groups(client, args.file)
        elif args.type == 'subinterfaces':
            import_subinterfaces(client, args.file)
        elif args.type == 'address-objects':
            import_address_objects(client, args.file)
        elif args.type == 'address-groups':
            import_address_groups(client, args.file)
        elif args.type == 'service-objects':
            import_service_objects(client, args.file)
        elif args.type == 'service-groups':
            import_service_groups(client, args.file)
        elif args.type == 'routes':
            import_static_routes(client, args.file)
        elif args.type == 'rules':
            import_access_rules(client, args.file)
    
    # Check if any --only flags are set
    elif any([args.only_physical_interfaces, args.only_etherchannels, 
              args.only_bridge_groups, args.only_subinterfaces,
              args.only_address_objects, args.only_address_groups, 
              args.only_service_objects, args.only_service_groups,
              args.only_routes, args.only_rules]):
        
        print("\nSelective Import Mode:")
        imported_any = False
        
        if args.only_physical_interfaces:
            print("  - Physical Interfaces")
            import_physical_interfaces(client, f"{args.base}_physical_interfaces.json")
            imported_any = True
        
        if args.only_etherchannels:
            print("  - EtherChannels")
            import_etherchannels(client, f"{args.base}_etherchannels.json")
            imported_any = True
        
        if args.only_bridge_groups:
            print("  - Bridge Groups")
            import_bridge_groups(client, f"{args.base}_bridge_groups.json")
            imported_any = True
        
        if args.only_subinterfaces:
            print("  - Subinterfaces")
            import_subinterfaces(client, f"{args.base}_subinterfaces.json")
            imported_any = True

        if args.only_address_objects:
            print("  - Address Objects")
            import_address_objects(client, f"{args.base}_address_objects.json")
            imported_any = True
        
        if args.only_address_groups:
            print("  - Address Groups")
            import_address_groups(client, f"{args.base}_address_groups.json")
            imported_any = True
        
        if args.only_service_objects:
            print("  - Service Objects")
            import_service_objects(client, f"{args.base}_service_objects.json")
            imported_any = True
        
        if args.only_service_groups:
            print("  - Service Groups")
            import_service_groups(client, f"{args.base}_service_groups.json")
            imported_any = True
        
        if args.only_routes:
            print("  - Static Routes")
            import_static_routes(client, f"{args.base}_static_routes.json")
            imported_any = True
        
        if args.only_rules:
            print("  - Access Rules")
            import_access_rules(client, f"{args.base}_access_rules.json")
            imported_any = True
        
        if not imported_any:
            print("\n[ERROR] No import flags specified. Nothing to import.")
            return 1
    
    # Default: Import everything in order
    else:
        print("\nFull Import Mode - All objects in order:")
        print("  1. Physical Interfaces (update)")
        print("  2. EtherChannels (create)")
        print("  3. Bridge Groups (create)")
        print("  4. Subinterfaces (create)")
        print("  1. Address Objects")
        print("  2. Address Groups")
        print("  3. Service Objects")
        print("  4. Service Groups")
        print("  5. Static Routes")
        print("  6. Access Rules")
        
        # Step 5: Import physical interface updates
        import_physical_interfaces(client, f"{args.base}_physical_interfaces.json")
        
        # Step 6: Import etherchannels
        import_etherchannels(client, f"{args.base}_etherchannels.json")
        
        # Step 7: Import bridge groups
        import_bridge_groups(client, f"{args.base}_bridge_groups.json")
        
        # Step 8: Import subinterfaces
        import_subinterfaces(client, f"{args.base}_subinterfaces.json")

        # Step 1: Import address objects
        import_address_objects(client, f"{args.base}_address_objects.json")
        
        # Step 2: Import address groups
        import_address_groups(client, f"{args.base}_address_groups.json")
        
        # Step 3: Import service objects
        import_service_objects(client, f"{args.base}_service_objects.json")
        
        # Step 4: Import service groups
        import_service_groups(client, f"{args.base}_service_groups.json")

        # Step 5: Import static routes
        import_static_routes(client, f"{args.base}_static_routes.json")
        
        # Step 6: Import access rules
        import_access_rules(client, f"{args.base}_access_rules.json")
    
    # Print statistics
    client.print_statistics()
    
    # Deploy changes if requested
    if args.deploy:
        client.deploy_changes()
    else:
        print(f"\n{'='*60}")
        print("Import complete. Changes are pending deployment.")
        print("To deploy, either:")
        print("  1. Run this script again with --deploy flag")
        print("  2. Deploy manually from the FDM web interface")
        print(f"{'='*60}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())