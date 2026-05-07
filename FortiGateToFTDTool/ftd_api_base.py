#!/usr/bin/env python3
"""
FTD FDM API Base Client
========================
Shared foundation for FTDAPIClient (importer) and FTDBulkDelete (cleanup).

Centralizes authentication, endpoint validation, and virtual-router
discovery so both tools stay in sync.
"""

import requests
import threading
import time
import urllib3
from typing import Optional, Tuple

from flair import flair

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
        # Auto-refresh on 401 for every request made through this session.
        self.session.hooks["response"].append(self._auto_refresh_hook)

        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.appliance_model: str = "generic"

        # Guards concurrent token-refresh attempts across worker threads.
        self._auth_lock = threading.Lock()
        # Epoch time of the last successful token refresh so threads that
        # wake up after another thread already refreshed don't refresh again.
        self._last_refresh_time: float = 0.0

    # ------------------------------------------------------------------
    # 401 auto-retry hook
    # ------------------------------------------------------------------
    def _auto_refresh_hook(self, response, *args, **kwargs):
        """Session hook: on 401, refresh the token once and retry the request.

        Skips the auth endpoint itself (refreshing during refresh would loop)
        and any request already retried (marked via the ``_ftd_retried`` attr).
        """
        if response.status_code != 401:
            return response
        if getattr(response.request, "_ftd_retried", False):
            return response
        if response.request.url and response.request.url.endswith("/fdm/token"):
            return response

        if not self.refresh_access_token():
            return response

        new_req = response.request.copy()
        new_req.headers["Authorization"] = self.session.headers.get("Authorization", "")
        new_req._ftd_retried = True
        # Reuse the original send settings (verify, cert, proxies, timeout).
        send_kwargs = {
            "verify": kwargs.get("verify", self.session.verify),
            "cert": kwargs.get("cert", self.session.cert),
            "proxies": kwargs.get("proxies"),
            "timeout": kwargs.get("timeout"),
            "allow_redirects": kwargs.get("allow_redirects", True),
            "stream": kwargs.get("stream", False),
        }
        return self.session.send(new_req, **send_kwargs)

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
                auth_url, json=payload, headers=headers, timeout=120
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

                print(flair("auth", "OK"))
                return True
            else:
                # Never dump raw response.text — FDM error replies can echo
                # submitted form fields including the password. Extract the
                # description if it's structured JSON; otherwise just the code.
                detail = self._safe_auth_error(response)
                print(flair("auth", "FAIL", detail=f"HTTP {response.status_code}: {detail}"))
                return False

        except requests.exceptions.RequestException as e:
            print(flair("auth", "FAIL", detail=f"connection error: {self._scrub_secrets(str(e))}"))
            return False

    def _safe_auth_error(self, response) -> str:
        """Extract a short error description from an FDM auth response.

        Avoids dumping the full body because FDM error replies sometimes
        include the submitted credentials. Falls back to a generic string
        if parsing fails or the description would leak the password.
        """
        try:
            data = response.json()
            messages = data.get("error", {}).get("messages", [])
            if messages and isinstance(messages[0], dict):
                desc = str(messages[0].get("description", "")).strip()
                if desc and (not self.password or self.password not in desc):
                    return desc
        except (ValueError, TypeError):
            pass
        return "authentication failed"

    def _scrub_secrets(self, text: str) -> str:
        """Remove the configured password from arbitrary text before logging."""
        if self.password and text:
            return text.replace(self.password, "***REDACTED***")
        return text

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------
    def refresh_access_token(self) -> bool:
        """Silently refresh the access token using the stored refresh token.

        Called automatically when any request returns HTTP 401.  Uses a lock
        so that concurrent worker threads don't flood the auth endpoint; if
        another thread refreshed the token within the last few seconds the
        caller simply returns True and retries its request with the already-
        updated session header.

        Falls back to a full password re-authentication if the refresh-token
        grant fails.

        Returns:
            True if a new access token was obtained, False otherwise.
        """
        with self._auth_lock:
            # If another thread refreshed very recently, trust its result.
            if time.time() - self._last_refresh_time < 10.0:
                return True

            auth_url = f"{self.base_url}/fdm/token"

            # 1. Try the refresh-token grant first (cheaper, no password needed).
            if self.refresh_token:
                try:
                    resp = self.session.post(
                        auth_url,
                        json={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        tokens = resp.json()
                        self.access_token = tokens.get("access_token")
                        self.refresh_token = tokens.get("refresh_token")
                        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
                        self._last_refresh_time = time.time()
                        print("  [AUTH] Token refreshed via refresh_token grant.")
                        return True
                except requests.exceptions.RequestException:
                    pass

            # 2. Fall back to full password re-authentication.
            try:
                resp = self.session.post(
                    auth_url,
                    json={"grant_type": "password", "username": self.username, "password": self.password},
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    timeout=30,
                )
                if resp.status_code == 200:
                    tokens = resp.json()
                    self.access_token = tokens.get("access_token")
                    self.refresh_token = tokens.get("refresh_token")
                    self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
                    self._last_refresh_time = time.time()
                    print("  [AUTH] Token refreshed via password re-authentication.")
                    return True
                print(f"  [AUTH] Token refresh failed: HTTP {resp.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"  [AUTH] Token refresh error: {e}")

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
                    print(f"  {flair('validate', 'OK', f'{label:<25}', f'{count} objects')}")
                else:
                    print(f"  {flair('validate', 'FAIL', f'{label:<25}', f'HTTP {resp.status_code}')}")
                    all_ok = False
            except requests.exceptions.RequestException as e:
                print(f"  {flair('validate', 'FAIL', f'{label:<25}', str(e))}")
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
