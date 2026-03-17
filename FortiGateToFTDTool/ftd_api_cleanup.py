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
import json
import argparse
import sys
import time
import getpass
import urllib3
import threading
from typing import Dict, List, Optional, Tuple
from concurrency_utils import run_with_retry, run_indexed_thread_pool
from platform_profiles import is_ftd_1000, is_ftd_3100
from ftd_api_base import FTDBaseClient

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FTDBulkDelete(FTDBaseClient):
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
        super().__init__(host, username, password, verify_ssl, debug)

        # Track cumulative statistics across all deletion phases
        self.stats = {
            "total_found": 0,
            "system_objects": 0,
            "custom_objects": 0,
            "deleted": 0,
            "failed": 0
        }

    def compute_outcome(self) -> tuple:
        """Determine overall run outcome from cumulative stats.

        Returns:
            (exit_code, outcome_label) where:
                0, "SUCCESS"         – every item succeeded
                2, "PARTIAL_FAILURE" – at least one item failed but some succeeded
                3, "ALL_FAILED"      – every attempted item failed
        """
        if self.stats["failed"] == 0:
            return 0, "SUCCESS"
        if self.stats["deleted"] > 0:
            return 2, "PARTIAL_FAILURE"
        return 3, "ALL_FAILED"

    @staticmethod
    def write_json_report(path: str, payload: Dict) -> bool:
        """Write a machine-readable cleanup report to disk."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            return True
        except (OSError, TypeError, ValueError):
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

    def delete_all_static_routes(self, dry_run: bool = False, max_workers: int = 1, max_attempts: int = 4, base_backoff: float = 0.3, max_jitter: float = 0.25) -> bool:
        """
        Delete all static route entries from the default Virtual Router.

        Why this exists:
            The FDM API scopes static route entries under a virtual router:
            - GET/DELETE: /devices/default/routing/virtualrouters/{vr_id}/staticrouteentries

        Args:
            dry_run: If True, do not delete; only print what would happen.

        Returns:
            True if all deletions succeeded (or dry-run), False otherwise.
        """
        print(f"\n{'='*60}")
        print("Processing Static Routes")
        print(f"{'='*60}")

        success, vr_id_or_error = self.get_default_virtual_router_id()
        if not success:
            print(f"  [FAIL] Failed to resolve virtual router: {vr_id_or_error}")
            return False

        vr_id = vr_id_or_error
        endpoint = f"/devices/default/routing/virtualrouters/{vr_id}/staticrouteentries"

        # Fetch all routes under the VR
        routes = self.get_all_objects(endpoint)
        if not routes:
            print("  No static routes found")
            return True

        print(f"\n  Found {len(routes)} static routes")

        # Show what will be deleted
        print(f"\n  Static routes to delete:")
        for r in routes[:10]:
            name = r.get("name", "UNNAMED")
            rid = r.get("id", "")
            print(f"    - {name} (id={rid})")
        if len(routes) > 10:
            print(f"    . and {len(routes) - 10} more")

        if dry_run:
            print(f"\n  [DRY RUN] Would delete {len(routes)} static routes.")
            for i, r in enumerate(routes, 1):
                name = r.get("name", "UNNAMED")
                print(f"  [{i}/{len(routes)}] Would delete: {name}")
            print("\n  Summary: 0 deleted, 0 failed")
            return True

        print(f"\n  Deleting {len(routes)} static routes with up to {max_workers} workers.")

        max_workers = max(1, max_workers)
        print_lock = threading.Lock()
        failure_flag = [False]
        failed_objects = []
        counters = {"deleted": 0, "failed": 0}

        def worker(idx: int, r: Dict) -> None:
            name = r.get("name", "UNNAMED")
            obj_id = r.get("id")

            if not obj_id:
                with print_lock:
                    print(f"  [{idx+1}/{len(routes)}] Skipping: {name} [FAIL] missing id", flush=True)
                    counters["failed"] += 1
                failure_flag[0] = True
                return

            ok, err = run_with_retry(
                lambda: self.delete_object(endpoint, obj_id),
                max_attempts=max_attempts,
                base_backoff=base_backoff,
                max_jitter=max_jitter,
            )
            if ok:
                with print_lock:
                    print(f"  [{idx+1}/{len(routes)}] Deleting: {name}... [OK]", flush=True)
                    counters["deleted"] += 1
                return

            with print_lock:
                print(f"  [{idx+1}/{len(routes)}] Deleting: {name}... [FAIL] {err}", flush=True)
                counters["failed"] += 1
                failed_objects.append((name, err))
            failure_flag[0] = True
            return

        run_indexed_thread_pool(max_workers=max_workers, items=routes, worker=worker)

        self.stats["total_found"] += len(routes)
        self.stats["custom_objects"] += len(routes)
        self.stats["deleted"] += counters["deleted"]
        self.stats["failed"] += counters["failed"]

        print(f"\n  Summary: {counters['deleted']} deleted, {counters['failed']} failed")

        if failed_objects:
            print("\n  Failed routes:")
            for name, err in failed_objects[:10]:
                print(f"    - {name}: {err}")
            if len(failed_objects) > 10:
                print(f"    ... and {len(failed_objects) - 10} more")

        return not failure_flag[0]

    
    def delete_object(self, endpoint: str, object_id: str) -> Tuple[bool, str]:
        """Delete a single object by ID.
        
        Returns:
            Tuple of (success: bool, error_message: str)
        """
        url = f"{self.base_url}{endpoint}/{object_id}"
        
        try:
            response = self.session.delete(url, timeout=30)
            
            if response.status_code in [200, 204]:
                return True, ""
            elif response.status_code == 404:
                return True, "already deleted"  # Already gone
            elif response.status_code == 422:
                # Unprocessable - get the actual error
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                    return False, error_msg
                except (ValueError, KeyError, IndexError, TypeError):
                    return False, f"HTTP 422: {response.text[:100]}"
            elif response.status_code == 400:
                # Bad request - often means object is in use
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', 'Unknown error')
                    return False, error_msg
                except (ValueError, KeyError, IndexError, TypeError):
                    return False, f"HTTP 400: {response.text[:100]}"
            else:
                return False, f"HTTP {response.status_code}"
                
        except requests.exceptions.RequestException as e:
            return False, str(e)
    
    def delete_all_custom_objects(
        self,
        endpoint: str,
        object_type: str,
        dry_run: bool = False,
        max_workers: int = 1,
        max_attempts: int = 4,
        base_backoff: float = 0.3,
        max_jitter: float = 0.25,
    ) -> bool:
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
        
        self.stats["total_found"] += len(all_objects)

        # Filter out system-defined objects
        custom_objects = [obj for obj in all_objects if not obj.get('isSystemDefined', False)]
        system_objects = [obj for obj in all_objects if obj.get('isSystemDefined', False)]

        self.stats["custom_objects"] += len(custom_objects)
        self.stats["system_objects"] += len(system_objects)
        
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
        if dry_run:
            print(f"\n  [DRY RUN] Would delete {len(custom_objects)} custom objects...")
            for i, obj in enumerate(custom_objects, 1):
                name = obj.get('name', 'UNNAMED')
                print(f"  [{i}/{len(custom_objects)}] Would delete: {name}")
            print("\n  Summary:")
            print(f"    Deleted: 0")
            print(f"    Failed: 0")
            return True

        print(f"\n  Deleting {len(custom_objects)} custom objects with up to {max_workers} workers...")

        max_workers = max(1, max_workers)
        print_lock = threading.Lock()
        failure_flag = [False]
        failed_objects = []
        counters = {"deleted": 0, "failed": 0}

        def worker(idx: int, obj: Dict) -> None:
            name = obj.get('name', 'UNNAMED')
            obj_id = obj.get('id')

            if not obj_id:
                with print_lock:
                    print(f"  [{idx+1}/{len(custom_objects)}] Deleting: {name}... [FAIL] missing id", flush=True)
                    counters["failed"] += 1
                failure_flag[0] = True
                return

            success, error_msg = run_with_retry(
                lambda: self.delete_object(endpoint, obj_id),
                max_attempts=max_attempts,
                base_backoff=base_backoff,
                max_jitter=max_jitter,
            )

            if success:
                with print_lock:
                    status = "[SKIP] already deleted" if error_msg == "already deleted" else "[OK]"
                    print(f"  [{idx+1}/{len(custom_objects)}] Deleting: {name}... {status}", flush=True)
                    counters["deleted"] += 1
                return

            with print_lock:
                print(f"  [{idx+1}/{len(custom_objects)}] Deleting: {name}... [FAIL] {error_msg}", flush=True)
                counters["failed"] += 1
                failed_objects.append((name, error_msg))
            failure_flag[0] = True
            return

        run_indexed_thread_pool(max_workers=max_workers, items=custom_objects, worker=worker)

        self.stats["deleted"] += counters["deleted"]
        self.stats["failed"] += counters["failed"]

        print(f"\n  Summary:")
        print(f"    Deleted: {counters['deleted']}")
        print(f"    Failed: {counters['failed']}")

        if failed_objects:
            print(f"\n  Failed objects:")
            for name, error in failed_objects[:10]:
                print(f"    - {name}: {error}")
            if len(failed_objects) > 10:
                print(f"    ... and {len(failed_objects) - 10} more")

        return not failure_flag[0]
    
    @staticmethod
    def _parse_port_number(hardware_name: str) -> Optional[int]:
        """
        Extract the port number from a hardware interface name.
        
        Parses names like 'Ethernet1/9' -> 9, 'Ethernet1/1' -> 1.
        Returns None if the name cannot be parsed (e.g. Management, 
        Port-channel, or unexpected format).
        
        Args:
            hardware_name: Hardware interface name (e.g. 'Ethernet1/9')
            
        Returns:
            Port number as int, or None if not parseable
        """
        # Expected format: "Ethernet<slot>/<port>" e.g. "Ethernet1/9"
        if '/' not in hardware_name:
            return None
        try:
            return int(hardware_name.rsplit('/', 1)[1])
        except (ValueError, IndexError):
            return None
    
    def reset_physical_interface(self, intf: Dict, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Reset a physical interface to default (unconfigured) state.
        
        Physical interfaces cannot be deleted, only reset to defaults.
        This clears the name, IP address, description, resets MTU to 1500,
        disables the interface, and sets speed/duplex/FEC to AUTO defaults.
        
        IMPORTANT: For SFP interfaces, the following defaults are required
        before the interface can be added to an EtherChannel:
            - speedType: DETECT_SFP or AUTO
            - fecMode: AUTO
            - autoNegotiation: True (enabled)
            - duplexType: FULL
        
        Args:
            intf: Interface object from FTD
            dry_run: If True, only show what would be reset
            
        Returns:
            Tuple of (success: bool, error_message: str)
        """
        intf_id = intf.get('id')
        hardware_name = intf.get('hardwareName', 'Unknown')
        
        if not intf_id:
            return False, "No interface ID"
        
        if dry_run:
            return True, ""
        
        # Build reset payload - start with existing interface and modify
        reset_payload = intf.copy()
        
        # Clear logical configuration
        reset_payload['name'] = ''  # Clear logical name
        reset_payload['enabled'] = False  # Disable interface
        reset_payload['description'] = ''  # Clear description
        reset_payload['mtu'] = 1500  # Reset MTU to default
        
        # Clear IP configuration - set to None or remove
        reset_payload['ipv4'] = None
        reset_payload['ipv6'] = None

        # Disable HA interface monitoring before resetting.
        # On HA-enabled appliances (e.g. FTD-3120), physical interfaces
        # default to monitorInterface=True.  The API may reject a PUT that
        # changes the interface configuration while it is still on the
        # HA-monitored list.  Setting this to False first ensures the
        # reset payload is accepted.
        reset_payload['monitorInterface'] = False

        # Reset mode to ROUTED
        reset_payload['mode'] = 'ROUTED'
        
        # Reset speed/duplex/FEC settings
        # IMPORTANT: Both speed and duplex must be AUTO together, or both specific.
        # CRITICAL: After an interface leaves an EtherChannel or bridge group,
        #           FTD may change the reported speedType (e.g. SFP port reports
        #           THOUSAND instead of SFP_DETECT). We CANNOT trust speedType
        #           alone to detect port media type. Use hardware port number on
        #           known platforms as the authoritative source.
        
        # Remove old field names if present
        reset_payload.pop('duplex', None)
        
        current_speed = intf.get('speedType', None)
        
        # Get the appliance model for platform-specific behavior
        model = str(getattr(self, 'appliance_model', 'generic')).lower().strip()
        
        # --- Determine if the port is SFP or copper ---
        # On known platforms we use the hardware port number because speedType
        # is unreliable after EtherChannel/bridge-group membership changes.
        # FTD-3120 port layout: Ethernet1/1-1/8 = copper, Ethernet1/9-1/16 = SFP
        # FTD-3110 port layout: Ethernet1/1-1/8 = copper, Ethernet1/9-1/12 = SFP
        # FTD-3130 port layout: Ethernet1/1-1/8 = copper, Ethernet1/9-1/20 = SFP
        # FTD-3140 port layout: Ethernet1/1-1/8 = copper, Ethernet1/9-1/24 = SFP
        is_sfp = current_speed in {'DETECT_SFP', 'SFP_DETECT'}  # default fallback
        
        if is_ftd_3100(model):
            # Parse port number from hardwareName (e.g. "Ethernet1/9" -> 9)
            port_num = self._parse_port_number(hardware_name)
            if port_num is not None:
                # On all 3100-series: ports 1-8 are copper, 9+ are SFP
                is_sfp = port_num >= 9
        
        if is_sfp:
            # SFP interface - use SFP_DETECT with FULL duplex
            reset_payload['speedType'] = 'SFP_DETECT'
            reset_payload['duplexType'] = 'FULL'
            if 'fecMode' in intf:
                reset_payload['fecMode'] = 'AUTO'
            # Only set autoNeg for platforms that support it
            if not is_ftd_1000(model):
                reset_payload['autoNegotiation'] = True
                reset_payload['autoNeg'] = True
            else:
                # 1000-series: remove autoNeg fields entirely
                reset_payload.pop('autoNeg', None)
                reset_payload.pop('autoNegotiation', None)
                
        elif is_ftd_3100(model):
            # 3100-series copper: Cannot use AUTO speed, must use THOUSAND
            reset_payload['speedType'] = 'THOUSAND'
            reset_payload['duplexType'] = 'FULL'
            reset_payload['autoNegotiation'] = True
            reset_payload['autoNeg'] = True
            
        elif is_ftd_1000(model):
            # 1000-series copper: Support AUTO speed, do NOT support autoNeg
            reset_payload['speedType'] = 'AUTO'
            reset_payload['duplexType'] = 'AUTO'
            reset_payload.pop('autoNeg', None)
            reset_payload.pop('autoNegotiation', None)
            
        else:
            # Default for 2000-series and unknown platforms
            reset_payload['speedType'] = 'AUTO'
            reset_payload['duplexType'] = 'AUTO'
            reset_payload['autoNegotiation'] = True
        
        # Remove ALL switchport-specific fields that are incompatible with ROUTED mode
        switchport_fields = [
            'switchPortMode',
            'switchPortConfig', 
            'nativeVlan',
            'allowedVlans',
            'voiceVlan',
            'spanningTreePortfast',
            'stpGuardType',
            'stpPathCost',
            'stpPortPriority',
            'vlanId'
        ]
        for field in switchport_fields:
            reset_payload.pop(field, None)
        
        # Clear security zone assignment
        if 'securityZone' in reset_payload:
            reset_payload['securityZone'] = None
        
        # PUT request to update
        endpoint = f"{self.base_url}/devices/default/interfaces/{intf_id}"
        
        try:
            response = self.session.put(endpoint, json=reset_payload, timeout=30)
            
            if response.status_code in [200, 201, 204]:
                return True, ""
            else:
                # Extract detailed error message
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', {}).get('messages', [{}])[0].get('description', response.text[:200])
                except:
                    error_msg = response.text[:200]
                return False, f"HTTP {response.status_code}: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            return False, str(e)
    
    def reset_all_physical_interfaces(self, dry_run: bool = False, delay: float = 0.2) -> bool:
        """
        Reset ALL physical interfaces to default state.
        
        Resets:
        - Name (cleared)
        - Description (cleared)
        - IPv4 address (cleared)
        - MTU (reset to 1500)
        - Enabled (set to False)
        - Security Zone (cleared)
        
        Args:
            dry_run: If True, only show what would be reset
            
        Returns:
            True if successful
        """
        print(f"\n{'='*60}")
        print("Processing Physical Interfaces (Reset to Default)")
        print(f"{'='*60}")
        print("  Reset includes: name, description, IP, MTUâ†’1500, disabled")
        
        # Get all interfaces
        all_interfaces = self.get_all_objects("/devices/default/interfaces")
        
        if not all_interfaces:
            print("  No interfaces found")
            return True
        
        # Filter to only physical interfaces that have been configured
        # (have a name, IP address, or non-default MTU)
        configured_interfaces = []
        for intf in all_interfaces:
            intf_type = intf.get('type', '')
            name = intf.get('name', '')
            ipv4 = intf.get('ipv4')
            hardware = intf.get('hardwareName', '')
            mtu = intf.get('mtu', 1500)
            
            # Only process physical interfaces that have configuration
            if intf_type == 'physicalinterface' and (name or ipv4 or mtu != 1500):
                # Skip management interface
                if 'Management' in hardware or 'mgmt' in hardware.lower():
                    continue
                configured_interfaces.append(intf)
        
        print(f"\n  Found {len(all_interfaces)} total interfaces")
        print(f"  Configured (non-default) interfaces: {len(configured_interfaces)}")
        
        if not configured_interfaces:
            print("  No configured interfaces to reset")
            return True
        
        # Show what will be reset
        print(f"\n  Interfaces to reset:")
        for intf in configured_interfaces[:10]:
            hardware = intf.get('hardwareName', 'Unknown')
            name = intf.get('name', '(unnamed)')
            mtu = intf.get('mtu', 1500)
            mtu_note = f" MTU:{mtu}" if mtu != 1500 else ""
            print(f"    - {hardware}: {name}{mtu_note}")
        
        if len(configured_interfaces) > 10:
            print(f"    ... and {len(configured_interfaces) - 10} more")
        
        # Reset interfaces
        print(f"\n  {'[DRY RUN] Would reset' if dry_run else 'Resetting'} {len(configured_interfaces)} interfaces...")
        
        success_count = 0
        fail_count = 0
        
        for i, intf in enumerate(configured_interfaces, 1):
            hardware = intf.get('hardwareName', 'Unknown')
            name = intf.get('name', '(unnamed)')
            
            if dry_run:
                print(f"  [{i}/{len(configured_interfaces)}] Would reset: {hardware} ({name})")
                success_count += 1
            else:
                print(f"  [{i}/{len(configured_interfaces)}] Resetting: {hardware} ({name})...", end=" ")
                
                success, error_msg = self.reset_physical_interface(intf, dry_run)
                
                if success:
                    print("[OK]")
                    success_count += 1
                else:
                    print(f"[FAIL] {error_msg}")
                    fail_count += 1
                
                time.sleep(delay)
        
        self.stats["total_found"] += len(configured_interfaces)
        self.stats["custom_objects"] += len(configured_interfaces)
        self.stats["deleted"] += success_count
        self.stats["failed"] += fail_count

        print(f"\n  Summary:")
        print(f"    Reset: {success_count}")
        print(f"    Failed: {fail_count}")

        return fail_count == 0
    
    def get_all_subinterfaces(self) -> List[Dict]:
        """
        Get all subinterfaces from FTD.
        
        Subinterfaces are accessed via their parent interface:
        - Physical: GET /devices/default/interfaces/{parentId}/subinterfaces
        - EtherChannel: GET /devices/default/etherchannelinterfaces/{parentId}/subinterfaces
        
        Returns:
            List of all subinterfaces found
        """
        all_subinterfaces = []
        
        print("  Scanning for subinterfaces...")
        
        # Check under physical interfaces
        # GET /devices/default/interfaces
        interfaces = self.get_all_objects("/devices/default/interfaces")
        
        if interfaces:
            for intf in interfaces:
                intf_id = intf.get('id')
                intf_type = intf.get('type', '')
                intf_name = intf.get('hardwareName', intf.get('name', ''))
                
                # Only check physical interfaces (not etherchannels which are separate)
                if intf_id and intf_type == 'physicalinterface':
                    subintfs = self.get_all_objects(f"/devices/default/interfaces/{intf_id}/subinterfaces")
                    if subintfs:
                        for si in subintfs:
                            si['_parent_id'] = intf_id
                            si['_parent_name'] = intf_name
                            si['_parent_type'] = 'physical'
                        all_subinterfaces.extend(subintfs)
                        
                        if self.debug:
                            print(f"    Found {len(subintfs)} subinterfaces under {intf_name}")
        
        # Check under etherchannels
        # GET /devices/default/etherchannelinterfaces
        etherchannels = self.get_all_objects("/devices/default/etherchannelinterfaces")
        
        if etherchannels:
            for ec in etherchannels:
                ec_id = ec.get('id')
                ec_name = ec.get('hardwareName', ec.get('name', ''))
                
                if ec_id:
                    subintfs = self.get_all_objects(f"/devices/default/etherchannelinterfaces/{ec_id}/subinterfaces")
                    if subintfs:
                        for si in subintfs:
                            si['_parent_id'] = ec_id
                            si['_parent_name'] = ec_name
                            si['_parent_type'] = 'etherchannel'
                        all_subinterfaces.extend(subintfs)
                        
                        if self.debug:
                            print(f"    Found {len(subintfs)} subinterfaces under {ec_name}")
        
        return all_subinterfaces
    
    def delete_subinterface(self, subintf: Dict, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Delete a single subinterface.
        
        Endpoints:
        - Physical parent: DELETE /devices/default/interfaces/{parentId}/subinterfaces/{objId}
        - EtherChannel parent: DELETE /devices/default/etherchannelinterfaces/{parentId}/subinterfaces/{objId}
        
        Args:
            subintf: Subinterface object dictionary
            dry_run: If True, don't actually delete
            
        Returns:
            Tuple of (success, error_message)
        """
        obj_id = subintf.get('id')
        parent_id = subintf.get('_parent_id')
        parent_type = subintf.get('_parent_type', 'physical')
        
        if not obj_id:
            return False, "No subinterface ID"
        
        if not parent_id:
            return False, "No parent ID"
        
        if dry_run:
            return True, ""

        # Use different endpoint based on parent type
        if parent_type == 'etherchannel':
            endpoint = f"/devices/default/etherchannelinterfaces/{parent_id}/subinterfaces"
        else:
            endpoint = f"/devices/default/interfaces/{parent_id}/subinterfaces"

        # Defensively disable HA monitoring if it is enabled.
        # Subinterfaces are typically monitorInterface=False, but a user
        # may have manually enabled monitoring.  Attempting the DELETE
        # while monitoring is active will be rejected by the API on
        # HA-enabled appliances.
        self._disable_ha_monitor(endpoint, obj_id, f"subintf-{obj_id[:8]}")

        return self.delete_object(endpoint, obj_id)
    
    def delete_all_subinterfaces(self, dry_run: bool = False, delay: float = 0.2) -> bool:
        """
        Delete all subinterfaces.
        
        Subinterfaces must be deleted BEFORE their parent interfaces
        (physical or etherchannel).
        
        Endpoint: DELETE /devices/default/interfaces/{parentId}/subinterfaces/{objId}
        """
        print(f"\n{'='*60}")
        print("Processing Subinterfaces")
        print(f"{'='*60}")
        
        # Get all subinterfaces from all parent interfaces
        all_subinterfaces = self.get_all_subinterfaces()
        
        if not all_subinterfaces:
            print("  No subinterfaces found")
            return True
        
        print(f"\n  Found {len(all_subinterfaces)} subinterfaces total")
        
        # Show what will be deleted
        print(f"\n  Subinterfaces to delete:")
        for intf in all_subinterfaces[:10]:
            name = intf.get('name', 'UNNAMED')
            hardware = intf.get('hardwareName', 'Unknown')
            vlan = intf.get('subIntfId', intf.get('vlanId', '?'))
            parent = intf.get('_parent_name', 'unknown')
            print(f"    - {name} ({hardware} VLAN {vlan}) [parent: {parent}]")
        
        if len(all_subinterfaces) > 10:
            print(f"    ... and {len(all_subinterfaces) - 10} more")
        
        # Delete subinterfaces
        print(f"\n  {'[DRY RUN] Would delete' if dry_run else 'Deleting'} {len(all_subinterfaces)} subinterfaces...")
        
        success_count = 0
        fail_count = 0
        failed_objects = []
        
        for i, intf in enumerate(all_subinterfaces, 1):
            name = intf.get('name', 'UNNAMED')
            
            if dry_run:
                print(f"  [{i}/{len(all_subinterfaces)}] Would delete: {name}")
                success_count += 1
            else:
                print(f"  [{i}/{len(all_subinterfaces)}] Deleting: {name}...", end=" ")
                
                success, error_msg = self.delete_subinterface(intf, dry_run)
                
                if success:
                    print("[OK]")
                    success_count += 1
                else:
                    print(f"[FAIL] {error_msg}")
                    fail_count += 1
                    failed_objects.append((name, error_msg))
                
                time.sleep(delay)
        
        self.stats["total_found"] += len(all_subinterfaces)
        self.stats["custom_objects"] += len(all_subinterfaces)
        self.stats["deleted"] += success_count
        self.stats["failed"] += fail_count

        print(f"\n  Summary: {success_count} deleted, {fail_count} failed")

        if failed_objects:
            print(f"\n  Failed subinterfaces:")
            for name, error in failed_objects[:10]:
                print(f"    - {name}: {error}")
            if len(failed_objects) > 10:
                print(f"    ... and {len(failed_objects) - 10} more")

        return fail_count == 0

    def _disable_ha_monitor(self, endpoint: str, obj_id: str, obj_name: str) -> Tuple[bool, str]:
        """
        Disable HA interface monitoring on an object before deletion.

        On FTD appliances running in HA (High Availability) mode, interfaces
        (including EtherChannels and Bridge Groups) that have
        ``monitorInterface: true`` are on the HA-monitored list.  The FDM API
        will reject a DELETE request on any interface that is still being
        monitored for HA failover.

        This method performs a GET on the object, checks whether
        ``monitorInterface`` is ``True``, and if so, PUTs it back with
        ``monitorInterface`` set to ``False`` so the subsequent DELETE can
        succeed.

        Args:
            endpoint: Full API path to the object collection
                      (e.g. ``/devices/default/etherchannelinterfaces``).
            obj_id:   UUID of the specific object.
            obj_name: Human-readable name for log messages.

        Returns:
            Tuple of (success, error_message).
            ``(True, "")`` when monitoring was already off or was
            successfully disabled.  ``(False, "<reason>")`` on failure.
        """
        url = f"{self.base_url}{endpoint}/{obj_id}"

        try:
            # --- Step 1: GET the current object state -------------------------
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                return False, f"GET failed: HTTP {response.status_code}"

            obj_data = response.json()

            # --- Step 2: Check if HA monitoring is enabled --------------------
            if not obj_data.get("monitorInterface", False):
                # Already off — nothing to do
                return True, ""

            # --- Step 3: PUT with monitorInterface = false --------------------
            obj_data["monitorInterface"] = False

            put_resp = self.session.put(url, json=obj_data, timeout=30)
            if put_resp.status_code in (200, 201, 204):
                if self.debug:
                    print(f"    [DEBUG] Disabled HA monitor on {obj_name}")
                return True, ""

            # Extract meaningful error from the response body
            try:
                err = put_resp.json()
                msg = (
                    err.get("error", {})
                    .get("messages", [{}])[0]
                    .get("description", put_resp.text[:200])
                )
            except Exception:
                msg = put_resp.text[:200]

            return False, f"PUT failed (disable HA monitor): HTTP {put_resp.status_code}: {msg}"

        except requests.exceptions.RequestException as exc:
            return False, f"Request error (disable HA monitor): {exc}"

    def delete_all_etherchannels(self, dry_run: bool = False, delay: float = 0.3) -> bool:
        """
        Delete all EtherChannel interfaces.
        
        NOTE: Subinterfaces on etherchannels must be deleted first.
        This method will attempt to remove member interfaces before deletion.
        """
        print(f"\n{'='*60}")
        print("Processing EtherChannels")
        print(f"{'='*60}")
        
        # Get all etherchannels
        all_etherchannels = self.get_all_objects("/devices/default/etherchannelinterfaces")
        
        if not all_etherchannels:
            print("  No etherchannels found")
            return True
        
        print(f"\n  Found {len(all_etherchannels)} etherchannels")
        
        # Show what will be deleted
        print(f"\n  EtherChannels to delete:")
        for intf in all_etherchannels[:10]:
            name = intf.get('name', 'UNNAMED')
            hardware = intf.get('hardwareName', 'Unknown')
            members = intf.get('selectedInterfaces', [])
            member_count = len(members) if members else 0
            print(f"    - {name} ({hardware}, {member_count} members)")
        
        if len(all_etherchannels) > 10:
            print(f"    ... and {len(all_etherchannels) - 10} more")
        
        # Delete etherchannels
        print(f"\n  {'[DRY RUN] Would delete' if dry_run else 'Deleting'} {len(all_etherchannels)} etherchannels...")
        
        success_count = 0
        fail_count = 0
        
        for i, intf in enumerate(all_etherchannels, 1):
            name = intf.get('name', 'UNNAMED')
            obj_id = intf.get('id')
            hardware = intf.get('hardwareName', 'Unknown')
            
            if dry_run:
                print(f"  [{i}/{len(all_etherchannels)}] Would delete: {name} ({hardware})")
                success_count += 1
            else:
                print(f"  [{i}/{len(all_etherchannels)}] Deleting: {name} ({hardware})...", end=" ")

                # --- Disable HA monitoring so the DELETE is allowed -----------
                ha_ok, ha_err = self._disable_ha_monitor(
                    "/devices/default/etherchannelinterfaces", obj_id, name  # pyright: ignore[reportArgumentType]
                )
                if not ha_ok:
                    print(f"[FAIL] Could not disable HA monitor: {ha_err}")
                    fail_count += 1
                    time.sleep(delay)
                    continue

                # --- Now delete the EtherChannel ------------------------------
                success, error_msg = self.delete_object("/devices/default/etherchannelinterfaces", obj_id)  # pyright: ignore[reportArgumentType]

                if success:
                    print("[OK]")
                    success_count += 1
                else:
                    print(f"[FAIL] {error_msg}")
                    fail_count += 1

                time.sleep(delay)
        
        self.stats["total_found"] += len(all_etherchannels)
        self.stats["custom_objects"] += len(all_etherchannels)
        self.stats["deleted"] += success_count
        self.stats["failed"] += fail_count

        print(f"\n  Summary: {success_count} deleted, {fail_count} failed")

        if fail_count > 0:
            print("\n  TIP: If etherchannels failed to delete, try:")
            print("    1. Delete subinterfaces first: --delete-subinterfaces")
            print("    2. Then delete etherchannels: --delete-etherchannels")

        return fail_count == 0

    def delete_all_bridge_groups(self, dry_run: bool = False, delay: float = 0.3) -> bool:
        """
        Delete all bridge group interfaces.
        
        NOTE: Bridge groups may have member interfaces that need to be
        removed first.
        """
        print(f"\n{'='*60}")
        print("Processing Bridge Groups")
        print(f"{'='*60}")
        
        # Get all bridge groups
        all_bridge_groups = self.get_all_objects("/devices/default/bridgegroupinterfaces")
        
        if not all_bridge_groups:
            print("  No bridge groups found")
            return True
        
        print(f"\n  Found {len(all_bridge_groups)} bridge groups")
        
        # Show what will be deleted
        print(f"\n  Bridge groups to delete:")
        for intf in all_bridge_groups[:10]:
            name = intf.get('name', 'UNNAMED')
            bvi_id = intf.get('bridgeGroupId', '?')
            members = intf.get('selectedInterfaces', [])
            member_count = len(members) if members else 0
            print(f"    - {name} (BVI{bvi_id}, {member_count} members)")
        
        if len(all_bridge_groups) > 10:
            print(f"    ... and {len(all_bridge_groups) - 10} more")
        
        # Delete bridge groups
        print(f"\n  {'[DRY RUN] Would delete' if dry_run else 'Deleting'} {len(all_bridge_groups)} bridge groups...")
        
        success_count = 0
        fail_count = 0
        
        for i, intf in enumerate(all_bridge_groups, 1):
            name = intf.get('name', 'UNNAMED')
            obj_id = intf.get('id')
            
            if dry_run:
                print(f"  [{i}/{len(all_bridge_groups)}] Would delete: {name}")
                success_count += 1
            else:
                print(f"  [{i}/{len(all_bridge_groups)}] Deleting: {name}...", end=" ")

                # --- Disable HA monitoring so the DELETE is allowed -----------
                ha_ok, ha_err = self._disable_ha_monitor(
                    "/devices/default/bridgegroupinterfaces", obj_id, name  # pyright: ignore[reportArgumentType]
                )
                if not ha_ok:
                    print(f"[FAIL] Could not disable HA monitor: {ha_err}")
                    fail_count += 1
                    time.sleep(delay)
                    continue

                # --- Now delete the bridge group ------------------------------
                success, error_msg = self.delete_object("/devices/default/bridgegroupinterfaces", obj_id)  # pyright: ignore[reportArgumentType]

                if success:
                    print("[OK]")
                    success_count += 1
                else:
                    print(f"[FAIL] {error_msg}")
                    fail_count += 1

                time.sleep(delay)
        
        self.stats["total_found"] += len(all_bridge_groups)
        self.stats["custom_objects"] += len(all_bridge_groups)
        self.stats["deleted"] += success_count
        self.stats["failed"] += fail_count

        print(f"\n  Summary: {success_count} deleted, {fail_count} failed")
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
                print("[OK] Deployment initiated")
                print("  (Deployment may take several minutes)")
                return True
            else:
                print(f"[FAIL] Deployment failed: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[FAIL] Deployment error: {e}")
            return False


def main(argv=None):
    """Main function.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:] when None).
    """
    parser = argparse.ArgumentParser(
        description='Bulk delete ALL custom objects from Cisco FTD via FDM API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
[WARNING] DELETES ALL CUSTOM OBJECTS OF SELECTED TYPES! [WARNING]

Examples:
  # Dry run - see what would be deleted
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects --dry-run
  
  # Delete all address objects
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects
  
  # Delete all rules
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-rules

  # Delete all security zones
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-security-zones
  
  # Delete all interface configurations (subinterfaces, etherchannels, bridges, reset physical)
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all-interfaces
  
  # Delete just subinterfaces
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-subinterfaces
  
  # Delete just etherchannels (port-channels)
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-etherchannels
  
  # Reset physical interfaces to default (clear names, IPs, disable)
  python ftd_api_cleanup.py --host 192.168.1.1 -u admin --reset-physical-interfaces
  
  # Delete everything (all objects AND interfaces)
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
    def _positive_int(value: str) -> int:
        ivalue = int(value)
        if ivalue < 1 or ivalue > 32:
            raise argparse.ArgumentTypeError(f"workers must be between 1 and 32, got {ivalue}")
        return ivalue
    parser.add_argument('--workers', type=_positive_int, default=6,
                        help='Max concurrent workers for object/static route deletions (1-32, default: 6)')
    parser.add_argument('--max-attempts', type=int, default=4,
                        help='Max retry attempts for transient API errors (default: 4)')
    parser.add_argument('--base-backoff', type=float, default=0.3,
                        help='Initial backoff delay in seconds between retries (default: 0.3)')
    parser.add_argument('--max-jitter', type=float, default=0.25,
                        help='Max random jitter in seconds added to backoff (default: 0.25)')
    parser.add_argument('--delay', type=float, default=0.2,
                        help='Delay in seconds between sequential API calls (default: 0.2)')
    parser.add_argument('--json-report', default='', help='Write cleanup summary to a JSON report file')
    parser.add_argument('--validate-only', action='store_true',
                        help='Authenticate and probe all API endpoints without deleting anything')
    parser.add_argument("--metadata-file", default="", help="Path to *_metadata.json generated by fortigate_converter.py (used for model-specific behavior).",)
    parser.add_argument("--appliance-model", default="generic", dest="appliance_model",
                       help="Target FTD appliance model (e.g., ftd-3120). Auto-detected from metadata if not specified.")
    
    # Object type selection
    parser.add_argument('--delete-address-objects', action='store_true', help='Delete all address objects')
    parser.add_argument('--delete-address-groups', action='store_true', help='Delete all address groups')
    parser.add_argument('--delete-service-objects', action='store_true', help='Delete all service objects')
    parser.add_argument('--delete-service-groups', action='store_true', help='Delete all service groups')
    parser.add_argument('--delete-security-zones', action='store_true', help='Delete all security zones')
    parser.add_argument('--delete-routes', action='store_true', help='Delete all static routes')
    parser.add_argument('--delete-rules', action='store_true', help='Delete all access rules')
    parser.add_argument('--delete-subinterfaces', action='store_true', help='Delete all subinterfaces')
    parser.add_argument('--delete-etherchannels', action='store_true', help='Delete all EtherChannels')
    parser.add_argument('--delete-bridge-groups', action='store_true', help='Delete all bridge groups')
    parser.add_argument('--reset-physical-interfaces', action='store_true', help='Reset physical interfaces to default')
    parser.add_argument('--delete-all', action='store_true', help='Delete ALL custom objects (everything)')
    parser.add_argument('--delete-all-interfaces', action='store_true', help='Delete/reset ALL interface configs')
    
    args = parser.parse_args(argv)

    # Check if at least one delete option or --validate-only is selected
    if not args.validate_only and not any([
                args.delete_address_objects, args.delete_address_groups,
                args.delete_service_objects, args.delete_service_groups,
                args.delete_security_zones,
                args.delete_routes, args.delete_rules, args.delete_all,
                args.delete_subinterfaces, args.delete_etherchannels,
                args.delete_bridge_groups, args.reset_physical_interfaces,
                args.delete_all_interfaces]):
        parser.error("Must specify at least one --delete-* option or --validate-only")
    
    # Prompt for password
    if not args.password:
        args.password = getpass.getpass(f"Enter password for {args.username}: ")
    
    # Safety confirmation
    if not args.dry_run and not args.yes:
        print("\n" + "="*60)
        print("  FINAL WARNING ")
        print("="*60)
        print("\nThis will DELETE ALL CUSTOM OBJECTS of the selected types!")
        print("This does NOT check import files - it deletes EVERYTHING it finds.")
        print("\nOnly system-defined objects will be preserved.")
        print("\nHave you backed up your FTD? (yes/no): ", end="")
        
        backup = input().strip().lower()
        if backup != 'yes':
            print("\n[ERROR] Please backup first!")
            return 1
        
        print("\nType 'DELETE ALL' to confirm: ", end="")
        confirm = input().strip()
        if confirm != 'DELETE ALL':
            print("\n[ERROR] Cancelled")
            return 1
    
    meta = {}
    if args.metadata_file:
        try:
            with open(args.metadata_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}

    # If user did not explicitly set appliance model, use metadata
    if args.appliance_model == "generic" and meta.get("target_model"):
        args.appliance_model = str(meta["target_model"]).lower().strip()


    # Create client
    client = FTDBulkDelete(
        host=args.host,
        username=args.username,
        password=args.password,
        debug=args.debug
    )
    
    # Set appliance model on client for platform-specific behavior
    client.appliance_model = args.appliance_model
    if client.appliance_model and client.appliance_model != "generic":
        print(f"[INFO] Target firewall model: {client.appliance_model}")
    
    # Authenticate
    if not client.authenticate():
        return 1

    # Validate-only mode: probe endpoints and exit
    if args.validate_only:
        ok = client.validate_endpoints()
        return 0 if ok else 1

    mode = "DRY RUN" if args.dry_run else "DELETE"
    print(f"\n{'='*60}")
    print(f"BULK DELETE MODE: {mode}")
    print(f"{'='*60}")

    # Track per-phase timings for performance comparisons
    phase_timings = []

    def record_phase(label: str, func, *func_args, **func_kwargs):
        """Run a phase, time it, and capture success for summary output."""
        start = time.perf_counter()
        result = func(*func_args, **func_kwargs)
        duration = time.perf_counter() - start
        success = True if result is None else bool(result)
        phase_timings.append({"label": label, "seconds": duration, "success": success})
        return result

    # Delete in reverse dependency order
    if args.delete_all or args.delete_rules:
        record_phase("Access Rules", client.delete_all_custom_objects,
            "/policy/accesspolicies/default/accessrules",
            "Access Rules",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )

    if args.delete_all or args.delete_routes:
        record_phase("Static Routes", client.delete_all_static_routes, args.dry_run, args.workers, args.max_attempts, args.base_backoff, args.max_jitter)

    # Security zones depend on interfaces, delete zones before interfaces
    if args.delete_all or args.delete_security_zones:
        record_phase("Security Zones", client.delete_all_custom_objects,
            "/object/securityzones",
            "Security Zones",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )

    # Delete interfaces BEFORE objects (interfaces may reference objects)
    # Order: subinterfaces -> etherchannels -> bridge groups -> physical reset
    if args.delete_all or args.delete_all_interfaces or args.delete_subinterfaces:
        record_phase("Subinterfaces", client.delete_all_subinterfaces, args.dry_run, delay=args.delay)

    if args.delete_all or args.delete_all_interfaces or args.delete_etherchannels:
        record_phase("EtherChannels", client.delete_all_etherchannels, args.dry_run, delay=args.delay)

    if args.delete_all or args.delete_all_interfaces or args.delete_bridge_groups:
        record_phase("Bridge Groups", client.delete_all_bridge_groups, args.dry_run, delay=args.delay)

    if args.delete_all or args.delete_all_interfaces or args.reset_physical_interfaces:
        record_phase("Physical Interfaces", client.reset_all_physical_interfaces, args.dry_run, delay=args.delay)

    if args.delete_all or args.delete_service_groups:
        record_phase("Service Groups", client.delete_all_custom_objects,
            "/object/portgroups",
            "Service Groups",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )

    if args.delete_all or args.delete_service_objects:
        # Delete TCP ports
        record_phase("TCP Port Objects", client.delete_all_custom_objects,
            "/object/tcpports",
            "TCP Port Objects",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )
        # Delete UDP ports
        record_phase("UDP Port Objects", client.delete_all_custom_objects,
            "/object/udpports",
            "UDP Port Objects",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )

    if args.delete_all or args.delete_address_groups:
        record_phase("Address Groups", client.delete_all_custom_objects,
            "/object/networkgroups",
            "Address Groups",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )

    if args.delete_all or args.delete_address_objects:
        record_phase("Address Objects", client.delete_all_custom_objects,
            "/object/networks",
            "Address Objects",
            args.dry_run,
            args.workers,
            args.max_attempts,
            args.base_backoff,
            args.max_jitter,
        )

    if phase_timings:
        print(f"\n{'='*60}")
        print("TIMING SUMMARY (seconds)")
        print(f"{'='*60}")
        total_seconds = 0.0
        for entry in phase_timings:
            total_seconds += entry["seconds"]
            status = "OK" if entry["success"] else "FAIL"
            print(f"{entry['label']:<35}{entry['seconds']:.2f}s [{status}]")
        print("-"*60)
        print(f"{'Total':<35}{total_seconds:.2f}s")
    else:
        total_seconds = 0.0

    # Deploy if requested
    if args.deploy and not args.dry_run:
        client.deploy_changes()

    exit_code, outcome = client.compute_outcome()

    if args.json_report:
        report_payload = {
            "host": args.host,
            "mode": mode,
            "workers": args.workers,
            "deploy_requested": args.deploy,
            "target_model": client.appliance_model,
            "stats": client.stats,
            "phase_timings": phase_timings,
            "total_seconds": total_seconds,
            "selected_actions": {
                "delete_address_objects": args.delete_address_objects,
                "delete_address_groups": args.delete_address_groups,
                "delete_service_objects": args.delete_service_objects,
                "delete_service_groups": args.delete_service_groups,
                "delete_security_zones": args.delete_security_zones,
                "delete_routes": args.delete_routes,
                "delete_rules": args.delete_rules,
                "delete_subinterfaces": args.delete_subinterfaces,
                "delete_etherchannels": args.delete_etherchannels,
                "delete_bridge_groups": args.delete_bridge_groups,
                "reset_physical_interfaces": args.reset_physical_interfaces,
                "delete_all_interfaces": args.delete_all_interfaces,
                "delete_all": args.delete_all,
            },
            "exit_code": exit_code,
            "outcome": outcome,
        }
        if FTDBulkDelete.write_json_report(args.json_report, report_payload):
            print(f"[OK] JSON report written: {args.json_report}")
        else:
            print(f"[FAIL] Could not write JSON report: {args.json_report}")

    print(f"\n{'='*60}")
    if args.dry_run:
        print("DRY RUN COMPLETE - No changes made")
        print("Remove --dry-run to actually delete")
    else:
        print("DELETION COMPLETE")
        if not args.deploy:
            print("Changes pending - deploy manually or use --deploy")
    print(f"Outcome: {outcome} (exit code {exit_code})")
    print(f"{'='*60}")

    return exit_code


if __name__ == '__main__':
    sys.exit(main())