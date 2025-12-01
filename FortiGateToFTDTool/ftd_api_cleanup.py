#!/usr/bin/env python3
"""
Cisco FTD FDM API Bulk Delete Script
=====================================
This script deletes ALL custom objects of specified types from Cisco FTD.

âš ï¸  WARNING: THIS DELETES ALL CUSTOM CONFIGURATION! âš ï¸
    - This does NOT use import files - it deletes EVERYTHING it finds
    - Only deletes custom objects (skips system-defined objects)
    - Always backup your FTD configuration before running
    - Test in a lab environment first
    - Cannot be undone without restoring from backup

REQUIREMENTS:
    - Python 3.6 or higher
    - requests library (install with: pip install requests)
    - urllib3 library (install with: pip install urllib3)

WHAT THIS SCRIPT DOES:
    1. Authenticates to FTD FDM API
    2. Retrieves ALL objects of the specified type from FTD
    3. Filters out system-defined objects (keeps only custom objects)
    4. Deletes all custom objects found
    5. Optionally deploys changes

HOW TO RUN:
    python ftd_api_cleanup.py --host 192.168.1.1 --username admin --delete-address-objects

SAFETY FEATURES:
    - Dry-run mode (preview without deleting)
    - Interactive confirmation required
    - Only deletes custom objects (system-defined are protected)
    - Detailed logging of what's being deleted
"""

