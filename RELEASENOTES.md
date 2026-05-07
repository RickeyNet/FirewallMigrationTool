# Release Notes

## v1.7.4 - Security: Codebase-Wide Credential Leak Audit

### Overview

Follow-up to v1.7.3. After fixing the two confirmed leaks in PAN-OS keygen and FTD authenticate, an audit across all five conversion pipelines and the GUI surfaced eight more spots where raw `response.text` could reach the output window. None were as severe as the v1.7.3 finds (most were post-auth and only a leak risk if the FDM/PAN-OS response happened to echo submitted form fields), but they were closed for defense in depth. The GUI's catch-all exception handler now also scrubs any password typed into the Import or Cleanup tabs before writing the exception or traceback to the output window.

---

### Bug Fixes

#### FTD Importer — Eight Sites Routed Through `_extract_error_message`

- `_create_api_object` 4xx/5xx fallback ([ftd_api_importer.py:394](FortiGateToFTDTool/ftd_api_importer.py#L394))
- Interface-list fetch warning ([ftd_api_importer.py:657](FortiGateToFTDTool/ftd_api_importer.py#L657))
- Deployment failure response ([ftd_api_importer.py:2032](FortiGateToFTDTool/ftd_api_importer.py#L2032))
- Interface lookup pagination error ([ftd_api_importer.py:980](FortiGateToFTDTool/ftd_api_importer.py#L980))
- Interface PUT 422/non-200 returns ([ftd_api_importer.py:1410-1412](FortiGateToFTDTool/ftd_api_importer.py#L1410-L1412))
- Subinterface POST 422/non-200 returns ([ftd_api_importer.py:1594-1597](FortiGateToFTDTool/ftd_api_importer.py#L1594-L1597))

All now emit only the parsed FDM `error.messages[0].description` instead of dumping the raw response body.

#### FTD Cleanup — Debug Response Print Sanitized

- `ftd_api_cleanup.py` debug-mode print now extracts only the FDM error description; the raw `response.text[:200]` dump is gone.

#### Cisco FTD → FortiGate Reader — Pagination Warning Sanitized

- `CiscoFTDToFortiGateTool/ftd_reader.py` HTTP-error warning during paginated GETs now extracts only the parsed error description.

#### PAN-OS Validation — Unexpected-Response Print Parsed

- `panos_api_base.py` validation path no longer dumps `resp.text[:200]`. It now parses the `<msg>` / `<line>` element and only that. The connection-error branch on the same path uses `_scrub_secrets()` for symmetry with `authenticate()`.

#### GUI Exception Handler — Output Scrubbed

- `gui_app.py` catch-all `except Exception` now passes both the exception string and the full traceback through a new `_scrub_secrets()` helper that replaces any text matching `imp_pass_var` or `cln_pass_var` with `***REDACTED***`. Backstop for any future code path that might surface credentials in a URL or request body.

---

### Files Modified

| File | Changes |
|------|---------|
| `FortiGateToFTDTool/ftd_api_importer.py` | 8 `response.text` print/return sites routed through `_extract_error_message()` |
| `FortiGateToFTDTool/ftd_api_cleanup.py` | Debug-gated response print parses error description instead of raw body |
| `CiscoFTDToFortiGateTool/ftd_reader.py` | Paginated-GET warning extracts FDM error description; raw body never printed |
| `FortiGateToPaloAltoTool/panos_api_base.py` | Validation `[FAIL]` path parses `<msg>`/`<line>` only; connection error uses `_scrub_secrets()` |
| `gui_app.py` | New `_scrub_secrets()` helper; catch-all exception handler scrubs both `str(exc)` and `traceback.format_exc()` before queueing them to the output widget; version bumped to 1.7.4 |

---

---

## v1.7.3 - Security: Stop Leaking Passwords to the Output Window

### Overview

**Security fix.** Two paths in the authentication flow could leak the user-supplied admin password into the GUI output window in plain text:

1. **PAN-OS keygen** sent `user` and `password` as URL **query string** parameters via HTTP GET. On a connection error, `requests.exceptions.RequestException`'s string form includes the full URL — so the password ended up in the `[FAIL] Connection error:` line printed to the output window.
2. **FTD authenticate** dumped the raw `response.text` on a non-200 reply. FDM error responses can echo the submitted form payload (including the password) back in the body, so a wrong-password attempt could surface the typed password in the output.

Anyone with access to the GUI window, a copy of a screen recording, or a log file from a failed run could read the credentials in plain text. Upgrade and rotate any passwords that may have appeared in shared output.

---

### Bug Fixes

#### PAN-OS Keygen No Longer Puts the Password in the URL

- `panos_api_base.py` now POSTs `user` / `password` / `type=keygen` as form data instead of GETting them as URL query parameters. The credentials never appear in the request line, so connection-error tracebacks, proxy logs, and `requests` exception strings can no longer expose them.
- The auth-failure branch no longer falls through to raw `resp.text` — only the parsed `<msg>` / `<line>` element is printed, with a generic `"auth failed"` fallback if parsing fails.
- Connection-error messages are passed through a `_scrub_secrets()` helper that replaces any occurrence of the configured password with `***REDACTED***` as a defense-in-depth backstop.

#### FTD Authenticate No Longer Dumps Raw Response Bodies

- `ftd_api_base.py` no longer prints `response.text` on auth failure. A new `_safe_auth_error()` helper extracts only the FDM error description from the structured JSON reply, refuses to print the description if it contains the password, and falls back to `"authentication failed"` if anything looks off. The HTTP status code is still surfaced.
- The `RequestException` branch now scrubs the configured password out of the exception string before printing, mirroring the PAN-OS path.

---

### Files Modified

| File | Changes |
|------|---------|
| `FortiGateToPaloAltoTool/panos_api_base.py` | `authenticate()` switched from GET-with-query-params to POST-with-form-body; removed raw `resp.text` fallback in error message; added `_scrub_secrets()` helper used on the connection-error branch |
| `FortiGateToFTDTool/ftd_api_base.py` | Removed `print(f"  Response: {response.text}")` on auth failure; new `_safe_auth_error()` extracts the FDM error description without leaking; new `_scrub_secrets()` helper redacts the password from connection-error strings |
| `gui_app.py` | Version bumped to 1.7.3 |

---

### Action Recommended

If any operator passwords were typed into the tool while running 1.7.2 or earlier and the run produced a `[FAIL] Connection error:` or `[FAIL] HTTP ...` line during authentication that anyone else might have seen, **rotate those passwords**.

---

---

## v1.7.2 - Skip Updates That Wouldn't Change Anything

### Overview

Bug-fix release for FTD imports that produced a flood of `[FAIL] Update failed:` lines on address objects (and other object types) that already existed on the target FDM. With `update_existing` enabled, the importer was unconditionally PUTting every duplicate, which FDM frequently rejects when the payload is semantically identical to the existing object. The importer now compares first and only updates when something actually changed.

---

### Bug Fixes

#### Pre-Update Equality Check

- `_update_existing_object` now strips FDM bookkeeping fields (`id`, `version`, `links`, `self`, `metadata`, `isSystemDefined`, `kind`) from both sides and compares the remaining value-bearing fields. If every field present in the new payload already matches the existing object, the importer records `_skipped` and returns `[SKIP] identical to existing '<name>'` without ever issuing the PUT.
- Applies to every object type that flows through `_update_existing_object` — network objects and groups, port objects and groups, access rules, and static routes.
- `type` is intentionally **not** stripped from the comparison because it is part of the object's identity (e.g. `HOST` vs `NETWORK` vs `RANGE` on a NetworkObject); a change there means a genuinely different object even if the name and value happened to match.

#### More Useful Update-Failure Messages

- When an update genuinely does fail, the error line now leads with the HTTP status code: `[FAIL] Update failed (HTTP 422): <description>` instead of just `[FAIL] Update failed: <description>`. Makes debugging future failures actionable at a glance without digging into logs.

---

### Files Modified

| File | Changes |
|------|---------|
| `FortiGateToFTDTool/ftd_api_importer.py` | New `_payload_matches_existing()` helper and `_FDM_META_KEYS` constant; `_update_existing_object()` short-circuits to SKIP when the payload would be a no-op; failure message includes HTTP status |
| `gui_app.py` | Version bumped to 1.7.2 |

---

---

## v1.7.1 - FDM Token Auto-Refresh on Long Imports

### Overview

Bug-fix release for long FTD imports that were failing partway through with HTTP 401 ("JWT expired") once the FDM access token's ~30-minute lifetime ran out mid-run. The base client already supported `refresh_access_token()`, but the importer's many direct `self.session.*` call sites never invoked it, so any unlucky request after expiry surfaced a `[FAIL]` line and aborted that object.

---

### Bug Fixes

#### Automatic 401 Retry Across Every API Call

- Installed a `requests` session-level response hook on `FTDBaseClient` that catches 401 responses, calls the existing thread-safe `refresh_access_token()`, rewrites the `Authorization` header on the original request, and resends it once.
- The hook skips the `/fdm/token` endpoint itself (so a refresh attempt cannot recurse during a refresh) and tags retried requests with an internal `_ftd_retried` flag so a genuine post-refresh 401 surfaces normally instead of looping.
- Because the hook lives on the shared session, every current and future `self.session.{get,post,put,delete}` call in both the importer and cleanup paths inherits the retry without per-call-site changes.

---

### Files Modified

| File | Changes |
|------|---------|
| `FortiGateToFTDTool/ftd_api_base.py` | Session response hook `_auto_refresh_hook` registered in `__init__`; refreshes the FDM token on 401 and re-sends the original request once with the new bearer header |
| `gui_app.py` | Version bumped to 1.7.1 |

---

---

## v1.7.0 - Flair Output & Frozen-Exe Icon Fix

### Overview

Adds personality to operator output across the FTD cleanup and shared FTD API base while preserving the strict `[OK] / [SKIP] / [FAIL]` bracket tags that JSON reports, exit-code logic, and grep-based log scraping depend on. Also fixes a crash on frozen Windows builds where the GUI failed to start with `failed to execute script 'gui_app' due to unhandled exception: bitmap`.

---

### Improvements

#### Flair Phrase System

- New `FortiGateToFTDTool/flair.py` module exposes `flair(action, outcome, subject, detail)` returning lines like `[OK] Yeeted into the void: net-obj-foo` or `[FAIL] Bounced: rule-42 — 422 duplicate name`.
- Phrase pools are keyed by `(action, outcome)` tuples (`create`, `delete`, `update`, `convert`, `auth`, `validate`, `deploy`, `report`) with random selection per call. Unknown keys fall back to a generic pool so callers never crash on a typo.
- The leading bracket tag is preserved verbatim — only the message body becomes flavorful — so existing log-parsing tooling continues to work unchanged.

#### Flair Wired Into FTD Cleanup and Shared Base

- `ftd_api_cleanup.py` now emits flair-tagged lines for all delete sites (static routes, custom objects, physical interface resets, subinterfaces, etherchannels, bridge groups, deploy, JSON report).
- `ftd_api_base.py` emits flair lines for `authenticate()` and per-endpoint `validate_endpoints()` results — and because the FTD importer inherits from `FTDBaseClient`, those lines appear during imports too. Propagation to the importer's own per-object output and to the other five conversion pipelines is staged for a follow-up.

---

### Bug Fixes

#### Frozen-Exe `bitmap` Crash on GUI Start

- `gui_app.py` previously called `self.iconbitmap(sys.executable)` when frozen, which raised `_tkinter.TclError: bitmap "...exe" not defined` on some Windows builds and caused PyInstaller to surface "failed to execute script 'gui_app' due to unhandled exception: bitmap" before the main window appeared.
- Icon load now resolves `app_icon.ico` from `sys._MEIPASS` when frozen (and from the project directory in dev), and is wrapped in a `try/except tk.TclError` so a missing or unreadable icon can never kill the GUI.
- `build.bat` adds `--add-data "app_icon.ico;."` so the icon is actually present inside the onefile bundle at runtime — `--icon` alone only sets the exe's shell icon and does not bundle the file.

---

### Files Modified

| File | Changes |
|------|---------|
| `FortiGateToFTDTool/flair.py` | **New.** Phrase pools and `flair()` formatter |
| `FortiGateToFTDTool/ftd_api_cleanup.py` | All 13 `[OK]/[SKIP]/[FAIL]` print sites routed through `flair()` |
| `FortiGateToFTDTool/ftd_api_base.py` | `authenticate()` and `validate_endpoints()` use `flair()` |
| `gui_app.py` | Window-icon load uses `sys._MEIPASS` when frozen; wrapped in `try/except tk.TclError`; version bumped to 1.7.0 |
| `build.bat` | Added `--add-data "app_icon.ico;."` so the icon is bundled into the onefile exe |

---

---

## v1.6.2 - GUI Source/Target Matrix Polish

### Overview

Follow-up to v1.6.1 addressing the highest-priority Source/Target UX issues. The Target combobox now visually reflects when it's locked to a single choice, custom Output Base Names survive platform switches, and the Import/Cleanup tab forms are fully disabled - not just retitled - when the target doesn't support API-based operations.

---

### Improvements

#### Target Combobox Locks Visually

- When the source platform forces a single target (Cisco ASA → PAN-OS only; Palo Alto → FortiGate only; Cisco FTD → FortiGate only), the Target combobox now switches to `disabled` state so it clearly reads as locked. Switching back to FortiGate as source restores `readonly` state with the full set of choices.

#### Custom Output Base Name Preserved Across Platform Changes

- `Output Base Name` (Convert tab) and `JSON Base Name` (Import tab) no longer overwrite a user-typed value when the source or target changes. Overwrites now only happen when the field still holds one of the known auto-generated defaults (`""`, `"ftd_config"`, `"pa_config"`, `"fg_config"`). A custom name like `"prod_migration_q2"` survives any number of selector changes.

#### Import & Cleanup Forms Disabled for FortiGate Target

- Previously the Import and Cleanup tabs were retitled "(N/A for FortiGate)" but the full form was still clickable - users could type into fields and press Start only to hit a "not applicable" popup. Now the entire tab contents (entries, checkboxes, spinboxes, comboboxes, and the Start/Cancel buttons) are disabled when the target is FortiGate. Output text areas remain visible for reviewing prior logs, and the Clear Output button was intentionally disabled as well (use Cancel/Clear once the tab is re-enabled).
- Lockout state is respected by the shared `_set_buttons_state()` helper so Convert-tab operations don't accidentally re-enable the Import/Cleanup run buttons mid-run.
- The Cleanup password reset button correctly re-syncs with `has_custom_password()` when the tab is unlocked.

---

### Files Modified

| File | Changes |
|------|---------|
| `gui_app.py` | Target combobox `state` toggled alongside `values` in `_on_source_change`; added `DEFAULT_OUTPUT_BASES` guard around `conv_output_var` / `imp_base_var` resets; new `_set_tab_enabled()` helper walks tab descendants and disables interactive widgets; `_retitle_import_cleanup_tabs()` applies the lockout; `_set_buttons_state()` respects per-tab lockout flags; version bumped to 1.6.2 |

---

---

## v1.6.1 - GUI Label & Tab Fixes

### Overview

Fixes GUI labeling bugs introduced in v1.6.0 where the HA Port field label and the Import/Cleanup tab titles remained locked to FTD wording regardless of the selected source or target platform.

---

### Bug Fixes

#### Convert Tab - HA Port / FTD Username Label

- The field next to the username entry now correctly reads **"FTD Username:"** when Cisco FTD is selected as the source. Previously, the label stayed as "HA Port (optional):" while the helper text below read "FTD username (leave blank for 'admin')", producing a contradictory UI.
- Label text now updates alongside the hint text in all five state transitions: FTD source (API mode), FTD source (JSON file mode), PAN-OS target, FortiGate target with non-FTD source, and FTD target.

#### Import & Cleanup Tabs - Dynamic Tab Titles

- The Import and Cleanup tab titles and section frame headers now update based on the selected target platform instead of being hard-coded to "FTD":
  - **FTD target**: "Import to FTD" / "Cleanup FTD"
  - **PAN-OS target**: "Import to PAN-OS" / "Cleanup PAN-OS"
  - **FortiGate target**: "Import (N/A for FortiGate)" / "Cleanup (N/A for FortiGate)" - reflects that API-based import/cleanup is not supported for FortiGate (config must be applied manually)
- The top `LabelFrame` section headers on both tabs (e.g. "FTD Connection & Import Options") are retitled to match.

---

### Files Modified

| File | Changes |
|------|---------|
| `gui_app.py` | HA Port label text now switches to "FTD Username:" when FTD is the source; new `_retitle_import_cleanup_tabs` helper updates Import/Cleanup tab titles and section frame labels per target platform; version bumped to 1.6.1 |

---

---

## v1.6.0 - Cisco FTD → FortiGate Conversion Support

### Overview

Adds a live Cisco FTD to FortiGate conversion pipeline. The converter connects directly to the FTD Firepower Device Manager (FDM) REST API, reads the running configuration, and produces a single FortiGate CLI `.conf` file - no offline export required. Apply the output via CLI paste or the FortiGate web UI restore feature.

---

### New Features

#### Cisco FTD → FortiGate Conversion Engine (`CiscoFTDToFortiGateTool/`)

- **FDM API Reader** (`ftd_reader.py`) - Authenticates to the FTD FDM REST API (OAuth 2.0 password grant), reads all supported object types with automatic offset/limit pagination; handles 404 gracefully for object types not present on a given FTD version
- **Address Objects** - FTD `networkobject` (`HOST`, `NETWORK`, `RANGE`, `FQDN`) → FortiGate `config firewall address`
- **Address Groups** - FTD `networkgroup` (with inline literal expansion) → FortiGate `config firewall addrgrp`; inline IP/subnet literals auto-generate supplemental address objects
- **Service Objects** - FTD TCP and UDP port objects → FortiGate `config firewall service custom`; `_TCP`/`_UDP` suffix pairs (produced by the reverse FG→PA converter) automatically merged back into dual-protocol FortiGate service objects
- **Service Groups** - FTD port groups → FortiGate `config firewall service group`
- **Interfaces** - Physical Ethernet and EtherChannel (LACP aggregate) interfaces → FortiGate `config system interface` with IP, admin state, and zone membership
- **Zones** - FTD security zones → FortiGate `config system zone` with member interface lists
- **Security Policies** - FTD access rules → FortiGate `config firewall policy`; maps source/destination zones, address objects, service objects, rule action (`PERMIT`→`accept`, `DENY`→`deny`), logging, and disabled state
- **Static Routes** - FTD static routes from all virtual routers → FortiGate `config router static`
- **Main Orchestrator** (`fg_ftd_converter.py`) - 8-phase pipeline; outputs a single timestamped `.conf` file with a header comment documenting the source host, generation time, and application notes

#### GUI Updates

- **"Cisco FTD" source option** added to the Source dropdown
- Selecting Cisco FTD source automatically locks the Target to "FortiGate"
- Input field repurposed as **FTD Host / IP** entry; file browse button disabled
- HA port field repurposed as **FTD username** entry (defaults to `admin`)
- Password collected via a secure dialog at convert time (not stored)
- Model selector disabled (not applicable for FortiGate target)
- Import and Cleanup buttons show an informational dialog for FortiGate targets
- Title bar updates to "Cisco FTD to FortiGate Migration Tool"

---

### Files Added

| File | Purpose |
|------|---------|
| `CiscoFTDToFortiGateTool/__init__.py` | Package marker |
| `CiscoFTDToFortiGateTool/ftd_reader.py` | FDM REST API reader with pagination |
| `CiscoFTDToFortiGateTool/fg_ftd_converter.py` | 8-phase conversion orchestrator |
| `Firewall-Migration-Tool-v1.6.0.spec` | PyInstaller build spec |

### Files Modified

| File | Changes |
|------|---------|
| `gui_app.py` | Cisco FTD source option, FDM host/username input, secure password dialog, v1.6.0 |

---

---

## v1.5.0 - Palo Alto → FortiGate Conversion Support & Dependency Updates

### Overview

Adds a full Palo Alto PAN-OS to FortiGate conversion pipeline. A PAN-OS XML running configuration (exported from the device or retrieved via the XML API) is parsed and converted to a single FortiGate CLI `.conf` file that can be applied directly via CLI paste or the FortiGate web UI restore feature. Also updates all runtime and build dependencies to their latest versions.

---

### New Features

#### Palo Alto → FortiGate Conversion Engine (`PaloAltoToFortiGateTool/`)

- **PAN-OS XML Parser** (`fg_pa_parser.py`) - Parses PAN-OS XML running configs including device exports, `show config running` output, and XML API responses; supports both NGFW (vsys1) and Panorama shared-object layouts
- **Address Objects** (`fg_address_converter.py`) - `ip-netmask` (subnet/host), `ip-range`, and `fqdn` types → FortiGate `firewall address`
- **Address Groups** (`fg_address_group_converter.py`) - Static groups → FortiGate `firewall addrgrp`; nested groups preserved natively (no flattening required)
- **Service Objects** (`fg_service_converter.py`) - TCP and UDP service objects → FortiGate `firewall service custom`; companion `_TCP`/`_UDP` pairs (produced by the reverse FG→PA converter) are automatically detected and merged back into a single dual-protocol FortiGate object
- **Service Groups** (`fg_service_group_converter.py`) - Service groups → FortiGate `firewall service group` with name-map resolution for merged service objects
- **Security Policies** (`fg_policy_converter.py`) - Security rules → FortiGate `firewall policy`; maps zones to `srcintf`/`dstintf`, PAN-OS `any` address to FortiGate `all`, `application-default` service to `ALL`, action deny/drop/reset-* to FortiGate `deny`, and preserves disabled rule state
- **Static Routes** (`fg_route_converter.py`) - Static routes → FortiGate `router static`; CIDR notation converted to IP + netmask pairs
- **Interfaces & Zones** (`fg_interface_converter.py`) - Physical, VLAN, and loopback interfaces → FortiGate `system interface`; PAN-OS zones → FortiGate `system zone`
- **Main Orchestrator** (`fg_converter.py`) - Runs all 7 phases in dependency order and writes a single timestamped `.conf` file with a header block documenting the source file, generation time, and application notes

#### GUI Updates

- **"Palo Alto" source option** added to the Source dropdown
- Selecting Palo Alto source automatically locks the Target to "FortiGate" and sets the input file browser to filter for `.xml` files
- Model selector and HA port field are disabled (not applicable for FortiGate target)
- Import and Cleanup buttons show an informational dialog explaining how to apply the `.conf` file manually
- Title bar updates to "Palo Alto to FortiGate Migration Tool"

---

### How to Apply the Output

The converter produces a single `<output_base>.conf` file. Apply it using either method:

**FortiGate CLI** - paste sections directly (granular, section-by-section):
```
config firewall address
    edit "webserver"
        set subnet 10.10.20.100 255.255.255.255
    next
end
```

**Web UI restore** - go to **System > Configuration > Restore**, upload the `.conf` file. FortiGate merges the commands into the running configuration automatically.

> **Note:** Interface-to-physical-port assignments must be reviewed and adjusted to match the target FortiGate hardware after applying the configuration.

---

### Dependency Updates

All runtime and build dependencies updated to latest versions:

| Package | Previous | Updated |
|---------|----------|---------|
| certifi | 2025.11.12 | 2026.4.22 |
| charset-normalizer | 3.4.4 | 3.4.7 |
| cryptography | 42.0.8 | 43.0.3 |
| idna | 3.11 | 3.13 |
| invoke | 2.2.1 | 3.0.3 |
| packaging | 26.0 | 26.1 |
| pydantic | 2.12.5 | 2.13.3 |
| pydantic_core | 2.41.5 | 2.46.3 |
| Pygments | 2.19.2 | 2.20.0 |
| pyinstaller | 6.19.0 | 6.20.0 |
| pyinstaller-hooks-contrib | 2026.3 | 2026.4 |
| PyNaCl | 1.6.1 | 1.6.2 |
| rich | 14.2.0 | 15.0.0 |
| ruamel.yaml | 0.18.16 | 0.19.1 |
| setuptools | 80.9.0 | 82.0.1 |
| tomli | 2.4.0 | 2.4.1 |
| urllib3 | 2.6.0 | 2.6.3 |
| wheel | 0.45.1 | 0.47.0 |
| zipp | 3.23.0 | 3.23.1 |

`requirements.txt` minimum versions updated to reflect the currently tested versions (`pyyaml>=6.0.3`, `requests>=2.32.5`, `urllib3>=2.6.3`).

---

### Files Added

| File | Purpose |
|------|---------|
| `PaloAltoToFortiGateTool/__init__.py` | Package marker |
| `PaloAltoToFortiGateTool/fg_common.py` | Shared utilities (CIDR↔netmask, name sanitization) |
| `PaloAltoToFortiGateTool/fg_pa_parser.py` | PAN-OS XML configuration parser |
| `PaloAltoToFortiGateTool/fg_address_converter.py` | Address object converter |
| `PaloAltoToFortiGateTool/fg_address_group_converter.py` | Address group converter |
| `PaloAltoToFortiGateTool/fg_service_converter.py` | Service object converter with TCP+UDP merge |
| `PaloAltoToFortiGateTool/fg_service_group_converter.py` | Service group converter |
| `PaloAltoToFortiGateTool/fg_policy_converter.py` | Security policy converter |
| `PaloAltoToFortiGateTool/fg_route_converter.py` | Static route converter |
| `PaloAltoToFortiGateTool/fg_interface_converter.py` | Interface and zone converter |
| `PaloAltoToFortiGateTool/fg_converter.py` | Main orchestrator |
| `Firewall-Migration-Tool-v1.5.0.spec` | PyInstaller build spec |

### Files Modified

| File | Changes |
|------|---------|
| `gui_app.py` | Palo Alto source option, FortiGate target handling, XML file browser, v1.5.0 |
| `requirements.txt` | Minimum version bumps for pyyaml, requests, urllib3 |

---

---

## v1.4.0 - Update Existing Objects, Cleanup Password Protection, Python 3.14

### Overview

Adds the ability to update existing firewall objects during import (instead of skipping duplicates), password protection for the cleanup feature, and upgrades the build toolchain to Python 3.14.

---

### New Features

#### Update Existing Objects (FTD Import)

- **Update-by-default** - When an object already exists on the target FTD, the importer now automatically updates it to match the new configuration via GET + merge + PUT instead of skipping it
- **Generic object lookup** - New `_get_object_by_name_from_endpoint()` method uses filter parameters with paginated fallback to find existing objects across all endpoint types
- **Merge-and-PUT pattern** - Retrieves the existing object (to get `id`/`version`), merges the new payload on top, and PUTs it back
- **Works for all object types** - Address objects, address groups, service objects, service groups, security zones, static routes, access rules, EtherChannels, bridge groups, and subinterfaces
- **`--skip-existing` flag** - Opt out of updates and revert to the previous skip-on-duplicate behavior
- **GUI checkbox** - "Update existing objects" checkbox in the Import tab (checked by default)
- **Updated statistics** - `print_statistics()` now shows an "Updated:" count for every object type
- **Threaded support** - Update detection works correctly with the threaded import pool via the `"UPDATED:"` result prefix convention

#### Cleanup Password Protection

- **Password-gated cleanup** - A password prompt appears every time "Start Cleanup" is clicked in the GUI, preventing accidental deletion of firewall objects
- **Built-in default password** - A PBKDF2-HMAC-SHA256 hashed password is baked into the source code at build time (no external files required)
- **User-changeable password** - "Change Cleanup Password" button creates a `cleanup_auth.json` override file next to the application
- **Automatic fallback** - If `cleanup_auth.json` is deleted, the app falls back to the built-in default password (users are never locked out)
- **Reset to default** - "Reset to Default Password" button removes the override file and reverts to the built-in password
- **`set_cleanup_password.py` utility** - Change the built-in default password before building the exe
- **Standard library only** - Uses `hashlib.pbkdf2_hmac` (no third-party crypto dependencies), fully portable across machines

#### Python 3.14 Build

- **Build toolchain upgraded** - `build.bat` now uses `py -3.14` explicitly for both pip and PyInstaller
- **Modern Python features** - Union type syntax (`str | None`), improved performance, and full `cryptography` library compatibility

---

### GUI Changes

- **Import tab** - New "Update existing objects (uncheck to skip duplicates)" checkbox at row 8
- **Cleanup tab** - New "Change Cleanup Password" and "Reset to Default Password" buttons (right-aligned in button row)
- **Cleanup tab** - Password prompt dialog before every cleanup operation

---

### CLI Changes

#### FTD Importer (`ftd_api_importer.py`)

| Flag | Description |
|------|-------------|
| `--skip-existing` | Skip objects that already exist instead of updating them (default: update) |

#### Utility Scripts

| Script | Description |
|--------|-------------|
| `set_cleanup_password.py <password>` | Set the built-in default cleanup password (rebuild exe afterward) |

---

### Files Added

| File | Purpose |
|------|---------|
| `cleanup_auth.py` | Cleanup password authentication module (PBKDF2 hashing, fallback logic) |
| `set_cleanup_password.py` | Utility to change the built-in default cleanup password |

### Files Modified

| File | Changes |
|------|---------|
| `gui_app.py` | Update-existing checkbox, cleanup password UI, password gate on cleanup |
| `FortiGateToFTDTool/ftd_api_importer.py` | `_get_object_by_name_from_endpoint()`, `_update_existing_object()`, update logic in all create methods, `--skip-existing` flag, updated statistics |
| `build.bat` | Python 3.14 (`py -3.14`), `cleanup_auth` hidden import |
| `README.md` | Cleanup password documentation, file listing updates |

---

---

## v1.2.0 - Theme Selector

### Overview

Adds a live theme selector to the GUI with two built-in themes. The theme system is data-driven - adding new themes only requires adding an entry to the `THEMES` dictionary in `gui_app.py`.

---

### New Features

#### Theme Engine

- **Live theme switching** - Theme dropdown in the top toolbar (right-aligned) allows switching themes without restarting the app
- **Ocean Coral** (default) - Dark teal background with coral accents and teal highlights
- **Chris** - Hot pink background with neon green accents and blue text

#### Theme Architecture

- All color values defined in a single `THEMES` dictionary for easy customization
- Theme applies to all ttk-styled widgets (frames, labels, buttons, tabs, entries, comboboxes, checkbuttons, spinboxes, scrollbars)
- Raw tk widgets (Text, Listbox) are registered and recolored on theme change
- Button text color is theme-aware via `btn_fg` key (ensures readability on colored button backgrounds)

#### Adding Custom Themes

Add a new entry to the `THEMES` dict in `gui_app.py` with these keys:

| Key        | Description                         |
|------------|-------------------------------------|
| `bg`       | Root/frame background               |
| `input`    | Entry/combobox field background     |
| `fg`       | Primary text color                  |
| `fg_dim`   | Secondary/disabled text             |
| `accent`   | Accent color (active elements)      |
| `accent_d` | Dark accent (selected tabs, pressed)|
| `accent_h` | Hover accent                        |
| `border`   | Border color                        |
| `btn_bg`   | Button background                   |
| `btn_fg`   | Button text color                   |
| `tab_bg`   | Inactive tab background             |
| `out_bg`   | Output console background           |
| `out_fg`   | Output console text color           |

---

### Other Changes

- Renamed color variables from `_PURPLE`/`_PURPLE_D`/`_PURPLE_H` to `_ACCENT`/`_ACCENT_D`/`_ACCENT_H` for clarity

---

---

## v1.1.0 - Palo Alto PAN-OS Target Support

### Overview

Adds Palo Alto PAN-OS as a second conversion target alongside Cisco FTD. FortiGate configurations can now be migrated to either Cisco FTD or Palo Alto firewalls using the same source YAML input. The Palo Alto implementation includes a full conversion engine, XML API importer, bulk cleanup tool, and GUI integration. **Note:** Palo Alto support is in beta - the base is implemented but live device testing is still in progress.

---

### New Features

#### Palo Alto Conversion Engine (`FortiGateToPaloAltoTool/`)

- **Address Objects** - Hosts (ip-netmask /32), subnets (ip-netmask), IP ranges (ip-range), and FQDNs with PAN-OS name sanitization (63-char max, alphanumeric/underscore/hyphen/period)
- **Address Groups** - Static address groups with nested group support
- **Service Objects** - TCP/UDP port objects; dual-protocol services automatically split into separate PAN-OS objects (one protocol per object requirement)
- **Service Groups** - Port groups with automatic split-service reference resolution and member deduplication
- **Security Rules** - FortiGate policies mapped to PAN-OS security rules with zone-based source/destination, address objects, service objects, and action mapping (accept→allow, deny→deny); logging configurable
- **Static Routes** - IPv4 routes using CIDR notation directly (no separate gateway objects); blackhole route filtering
- **Interfaces** - Physical interfaces, VLAN subinterfaces, and aggregate-ethernet (LACP) with model-aware port mapping
- **Zones** - Auto-generated from interface assignments
- **10 output JSON files** per conversion including summary statistics and metadata

#### Supported Palo Alto Models (6)

| Model   | Description  |
|---------|--------------|
| PA-440  | Entry-level  |
| PA-450  | Entry-level  |
| PA-460  | Entry-level  |
| PA-3220 | Mid-range    |
| PA-3250 | Mid-range    |
| PA-5220 | Enterprise   |

#### PAN-OS XML API Importer (`panos_api_importer.py`)

- **Dependency-ordered import** - Zones → addresses → address groups → services → service groups → routes → security rules
- **API key authentication** - Automatic key generation via PAN-OS keygen endpoint
- **Dry-run mode** - Preview import without making changes
- **Optional auto-commit** - Commit configuration changes after import via `--commit`
- **Debug mode** - Inspect XML API payloads
- **SSL handling** - Self-signed certificate support

#### PAN-OS Bulk Cleanup (`panos_api_cleanup.py`)

- **Selective or full deletion** - Delete specific object types or all custom objects
- **Reverse dependency order** - Security rules → service groups → services → address groups → addresses → routes → zones
- **Dry-run mode** - Preview deletions
- **Interactive confirmation** - Safety prompt before destructive operations
- **Optional auto-commit** - Commit after cleanup

#### GUI Updates

- **Platform selector** - Dropdown at top of GUI to switch between Cisco FTD and Palo Alto PAN-OS
- **Dynamic tab updates** - Convert, Import, and Cleanup tabs adapt to selected platform
- **Palo Alto model selection** - PA model dropdown replaces FTD models when PA is selected
- **Commit toggle** - "Commit after import/cleanup" checkbox for PAN-OS operations

---

### Key Differences: Palo Alto vs Cisco FTD

| Aspect | Palo Alto PAN-OS | Cisco FTD |
|--------|------------------|-----------|
| API | XML API (keygen auth) | REST API (OAuth 2.0) |
| Service objects | One protocol per object (auto-split) | Supports dual-protocol |
| Routes | CIDR notation directly | Separate gateway network objects |
| Zones | Auto-generated from interfaces | Defined in config |
| Import concurrency | Sequential | Multithreaded (`--workers`) |
| HA configuration | Managed externally | Configurable via `--ha-port` |
| Name max length | 63 characters | Varies |

---

### CLI Quick Reference

```bash
# Convert for Palo Alto
python FortiGateToPaloAltoTool/pa_converter.py config.yaml --target-model pa-3220 --pretty

# List PA models
python FortiGateToPaloAltoTool/pa_converter.py --list-models

# Import to PAN-OS
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin --commit

# Dry-run import
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin --dry-run

# Cleanup PAN-OS
python FortiGateToPaloAltoTool/panos_api_cleanup.py --host 10.0.0.1 --username admin --delete-all --dry-run
```

---

### Known Limitations (Palo Alto)

- ICMP, ICMP6, IP, IPIP, GRE, ESP, and AH protocol services are skipped during conversion
- Application field in security rules is set to "any" (manual tuning recommended post-migration)
- Loopback, tunnel, and switch interfaces are not converted
- Only IPv4 addresses and routes are supported
- Live device testing is in progress - verify results on a test device before production use

---

---

## v1.0.0 - Initial Release

### Overview

FortiGate to Cisco FTD Configuration Converter is a three-phase migration tool that converts FortiGate firewall configurations (YAML) into Cisco FTD-compatible JSON, imports them via the FDM REST API, and provides bulk cleanup/rollback capabilities. Includes a full GUI application and CLI interface.

---

### Features

#### Conversion Engine

- **Network Objects** - Hosts, subnets (CIDR), IP ranges, and FQDNs with automatic type detection and name sanitization
- **Network Groups** - Address groups with automatic nested-group flattening and circular reference detection
- **Service Objects** - TCP/UDP port objects with automatic splitting of dual-protocol services into separate FTD-compatible entries
- **Service Groups** - Port object groups with expanded split-service references and member deduplication
- **Access Control Rules** - Firewall policies with multi-zone, multi-service, and multi-network support; FortiGate action mapping (accept/deny to PERMIT/DENY)
- **Static Routes** - IPv4 routing entries with gateway object creation, default route handling, and blackhole route filtering
- **Interfaces** - Physical interfaces, EtherChannels, subinterfaces (VLANs), and bridge groups with model-aware port mapping
- **Security Zones** - Auto-generated from interface names and aliases
- **13 output JSON files** per conversion including summary statistics and metadata

#### Supported FTD Models (13)

| Model    | Ports | HA Port     |
|----------|-------|-------------|
| FTD-1010 | 8     | None        |
| FTD-1120 | 12    | Ethernet1/2 |
| FTD-1140 | 12    | Ethernet1/2 |
| FTD-2110 | 12    | Ethernet1/2 |
| FTD-2120 | 12    | Ethernet1/2 |
| FTD-2130 | 16    | Ethernet1/2 |
| FTD-2140 | 16    | Ethernet1/2 |
| FTD-3105 | 8     | Ethernet1/2 |
| FTD-3110 | 16    | Ethernet1/2 |
| FTD-3120 | 16    | Ethernet1/2 |
| FTD-3130 | 24    | Ethernet1/2 |
| FTD-3140 | 24    | Ethernet1/2 |
| FTD-4215 | 8     | Ethernet1/2 |

Custom HA port override supported via `--ha-port`.

#### FDM API Import

- **11 selective import filters** - Physical interfaces, EtherChannels, subinterfaces, bridge groups, security zones, address objects, address groups, service objects, service groups, static routes, and access rules
- **Dependency-ordered import** - Objects created in the correct sequence to satisfy FTD reference requirements
- **Idempotent operations** - Existing objects are skipped without error
- **Multithreaded** - Configurable worker count (1–32, default 6) for concurrent object creation
- **OAuth 2.0 authentication** - Automatic token refresh with thread-safe locking and fallback re-authentication
- **Retry with exponential backoff** - Up to 4 attempts with jittered delays for transient errors (429, 503, 504)
- **Optional deployment** - Trigger FTD deployment immediately after import
- **JSON report output** - Machine-readable import summary

#### Bulk Cleanup / Rollback

- **Selective or full deletion** - Delete specific object types or all custom objects
- **Dry-run mode** - Preview what would be deleted without making changes
- **System-object protection** - System-defined objects are never deleted
- **Confirmation prompt** - Interactive approval required before destructive operations
- **Multithreaded deletion** - Same configurable concurrency as import

#### GUI Application

- **Three-tab interface** - Convert, Import to FTD, and Cleanup tabs
- **Real-time console output** - Streaming progress updates during all operations
- **Dark theme** - Professional dark interface with green accents
- **Full control** - All CLI options exposed through the GUI (model selection, worker count, selective imports, dry-run, deploy toggle, debug mode)
- **File/directory browsers** - Native OS dialogs for selecting input configs and output directories

#### CLI Interface

```
# Convert
python fortigate_converter.py config.yaml --target-model ftd-3120 --pretty

# Import
python ftd_api_importer.py --host 192.168.1.1 -u admin --deploy --workers 6

# Cleanup
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --dry-run
```

---

### Requirements

- Python 3.9+
- FTD 7.4.x with FDM local management (not FMC-managed)
- Dependencies: `pyyaml>=6.0`, `requests>=2.28.0`, `urllib3>=1.26.0`
- Airgapped installation supported via pip wheel packages

---

### Known Limitations

- ICMP and non-port protocol services are skipped during conversion
- FortiGate schedule-based policies are converted but schedule conditions are not mapped
- Only IPv4 addresses and routes are supported
- FTD must be locally managed via FDM (FMC-managed devices are not supported)
