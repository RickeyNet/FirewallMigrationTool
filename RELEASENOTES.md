# Release Notes

## v1.1.0 — Palo Alto PAN-OS Target Support

### Overview

Adds Palo Alto PAN-OS as a second conversion target alongside Cisco FTD. FortiGate configurations can now be migrated to either Cisco FTD or Palo Alto firewalls using the same source YAML input. The Palo Alto implementation includes a full conversion engine, XML API importer, bulk cleanup tool, and GUI integration. **Note:** Palo Alto support is in beta — the base is implemented but live device testing is still in progress.

---

### New Features

#### Palo Alto Conversion Engine (`FortiGateToPaloAltoTool/`)

- **Address Objects** — Hosts (ip-netmask /32), subnets (ip-netmask), IP ranges (ip-range), and FQDNs with PAN-OS name sanitization (63-char max, alphanumeric/underscore/hyphen/period)
- **Address Groups** — Static address groups with nested group support
- **Service Objects** — TCP/UDP port objects; dual-protocol services automatically split into separate PAN-OS objects (one protocol per object requirement)
- **Service Groups** — Port groups with automatic split-service reference resolution and member deduplication
- **Security Rules** — FortiGate policies mapped to PAN-OS security rules with zone-based source/destination, address objects, service objects, and action mapping (accept→allow, deny→deny); logging configurable
- **Static Routes** — IPv4 routes using CIDR notation directly (no separate gateway objects); blackhole route filtering
- **Interfaces** — Physical interfaces, VLAN subinterfaces, and aggregate-ethernet (LACP) with model-aware port mapping
- **Zones** — Auto-generated from interface assignments
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

- **Dependency-ordered import** — Zones → addresses → address groups → services → service groups → routes → security rules
- **API key authentication** — Automatic key generation via PAN-OS keygen endpoint
- **Dry-run mode** — Preview import without making changes
- **Optional auto-commit** — Commit configuration changes after import via `--commit`
- **Debug mode** — Inspect XML API payloads
- **SSL handling** — Self-signed certificate support

#### PAN-OS Bulk Cleanup (`panos_api_cleanup.py`)

- **Selective or full deletion** — Delete specific object types or all custom objects
- **Reverse dependency order** — Security rules → service groups → services → address groups → addresses → routes → zones
- **Dry-run mode** — Preview deletions
- **Interactive confirmation** — Safety prompt before destructive operations
- **Optional auto-commit** — Commit after cleanup

#### GUI Updates

- **Platform selector** — Dropdown at top of GUI to switch between Cisco FTD and Palo Alto PAN-OS
- **Dynamic tab updates** — Convert, Import, and Cleanup tabs adapt to selected platform
- **Palo Alto model selection** — PA model dropdown replaces FTD models when PA is selected
- **Commit toggle** — "Commit after import/cleanup" checkbox for PAN-OS operations

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
- Live device testing is in progress — verify results on a test device before production use

---

---

## v1.0.0 — Initial Release

### Overview

FortiGate to Cisco FTD Configuration Converter is a three-phase migration tool that converts FortiGate firewall configurations (YAML) into Cisco FTD-compatible JSON, imports them via the FDM REST API, and provides bulk cleanup/rollback capabilities. Includes a full GUI application and CLI interface.

---

### Features

#### Conversion Engine

- **Network Objects** — Hosts, subnets (CIDR), IP ranges, and FQDNs with automatic type detection and name sanitization
- **Network Groups** — Address groups with automatic nested-group flattening and circular reference detection
- **Service Objects** — TCP/UDP port objects with automatic splitting of dual-protocol services into separate FTD-compatible entries
- **Service Groups** — Port object groups with expanded split-service references and member deduplication
- **Access Control Rules** — Firewall policies with multi-zone, multi-service, and multi-network support; FortiGate action mapping (accept/deny to PERMIT/DENY)
- **Static Routes** — IPv4 routing entries with gateway object creation, default route handling, and blackhole route filtering
- **Interfaces** — Physical interfaces, EtherChannels, subinterfaces (VLANs), and bridge groups with model-aware port mapping
- **Security Zones** — Auto-generated from interface names and aliases
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

- **11 selective import filters** — Physical interfaces, EtherChannels, subinterfaces, bridge groups, security zones, address objects, address groups, service objects, service groups, static routes, and access rules
- **Dependency-ordered import** — Objects created in the correct sequence to satisfy FTD reference requirements
- **Idempotent operations** — Existing objects are skipped without error
- **Multithreaded** — Configurable worker count (1–32, default 6) for concurrent object creation
- **OAuth 2.0 authentication** — Automatic token refresh with thread-safe locking and fallback re-authentication
- **Retry with exponential backoff** — Up to 4 attempts with jittered delays for transient errors (429, 503, 504)
- **Optional deployment** — Trigger FTD deployment immediately after import
- **JSON report output** — Machine-readable import summary

#### Bulk Cleanup / Rollback

- **Selective or full deletion** — Delete specific object types or all custom objects
- **Dry-run mode** — Preview what would be deleted without making changes
- **System-object protection** — System-defined objects are never deleted
- **Confirmation prompt** — Interactive approval required before destructive operations
- **Multithreaded deletion** — Same configurable concurrency as import

#### GUI Application

- **Three-tab interface** — Convert, Import to FTD, and Cleanup tabs
- **Real-time console output** — Streaming progress updates during all operations
- **Dark theme** — Professional dark interface with green accents
- **Full control** — All CLI options exposed through the GUI (model selection, worker count, selective imports, dry-run, deploy toggle, debug mode)
- **File/directory browsers** — Native OS dialogs for selecting input configs and output directories

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
