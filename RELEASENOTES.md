# Release Notes

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

| Model | Ports | HA Port |
|-------|-------|---------|
| FTD-1010 | 8 | None |
| FTD-1120 | 12 | Ethernet1/2 |
| FTD-1140 | 12 | Ethernet1/2 |
| FTD-2110 | 12 | Ethernet1/2 |
| FTD-2120 | 12 | Ethernet1/2 |
| FTD-2130 | 16 | Ethernet1/2 |
| FTD-2140 | 16 | Ethernet1/2 |
| FTD-3105 | 8 | Ethernet1/2 |
| FTD-3110 | 16 | Ethernet1/2 |
| FTD-3120 | 16 | Ethernet1/2 |
| FTD-3130 | 24 | Ethernet1/2 |
| FTD-3140 | 24 | Ethernet1/2 |
| FTD-4215 | 8 | Ethernet1/2 |

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
