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
            "rules_skipped": 0
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
                
                print("✓ Authentication successful")
                return True
            else:
                print(f"✗ Authentication failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Connection error: {e}")
            return False
    
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
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                # Check if it's a duplicate/already exists error
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["address_objects_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"  # Return True to indicate it's not a failure
                else:
                    self.stats["address_objects_failed"] += 1
                    return False, error_msg
            else:
                self.stats["address_objects_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["address_objects_failed"] += 1
            return False, str(e)
    
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
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["address_groups_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["address_groups_failed"] += 1
                    return False, error_msg
            else:
                self.stats["address_groups_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["address_groups_failed"] += 1
            return False, str(e)
    
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
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["port_objects_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["port_objects_failed"] += 1
                    return False, error_msg
            else:
                self.stats["port_objects_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["port_objects_failed"] += 1
            return False, str(e)
    
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
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["port_groups_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["port_groups_failed"] += 1
                    return False, error_msg
            else:
                self.stats["port_groups_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["port_groups_failed"] += 1
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
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["routes_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["routes_failed"] += 1
                    return False, error_msg
            else:
                self.stats["routes_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["routes_failed"] += 1
            return False, str(e)
    
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
                error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    self.stats["rules_skipped"] += 1
                    return True, f"SKIPPED: {error_msg}"
                else:
                    self.stats["rules_failed"] += 1
                    return False, error_msg
            else:
                self.stats["rules_failed"] += 1
                error_msg = response.text
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            self.stats["rules_failed"] += 1
            return False, str(e)
    
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
                print("✓ Deployment initiated successfully")
                print("  Note: Deployment may take several minutes to complete")
                print("  Check FDM web interface for deployment status")
                return True
            else:
                print(f"✗ Deployment failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Deployment error: {e}")
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
        print(f"✗ File not found: {filename}")
        return None
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON in {filename}: {e}")
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
                print("⊘ (already exists)")
            else:
                print("✓")
        else:
            print(f"✗")
            print(f"      Error: {result}")
            all_success = False
        
        # Small delay to avoid overwhelming the API
        time.sleep(0.2)
    
    return all_success


def import_address_groups(client: FTDAPIClient, filename: str) -> bool:
    """
    Import address groups from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to address groups JSON file
        
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
        
        # Clean the group object - ensure member objects only have name and type
        cleaned_group = clean_group_object(group)
        
        print(f"  [{i}/{len(groups)}] Creating: {name}...", end=" ")
        
        success, result = client.create_network_group(cleaned_group)
        if success:
            print("✓")
        else:
            print(f"✗ {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success


def clean_group_object(group: Dict) -> Dict:
    """
    Clean a group object to ensure member references only have name and type.
    
    FTD groups reference member objects by name only. Remove any UUIDs, IDs,
    versions, or other fields that might cause "cannot find entity" errors.
    
    Args:
        group: Group object dictionary
        
    Returns:
        Cleaned group object
    """
    cleaned = group.copy()
    
    # Clean the member objects in the "objects" array
    if "objects" in cleaned and isinstance(cleaned["objects"], list):
        cleaned_members = []
        for member in cleaned["objects"]:
            if isinstance(member, dict):
                # Keep ONLY name and type - remove everything else
                cleaned_member = {
                    "name": member.get("name"),
                    "type": member.get("type", "networkobject")
                }
                cleaned_members.append(cleaned_member)
            else:
                # If member is just a string, convert to proper format
                cleaned_members.append({
                    "name": str(member),
                    "type": "networkobject"
                })
        
        cleaned["objects"] = cleaned_members
    
    # Remove any UUID, id, or version fields from the group itself that came from FortiGate
    cleaned.pop("uuid", None)
    cleaned.pop("id", None) 
    cleaned.pop("version", None)
    
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
            print("✓")
        else:
            print(f"✗ {result}")
            all_success = False
        
        time.sleep(0.2)
    
    return all_success


def import_service_groups(client: FTDAPIClient, filename: str) -> bool:
    """
    Import service port groups from JSON file to FTD.
    
    Args:
        client: Authenticated FTD API client
        filename: Path to service groups JSON file
        
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
        
        # Clean the group object - ensure member objects only have name and type
        cleaned_group = clean_group_object(group)
        
        print(f"  [{i}/{len(groups)}] Creating: {name}...", end=" ")
        
        success, result = client.create_port_group(cleaned_group)
        if success:
            print("✓")
        else:
            print(f"✗ {result}")
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
            print("✓")
        else:
            print(f"✗ {result}")
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
            print("✓")
        else:
            print(f"✗ {result}")
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
        print("\n✗ Authentication failed. Exiting.")
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
        if args.type == 'address-objects':
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
    elif any([args.only_address_objects, args.only_address_groups, 
              args.only_service_objects, args.only_service_groups,
              args.only_routes, args.only_rules]):
        
        print("\nSelective Import Mode:")
        imported_any = False
        
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
            print("\n✗ No import flags specified. Nothing to import.")
            return 1
    
    # Default: Import everything in order
    else:
        print("\nFull Import Mode - All objects in order:")
        print("  1. Address Objects")
        print("  2. Address Groups")
        print("  3. Service Objects")
        print("  4. Service Groups")
        print("  5. Static Routes")
        print("  6. Access Rules")
        
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