#!/usr/bin/env python3
"""
Cisco FTD FDM API Cleanup Script
=================================
This script deletes configurations that were imported to Cisco FTD
using the ftd_api_importer.py script.

⚠️  WARNING: THIS SCRIPT DELETES CONFIGURATION! ⚠️
    - Always backup your FTD configuration before running
    - Test in a lab environment first
    - Review what will be deleted before confirming
    - Cannot be undone without restoring from backup

REQUIREMENTS:
    - Python 3.6 or higher
    - requests library (install with: pip install requests)
    - urllib3 library (install with: pip install urllib3)

SUPPORTED FTD VERSIONS:
    - FTD 7.4.x with FDM (tested on 7.4.2.4-9)
    - Local management via FDM

WHAT THIS SCRIPT DOES:
    1. Authenticates to FTD FDM API
    2. Retrieves lists of objects from JSON files
    3. Finds matching objects in FTD
    4. Deletes objects in reverse dependency order:
       - Access rules first (depend on everything)
       - Static routes
       - Service groups (depend on service objects)
       - Service objects
       - Address groups (depend on address objects)
       - Address objects last
    5. Optionally deploys changes

HOW TO RUN:
    python ftd_api_cleanup.py --host 192.168.1.1 --username admin --base ftd_config

SAFETY FEATURES:
    - Dry-run mode (preview without deleting)
    - Interactive confirmation required
    - Selective deletion by type
    - Detailed logging of what's being deleted
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


class FTDAPICleanup:
    """
    Client for deleting objects from Cisco FTD via FDM API.
    
    This class handles:
    - Authentication and token management
    - Retrieving object lists from FTD
    - Matching imported objects with FTD objects
    - Deleting objects in correct dependency order
    - Progress reporting and error handling
    """
    
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        """
        Initialize the FTD API cleanup client.
        
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
        
        # Authentication tokens
        self.access_token = None
        self.refresh_token = None
        
        # Track statistics
        self.stats = {
            "rules_deleted": 0,
            "rules_failed": 0,
            "routes_deleted": 0,
            "routes_failed": 0,
            "port_groups_deleted": 0,
            "port_groups_failed": 0,
            "port_objects_deleted": 0,
            "port_objects_failed": 0,
            "address_groups_deleted": 0,
            "address_groups_failed": 0,
            "address_objects_deleted": 0,
            "address_objects_failed": 0
        }
    
    def authenticate(self) -> bool:
        """
        Authenticate to the FTD FDM API and obtain access tokens.
        
        Returns:
            True if authentication successful, False otherwise
        """
        print(f"\n{'='*60}")
        print(f"Authenticating to FTD at {self.host}")
        print(f"{'='*60}")
        
        auth_url = f"{self.base_url}/fdm/token"
        
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
            response = self.session.post(auth_url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens.get("access_token")
                self.refresh_token = tokens.get("refresh_token")
                
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
    
    def get_all_objects(self, endpoint: str) -> List[Dict]:
        """
        Retrieve all objects from a specific FTD endpoint.
        
        Args:
            endpoint: API endpoint path (e.g., "/object/networks")
            
        Returns:
            List of objects from FTD
        """
        url = f"{self.base_url}{endpoint}"
        all_items = []
        offset = 0
        limit = 100
        
        try:
            while True:
                params = {"offset": offset, "limit": limit}
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("items", [])
                    
                    if not items:
                        break
                    
                    all_items.extend(items)
                    offset += limit
                    
                    # Check if we've retrieved all items
                    paging = data.get("paging", {})
                    if not paging.get("next"):
                        break
                else:
                    print(f"  Warning: Failed to retrieve objects from {endpoint}: {response.status_code}")
                    break
            
            return all_items
            
        except requests.exceptions.RequestException as e:
            print(f"  Error retrieving objects from {endpoint}: {e}")
            return []
    
    def delete_object(self, endpoint: str, object_id: str) -> bool:
        """
        Delete a specific object from FTD.
        
        Args:
            endpoint: API endpoint path
            object_id: UUID of the object to delete
            
        Returns:
            True if successful, False otherwise
        """
        url = f"{self.base_url}{endpoint}/{object_id}"
        
        try:
            response = self.session.delete(url, timeout=30)
            
            if response.status_code in [200, 204]:
                return True
            elif response.status_code == 404:
                # Object not found - already deleted or never existed
                return True
            else:
                return False
                
        except requests.exceptions.RequestException as e:
            return False
    
    def delete_access_rules(self, rules_file: str, dry_run: bool = False) -> bool:
        """
        Delete access rules from FTD based on imported file.
        
        Args:
            rules_file: Path to JSON file with imported rules
            dry_run: If True, only show what would be deleted
            
        Returns:
            True if all deletions successful, False if any failed
        """
        print(f"\n{'-'*60}")
        print(f"Processing Access Rules from {rules_file}")
        print(f"{'-'*60}")
        
        # Load the imported rules
        try:
            with open(rules_file, 'r') as f:
                imported_rules = json.load(f)
        except FileNotFoundError:
            print(f"  File not found: {rules_file} (skipping)")
            return True
        except json.JSONDecodeError:
            print(f"  Invalid JSON in {rules_file} (skipping)")
            return True
        
        if not imported_rules:
            print("  No rules to delete")
            return True
        
        # Get all rules from FTD
        print("  Retrieving access rules from FTD...")
        ftd_rules = self.get_all_objects("/policy/accesspolicies/default/accessrules")
        
        # Match imported rules with FTD rules by name
        print(f"  Found {len(ftd_rules)} rules in FTD")
        print(f"  Looking for {len(imported_rules)} imported rules to delete...")
        
        all_success = True
        for imported_rule in imported_rules:
            imported_name = imported_rule.get("name", "")
            
            # Find matching rule in FTD
            matching_rule = None
            for ftd_rule in ftd_rules:
                if ftd_rule.get("name") == imported_name:
                    matching_rule = ftd_rule
                    break
            
            if matching_rule:
                rule_id = matching_rule.get("id")
                
                if dry_run:
                    print(f"  [DRY RUN] Would delete: {imported_name}")
                    self.stats["rules_deleted"] += 1
                else:
                    print(f"  Deleting: {imported_name}...", end=" ")
                    success = self.delete_object("/policy/accesspolicies/default/accessrules", rule_id) # pyright: ignore[reportArgumentType]
                    
                    if success:
                        print("✓")
                        self.stats["rules_deleted"] += 1
                    else:
                        print("✗")
                        self.stats["rules_failed"] += 1
                        all_success = False
                    
                    time.sleep(0.2)
            else:
                print(f"  Not found in FTD: {imported_name}")
        
        return all_success
    
    def delete_static_routes(self, routes_file: str, dry_run: bool = False) -> bool:
        """
        Delete static routes from FTD based on imported file.
        
        Args:
            routes_file: Path to JSON file with imported routes
            dry_run: If True, only show what would be deleted
            
        Returns:
            True if all deletions successful, False if any failed
        """
        print(f"\n{'-'*60}")
        print(f"Processing Static Routes from {routes_file}")
        print(f"{'-'*60}")
        
        try:
            with open(routes_file, 'r') as f:
                imported_routes = json.load(f)
        except FileNotFoundError:
            print(f"  File not found: {routes_file} (skipping)")
            return True
        except json.JSONDecodeError:
            print(f"  Invalid JSON in {routes_file} (skipping)")
            return True
        
        if not imported_routes:
            print("  No routes to delete")
            return True
        
        print("  Retrieving static routes from FTD...")
        ftd_routes = self.get_all_objects("/devices/default/routing/staticrouteentries")
        
        print(f"  Found {len(ftd_routes)} routes in FTD")
        print(f"  Looking for {len(imported_routes)} imported routes to delete...")
        
        all_success = True
        for imported_route in imported_routes:
            imported_name = imported_route.get("name", "")
            
            matching_route = None
            for ftd_route in ftd_routes:
                if ftd_route.get("name") == imported_name:
                    matching_route = ftd_route
                    break
            
            if matching_route:
                route_id = matching_route.get("id")
                
                if dry_run:
                    print(f"  [DRY RUN] Would delete: {imported_name}")
                    self.stats["routes_deleted"] += 1
                else:
                    print(f"  Deleting: {imported_name}...", end=" ")
                    success = self.delete_object("/devices/default/routing/staticrouteentries", route_id) # pyright: ignore[reportArgumentType]
                    
                    if success:
                        print("✓")
                        self.stats["routes_deleted"] += 1
                    else:
                        print("✗")
                        self.stats["routes_failed"] += 1
                        all_success = False
                    
                    time.sleep(0.2)
            else:
                print(f"  Not found in FTD: {imported_name}")
        
        return all_success
    
    def delete_port_groups(self, groups_file: str, dry_run: bool = False) -> bool:
        """Delete port groups from FTD."""
        return self._delete_generic_objects(
            groups_file, 
            "/object/portgroups",
            "Port Groups",
            "port_groups_deleted",
            "port_groups_failed",
            dry_run
        )
    
    def delete_port_objects(self, objects_file: str, dry_run: bool = False) -> bool:
        """Delete port objects (TCP and UDP) from FTD."""
        print(f"\n{'-'*60}")
        print(f"Processing Port Objects from {objects_file}")
        print(f"{'-'*60}")
        
        try:
            with open(objects_file, 'r') as f:
                imported_objects = json.load(f)
        except FileNotFoundError:
            print(f"  File not found: {objects_file} (skipping)")
            return True
        except json.JSONDecodeError:
            print(f"  Invalid JSON in {objects_file} (skipping)")
            return True
        
        if not imported_objects:
            print("  No port objects to delete")
            return True
        
        # Get TCP and UDP port objects from FTD
        print("  Retrieving port objects from FTD...")
        ftd_tcp_ports = self.get_all_objects("/object/tcpports")
        ftd_udp_ports = self.get_all_objects("/object/udpports")
        ftd_all_ports = ftd_tcp_ports + ftd_udp_ports
        
        print(f"  Found {len(ftd_all_ports)} port objects in FTD")
        print(f"  Looking for {len(imported_objects)} imported objects to delete...")
        
        all_success = True
        for imported_obj in imported_objects:
            imported_name = imported_obj.get("name", "")
            obj_type = imported_obj.get("type", "")
            
            matching_obj = None
            for ftd_obj in ftd_all_ports:
                if ftd_obj.get("name") == imported_name:
                    matching_obj = ftd_obj
                    break
            
            if matching_obj:
                obj_id = matching_obj.get("id")
                
                # Determine endpoint based on type
                if obj_type == "tcpportobject" or matching_obj.get("type") == "tcpportobject":
                    endpoint = "/object/tcpports"
                else:
                    endpoint = "/object/udpports"
                
                if dry_run:
                    print(f"  [DRY RUN] Would delete: {imported_name} ({obj_type})")
                    self.stats["port_objects_deleted"] += 1
                else:
                    print(f"  Deleting: {imported_name} ({obj_type})...", end=" ")
                    success = self.delete_object(endpoint, obj_id) # pyright: ignore[reportArgumentType]
                    
                    if success:
                        print("✓")
                        self.stats["port_objects_deleted"] += 1
                    else:
                        print("✗")
                        self.stats["port_objects_failed"] += 1
                        all_success = False
                    
                    time.sleep(0.2)
            else:
                print(f"  Not found in FTD: {imported_name}")
        
        return all_success
    
    def delete_address_groups(self, groups_file: str, dry_run: bool = False) -> bool:
        """Delete address groups from FTD."""
        return self._delete_generic_objects(
            groups_file,
            "/object/networkgroups",
            "Address Groups",
            "address_groups_deleted",
            "address_groups_failed",
            dry_run
        )
    
    def delete_address_objects(self, objects_file: str, dry_run: bool = False) -> bool:
        """Delete address objects from FTD."""
        return self._delete_generic_objects(
            objects_file,
            "/object/networks",
            "Address Objects",
            "address_objects_deleted",
            "address_objects_failed",
            dry_run
        )
    
    def _delete_generic_objects(self, file_path: str, endpoint: str, 
                                object_type: str, success_stat: str, 
                                fail_stat: str, dry_run: bool = False) -> bool:
        """
        Generic method to delete objects from FTD.
        
        Args:
            file_path: Path to JSON file
            endpoint: API endpoint
            object_type: Type name for display
            success_stat: Statistics key for successful deletions
            fail_stat: Statistics key for failed deletions
            dry_run: If True, only show what would be deleted
        """
        print(f"\n{'-'*60}")
        print(f"Processing {object_type} from {file_path}")
        print(f"{'-'*60}")
        
        try:
            with open(file_path, 'r') as f:
                imported_objects = json.load(f)
        except FileNotFoundError:
            print(f"  File not found: {file_path} (skipping)")
            return True
        except json.JSONDecodeError:
            print(f"  Invalid JSON in {file_path} (skipping)")
            return True
        
        if not imported_objects:
            print(f"  No {object_type.lower()} to delete")
            return True
        
        print(f"  Retrieving {object_type.lower()} from FTD...")
        ftd_objects = self.get_all_objects(endpoint)
        
        print(f"  Found {len(ftd_objects)} {object_type.lower()} in FTD")
        print(f"  Looking for {len(imported_objects)} imported objects to delete...")
        
        all_success = True
        for imported_obj in imported_objects:
            imported_name = imported_obj.get("name", "")
            
            matching_obj = None
            for ftd_obj in ftd_objects:
                if ftd_obj.get("name") == imported_name:
                    matching_obj = ftd_obj
                    break
            
            if matching_obj:
                obj_id = matching_obj.get("id")
                
                if dry_run:
                    print(f"  [DRY RUN] Would delete: {imported_name}")
                    self.stats[success_stat] += 1
                else:
                    print(f"  Deleting: {imported_name}...", end=" ")
                    success = self.delete_object(endpoint, obj_id) # pyright: ignore[reportArgumentType]
                    
                    if success:
                        print("✓")
                        self.stats[success_stat] += 1
                    else:
                        print("✗")
                        self.stats[fail_stat] += 1
                        all_success = False
                    
                    time.sleep(0.2)
            else:
                print(f"  Not found in FTD: {imported_name}")
        
        return all_success
    
    def deploy_changes(self) -> bool:
        """Deploy pending configuration changes to FTD."""
        print(f"\n{'='*60}")
        print("Deploying configuration changes...")
        print(f"{'='*60}")
        
        endpoint = f"{self.base_url}/operational/deploy"
        
        try:
            response = self.session.post(endpoint, json={}, timeout=30)
            
            if response.status_code in [200, 201, 202]:
                print("✓ Deployment initiated successfully")
                print("  Note: Deployment may take several minutes to complete")
                return True
            else:
                print(f"✗ Deployment failed: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Deployment error: {e}")
            return False
    
    def print_statistics(self):
        """Print deletion statistics."""
        print(f"\n{'='*60}")
        print("DELETION STATISTICS")
        print(f"{'='*60}")
        print(f"\nAccess Rules:")
        print(f"  Deleted: {self.stats['rules_deleted']}")
        print(f"  Failed:  {self.stats['rules_failed']}")
        print(f"\nStatic Routes:")
        print(f"  Deleted: {self.stats['routes_deleted']}")
        print(f"  Failed:  {self.stats['routes_failed']}")
        print(f"\nPort Groups:")
        print(f"  Deleted: {self.stats['port_groups_deleted']}")
        print(f"  Failed:  {self.stats['port_groups_failed']}")
        print(f"\nPort Objects:")
        print(f"  Deleted: {self.stats['port_objects_deleted']}")
        print(f"  Failed:  {self.stats['port_objects_failed']}")
        print(f"\nAddress Groups:")
        print(f"  Deleted: {self.stats['address_groups_deleted']}")
        print(f"  Failed:  {self.stats['address_groups_failed']}")
        print(f"\nAddress Objects:")
        print(f"  Deleted: {self.stats['address_objects_deleted']}")
        print(f"  Failed:  {self.stats['address_objects_failed']}")
        
        total_deleted = sum([
            self.stats['rules_deleted'],
            self.stats['routes_deleted'],
            self.stats['port_groups_deleted'],
            self.stats['port_objects_deleted'],
            self.stats['address_groups_deleted'],
            self.stats['address_objects_deleted']
        ])
        
        total_failed = sum([
            self.stats['rules_failed'],
            self.stats['routes_failed'],
            self.stats['port_groups_failed'],
            self.stats['port_objects_failed'],
            self.stats['address_groups_failed'],
            self.stats['address_objects_failed']
        ])
        
        print(f"\nTOTAL:")
        print(f"  Deleted: {total_deleted}")
        print(f"  Failed:  {total_failed}")
        print(f"\n{'='*60}")


def main():
    """Main function to orchestrate the cleanup process."""
    parser = argparse.ArgumentParser(
        description='Delete imported configurations from Cisco FTD via FDM API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
⚠️  WARNING: THIS DELETES CONFIGURATION FROM YOUR FIREWALL! ⚠️

Examples:
  # Dry run (preview what will be deleted)
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --dry-run
  
  # Delete everything
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --base ftd_config
  
  # Delete only address objects
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --only-address-objects
  
  # Delete and deploy
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --deploy
        """
    )
    
    parser.add_argument('--host', required=True,
                       help='FTD management IP address or hostname')
    parser.add_argument('-u', '--username', required=True,
                       help='FDM username (typically "admin")')
    parser.add_argument('-p', '--password',
                       help='FDM password (will prompt if not provided)')
    parser.add_argument('--base', default='ftd_config',
                       help='Base name of JSON files (default: ftd_config)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be deleted without actually deleting')
    parser.add_argument('--deploy', action='store_true',
                       help='Automatically deploy changes after deletion')
    parser.add_argument('--skip-verify', action='store_true', default=True,
                       help='Skip SSL certificate verification (default: True)')
    parser.add_argument('--yes', action='store_true',
                       help='Skip confirmation prompt (dangerous!)')
    
    # Selective deletion options
    parser.add_argument('--only-address-objects', action='store_true',
                       help='Delete only address objects')
    parser.add_argument('--only-address-groups', action='store_true',
                       help='Delete only address groups')
    parser.add_argument('--only-service-objects', action='store_true',
                       help='Delete only service objects')
    parser.add_argument('--only-service-groups', action='store_true',
                       help='Delete only service groups')
    parser.add_argument('--only-routes', action='store_true',
                       help='Delete only static routes')
    parser.add_argument('--only-rules', action='store_true',
                       help='Delete only access rules')
    
    args = parser.parse_args()
    
    # Prompt for password if not provided
    if not args.password:
        args.password = getpass.getpass(f"Enter password for {args.username}: ")
    
    # Safety confirmation
    if not args.dry_run and not args.yes:
        print("\n" + "="*60)
        print("⚠️  WARNING: YOU ARE ABOUT TO DELETE CONFIGURATION! ⚠️")
        print("="*60)
        print("\nThis will delete imported objects from your FTD firewall.")
        print("This action cannot be undone without restoring from backup.")
        print("\nRecommended: Run with --dry-run first to preview changes.")
        print("\nHave you backed up your FTD configuration? (yes/no): ", end="")
        
        backup_confirm = input().strip().lower()
        if backup_confirm != 'yes':
            print("\n✗ Please backup your configuration first!")
            return 1
        
        print("\nAre you sure you want to proceed? (yes/no): ", end="")
        confirm = input().strip().lower()
        if confirm != 'yes':
            print("\n✗ Operation cancelled")
            return 1
    
    # Create API client
    client = FTDAPICleanup(
        host=args.host,
        username=args.username,
        password=args.password,
        verify_ssl=not args.skip_verify
    )
    
    # Authenticate
    if not client.authenticate():
        print("\n✗ Authentication failed. Exiting.")
        return 1
    
    # Display mode
    mode = "DRY RUN" if args.dry_run else "DELETE"
    print(f"\n{'='*60}")
    print(f"Starting Cleanup Process - {mode} MODE")
    print(f"{'='*60}")
    
    # Determine what to delete
    delete_all = not any([
        args.only_address_objects,
        args.only_address_groups,
        args.only_service_objects,
        args.only_service_groups,
        args.only_routes,
        args.only_rules
    ])
    
    # Delete in reverse dependency order
    if delete_all or args.only_rules:
        client.delete_access_rules(f"{args.base}_access_rules.json", args.dry_run)
    
    if delete_all or args.only_routes:
        client.delete_static_routes(f"{args.base}_static_routes.json", args.dry_run)
    
    if delete_all or args.only_service_groups:
        client.delete_port_groups(f"{args.base}_service_groups.json", args.dry_run)
    
    if delete_all or args.only_service_objects:
        client.delete_port_objects(f"{args.base}_service_objects.json", args.dry_run)
    
    if delete_all or args.only_address_groups:
        client.delete_address_groups(f"{args.base}_address_groups.json", args.dry_run)
    
    if delete_all or args.only_address_objects:
        client.delete_address_objects(f"{args.base}_address_objects.json", args.dry_run)
    
    # Print statistics
    client.print_statistics()
    
    # Deploy if requested and not dry run
    if args.deploy and not args.dry_run:
        client.deploy_changes()
    elif not args.dry_run:
        print(f"\n{'='*60}")
        print("Deletion complete. Changes are pending deployment.")
        print("To deploy:")
        print("  1. Run this script again with --deploy flag")
        print("  2. Deploy manually from FDM web interface")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print("DRY RUN complete - no actual changes made")
        print("Remove --dry-run flag to perform actual deletion")
        print(f"{'='*60}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())