import requests
import argparse
import sys
import time
import getpass
import urllib3
from typing import Dict, List, Optional

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FTDBulkDelete:
    """
    Client for bulk deleting all objects from Cisco FTD via FDM API.
    """
    
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False, debug: bool = False):
        """
        Initialize the FTD API client.
        
        Args:
            host: FTD management IP address or hostname
            username: FDM username
            password: FDM password
            verify_ssl: Whether to verify SSL certificates
            debug: Enable debug output
        """
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.debug = debug
        
        self.base_url = f"https://{host}/api/fdm/latest"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        
        self.access_token = None
        self.refresh_token = None
        
        # Track statistics
        self.stats = {
            "total_found": 0,
            "system_objects": 0,
            "custom_objects": 0,
            "deleted": 0,
            "failed": 0
        }
    
    def authenticate(self) -> bool:
        """Authenticate to FTD FDM API."""
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
                
                print("âœ“ Authentication successful")
                return True
            else:
                print(f"âœ— Authentication failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"âœ— Connection error: {e}")
            return False
    
    def get_all_objects(self, endpoint: str) -> List[Dict]:
        """
        Retrieve ALL objects from FTD endpoint with pagination.
        
        Args:
            endpoint: API endpoint path
            
        Returns:
            List of all objects
        """
        url = f"{self.base_url}{endpoint}"
        all_items = []
        offset = 0
        limit = 100
        
        try:
            print(f"  Fetching from {endpoint}...")
            
            while True:
                params = {"offset": offset, "limit": limit}
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("items", [])
                    
                    if self.debug:
                        print(f"    Retrieved {len(items)} objects (offset: {offset})")
                    
                    # Debug: Show first object
                    if self.debug and items and offset == 0:
                        print(f"\n    [DEBUG] First object:")
                        print(f"      Name: {items[0].get('name')}")
                        print(f"      ID: {items[0].get('id')}")
                        print(f"      Type: {items[0].get('type')}")
                        print(f"      isSystemDefined: {items[0].get('isSystemDefined')}\n")
                    
                    if not items:
                        break
                    
                    all_items.extend(items)
                    offset += limit
                    
                    # Check pagination
                    paging = data.get("paging", {})
                    if not paging.get("next"):
                        break
                    
                    # Safety limit
                    if offset > 10000:
                        print(f"    Warning: Stopped at {offset} objects (safety limit)")
                        break
                else:
                    print(f"    Warning: HTTP {response.status_code}")
                    if self.debug:
                        print(f"    Response: {response.text[:200]}")
                    break
            
            print(f"  Total retrieved: {len(all_items)} objects")
            return all_items
            
        except requests.exceptions.RequestException as e:
            print(f"  Error: {e}")
            return []
    
    def delete_object(self, endpoint: str, object_id: str) -> bool:
        """Delete a single object by ID."""
        url = f"{self.base_url}{endpoint}/{object_id}"
        
        try:
            response = self.session.delete(url, timeout=30)
            
            if response.status_code in [200, 204]:
                return True
            elif response.status_code == 404:
                return True  # Already gone
            else:
                if self.debug:
                    print(f" (HTTP {response.status_code})")
                return False
                
        except requests.exceptions.RequestException:
            return False
    
    def delete_all_custom_objects(self, endpoint: str, object_type: str, dry_run: bool = False) -> bool:
        """
        Delete ALL custom (non-system) objects of a type.
        
        Args:
            endpoint: API endpoint
            object_type: Type name for display
            dry_run: If True, only show what would be deleted
            
        Returns:
            True if successful
        """
        print(f"\n{'='*60}")
        print(f"Processing {object_type}")
        print(f"{'='*60}")
        
        # Get ALL objects from FTD
        all_objects = self.get_all_objects(endpoint)
        
        if not all_objects:
            print(f"  No {object_type.lower()} found in FTD")
            return True
        
        self.stats["total_found"] = len(all_objects)
        
        # Filter out system-defined objects
        custom_objects = [obj for obj in all_objects if not obj.get('isSystemDefined', False)]
        system_objects = [obj for obj in all_objects if obj.get('isSystemDefined', False)]
        
        self.stats["custom_objects"] = len(custom_objects)
        self.stats["system_objects"] = len(system_objects)
        
        print(f"\n  Found {len(all_objects)} total objects:")
        print(f"    - Custom objects: {len(custom_objects)} (will be deleted)")
        print(f"    - System objects: {len(system_objects)} (protected)")
        
        if not custom_objects:
            print(f"\n  No custom {object_type.lower()} to delete")
            return True
        
        # Show sample of what will be deleted
        print(f"\n  Sample custom objects found:")
        for obj in custom_objects[:10]:
            name = obj.get('name', 'UNNAMED')
            obj_id = obj.get('id', 'NO_ID')
            print(f"    - {name} (ID: {obj_id[:20]}...)")
        
        if len(custom_objects) > 10:
            print(f"    ... and {len(custom_objects) - 10} more")
        
        # Delete custom objects
        print(f"\n  {'[DRY RUN] Would delete' if dry_run else 'Deleting'} {len(custom_objects)} custom objects...")
        
        success_count = 0
        fail_count = 0
        
        for i, obj in enumerate(custom_objects, 1):
            name = obj.get('name', 'UNNAMED')
            obj_id = obj.get('id')
            
            if not obj_id:
                print(f"  [{i}/{len(custom_objects)}] Error: {name} - No ID")
                fail_count += 1
                continue
            
            if dry_run:
                print(f"  [{i}/{len(custom_objects)}] Would delete: {name}")
                success_count += 1
            else:
                print(f"  [{i}/{len(custom_objects)}] Deleting: {name}...", end=" ")
                
                success = self.delete_object(endpoint, obj_id)
                
                if success:
                    print("âœ“")
                    success_count += 1
                else:
                    print("âœ—")
                    fail_count += 1
                
                time.sleep(0.2)  # Rate limiting
        
        self.stats["deleted"] = success_count
        self.stats["failed"] = fail_count
        
        print(f"\n  Summary:")
        print(f"    Deleted: {success_count}")
        print(f"    Failed: {fail_count}")
        
        return fail_count == 0
    
    def deploy_changes(self) -> bool:
        """Deploy pending changes."""
        print(f"\n{'='*60}")
        print("Deploying configuration changes...")
        print(f"{'='*60}")
        
        endpoint = f"{self.base_url}/operational/deploy"
        
        try:
            response = self.session.post(endpoint, json={}, timeout=30)
            
            if response.status_code in [200, 201, 202]:
                print("âœ“ Deployment initiated")
                print("  (Deployment may take several minutes)")
                return True
            else:
                print(f"âœ— Deployment failed: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"âœ— Deployment error: {e}")
            return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Bulk delete ALL custom objects from Cisco FTD via FDM API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
âš ï¸  WARNING: DELETES ALL CUSTOM OBJECTS OF SELECTED TYPES! âš ï¸

Examples:
  # Dry run - see what would be deleted
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects --dry-run
  
  # Delete all address objects
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects
  
  # Delete all rules
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-rules
  
  # Delete everything
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all
        """
    )
    
    parser.add_argument('--host', required=True, help='FTD management IP')
    parser.add_argument('-u', '--username', required=True, help='FDM username')
    parser.add_argument('-p', '--password', help='FDM password')
    parser.add_argument('--dry-run', action='store_true', help='Preview without deleting')
    parser.add_argument('--deploy', action='store_true', help='Deploy after deletion')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation')
    
    # Object type selection
    parser.add_argument('--delete-address-objects', action='store_true', help='Delete all address objects')
    parser.add_argument('--delete-address-groups', action='store_true', help='Delete all address groups')
    parser.add_argument('--delete-service-objects', action='store_true', help='Delete all service objects')
    parser.add_argument('--delete-service-groups', action='store_true', help='Delete all service groups')
    parser.add_argument('--delete-routes', action='store_true', help='Delete all static routes')
    parser.add_argument('--delete-rules', action='store_true', help='Delete all access rules')
    parser.add_argument('--delete-all', action='store_true', help='Delete ALL custom objects (everything)')
    
    args = parser.parse_args()
    
    # Check if at least one delete option is selected
    if not any([args.delete_address_objects, args.delete_address_groups, 
                args.delete_service_objects, args.delete_service_groups,
                args.delete_routes, args.delete_rules, args.delete_all]):
        parser.error("Must specify at least one --delete-* option")
    
    # Prompt for password
    if not args.password:
        args.password = getpass.getpass(f"Enter password for {args.username}: ")
    
    # Safety confirmation
    if not args.dry_run and not args.yes:
        print("\n" + "="*60)
        print("âš ï¸  FINAL WARNING âš ï¸")
        print("="*60)
        print("\nThis will DELETE ALL CUSTOM OBJECTS of the selected types!")
        print("This does NOT check import files - it deletes EVERYTHING it finds.")
        print("\nOnly system-defined objects will be preserved.")
        print("\nHave you backed up your FTD? (yes/no): ", end="")
        
        backup = input().strip().lower()
        if backup != 'yes':
            print("\nâœ— Please backup first!")
            return 1
        
        print("\nType 'DELETE ALL' to confirm: ", end="")
        confirm = input().strip()
        if confirm != 'DELETE ALL':
            print("\nâœ— Cancelled")
            return 1
    
    # Create client
    client = FTDBulkDelete(
        host=args.host,
        username=args.username,
        password=args.password,
        debug=args.debug
    )
    
    # Authenticate
    if not client.authenticate():
        return 1
    
    mode = "DRY RUN" if args.dry_run else "DELETE"
    print(f"\n{'='*60}")
    print(f"BULK DELETE MODE: {mode}")
    print(f"{'='*60}")
    
    # Delete in reverse dependency order
    if args.delete_all or args.delete_rules:
        client.delete_all_custom_objects(
            "/policy/accesspolicies/default/accessrules",
            "Access Rules",
            args.dry_run
        )
    
    if args.delete_all or args.delete_routes:
        client.delete_all_custom_objects(
            "/devices/default/routing/staticrouteentries",
            "Static Routes",
            args.dry_run
        )
    
    if args.delete_all or args.delete_service_groups:
        client.delete_all_custom_objects(
            "/object/portgroups",
            "Service Groups",
            args.dry_run
        )
    
    if args.delete_all or args.delete_service_objects:
        # Delete TCP ports
        client.delete_all_custom_objects(
            "/object/tcpports",
            "TCP Port Objects",
            args.dry_run
        )
        # Delete UDP ports
        client.delete_all_custom_objects(
            "/object/udpports",
            "UDP Port Objects",
            args.dry_run
        )
    
    if args.delete_all or args.delete_address_groups:
        client.delete_all_custom_objects(
            "/object/networkgroups",
            "Address Groups",
            args.dry_run
        )
    
    if args.delete_all or args.delete_address_objects:
        client.delete_all_custom_objects(
            "/object/networks",
            "Address Objects",
            args.dry_run
        )
    
    # Deploy if requested
    if args.deploy and not args.dry_run:
        client.deploy_changes()
    
    print(f"\n{'='*60}")
    if args.dry_run:
        print("DRY RUN COMPLETE - No changes made")
        print("Remove --dry-run to actually delete")
    else:
        print("DELETION COMPLETE")
        if not args.deploy:
            print("Changes pending - deploy manually or use --deploy")
    print(f"{'='*60}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())