#!/usr/bin/env python3
"""
FTD FDM API Base Client
========================
Shared foundation for FTDAPIClient (importer) and FTDBulkDelete (cleanup).

Centralizes authentication, endpoint validation, and virtual-router
discovery so both tools stay in sync.
"""

import requests
import urllib3
from typing import Optional, Tuple

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Endpoints probed by validate_endpoints()
_FDM_ENDPOINTS = [
    ("/devices/default/interfaces", "Physical Interfaces"),
    ("/devices/default/etherchannelinterfaces", "EtherChannels"),
    ("/devices/default/bridgegroupinterfaces", "Bridge Groups"),
    ("/object/securityzones", "Security Zones"),
    ("/object/networks", "Address Objects"),
    ("/object/networkgroups", "Address Groups"),
    ("/object/tcpports", "TCP Port Objects"),
    ("/object/udpports", "UDP Port Objects"),
    ("/object/portgroups", "Port Groups"),
    ("/devices/default/routing/virtualrouters", "Virtual Routers"),
    ("/policy/accesspolicies/default/accessrules", "Access Rules"),
]


class FTDBaseClient:
    """Shared base for FTD FDM API clients.

    Provides:
    - Session and credential management
    - ``authenticate()``
    - ``validate_endpoints()``
    - ``get_default_virtual_router_id()``
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        debug: bool = False,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.debug = debug

        self.base_url = f"https://{host}/api/fdm/latest"

        self.session = requests.Session()
        self.session.verify = verify_ssl

        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.appliance_model: str = "generic"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def authenticate(self) -> bool:
        """Authenticate to the FTD FDM API and obtain access tokens.

        Uses OAuth 2.0 password grant.  On success the session headers are
        updated so all subsequent requests carry the bearer token.

        Returns:
            True if authentication successful, False otherwise.
        """
        print(f"\n{'='*60}")
        print(f"Authenticating to FTD at {self.host}")
        print(f"{'='*60}")

        auth_url = f"{self.base_url}/fdm/token"

        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = self.session.post(
                auth_url, json=payload, headers=headers, timeout=30
            )

            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens.get("access_token")
                self.refresh_token = tokens.get("refresh_token")

                self.session.headers.update({
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                })

                print("Authentication successful!")
                return True
            else:
                print(f"[FAIL] Authentication failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"[FAIL] Connection error: {e}")
            return False

    # ------------------------------------------------------------------
    # Endpoint validation
    # ------------------------------------------------------------------
    def validate_endpoints(self) -> bool:
        """Probe required FDM API endpoints and print a capability summary.

        Each endpoint is tested with a lightweight GET (limit=1).  Intended
        as a fast preflight check before a long run.

        Returns:
            True if all endpoints are reachable, False otherwise.
        """
        print(f"\n{'='*60}")
        print("ENDPOINT VALIDATION")
        print(f"{'='*60}")

        all_ok = True
        for path, label in _FDM_ENDPOINTS:
            url = f"{self.base_url}{path}"
            try:
                resp = self.session.get(url, params={"limit": 1}, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    count = data.get("paging", {}).get("count", "?")
                    print(f"  [OK]   {label:<25} ({count} objects)")
                else:
                    print(f"  [FAIL] {label:<25} HTTP {resp.status_code}")
                    all_ok = False
            except requests.exceptions.RequestException as e:
                print(f"  [FAIL] {label:<25} {e}")
                all_ok = False

        print(f"{'='*60}")
        if all_ok:
            print("All endpoints reachable.")
        else:
            print("Some endpoints failed. Review errors above before proceeding.")
        print(f"{'='*60}")
        return all_ok

    # ------------------------------------------------------------------
    # Virtual router discovery
    # ------------------------------------------------------------------
    def get_default_virtual_router_id(self) -> Tuple[bool, Optional[str]]:
        """Get the ID of the default virtual router (typically 'Global').

        Static routes are scoped under a Virtual Router in the FDM API.
        The resolved ID is cached to avoid repeated API calls.

        Returns:
            (success, vr_id_or_error_message)
        """
        if hasattr(self, "_default_vr_id") and self._default_vr_id:
            return True, self._default_vr_id

        endpoint = f"{self.base_url}/devices/default/routing/virtualrouters"

        try:
            response = self.session.get(endpoint, timeout=30)
            if response.status_code != 200:
                return False, f"API error: {response.status_code}"

            data = response.json()
            items = data.get("items", [])

            # Prefer the well-known defaults first
            for vr in items:
                vr_name = str(vr.get("name", "")).strip().lower()
                if vr_name in {"global", "default", "global-vr"}:
                    self._default_vr_id = vr.get("id")
                    return True, self._default_vr_id

            # Fallback: pick the first VR if present
            if items:
                self._default_vr_id = items[0].get("id")
                return True, self._default_vr_id

            return False, "No virtual routers found"

        except requests.exceptions.RequestException as e:
            return False, str(e)
