#!/usr/bin/env python3
"""
FTD SNMPv3 Configuration Tool
==============================
Configures SNMPv3 on a locally managed Cisco FTD (FDM) via the REST API.

FDM does not expose SNMPv3 settings in its GUI - configuration must go
through the API (FDM 6.7+). This tool performs the full STIG-compliant
sequence (CASA-ND-001050 / CASA-ND-001070):

1. Create/update an SNMPv3 user (Auth/Priv: SHA auth + AES privacy)
2. Look up the source interface by its logical name
3. For EACH SNMP manager: create/update a network object for the NMS
   host and an SNMP host binding the NMS, user, and interface
4. Optionally deploy the pending changes

Multiple SNMP managers are supported - they share the SNMPv3 user and
source interface, and each manager gets its own network object and SNMP
host (object names suffixed with the manager IP).

All steps are create-or-update (idempotent): re-running with new values
updates the existing objects instead of failing on duplicates.

Verification after deploy (SSH to the FTD):
    show run snmp-server
    show snmp-server user

Usage:
    python ftd_snmp_config.py --host 192.168.1.1 -u admin \
        --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside \
        --auth-algorithm SHA --priv-algorithm AES256 --deploy
"""

import argparse
import getpass
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
import urllib3

from flair import flair
from ftd_api_base import FTDBaseClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AUTH_ALGORITHMS = ["SHA", "SHA256"]
PRIV_ALGORITHMS = ["AES128", "AES192", "AES256"]
SECURITY_LEVELS = ["PRIV", "AUTH"]  # NOAUTH intentionally excluded (STIG)

# Read-only FDM bookkeeping that must not be sent back in a PUT body
_META_KEYS = ("links",)


