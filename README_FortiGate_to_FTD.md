# FortiGate → Cisco FTD Migration Guide

A focused, standalone guide for converting a **FortiGate** firewall configuration to **Cisco FTD** (Firepower Threat Defense, FDM-managed) and importing it via the FDM REST API. This document covers only the FortiGate → FTD path and includes air-gapped installation instructions.

> For other migration paths (Palo Alto, Cisco ASA, reverse conversions) and the unified GUI, see the main `README.md`.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Air-Gapped / Offline Installation](#air-gapped--offline-installation)
5. [Quick Start Checklist](#quick-start-checklist)
6. [Phase 1: Convert the FortiGate Configuration](#phase-1-convert-the-fortigate-configuration)
   - [Target Models](#step-2-identify-your-target-ftd-model)
   - [Customizing HA Ports](#step-2a-customizing-ha-port-configuration)
   - [Advanced Interface Mapping (Map / Promote / Expand)](#step-2c-advanced-interface-mapping-map--promote--expand)
   - [Generated Files & Metadata](#step-4-review-generated-files)
   - [Automatic VLAN Conflict Resolution](#automatic-vlan-conflict-resolution)
7. [Phase 2: Import to FTD](#phase-2-import-to-ftd)
8. [Phase 3: Cleanup / Rollback](#phase-3-cleanup--rollback)
9. [SNMPv3 Configuration](#snmpv3-configuration-fdm-managed-ftd)
10. [Performance and Concurrency](#performance-and-concurrency)
11. [Troubleshooting](#troubleshooting)
12. [Best Practices](#best-practices)
13. [Appendix: File Formats & Complete Command Reference](#appendix-file-formats--complete-command-reference)

---

## Overview

This tool converts a FortiGate firewall configuration (exported as YAML) into Cisco FTD FDM API JSON files, then pushes those objects to the appliance through the FDM REST API.

The workflow has three phases:

1. **Convert** — `fortigate_converter.py` reads FortiGate YAML and writes 13 JSON files.
2. **Import** — `ftd_api_importer.py` pushes the JSON to FTD in dependency order.
3. **Cleanup (optional)** — `ftd_api_cleanup.py` removes the imported objects for rollback.

A separate `ftd_snmp_config.py` script pushes a STIG-compliant SNMPv3 configuration that FDM's GUI does not expose.

### What Gets Converted

| Object Type          | Notes                                                                 |
|----------------------|-----------------------------------------------------------------------|
| Address Objects      | Hosts, subnets, ranges, FQDNs                                         |
| Address Groups       | Network object groups                                                  |
| Service Port Objects | TCP/UDP ports (services with both TCP and UDP are auto-split)         |
| Service Port Groups  | Port object groups                                                     |
| ICMP "ping"          | Migrated to two ICMPv4 port objects (echo request + echo reply) grouped as `PING` |
| Interfaces           | Physical, subinterfaces, EtherChannels, bridge groups                 |
| Security Zones       | Auto-created from interface aliases                                    |
| Static Routes        | IPv4 routes with gateway references                                   |
| Firewall Policies    | Access control rules                                                   |

### Key Features

- Model-aware interface port mapping with customizable HA port assignment (supports dual-HA links).
- Advanced interface mapping — pin interfaces to specific ports, or promote/expand EtherChannels and bridge groups.
- Network-module support — add expansion-card ports (`Ethernet2/x`) to the pool.
- Automatic VLAN ID conflict resolution (FTD requires device-wide unique VLAN IDs).
- Automatic name sanitization (spaces → underscores).
- Idempotent imports (existing objects are updated in place; re-runs are safe).
- Bulk cleanup/delete for rollback.
- SNMPv3 configuration push for FDM-managed FTD (STIG CASA-ND-001050 / CASA-ND-001070).

---

## Prerequisites

### System Requirements

| Requirement | Minimum                           | Recommended   |
|-------------|-----------------------------------|---------------|
| Python      | 3.9                               | 3.9 or higher |
| OS          | Windows, macOS, Linux             | Any           |
| Network     | Connectivity to FTD management IP | HTTPS (443)   |

### FTD Requirements

| Requirement      | Details                                                                          |
|------------------|----------------------------------------------------------------------------------|
| Management Mode  | Local FDM (Firewall Device Manager) — **not** FMC-managed                        |
| Firmware         | 7.4.x (tested on 7.4.2.4-9)                                                       |
| Credentials      | Admin username and password                                                      |
| Supported Models | FTD-1010, 1120, 1140, 2110, 2120, 2130, 2140, 3105, 3110, 3120, 3130, 3140, 4215 |

### Python Libraries

```bash
pip install -r requirements.txt
```

The tool depends on `PyYAML`, `requests`, and `urllib3` (plus their transitive dependencies).

---

## Installation

### Step 1: Get the Project

Clone or download the full repository. The tools live in subdirectories and import each other as packages, so copy the **entire project** — not individual script files.

```bash
git clone https://github.com/RickeyNet/FirewallMigrationTool.git
cd FirewallMigrationTool
```

The FortiGate → FTD path uses these files:

```
FirewallMigrationTool/
├── requirements.txt                    # Python dependencies
├── FortiGateToFTDTool/
│   ├── fortigate_converter.py          # Convert FortiGate YAML → FTD JSON
│   ├── ftd_api_importer.py             # Import FTD JSON via FDM REST API
│   ├── ftd_api_cleanup.py              # FTD bulk delete/cleanup utility
│   ├── ftd_snmp_config.py              # SNMPv3 push for FDM-managed FTD
│   └── ...                             # Converter modules (address, service, policy, route, interface, etc.)
├── fortigate_config.yaml               # Your FortiGate YAML (input)
├── ftd_config_*.json                   # Generated FTD JSON files (output)
```

All CLI examples below assume you run commands from the **repository root**. You may instead `cd FortiGateToFTDTool` and drop the `FortiGateToFTDTool/` prefix.

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Verify Installation

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

---

## Air-Gapped / Offline Installation

For machines without internet access, download the Python packages on a connected machine, transfer them, and install from the local folder.

### On an Internet-Connected Machine

Test that Python can find the libraries (optional, if already installed there):

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

Create a directory for the packages and download them with all dependencies:

```bash
# Create a directory for the packages (from the repo root)
mkdir ftd_migration_packages

# Download packages and their dependencies
pip download -r requirements.txt -d ftd_migration_packages

# If you target a specific Python (e.g. 3.9) on Windows:
py -3.9 -m pip download -r requirements.txt -d ftd_migration_packages
```

This downloads files like:
- `PyYAML-6.0.1-cp39-cp39-win_amd64.whl`
- `requests-2.31.0-py3-none-any.whl`
- `urllib3-2.0.7-py3-none-any.whl`
- `certifi-2023.7.22-py3-none-any.whl` (dependency)
- `charset-normalizer-3.3.2-cp39-cp39-win_amd64.whl` (dependency)
- `idna-3.4-py3-none-any.whl` (dependency)

### On the Air-Gapped Machine

1. Move the package folder, `requirements.txt`, and **all scripts** to the air-gapped machine (including the Python 3.x installer if Python is not already installed).

2. Install Python and check **"Add to PATH"** on the installer.

3. Check that Python paths are present:
   ```bash
   # CMD Prompt
   echo %path%

   # PowerShell
   $Env:Path -split ";"
   ```

4. Or manually add to PATH via Environment Variables (then log out/in or reboot):
   - `C:\Users\<name>\AppData\Local\Programs\Python\Python39\`
   - `C:\Users\<name>\AppData\Local\Programs\Python\Python39\Scripts`

5. Test the Python installation:
   ```bash
   python
   # Should display: Python 3.x.x
   # Type exit() to quit
   ```

6. From the directory where `requirements.txt` lives, install from the local package folder:
   ```bash
   python -m pip install --no-index --find-links=ftd_migration_packages -r requirements.txt
   ```

7. Verify the libraries are installed:
   ```bash
   python -c "import yaml, requests, urllib3; print('All libraries installed!')"
   ```

> **Tip:** Build the download folder on a machine with the **same OS, CPU architecture, and Python version** as the air-gapped target. Wheels are platform- and version-specific (e.g. `cp39 ... win_amd64`).

---

## Quick Start Checklist

### Before You Begin

```
□ Install Python 3.9+
□ Install libraries: pip install -r requirements.txt
□ Clone or download the full project (the whole FortiGateToFTDTool directory)
□ Export FortiGate config as YAML
□ Backup the FTD configuration in FDM
□ Identify your target FTD model (e.g., ftd-3120)
```

### Conversion Phase

```
□ Run: python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --pretty
□ (Optional) Custom HA port: --ha-port Ethernet1/5 (or --ha-port none to disable)
□ Review generated JSON files (13 files including metadata)
□ Check ftd_config_summary.json for conversion statistics
□ Review any warnings in console output
□ Verify the HA port assignment matches your design
```

### Import Phase

```
□ Import interfaces first (the foundation):
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-physical-interfaces
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-etherchannels
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-subinterfaces
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-bridge-groups
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-security-zones

□ Import objects and rules (use --workers to tune concurrency, default 6):
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --workers 6

□ Deploy configuration in FDM (or pass --deploy)
□ Verify objects in the FDM web interface
□ Test traffic flows
```

### If Something Goes Wrong

```
□ Dry-run cleanup: python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run
□ Review what will be deleted
□ Execute: python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --deploy
□ Start over with a corrected configuration
```

---

## Phase 1: Convert the FortiGate Configuration

### Step 1: Export the FortiGate Configuration

1. Log in to the FortiGate web interface.
2. Click the username in the top-right corner.
3. Go to **Configuration → Backup**.
4. Select **YAML format**.
5. Click **OK** to download.
6. Save it as `fortigate_config.yaml` in your working directory.

### Step 2: Identify Your Target FTD Model

The target model controls interface port mapping.

**List available models:**
```bash
python FortiGateToFTDTool/fortigate_converter.py --list-models
```

**Supported models:**

| Model    | Ports | HA Port (default) | Description               |
|----------|-------|-------------------|---------------------------|
| ftd-1010 | 8     | None              | Entry-level, no HA        |
| ftd-1120 | 12    | None              | Small branch              |
| ftd-1140 | 12    | None              | Small branch              |
| ftd-2110 | 12    | None              | Mid-range                 |
| ftd-2120 | 12    | None              | Mid-range                 |
| ftd-2130 | 16    | None              | Mid-range                 |
| ftd-2140 | 16    | None              | Mid-range                 |
| ftd-3105 | 16    | Ethernet1/2       | Secure Firewall           |
| ftd-3110 | 16    | Ethernet1/2       | Secure Firewall           |
| ftd-3120 | 16    | Ethernet1/2       | Secure Firewall (default) |
| ftd-3130 | 24    | Ethernet1/2       | Secure Firewall           |
| ftd-3140 | 24    | Ethernet1/2       | Secure Firewall           |
| ftd-4215 | 24    | Ethernet1/2       | Enterprise                |

Models **3110/3120/3130/3140 and 4215** have a network-module slot. See [`--network-module`](#step-2c-advanced-interface-mapping-map--promote--expand).

### Step 2a: Customizing HA Port Configuration

By default, **Secure Firewall models (ftd-3105 and newer)** reserve **Ethernet1/2** for High Availability. Older models (ftd-1010 through ftd-2140) reserve no HA port unless you set one with `--ha-port`. Use `--ha-port none` on HA-capable models to free Ethernet1/2 for data.

**Syntax:**
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model MODEL --ha-port Ethernet1/X
```

**Format requirements:**
- Must be exactly `Ethernet1/X` where X is a valid port number for the model (case-sensitive — `Ethernet1/5`, not `eth1/5`).
- Port number must be between 1 and the model's maximum port count.
- For **dual-HA links**, comma-separate two ports: `--ha-port Ethernet1/2,Ethernet1/3`. All listed ports are reserved and excluded from data assignment.
- `--ha-port none` disables HA reservation entirely.

**Examples:**
```bash
# Use Ethernet1/5 for HA on a 16-port FTD-3120
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port Ethernet1/5 --pretty

# Dual-HA links
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3130 --ha-port Ethernet1/2,Ethernet1/3 --pretty

# Free Ethernet1/2 for data (no HA reservation)
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port none --pretty
```

Invalid ports/formats produce a clear error, e.g.:
```
ERROR: Invalid HA port: 'Ethernet1/99'. Model 'ftd-3120' only has ports 1-16.
```

> **Warning:** Changing the HA port after deployment requires manual FTD changes. Configure the correct HA port during initial conversion, and use the same HA port on both devices of an HA pair.

### Step 2c: Advanced Interface Mapping (Map / Promote / Expand)

By default the converter maps FortiGate interfaces to FTD ports greedily, in order. The flags below give explicit control. All are **repeatable** (pass once per interface).

The `SPEC` for promote/expand flags is one of two forms:
- **A target total count** — e.g. `wan1=2` means "end up with 2 member ports" (extras auto-assigned from the free pool).
- **An explicit port list** — e.g. `wan1=Ethernet1/6,Ethernet1/7` means "use exactly these ports as the added members."

#### `--map-port IFACE=PORT` — straight port assignment
Pin a FortiGate interface to a specific FTD port (no aggregation). It converts as a normal routed physical interface.
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --map-port wan1=Ethernet1/9 --map-port lan1=Ethernet1/10 --pretty
```

#### `--promote-portchannel IFACE=SPEC` — physical port → new EtherChannel
Promote a plain physical interface into a **new** EtherChannel. The MTU moves onto the port-channel. A routed port-channel cannot hold an IP directly, so pair with `--promote-portchannel-vlan` if the interface had an IP.
```bash
# 2-member port-channel; IP goes on Port-channelN.100
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --promote-portchannel wan1=2 --promote-portchannel-vlan wan1=100 --pretty
```

#### `--expand-portchannel PC=SPEC` — grow an existing EtherChannel
Increase the member count of an EtherChannel already present in the FortiGate config (an aggregate/802.3ad interface).
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --expand-portchannel WAN_LAG=4 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --expand-portchannel SRV_LAG=Ethernet1/5,Ethernet1/6 --pretty
```

#### `--promote-bridgegroup IFACE=SPEC` — physical port → new bridge group (BVI)
Promote a plain physical interface into a **new** bridge group so its subnet can span several bridged ports. The IP and MTU move onto the BVI.
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --promote-bridgegroup lan1=2 --pretty
```

#### `--expand-bridgegroup SWITCH=SPEC` — grow a bridge group
Increase the member count of a bridge group built from a FortiGate virtual switch (`system_switch-interface`). `SWITCH` is the virtual-switch name.
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --expand-bridgegroup lan_switch=4 --pretty
```

#### `--network-module MODULE` — add expansion-module ports
Models with a network-module slot (3110/3120/3130/3140, 4215) can take an add-on card. Declaring it adds the module's ports (`Ethernet2/1..N`) to the pool so the mapping/promote/expand flags can target them.
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 \
    --network-module 8x10g --map-port wan2=Ethernet2/1 --pretty
```
Choices: `none` (default), `8x1g`, `8x10g`, `8x25g`, `4x40g`, `2x100g`.

### Step 3: Run the Conversion

```bash
# Basic conversion (default ftd-3120)
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml --pretty

# Specify target model (recommended)
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml --target-model ftd-3120 --pretty

# Custom output base name
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml -o prod_ftd --target-model ftd-3120 --pretty
```

**Command options:**

| Option            | Description                                                                                          | Default      |
|-------------------|------------------------------------------------------------------------------------------------------|--------------|
| `input_file`      | FortiGate YAML configuration file                                                                    | Required     |
| `-o, --output`    | Output base name for JSON files                                                                      | `ftd_config` |
| `-p, --pretty`    | Format JSON with indentation                                                                         | Off          |
| `-m, --target-model` | Target FTD firewall model                                                                         | `ftd-3120`   |
| `--list-models`   | Display supported models and exit                                                                    | -            |
| `--ha-port`       | Custom HA port(s) (`Ethernet1/X`, comma-separate for dual-HA) or `none` to disable                   | Model default |
| `--network-module`| Add an expansion module's ports: `none`, `8x1g`, `8x10g`, `8x25g`, `4x40g`, `2x100g` (slot models)   | `none`       |
| `--map-port`      | Pin a FortiGate interface to a specific FTD port: `IFACE=Ethernet1/X`. Repeatable                     | -            |
| `--promote-portchannel` | Promote a physical interface into a NEW EtherChannel: `IFACE=COUNT` or `IFACE=Ethernet1/X,...`  | -            |
| `--expand-portchannel`  | Add members to an existing EtherChannel: `PC=COUNT` or `PC=Ethernet1/X,...`                     | -            |
| `--promote-portchannel-vlan` | Put a promoted port-channel's IP on a subinterface `Port-channelN.TAG`: `IFACE=TAG`        | -            |
| `--promote-bridgegroup` | Promote a physical interface into a NEW bridge group (BVI): `IFACE=COUNT` or `IFACE=Ethernet1/X,...` | -      |
| `--expand-bridgegroup`  | Add members to a bridge group built from a virtual switch: `SWITCH=COUNT` or `SWITCH=Ethernet1/X,...` | -       |

### Step 4: Review Generated Files

The converter creates 13 JSON files:

| File                                | Purpose                    | API Method    |
|-------------------------------------|----------------------------|---------------|
| `{output}_physical_interfaces.json` | Physical interface configs | PUT (update)  |
| `{output}_etherchannels.json`       | Port-channel configs       | POST (create) |
| `{output}_bridge_groups.json`       | Bridge group configs       | POST (create) |
| `{output}_subinterfaces.json`       | VLAN subinterface configs  | POST (create) |
| `{output}_security_zones.json`      | Security zone configs      | POST (create) |
| `{output}_address_objects.json`     | Network objects            | POST (create) |
| `{output}_address_groups.json`      | Network object groups      | POST (create) |
| `{output}_service_objects.json`     | Port objects (incl. ICMP)  | POST (create) |
| `{output}_service_groups.json`      | Port object groups (incl. `PING`) | POST (create) |
| `{output}_static_routes.json`       | Static route entries       | POST (create) |
| `{output}_access_rules.json`        | Access control rules       | POST (create) |
| `{output}_summary.json`             | Conversion statistics      | N/A           |
| `{output}_metadata.json`            | Conversion settings        | N/A           |

**The metadata file** stores the conversion settings so the importer can auto-discover them:

```json
{
  "target_model": "ftd-3120",
  "output_basename": "ftd_config",
  "ha_port": "Ethernet1/2",
  "schema_version": 1
}
```

The importer automatically finds `{base}_metadata.json` when you use `--base`. No need to pass `--metadata-file` manually.

**Verify the summary:**
```bash
# Windows
type ftd_config_summary.json
# macOS / Linux
cat ftd_config_summary.json
```

### Automatic VLAN Conflict Resolution

FortiGate allows VLAN interfaces on different parents to share the same VLAN ID. FTD requires VLAN IDs to be **unique device-wide**, so duplicates would fail to import. The converter resolves conflicts automatically:

- **Priority parents keep their VLAN IDs** — subinterfaces on EtherChannels and virtual switches (bridge groups) keep their original numbers.
- **Physical-parent subinterfaces are remapped** — conflicting subinterfaces move to the nearest unused VLAN ID (e.g., `Ethernet1/3.100` → `Ethernet1/3.102`).
- **References stay intact** — logical names never change, so zones, routes, and policies are unaffected.
- **Fully visible** — every remap is printed, appended to the interface description (`[remapped from VLAN 100]`), and counted in the summary.

Review the printed remaps and update your switch trunk configs/documentation to match the new VLAN IDs.

---

## Phase 2: Import to FTD

### Object Dependency Order

FTD requires objects to be imported in a specific order because later objects reference earlier ones:

```
1. Physical Interfaces     ← Foundation (update existing)
2. EtherChannels           ← Requires physical interfaces as members
3. Subinterfaces           ← Requires parent interfaces
4. Bridge Groups           ← Requires interfaces
5. Security Zones          ← Requires interfaces
6. Address Objects         ← Standalone
7. Address Groups          ← References address objects
8. Service Objects         ← Standalone
9. Service Groups          ← References service objects
10. Static Routes          ← References interfaces, address objects
11. Access Rules           ← References everything above
```

### Step 1: Import Interfaces First

```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-physical-interfaces
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-etherchannels
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-subinterfaces
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-bridge-groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-security-zones
```

The importer prompts for the password if `-p` is omitted.

### Step 2: Import Objects and Rules

```bash
# Import everything else (skips already-imported interfaces)
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin
```

Or import selectively:

```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-objects
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-objects
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-routes
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-rules
```

### Step 3: Deploy

**Via script:**
```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --deploy
```

**Via FDM web interface:** Login → **Deploy** (top right) → review pending changes → **Deploy Now**.

### Importer Command Reference

| Option            | Description                                                  |
|-------------------|--------------------------------------------------------------|
| `--host`          | FTD management IP address or hostname (required)             |
| `-u, --username`  | FDM username (required)                                      |
| `-p, --password`  | FDM password (prompts if omitted)                            |
| `--base`          | Base name of JSON files (default: `ftd_config`)              |
| `--metadata-file` | Explicit path to metadata JSON (auto-discovered from `--base`) |
| `--deploy`        | Deploy changes after import                                  |
| `--skip-verify`   | Skip SSL certificate verification (default: true)            |
| `--debug`         | Show API request/response payloads                           |
| `--workers`       | Max concurrent threads for address/service imports (1-32, default: 6) |
| `--json-report`   | Write a run summary to a JSON file                           |
| `--validate-only` | Authenticate and probe endpoints without importing           |
| `--skip-existing` | Skip objects that already exist (default: update existing)   |
| `--max-attempts`  | Max retry attempts for transient API errors (default: 4)     |
| `--base-backoff`  | Initial retry backoff in seconds (default: 0.3)              |
| `--max-jitter`    | Max random jitter added to backoff, seconds (default: 0.25)  |
| `--delay`         | Delay between sequential API calls, seconds (default: 0.2)   |
| `--only-*`        | Import only a specific object type (see below)              |
| `--file`          | Import a specific JSON file (overrides `--base`/`--only`)    |
| `--type`          | Object type for `--file` (required with `--file`)           |

**Selective import flags:** `--only-physical-interfaces`, `--only-etherchannels`, `--only-subinterfaces`, `--only-bridge-groups`, `--only-security-zones`, `--only-address-objects`, `--only-address-groups`, `--only-service-objects`, `--only-service-groups`, `--only-routes`, `--only-rules`.

**`--type` choices (for `--file`):** `address-objects`, `address-groups`, `service-objects`, `service-groups`, `routes`, `rules`, `security-zones`, `physical-interfaces`, `etherchannels`, `bridge-groups`, `subinterfaces`.

---

## Phase 3: Cleanup / Rollback

The cleanup script removes imported objects for rollback or a fresh start. Objects are deleted in **reverse dependency order** automatically.

### Step 1: Preview (Dry Run)

Always preview first:
```bash
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --dry-run
```

### Step 2: Execute

```bash
# Delete everything
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all

# Delete everything without the confirmation prompt
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --yes

# Delete and deploy
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --deploy
```

### Selective Deletion

```bash
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-rules
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-routes
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-service-objects
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-service-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-security-zones
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-subinterfaces
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-etherchannels
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-bridge-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-snmp
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --reset-physical-interfaces

# Delete/reset ALL interface configs in one shot
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all-interfaces
```

### Cleanup Command Reference

| Flag | Description |
|------|-------------|
| `--delete-all` | Delete all custom objects (everything) |
| `--delete-all-interfaces` | Delete/reset all interface configs (subinterfaces, etherchannels, bridge groups, physical reset) |
| `--delete-address-objects` / `--delete-address-groups` | Delete network objects / groups |
| `--delete-service-objects` / `--delete-service-groups` | Delete port objects / groups |
| `--delete-security-zones` | Delete security zones |
| `--delete-routes` / `--delete-rules` | Delete static routes / access rules |
| `--delete-snmp` | Delete SNMP hosts and users |
| `--delete-subinterfaces` / `--delete-etherchannels` / `--delete-bridge-groups` | Delete those interface types |
| `--reset-physical-interfaces` | Reset physical interfaces to defaults (cannot delete) |
| `--dry-run` | Preview without deleting (always use first) |
| `--yes` | Skip the confirmation prompt (unattended runs) |
| `--deploy` | Deploy after deletion |
| `--appliance-model` | Target FTD model (auto-detected from metadata if omitted) |
| `--validate-only` | Authenticate and probe endpoints without deleting |
| `--json-report` | Write the cleanup summary to a JSON file |
| `--workers` | Concurrent threads for deletion (1-32, default: 6) |
| `--max-attempts` / `--base-backoff` / `--max-jitter` / `--delay` | Retry/backoff tuning (same defaults as the importer) |

---

## SNMPv3 Configuration (FDM-Managed FTD)

FDM does not expose SNMPv3 in its GUI — locally managed FTDs must be configured through the REST API. `ftd_snmp_config.py` does this end to end, meeting STIG requirements CASA-ND-001050 / CASA-ND-001070.

### What It Creates

1. An **SNMPv3 user** with the chosen auth and privacy algorithms (Auth/Priv security level).
2. A **network object** and **SNMP host** entry per manager IP, bound to the source interface. Object names are suffixed with the manager IP, so pushes are **additive** — each management tool can get its own SNMPv3 user without overwriting earlier configs.
3. Optionally, the device-global **SNMP location and contact** (sysLocation / sysContact).

Re-running with new values updates existing objects in place (idempotent).

### Basic Usage

```bash
# Single SNMP manager (passwords prompted if omitted)
python FortiGateToFTDTool/ftd_snmp_config.py --host 192.168.1.1 -u admin \
    --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside

# Multiple managers (comma-separated or repeated flag)
python FortiGateToFTDTool/ftd_snmp_config.py --host 192.168.1.1 -u admin \
    --nms-ip 10.0.0.50,10.1.0.50 --snmp-user FWADMIN --interface outside

# Full specification with location/contact and deploy
python FortiGateToFTDTool/ftd_snmp_config.py --host 192.168.1.1 -u admin \
    --nms-ip 10.0.0.50 --snmp-user FWADMIN \
    --auth-algorithm SHA256 --auth-password 'AuthPass123' \
    --priv-algorithm AES256 --priv-password 'PrivPass123' \
    --interface outside \
    --location "DC-East Rack 12" --contact "netops@example.com" \
    --deploy
```

### Command Reference

| Flag | Description |
|------|-------------|
| `--host` | FTD management IP (required) |
| `-u, --username` | FDM username (required) |
| `-p, --password` | FDM password (prompted if omitted) |
| `--nms-ip` | SNMP manager / NMS IP. Repeat the flag or comma-separate for multiple managers (required) |
| `--snmp-user` | SNMPv3 user name, e.g. `FWADMIN` (required) |
| `--interface` | Logical name of the source interface, e.g. `outside` — not `Ethernet1/1`. Physical, EtherChannel, and subinterfaces are supported (required) |
| `--auth-algorithm` | `SHA` or `SHA256` (default: `SHA`) |
| `--auth-password` | Authentication password, min 8 characters (prompted if omitted) |
| `--priv-algorithm` | `AES128`, `AES192`, or `AES256` (default: `AES256`; `AES128` is the STIG minimum) |
| `--priv-password` | Privacy/encryption password, min 8 characters (prompted if omitted) |
| `--location` | Device-global sysLocation. Max 233 chars, no semicolons. Omitted = unchanged |
| `--contact` | Device-global sysContact. Max 234 chars, no semicolons. Omitted = unchanged |
| `--trap-events` | Device-wide trap event types. Comma-separate or repeat; `none` disables all. Omitted = unchanged |
| `--nms-object-name` | Base name for the NMS network object(s) (default: `snmpHost`) |
| `--host-object-name` | Base name for the SNMP host object(s) (default: `snmpv3-host`) |
| `--no-poll` | Disable SNMP polling (UDP 161) |
| `--no-trap` | Disable SNMP traps (UDP 162) |
| `--deploy` | Deploy the staged changes after configuring |
| `--debug` | Enable debug output |

**Removal:** use `ftd_api_cleanup.py --delete-snmp` to remove SNMP hosts and users (also included in `--delete-all`).

---

## Performance and Concurrency

### What Is Multithreaded vs Sequential

| Operation | Execution | Notes |
|-----------|-----------|-------|
| Address objects | **Multithreaded** | Bounded thread pool via `--workers` |
| Service objects | **Multithreaded** | Bounded thread pool via `--workers` |
| Address/Service groups | Sequential | 0.2 s sleep between items |
| Interfaces, zones, routes, rules | Sequential | Order-dependent |

### The `--workers` Flag

| Setting | Value |
|---------|-------|
| Default | **6** |
| Minimum | 1 (enforced at runtime) |
| Maximum | 32 |

- **Start with the default (6).** Safe baseline for most appliances.
- **Lower to 2-3** if you see frequent 429 (Too Many Requests) or 503 responses.
- **Raise to 8-10** only if round-trip latency is high and the appliance is not rate-limiting. Above 10 is rarely beneficial — the FDM API serializes writes internally.

```bash
# Conservative (rate-limited environment)
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin --workers 2

# Aggressive (high-latency link, powerful appliance)
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin --workers 10
```

### Retry and Backoff

All multithreaded operations retry transient errors with exponential backoff and jitter.

| Parameter | Default | Flag |
|-----------|---------|------|
| Max attempts | 4 (1 initial + 3 retries) | `--max-attempts` |
| Base backoff | 0.3 s | `--base-backoff` |
| Max jitter | 0.25 s | `--max-jitter` |
| Backoff growth | 2× (0.3 → 0.6 → 1.2 s) | — |

Retryable errors are matched (case-insensitive) against: `429`, `too many`, `rate limit`, `timeout`, `temporarily`, `503`, `504`. Non-transient errors (e.g. 422 validation failures) fail immediately.

### JSON Report Output

Both the importer and cleanup support `--json-report <path>` for CI/CD or scripted workflows:
```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin --json-report import_results.json
python FortiGateToFTDTool/ftd_api_cleanup.py --host 10.0.0.1 -u admin --delete-all --json-report cleanup_results.json
```

---

## Troubleshooting

### Connection refused or timeout
```
Connection error: Unable to connect to 192.168.1.1
```
1. Verify the FTD management IP.
2. Ensure HTTPS (port 443) is reachable.
3. Confirm FDM is enabled (not FMC-managed).
4. Try from a browser: `https://192.168.1.1`.

### SSL certificate error
```
SSL: CERTIFICATE_VERIFY_FAILED
```
`--skip-verify` is enabled by default. If issues persist, ensure `urllib3` is installed.

### Invalid HA port
```
ERROR: Invalid HA port: 'Ethernet1/X'
```
The port exceeds the model's port count, or the format is wrong (use `Ethernet1/X`, case-sensitive). Run `--list-models` to confirm the port range.

### Authentication failed (401)
1. Verify username and password.
2. Check if the account is locked in FDM.
3. Try logging into the FDM web interface first.

### Object already exists
```
Object 'Server1' already exists, skipping...
```
Normal — the importer is idempotent. Use `--skip-existing` to skip instead of update.

### Referenced object not found
1. Import objects in the correct dependency order.
2. Check conversion warnings for unmatched objects.
3. Create the missing object manually in FDM.

### API Error 422 (Validation failed)
1. Enable `--debug` to see the payload.
2. Check the error message for the specific field.
3. Verify the JSON matches FTD API requirements.

### Frequent 429 / 503 / timeouts
1. Reduce worker count: `--workers 2` or `3`.
2. The tool retries automatically (up to 4 attempts), but sustained 429s mean you're exceeding appliance capacity.
3. For very large imports (500+ objects), import in batches with `--file`.
4. Check FDM **System → Task Status** for pending deployments or background load.

### Deployment fails or is stuck
1. Check FDM **System → Task Status** for details (invalid references, overlapping routes, conflicting rules).
2. Large deployments can take 10-15 minutes — wait before cancelling.

---

## Best Practices

### Before Migration
- **Test in a lab first** — run the full migration against an identical lab FTD.
- **Backup everything** — FortiGate YAML, FTD (FDM backup), and all generated JSON.
- **Plan a maintenance window** — 2-4 hours for medium configs, with a rollback plan.
- **Review the converted config** — check `ftd_config_summary.json` and conversion warnings.

### During Migration
- **Import in phases** — follow the dependency order strictly and verify each phase.
- **Monitor progress** — watch for errors and check FDM logs.
- **Use dry-run cleanup** before any rollback.

### After Migration
- **Test all critical traffic flows**, remote access, routing, and NAT.
- **Monitor performance** — CPU/memory, connection counts, logs.
- **Update documentation** — new object names, VLAN remaps, network diagrams.

---

## Appendix: File Formats & Complete Command Reference

### A. File Formats (FTD JSON)

**Address Object:**
```json
{
  "name": "Server1",
  "description": "Web Server",
  "type": "networkobject",
  "subType": "HOST",
  "value": "10.0.0.10"
}
```

**Address Group:**
```json
{
  "name": "Web_Servers",
  "isSystemDefined": false,
  "objects": [
    {"name": "Server1", "type": "networkobject"},
    {"name": "Server2", "type": "networkobject"}
  ],
  "type": "networkobjectgroup"
}
```

**Port Object (TCP):**
```json
{
  "name": "HTTP_TCP",
  "isSystemDefined": false,
  "port": "80",
  "type": "tcpportobject"
}
```

**ICMP Port Object + PING group (ping migration):**
```json
{
  "name": "ICMP_Echo_Request",
  "isSystemDefined": false,
  "icmpv4Type": "ECHO_REQUEST",
  "type": "icmpv4portobject"
}
```
```json
{
  "name": "PING",
  "isSystemDefined": false,
  "objects": [
    {"name": "ICMP_Echo_Request", "type": "icmpv4portobject"},
    {"name": "ICMP_Echo_Reply", "type": "icmpv4portobject"}
  ],
  "type": "portobjectgroup"
}
```

**Static Route:**
```json
{
  "name": "Default_Route",
  "iface": {"name": "outside", "type": "physicalinterface"},
  "networks": [{"name": "any-ipv4", "type": "networkobject"}],
  "gateway": {"name": "Gateway_192_168_1_1", "type": "networkobject"},
  "metricValue": 1,
  "ipType": "IPv4",
  "type": "staticrouteentry"
}
```

**Metadata:**
```json
{
  "target_model": "ftd-3120",
  "output_basename": "ftd_config",
  "ha_port": "Ethernet1/2",
  "schema_version": 1
}
```

### B. Complete Command Reference

All commands assume the **repository root** as the working directory.

**Conversion:**
```bash
# Basic / model-specific / custom output
python FortiGateToFTDTool/fortigate_converter.py config.yaml --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml -o prod_ftd --target-model ftd-3120 --pretty

# List models
python FortiGateToFTDTool/fortigate_converter.py --list-models

# Custom / dual HA ports
python FortiGateToFTDTool/fortigate_converter.py config.yaml --ha-port Ethernet1/2,Ethernet1/3 --pretty

# Advanced interface mapping
python FortiGateToFTDTool/fortigate_converter.py config.yaml --map-port wan1=Ethernet1/9 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --promote-portchannel wan1=2 --promote-portchannel-vlan wan1=100 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --expand-portchannel WAN_LAG=4 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --promote-bridgegroup lan1=2 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --expand-bridgegroup lan_switch=4 --pretty
python FortiGateToFTDTool/fortigate_converter.py config.yaml --network-module 8x10g --map-port wan2=Ethernet2/1 --pretty

# Help
python FortiGateToFTDTool/fortigate_converter.py --help
```

**Import:**
```bash
# Full import (auto-discovers metadata)
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin

# Explicit metadata file
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --metadata-file ftd_config_metadata.json

# Interface imports (in order)
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-physical-interfaces
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-etherchannels
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-subinterfaces
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-bridge-groups
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-security-zones

# Object imports
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-address-objects
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-address-groups
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-service-objects
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-service-groups
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-routes
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-rules

# Specific file / deploy / workers / report / validate / skip-existing / debug
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --file custom.json --type address-objects
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --deploy
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --workers 3
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --json-report import_results.json
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --validate-only
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --skip-existing
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --debug

# Help
python FortiGateToFTDTool/ftd_api_importer.py --help
```

**Cleanup:**
```bash
# Dry run (preview)
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run

# Delete everything / without confirmation / and deploy
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --yes
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --deploy

# Selective
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-rules
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all-interfaces

# Report / workers
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --json-report cleanup_results.json
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --workers 3

# Help
python FortiGateToFTDTool/ftd_api_cleanup.py --help
```

**SNMPv3:**
```bash
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50,10.1.0.50 --snmp-user FWADMIN --interface outside
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside --deploy
python FortiGateToFTDTool/ftd_snmp_config.py --help
```

### C. Support and Resources

- **Cisco FDM API:** API Explorer at `https://YOUR_FTD_IP/apiexplorer/`
- **PyYAML:** https://pyyaml.org/
- **Requests:** https://docs.python-requests.org/
- **FDM logs/tasks:** System → Troubleshooting → Diagnostics; System → Task Status

---

**Compatible With:** FTD 7.4.x with FDM, Python 3.9+