class FTDSNMPConfig(FTDBaseClient):
    """Pushes SNMPv3 configuration objects to an FDM-managed FTD."""

    def __init__(self, host: str, username: str, password: str,
                 verify_ssl: bool = False, debug: bool = False):
        super().__init__(host, username, password, verify_ssl, debug)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _extract_error(self, response: requests.Response) -> str:
        """Best-effort FDM error extraction with safe fallbacks."""
        try:
            messages = response.json().get("error", {}).get("messages", [])
            if messages and isinstance(messages[0], dict):
                return str(messages[0].get("description", f"HTTP {response.status_code}"))
        except (ValueError, TypeError, KeyError):
            pass
        return f"HTTP {response.status_code}"

    def _get_by_name(self, endpoint: str, name: str) -> Optional[Dict]:
        """Find an object by name on a list endpoint (filter + paginated scan)."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(
                url, params={"filter": f"name:{name}", "limit": 10}, timeout=30,
            )
            if response.status_code == 200:
                for obj in response.json().get("items", []):
                    if obj.get("name") == name:
                        return obj

            offset = 0
            limit = 100
            while True:
                response = self.session.get(
                    url, params={"offset": offset, "limit": limit}, timeout=30,
                )
                if response.status_code != 200:
                    return None
                data = response.json()
                items = data.get("items", [])
                for obj in items:
                    if obj.get("name") == name:
                        return obj
                paging = data.get("paging", {})
                if not items or offset + len(items) >= paging.get("count", len(items)):
                    return None
                offset += limit
        except requests.exceptions.RequestException:
            return None

    def _upsert(self, endpoint: str, payload: Dict, label: str) -> Tuple[bool, Union[Dict, str]]:
        """
        Create the object, or update it in place if one with the same name
        already exists.

        Returns:
            (True, object_dict) on success, (False, error_message) on failure.
        """
        name = payload.get("name", "")
        existing = self._get_by_name(endpoint, name)

        try:
            if existing and existing.get("id"):
                update = dict(existing)
                update.update(payload)
                update["id"] = existing["id"]
                update["version"] = existing.get("version")
                for key in _META_KEYS:
                    update.pop(key, None)
                response = self.session.put(
                    f"{self.base_url}{endpoint}/{existing['id']}", json=update, timeout=30,
                )
                action = "update"
            else:
                response = self.session.post(
                    f"{self.base_url}{endpoint}", json=payload, timeout=30,
                )
                action = "create"

            if response.status_code in (200, 201):
                obj = response.json()
                print(f"  {flair(action, 'OK', f'{label} {name}')}")
                return True, obj

            error_msg = self._extract_error(response)
            print(f"  {flair(action, 'FAIL', f'{label} {name}', error_msg)}")
            return False, error_msg

        except requests.exceptions.RequestException as exc:
            print(f"  {flair('create', 'FAIL', f'{label} {name}', str(exc))}")
            return False, str(exc)

    @staticmethod
    def _ref(obj: Dict) -> Dict:
        """Build an FDM reference block from a full object."""
        ref = {
            "id": obj.get("id"),
            "type": obj.get("type"),
            "name": obj.get("name"),
        }
        if obj.get("version"):
            ref["version"] = obj["version"]
        return ref

    # ------------------------------------------------------------------
    # Interface lookup
    # ------------------------------------------------------------------
    def find_interface(self, name: str) -> Tuple[bool, Union[Dict, str]]:
        """
        Find an interface by logical name across physical interfaces,
        etherchannels, and their subinterfaces.

        Returns:
            (True, interface_dict) or (False, error_message).
        """
        physical_parents = []
        ec_parents = []

        # Pass 1: top-level interfaces (and remember parents for pass 2)
        for endpoint, parents in (
            ("/devices/default/interfaces", physical_parents),
            ("/devices/default/etherchannelinterfaces", ec_parents),
        ):
            try:
                response = self.session.get(
                    f"{self.base_url}{endpoint}", params={"limit": 200}, timeout=30,
                )
                if response.status_code != 200:
                    continue
                for intf in response.json().get("items", []):
                    if intf.get("name") == name:
                        return True, intf
                    if intf.get("id"):
                        parents.append(intf["id"])
            except requests.exceptions.RequestException as exc:
                return False, f"Interface lookup failed: {exc}"

        # Pass 2: subinterfaces under each parent
        for base, parent_ids in (
            ("/devices/default/interfaces", physical_parents),
            ("/devices/default/etherchannelinterfaces", ec_parents),
        ):
            for parent_id in parent_ids:
                try:
                    response = self.session.get(
                        f"{self.base_url}{base}/{parent_id}/subinterfaces",
                        params={"limit": 200}, timeout=30,
                    )
                    if response.status_code != 200:
                        continue
                    for intf in response.json().get("items", []):
                        if intf.get("name") == name:
                            return True, intf
                except requests.exceptions.RequestException:
                    continue

        return False, (
            f"Interface '{name}' not found. Use the logical name "
            f"(e.g. 'outside'), not the hardware name (e.g. 'Ethernet1/1')."
        )

    # ------------------------------------------------------------------
    # SNMP object builders
    # ------------------------------------------------------------------
    def ensure_network_object(self, name: str, ip: str) -> Tuple[bool, Union[Dict, str]]:
        """Create/update the network object for the NMS host."""
        payload = {
            "name": name,
            "description": "SNMP server (NMS) host",
            "subType": "HOST",
            "value": ip,
            "dnsResolution": "IPV4_ONLY",
            "type": "networkobject",
        }
        return self._upsert("/object/networks", payload, "network object")

    def ensure_snmp_user(
        self,
        name: str,
        security_level: str,
        auth_algorithm: str,
        auth_password: str,
        priv_algorithm: str,
        priv_password: str,
    ) -> Tuple[bool, Union[Dict, str]]:
        """Create/update the SNMPv3 user."""
        payload = {
            "name": name,
            "description": "SNMPv3 user",
            "securityLevel": security_level,
            "authenticationAlgorithm": auth_algorithm,
            "authenticationPassword": auth_password,
            "type": "snmpuser",
        }
        if security_level == "PRIV":
            payload["encryptionAlgorithm"] = priv_algorithm
            payload["encryptionPassword"] = priv_password
        return self._upsert("/object/snmpusers", payload, "SNMP user")

    def ensure_snmp_host(
        self,
        name: str,
        network_object: Dict,
        snmp_user: Dict,
        interface: Dict,
        poll_enabled: bool,
        trap_enabled: bool,
    ) -> Tuple[bool, Union[Dict, str]]:
        """Create/update the SNMP host binding NMS + user + interface."""
        payload = {
            "name": name,
            "managerAddress": self._ref(network_object),
            "pollEnabled": poll_enabled,
            "trapEnabled": trap_enabled,
            "securityConfiguration": {
                "authentication": self._ref(snmp_user),
                "type": "snmpv3securityconfiguration",
            },
            "interface": self._ref(interface),
            "type": "snmphost",
        }
        return self._upsert("/object/snmphosts", payload, "SNMP host")

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    @staticmethod
    def _per_host_name(base: str, ip: str, multiple: bool) -> str:
        """Object name for one NMS: suffix the base name with the IP when
        configuring multiple managers so each gets a unique object."""
        if not multiple:
            return base
        return f"{base}_{ip.replace('.', '_')}"

    def configure(
        self,
        nms_ips: List[str],
        nms_object_name: str,
        snmp_user_name: str,
        security_level: str,
        auth_algorithm: str,
        auth_password: str,
        priv_algorithm: str,
        priv_password: str,
        interface_name: str,
        host_object_name: str,
        poll_enabled: bool = True,
        trap_enabled: bool = True,
    ) -> bool:
        """
        Run the full SNMPv3 configuration sequence.

        One SNMPv3 user and source interface are shared by all SNMP
        managers; each manager IP gets its own network object and SNMP
        host. Returns True only if every manager was configured.
        """
        print(f"\n{'='*60}")
        print("Configuring SNMPv3")
        print(f"{'='*60}")
        print(f"  SNMP managers:   {', '.join(nms_ips)}")
        print(f"  SNMP user:       {snmp_user_name} ({security_level}, "
              f"{auth_algorithm}"
              f"{' + ' + priv_algorithm if security_level == 'PRIV' else ''})")
        print(f"  Source interface: {interface_name}")
        print(f"  Polling: {'enabled' if poll_enabled else 'disabled'}, "
              f"Traps: {'enabled' if trap_enabled else 'disabled'}")
        print()

        # Step 1: SNMPv3 user (shared by all managers)
        ok, user_obj = self.ensure_snmp_user(
            snmp_user_name, security_level,
            auth_algorithm, auth_password,
            priv_algorithm, priv_password,
        )
        if not ok or not isinstance(user_obj, dict):
            return False

        # Step 2: source interface (shared by all managers)
        ok, intf_obj = self.find_interface(interface_name)
        if not ok or not isinstance(intf_obj, dict):
            print(f"  {flair('lookup', 'FAIL', f'interface {interface_name}', str(intf_obj))}")
            return False
        hardware_name = intf_obj.get('hardwareName', '?')
        print(f"  {flair('lookup', 'OK', f'interface {interface_name} ({hardware_name})')}")

        # Step 3: per-manager network object + SNMP host
        multiple = len(nms_ips) > 1
        configured = 0
        failed = 0
        for ip in nms_ips:
            net_name = self._per_host_name(nms_object_name, ip, multiple)
            host_name = self._per_host_name(host_object_name, ip, multiple)

            ok, net_obj = self.ensure_network_object(net_name, ip)
            if not ok or not isinstance(net_obj, dict):
                failed += 1
                continue

            ok, _ = self.ensure_snmp_host(
                host_name, net_obj, user_obj, intf_obj,
                poll_enabled, trap_enabled,
            )
            if ok:
                configured += 1
            else:
                failed += 1

        print(f"\n  Summary: {configured} of {len(nms_ips)} SNMP manager(s) configured"
              f"{f', {failed} failed' if failed else ''}")
        if configured:
            print(f"  NMS access: UDP 161 (polling){' / UDP 162 (traps)' if trap_enabled else ''}")
            print(f"  Verify after deploy via SSH: show run snmp-server")
        return failed == 0

    def deploy_changes(self) -> bool:
        """Deploy pending changes."""
        print(f"\n{'='*60}")
        print("Deploying configuration changes...")
        print(f"{'='*60}")
        try:
            response = self.session.post(
                f"{self.base_url}/operational/deploy", json={}, timeout=30,
            )
            if response.status_code in (200, 201, 202):
                print(flair("deploy", "OK", "configuration changes"))
                print("  (Deployment may take several minutes)")
                return True
            print(flair("deploy", "FAIL", "configuration changes",
                        f"HTTP {response.status_code}"))
            return False
        except requests.exceptions.RequestException as exc:
            print(flair("deploy", "FAIL", "configuration changes", str(exc)))
            return False


def main(argv=None):
    """Main function.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:] when None).
    """
    parser = argparse.ArgumentParser(
        description="Configure SNMPv3 on Cisco FTD via the FDM REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full STIG-compliant SNMPv3 setup (prompts for passwords)
  python ftd_snmp_config.py --host 192.168.1.1 -u admin \\
      --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside --deploy

  # Multiple SNMP managers (comma-separated or repeated flag)
  python ftd_snmp_config.py --host 192.168.1.1 -u admin \\
      --nms-ip 10.0.0.50,10.0.0.51 --nms-ip 10.1.0.50 --nms-ip 10.2.0.50 \\
      --snmp-user FWADMIN --interface outside --deploy

  # Explicit algorithms, traps disabled (polling only)
  python ftd_snmp_config.py --host 192.168.1.1 -u admin \\
      --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface management_net \\
      --auth-algorithm SHA256 --priv-algorithm AES256 --no-trap
        """,
    )

    parser.add_argument('--host', required=True, help='FTD management IP')
    parser.add_argument('-u', '--username', required=True, help='FDM username')
    parser.add_argument('-p', '--password', help='FDM password (prompted if omitted)')
    parser.add_argument('--nms-ip', required=True, action='append',
                        help='IP address of an SNMP manager / NMS (e.g. SolarWinds). '
                             'Repeat the flag or comma-separate for multiple managers '
                             '(e.g. --nms-ip 10.0.0.50,10.0.0.51)')
    parser.add_argument('--nms-object-name', default='snmpHost',
                        help='Base name for the NMS network object(s) (default: snmpHost). '
                             'With multiple managers, each name is suffixed with its IP.')
    parser.add_argument('--snmp-user', required=True,
                        help='SNMPv3 user name (e.g. FWADMIN)')
    parser.add_argument('--security-level', choices=SECURITY_LEVELS, default='PRIV',
                        help='SNMPv3 security level (default: PRIV; STIG requires Auth/Priv)')
    parser.add_argument('--auth-algorithm', choices=AUTH_ALGORITHMS, default='SHA',
                        help='Authentication algorithm (default: SHA)')
    parser.add_argument('--auth-password',
                        help='Authentication password (prompted if omitted)')
    parser.add_argument('--priv-algorithm', choices=PRIV_ALGORITHMS, default='AES256',
                        help='Privacy/encryption algorithm (default: AES256; AES128 is the STIG minimum)')
    parser.add_argument('--priv-password',
                        help='Privacy/encryption password (prompted if omitted)')
    parser.add_argument('--interface', required=True,
                        help='Logical name of the interface that sources SNMP traffic (e.g. outside)')
    parser.add_argument('--host-object-name', default='snmpv3-host',
                        help='Base name for the SNMP host object(s) (default: snmpv3-host). '
                             'With multiple managers, each name is suffixed with its IP.')
    parser.add_argument('--no-poll', action='store_true', help='Disable SNMP polling')
    parser.add_argument('--no-trap', action='store_true', help='Disable SNMP traps')
    parser.add_argument('--deploy', action='store_true', help='Deploy after configuring')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')

    args = parser.parse_args(argv)

    # Flatten repeated/comma-separated --nms-ip values, dedupe preserving order
    nms_ips = []
    for chunk in args.nms_ip:
        for ip in chunk.split(','):
            ip = ip.strip()
            if ip and ip not in nms_ips:
                nms_ips.append(ip)
    if not nms_ips:
        print("[ERROR] No valid SNMP manager IPs given via --nms-ip.")
        return 1

    if not args.password:
        args.password = getpass.getpass(f"Enter FDM password for {args.username}: ")
    if not args.auth_password:
        args.auth_password = getpass.getpass("Enter SNMPv3 authentication password: ")
    if args.security_level == 'PRIV' and not args.priv_password:
        args.priv_password = getpass.getpass("Enter SNMPv3 privacy (encryption) password: ")

    if len(args.auth_password) < 8:
        print("[ERROR] Authentication password must be at least 8 characters (FDM requirement).")
        return 1
    if args.security_level == 'PRIV' and len(args.priv_password) < 8:
        print("[ERROR] Privacy password must be at least 8 characters (FDM requirement).")
        return 1
    if args.security_level != 'PRIV':
        print("[WARNING] Security level AUTH (no privacy) is NOT STIG-compliant "
              "(CASA-ND-001070 requires AES encryption). Use PRIV for compliance.")

    client = FTDSNMPConfig(
        host=args.host,
        username=args.username,
        password=args.password,
        debug=args.debug,
    )

    if not client.authenticate():
        return 1

    success = client.configure(
        nms_ips=nms_ips,
        nms_object_name=args.nms_object_name,
        snmp_user_name=args.snmp_user,
        security_level=args.security_level,
        auth_algorithm=args.auth_algorithm,
        auth_password=args.auth_password,
        priv_algorithm=args.priv_algorithm,
        priv_password=args.priv_password,
        interface_name=args.interface,
        host_object_name=args.host_object_name,
        poll_enabled=not args.no_poll,
        trap_enabled=not args.no_trap,
    )

    if not success:
        print("\n[ERROR] SNMPv3 configuration failed - see messages above.")
        return 1

    if args.deploy:
        if not client.deploy_changes():
            return 1
    else:
        print("\n[INFO] Changes are staged but NOT deployed.")
        print("       Deploy from FDM or re-run with --deploy to activate.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
