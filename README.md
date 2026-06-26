# FortiGate Firewall Migration Tool - Complete User Guide

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Quick Start Checklist](#quick-start-checklist)
5. [Phase 1: Converting FortiGate Configuration](#phase-1-converting-fortigate-configuration)
6. [Phase 2: Importing to Target Platform](#phase-2-importing-to-target-platform)
   - [Importing to Cisco FTD](#phase-2a-importing-to-ftd)
   - [Importing to Palo Alto PAN-OS](#phase-2b-importing-to-palo-alto-pan-os)
7. [Phase 3: Cleanup (Optional)](#phase-3-cleanup-optional)
   - [Cleanup Password Protection](#cleanup-password-protection)
   - [Changing the Built-in Default Password](#changing-the-built-in-default-password)
8. [SNMPv3 Configuration (FDM-Managed FTD)](#snmpv3-configuration-fdm-managed-ftd)
9. [Performance and Concurrency](#performance-and-concurrency)
10. [Troubleshooting](#troubleshooting)
11. [Best Practices](#best-practices)
12. [GUI How-To Guide](#gui-how-to-guide)
13. [Appendix](#appendix)

---

## Overview

This toolset converts FortiGate firewall configurations to **Cisco FTD** (Firepower Threat Defense) or **Palo Alto PAN-OS** format and imports them via the target platform's API.

### Supported Target Platforms

| Platform | API | Status |
|----------|-----|--------|
| Cisco FTD | FDM REST API | Production-ready |
| Palo Alto PAN-OS | XML API | Beta (testing in progress) |

### What Gets Converted

| Object Type          | Status | Notes                                                 |
|----------------------|--------|-------------------------------------------------------|
| Address Objects      |        | Hosts, subnets, ranges, FQDNs                         |
| Address Groups       |        | Network object groups                                 |
| Service Port Objects |        | TCP/UDP ports (auto-splits combined)                  |
| Service Port Groups  |        | Port object groups                                    |
| Interfaces           |        | Physical, subinterfaces, etherchannels, bridge groups |
| Security Zones       |        | Auto-created from interface aliases                   |
| Static Routes        |        | IPv4 routes with gateway references                   |
| Firewall Policies    |        | Access control rules                                  |

### Additional Features

- Automatic name sanitization (spaces → underscores)
- **Multi-platform support** - Convert to Cisco FTD or Palo Alto PAN-OS from the same FortiGate source
- Model-aware interface port mapping with customizable HA port assignment (FTD)
- Flexible HA port configuration (override model defaults)
- Automatic VLAN ID conflict resolution (FTD requires device-wide unique VLAN IDs; conflicting subinterfaces are remapped automatically)
- Metadata file for seamless import workflow
- Bulk cleanup/delete script for rollback
- Idempotent imports (existing objects are updated in place; re-runs are safe)
- **SNMPv3 configuration push** for FDM-managed FTD (STIG-compliant; FDM's GUI does not expose SNMPv3)
- Unified GUI with platform selector for Convert, Import, Cleanup, and SNMP workflows

---

## Prerequisites

### System Requirements

| Requirement | Minimum                           | Recommended   |
|-------------|-----------------------------------|---------------|
| Python      | 3.9                               | 3.9 or higher |
| OS          | Windows, macOS, Linux             | Any           |
| Network     | Connectivity to FTD management IP | HTTPS (443)   |

### Python Libraries

```bash
pip install -r requirements.txt
```

### FTD Requirements

| Requirement      | Details                                                                          |
|------------------|----------------------------------------------------------------------------------|
| Management Mode  | Local FDM (Firewall Device Manager)                                              |
| Firmware         | 7.4.x (tested on 7.4.2.4-9)                                                      |
| Credentials      | Admin username and password                                                      |
| Supported Models | FTD-1010, 1120, 1140, 2110, 2120, 2130, 2140, 3105, 3110, 3120, 3130, 3140, 4215 |

### Palo Alto PAN-OS Requirements

| Requirement      | Details                                                   |
|------------------|-----------------------------------------------------------|
| Management Mode  | Direct PAN-OS management (XML API access)                 |
| Firmware         | PAN-OS 10.1+                                              |
| Credentials      | Admin username and password (API key generated at runtime) |
| Supported Models | PA-440, PA-450, PA-460, PA-3220, PA-3250, PA-5220         |

---

## Installation

### Step 1: Get the Project

Clone or download the full repository. The tools live in subdirectories and import each other as packages, so copy the entire project - not individual script files.

```bash
git clone https://github.com/RickeyNet/FirewallMigrationTool.git
cd FirewallMigrationTool
```

Your working directory should look like this:

```
FirewallMigrationTool/
├── gui_app.py                          # Unified GUI (recommended entry point)
├── cleanup_auth.py                     # Cleanup password authentication module
├── set_cleanup_password.py             # Utility to change built-in default password
├── requirements.txt                    # Python dependencies
├── build.bat                           # Windows .exe build script (optional)
├── FortiGateToFTDTool/                 # FortiGate → Cisco FTD
│   ├── fortigate_converter.py          # Convert FortiGate YAML → FTD JSON
│   ├── ftd_api_importer.py             # Import FTD JSON via FDM REST API
│   ├── ftd_api_cleanup.py              # FTD bulk delete/cleanup utility
│   └── ...                             # Converter modules (address, policy, route, etc.)
├── FortiGateToPaloAltoTool/            # FortiGate → Palo Alto PAN-OS
│   ├── pa_converter.py                 # Convert FortiGate YAML → PA JSON
│   ├── panos_api_importer.py           # Import PA JSON via XML API
│   ├── panos_api_cleanup.py            # PAN-OS bulk delete/cleanup utility
│   └── ...                             # Converter modules
├── PaloAltoToFortiGateTool/            # Palo Alto PAN-OS → FortiGate CLI
│   └── fg_converter.py                 # Convert PAN-OS XML → FortiGate .conf
├── CiscoASAToPaloAltoTool/             # Cisco ASA → Palo Alto PAN-OS
│   └── asa_converter.py                # Convert ASA config → PA JSON
├── CiscoFTDToFortiGateTool/            # Cisco FTD → FortiGate CLI
│   └── fg_ftd_converter.py           # Convert FTD export → FortiGate .conf
├── fortigate_config.yaml               # Your FortiGate YAML (input)
├── ftd_config_*.json                   # Generated FTD JSON files (output)
└── pa_config_*.json                    # Generated PA JSON files (output)
```

For CLI use, run scripts from the repo root with the package path (for example, `python FortiGateToFTDTool/fortigate_converter.py`) or change into the relevant tool directory first.

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Verify Installation

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

---

========================================================================================================================================================================

## For Airgapped Networks

### Download required libraries from internet connected device:

```bash For Windows PowerShell
pip install -r requirements.txt
py -3.9 -m pip install -r requirements.txt

```

### Test that Python can find the libraries:

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

### Create a directory for the packages and download them:

```bash
# Create a directory for the packages (from the repo root)
mkdir ftd_migration_packages

# Download packages and their dependencies
pip download -r requirements.txt -d ftd_migration_packages
py -3.9 -m pip download -r requirements.txt -d ftd_migration_packages
```

This will download files like:
- PyYAML-6.0.1-cp39-cp39-win_amd64.whl
- requests-2.31.0-py3-none-any.whl
- urllib3-2.0.7-py3-none-any.whl
- certifi-2023.7.22-py3-none-any.whl (dependency)
- charset-normalizer-3.3.2-cp39-cp39-win_amd64.whl (dependency)
- idna-3.4-py3-none-any.whl (dependency)

### Airgapped Side Installation:

1. Move package folder, `requirements.txt`, and all scripts to airgapped machine (including Python 3.x installer if not already installed)

2. Install Python and select "Add to PATH" on installer

3. Check if Python paths are added:
```bash
-CMD Prompt
echo %path%

-PowerShell
$Env:Path -split ";"


```

4. Or manually add to PATH via Environment Variables:
   - `C:\Users\<name>\AppData\Local\Programs\Python\Python39\`
   - `C:\Users\<name>\AppData\Local\Programs\Python\Python39\Scripts`
   - (May require logout/login or reboot)

5. Test Python installation:
```bash
python
# Should display: Python 3.x.x
# Type exit() to exit
```

6. From the tool directory (where `requirements.txt` lives), install from the local package folder:
```bash
python -m pip install --no-index --find-links=ftd_migration_packages -r requirements.txt
```

7. Test that libraries are installed:
```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

===========================================================================================================================================================================

## Quick Start Checklist

### Before You Begin

```
□ Install Python 3.9+
□ Install libraries: pip install -r requirements.txt
□ Clone or download the full project (all tool directories)
□ Export FortiGate config as YAML
□ Backup FTD configuration in FDM
□ Identify your target FTD model (e.g., ftd-3120)
```

### Conversion Phase

```
□ Run: python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --pretty
□ (Optional) Specify custom HA port: --ha-port Ethernet1/5 (or --ha-port none to disable)
□ Review generated JSON files (13 files total including metadata)
□ Check ftd_config_summary.json for conversion statistics
□ Review any warnings in console output
□ Verify HA port assignment matches your design
```

### Import Phase

```
□ Import interfaces first (creates foundation):
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-physical-interfaces
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-etherchannels
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-subinterfaces
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-bridge-groups
    python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --only-security-zones

□ Import objects and rules:
  # Use --workers to control concurrent address/service object creation (default 6)
  python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --workers 6

□ Deploy configuration in FDM
□ Verify objects in FDM web interface
□ Test traffic flows
```

**Multithreaded imports:**
- Applies to address objects and service objects in both full import mode and selective/single-file runs.
- Flag: `--workers N` (default 6). Tune down if the FTD API rate-limits or up modestly if latency is high.
- Behavior: bounded ThreadPool with jittered backoff on 429/5xx/timeouts; still idempotent (skips existing).

### If Something Goes Wrong

```
□ Run cleanup: python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run
□ Review what will be deleted
□ Execute: python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --deploy
□ Start over with corrected configuration
```

---

## Phase 1: Converting FortiGate Configuration

All CLI examples below assume you run commands from the **repository root**. Use the `FortiGateToFTDTool/` path shown, or `cd FortiGateToFTDTool` and drop the prefix.

### Step 1: Export FortiGate Configuration

1. Login to FortiGate web interface
2. Click username in top right corner
3. Go to **Configuration → Backup**
4. Select **YAML format**
5. Click **OK** to download
6. Save as `fortigate_config.yaml` in your working directory

### Step 2: Identify Your Target FTD Model

Before converting, determine which FTD model you're migrating to. This affects interface port mapping.

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

**Note:** Default HA ports can be overridden using the `--ha-port` option. See [Customizing HA Port Configuration](#customizing-ha-port-configuration) for details.


### Step 2a: Customizing HA Port Configuration

By default, **Secure Firewall models (ftd-3105 and newer)** reserve **Ethernet1/2** for High Availability (HA) connections. Older models (ftd-1010 through ftd-2140) do not reserve an HA port unless you set one with `--ha-port`. Use `--ha-port none` on HA-capable models to disable the default reservation.

#### When to Use a Custom HA Port

- **Port conflicts**: Your network design requires Ethernet1/2 for data traffic
- **Cable management**: Physical rack layout requires a different HA port location
- **Multi-chassis setup**: HA links use specific ports for cross-chassis connections
- **Compliance requirements**: Security policy mandates specific HA port placement

#### How HA Port Assignment Works

1. **Default behavior**: ftd-3105 and newer reserve Ethernet1/2; other models reserve no HA port unless `--ha-port` is set
2. **Port reservation**: The HA port is automatically skipped during interface conversion
3. **Port validation**: Custom HA ports must be within the model's port range (1 to total_ports)
4. **Data port assignment**: All FortiGate interfaces are mapped to available FTD ports, excluding the HA port
5. **Disable HA reservation**: Pass `--ha-port none` to use all data ports on HA-capable models

#### Custom HA Port Syntax
```bash
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model MODEL --ha-port EthernetX/Y
```

**Format Requirements:**
- Must be exactly `Ethernet1/X` where X is a port number
- Port number must be between 1 and the model's maximum port count
- Cannot use Management ports for HA
- Case-sensitive: use `Ethernet1/5` not `ethernet1/5`

#### Examples

**Example 1: Use Ethernet1/5 for HA on FTD-3120 (16-port model)**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port Ethernet1/5 --pretty
```
**Result:**
- HA configured on: Ethernet1/5
- Available data ports: Ethernet1/1, 1/3, 1/4, 1/6-16 (Ethernet1/2 becomes available, 1/5 reserved)

---

**Example 2: Use Ethernet1/10 for HA on FTD-3140 (24-port model)**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3140 --ha-port Ethernet1/10 --pretty
```
**Result:**
- HA configured on: Ethernet1/10
- Available data ports: Ethernet1/1-9, 1/11-24 (Ethernet1/2 becomes available, 1/10 reserved)

---

**Example 3: Keep default HA port (Ethernet1/2)**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3120 --pretty
```
**Result:**
- HA configured on: Ethernet1/2 (default)
- Available data ports: Ethernet1/1, 1/3-16

---

**Example 4: Try invalid port number (will error)**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port Ethernet1/99
```
**Result:**
```
ERROR: Invalid HA port: 'Ethernet1/99'. Model 'ftd-3120' only has ports 1-16.
Specify a port between Ethernet1/1 and Ethernet1/16.
```

---

**Example 5: Try invalid format (will error)**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port eth1/5
```
**Result:**
```
ERROR: Invalid HA port format: 'eth1/5'.
Must be 'Ethernet1/X' where X is a port number (e.g., 'Ethernet1/5')
```

#### Port Availability After HA Assignment

The conversion script automatically adjusts port availability based on your HA port choice:

| HA Port Setting       | Ports Reserved        | Ports Available for Data Traffic          |
|-----------------------|-----------------------|-------------------------------------------|
| Default on 3105+ (Ethernet1/2) | Ethernet1/2 | Ethernet1/1, 1/3-16 on 16-port models (15 ports) |
| Custom (Ethernet1/5)  | Ethernet1/5           | Ethernet1/1-4, 1/6-16 (15 ports on ftd-3120) |
| Custom (Ethernet1/10) | Ethernet1/10          | Ethernet1/1-9, 1/11-24 (23 ports on ftd-3140) |
| No HA port (default on 1010-2140, or `--ha-port none`) | None | All model data ports available |

#### Verification

After conversion with custom HA port, verify the setting:

1. **Check the generated JSON files:**
```bash
# Look for interface assignments in ftd_config_physical_interfaces.json
grep -A 5 "hardwareName" ftd_config_physical_interfaces.json
```

2. **Review conversion summary:**
```bash
cat ftd_config_summary.json
```
Look for the `target_model` and note which ports were assigned.

3. **Check metadata file:**
```bash
cat ftd_config_metadata.json
```
The metadata file stores your model selection for the import process.

#### Important Notes

⚠️ **Warning**: Changing the HA port after initial deployment requires manual FTD configuration changes. Always configure the correct HA port during initial conversion.

✅ **Recommendation**: Document your HA port choice in your network diagrams and change management records.

💡 **Tip**: If you're migrating multiple FTD devices in an HA pair, use the same custom HA port on both devices for consistency.

### Step 3: Run the Conversion

**Basic conversion (uses default ftd-3120):**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml --pretty
```

**Specify target model (recommended):**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml --target-model ftd-3120 --pretty
```

**Custom output name:**
```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml -o prod_ftd --target-model ftd-3120 --pretty
```

**Command options:**

| Option           | Description                       | Default      |
|------------------|-----------------------------------|--------------|
| `input_file`     | FortiGate YAML configuration file | Required     |
| `-o, --output`   | Output base name for JSON files   | `ftd_config` |
| `--pretty`       | Format JSON with indentation      | Off          |
| `--target-model` | Target FTD firewall model         | `ftd-3120`   |
| `--list-models`  | Display supported models and exit | -            |
| `--ha-port`      | Custom HA port (`Ethernet1/X`) or `none` to disable | Model default (see table above) |
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
| `{output}_service_objects.json`     | Port objects               | POST (create) |
| `{output}_service_groups.json`      | Port object groups         | POST (create) |
| `{output}_static_routes.json`       | Static route entries       | POST (create) |
| `{output}_access_rules.json`        | Access control rules       | POST (create) |
| `{output}_summary.json`             | Conversion statistics      | N/A           |
| `{output}_metadata.json`            | Conversion settings        | N/A           |

### Step 5: Understand the Metadata File

The `{output}_metadata.json` file stores conversion settings:

```json
{
  "target_model": "ftd-3120",
  "output_basename": "ftd_config",
  "ha_port": "Ethernet1/2",
  "schema_version": 1
}
```

**Why this matters:**

| Field             | Purpose                                                              |
|-------------------|----------------------------------------------------------------------|
| `target_model`    | Tells importer which FTD model was targeted for correct port mapping |
| `output_basename` | Helps importer auto-discover related JSON files                      |
| `ha_port`         | Records the HA port reserved during conversion (`null` if none)     |
| `schema_version`  | Future-proofing for format changes                                   |

**Auto-discovery:** The importer automatically finds `{base}_metadata.json` when you use `--base`. No need to specify `--metadata-file` manually.

### Step 6: Verify Conversion Output

**Check the summary file:**
```bash
# Windows
type ftd_config_summary.json

# Mac/Linux
cat ftd_config_summary.json
```

**Example summary:**
```json
{
  "conversion_summary": {
    "interfaces": {
      "physical_updated": 8,
      "subinterfaces_created": 12,
      "etherchannels_created": 2,
      "bridge_groups_created": 1,
      "security_zones_created": 10,
      "skipped": 3
    },
    "address_objects": 48,
    "address_groups": 12,
    "service_objects": {
      "total": 75,
      "tcp": 45,
      "udp": 30,
      "split": 15
    },
    "service_groups": 8,
    "access_rules": {
      "total": 125,
      "permit": 100,
      "deny": 25
    },
    "static_routes": {
      "total": 10,
      "converted": 8,
      "blackhole_skipped": 2
    }
  }
}
```

### Automatic VLAN Conflict Resolution (FTD targets)

FortiGate allows VLAN interfaces on different parents (physical ports, port channels, virtual switches) to share the same VLAN ID. FTD requires VLAN IDs to be **unique device-wide**, so duplicates would fail to import. The converter resolves these conflicts automatically:

- **Priority parents keep their VLAN IDs** - subinterfaces on EtherChannels (port channels) and virtual switches (FTD bridge groups) always keep their original VLAN numbers.
- **Physical-parent subinterfaces are remapped** - conflicting subinterfaces on physical interfaces move to the nearest unused VLAN ID (e.g., `Ethernet1/3.100` → `Ethernet1/3.102`).
- **References stay intact** - logical names never change, so security zones, routes, and policies are unaffected.
- **Fully visible** - every remap is printed during conversion, appended to the interface description (`[remapped from VLAN 100]`), and counted in the conversion summary (`Duplicate VLAN IDs remapped: N`).

No action is required - this happens automatically during conversion. Review the printed remaps and update your documentation/switch trunk configs to match the new VLAN IDs.

---

### Palo Alto PAN-OS Conversion

Run from the **repository root**. To convert for Palo Alto instead of Cisco FTD, use `pa_converter.py` in the `FortiGateToPaloAltoTool/` directory:

**Basic conversion (uses default PA-440):**
```bash
python FortiGateToPaloAltoTool/pa_converter.py fortigate_config.yaml --pretty
```

**Specify target model:**
```bash
python FortiGateToPaloAltoTool/pa_converter.py fortigate_config.yaml --target-model pa-3220 --pretty
```

**List supported Palo Alto models:**
```bash
python FortiGateToPaloAltoTool/pa_converter.py --list-models
```

**Supported Palo Alto models:**

| Model   | Description        |
|---------|--------------------|
| pa-440  | Entry-level        |
| pa-450  | Entry-level        |
| pa-460  | Entry-level        |
| pa-3220 | Mid-range          |
| pa-3250 | Mid-range          |
| pa-5220 | Enterprise         |

The PA converter generates 10 JSON files (addresses, address groups, services, service groups, security rules, static routes, zones, interfaces, metadata, and summary).

**Key differences from FTD conversion:**
- Services with both TCP and UDP are automatically split into two separate objects (PAN-OS requires one protocol per service)
- Routes use CIDR notation directly instead of separate gateway network objects
- Zones are auto-generated from interface assignments
- No HA port configuration (managed externally on PAN-OS)

---

## Phase 2a: Importing to FTD

Run these commands from the **repository root** using the `FortiGateToFTDTool/` paths below (or `cd FortiGateToFTDTool` and drop the prefix).

### Important: Object Dependency Order

FTD requires objects to be imported in a specific order because later objects reference earlier ones.

**Required Import Order:**

```
1. Physical Interfaces     ← Foundation (update existing)
2. EtherChannels           ← Requires physical interfaces as members
3. Subinterfaces           ← Requires parent interfaces (physical or etherchannel)
4. Bridge Groups           ← Requires interfaces
5. Security Zones          ← Requires interfaces
6. Address Objects         ← Standalone
7. Address Groups          ← References address objects
8. Service Objects         ← Standalone
9. Service Groups          ← References service objects
10. Static Routes          ← References interfaces, address objects
11. Access Rules           ← References everything above
```

### Step 1: Connect and Authenticate

The importer prompts for password if not provided:

```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin
```

### Step 2: Import Interfaces First

Interfaces form the foundation. Import them in this specific order:

```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-physical-interfaces # Update physical interfaces
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-etherchannels # Create EtherChannels (port-channels)
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-subinterfaces # Create subinterfaces (VLANs)
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-bridge-groups # Create bridge groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-security-zones # Create security zones
```

### Step 3: Import Objects and Rules

After interfaces are configured, import remaining objects:

```bash
# Import everything else (skips already-imported interfaces)
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin
```

Or import selectively:

```bash
# Address objects and groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-objects
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-objects
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-groups
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-routes
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --only-rules
```

### Step 4: Deploy Configuration

**Option A: Deploy via script**
```bash
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin --deploy
```

**Option B: Deploy via FDM web interface**
1. Login to FDM
2. Click **Deploy** button (top right)
3. Review pending changes
4. Click **Deploy Now**
5. Wait for deployment to complete

### Importer Command Reference

| Option            | Description                                                  |
|-------------------|--------------------------------------------------------------|
| `--host`          | FTD management IP address (required)                         |
| `-u, --username`  | FDM username (required)                                      |
| `-p, --password`  | FDM password (prompts if omitted)                            |
| `--base`          | Base name of JSON files (default: `ftd_config`)              |
| `--metadata-file` | Explicit path to metadata JSON (auto-discovered from --base) |
| `--deploy`        | Deploy changes after import                                  |
| `--skip-verify`   | Skip SSL certificate verification (default: true)            |
| `--debug`         | Enable debug output showing API payloads                     |
| `--workers`       | Max concurrent threads for address/service imports (default: 6) |
| `--json-report`   | Write run summary to a JSON file                             |
| `--validate-only` | Authenticate and probe endpoints without importing           |
| `--skip-existing` | Skip objects that already exist (default: update existing)   |
| `--only-*`        | Import only specific object types                            |
| `--file`          | Import specific JSON file                                    |
| `--type`          | Object type for `--file`                                     |

### Selective Import Options

| Option                       | Object Type                        |
|------------------------------|------------------------------------|
| `--only-physical-interfaces` | Physical interface updates         |
| `--only-etherchannels`       | EtherChannel/port-channel creation |
| `--only-subinterfaces`       | VLAN subinterface creation         |
| `--only-bridge-groups`       | Bridge group creation              |
| `--only-security-zones`      | Security zone creation             |
| `--only-address-objects`     | Network objects                    |
| `--only-address-groups`      | Network object groups              |
| `--only-service-objects`     | Port objects                       |
| `--only-service-groups`      | Port object groups                 |
| `--only-routes`              | Static routes                      |
| `--only-rules`               | Access control rules               |

---

## Phase 2b: Importing to Palo Alto PAN-OS

Run from the **repository root** using the `FortiGateToPaloAltoTool/` paths below.

### Step 1: Import Configuration

The PAN-OS importer pushes converted JSON to your Palo Alto firewall via the XML API. It imports objects in dependency order automatically.

```bash
# Basic import (prompts for password)
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin

# Import with auto-commit
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin --password pass --commit

# Dry run (preview without changes)
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin --dry-run

# Debug mode (show API payloads)
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin --debug

# Specify custom input base name
python FortiGateToPaloAltoTool/panos_api_importer.py --host 10.0.0.1 --username admin --input my_pa_config
```

**Import order (handled automatically):**
```
1. Interfaces           ← Foundation (physical, aggregate, VLAN)
2. Zones                ← Requires interfaces
3. Address Objects      ← Standalone
4. Address Groups       ← References address objects
5. Service Objects      ← Standalone
6. Service Groups       ← References service objects
7. Static Routes        ← References interfaces
8. Security Rules       ← References everything above
9. Commit (optional)    ← Activates configuration
```

### Step 2: Commit Configuration

If you did not use `--commit`, commit manually via the PAN-OS web UI or CLI:

```
# PAN-OS CLI
commit
```

### PAN-OS Cleanup

To remove imported objects from PAN-OS:

```bash
# Preview deletion (dry run)
python FortiGateToPaloAltoTool/panos_api_cleanup.py --host 10.0.0.1 --username admin --delete-all --dry-run

# Delete all custom objects
python FortiGateToPaloAltoTool/panos_api_cleanup.py --host 10.0.0.1 --username admin --delete-all

# Delete and commit
python FortiGateToPaloAltoTool/panos_api_cleanup.py --host 10.0.0.1 --username admin --delete-all --commit

# Delete specific types
python FortiGateToPaloAltoTool/panos_api_cleanup.py --host 10.0.0.1 --username admin --delete-security-rules
```

---

## Phase 3: Cleanup (Optional)

Run these commands from the **repository root** using the `FortiGateToFTDTool/` paths below (or `cd FortiGateToFTDTool` and drop the prefix).

The FTD cleanup script removes imported objects for rollback or fresh start.

### Important: Deletion Order

Objects must be deleted in reverse dependency order:

```
1. Access Rules           ← Remove policies first
2. Static Routes          ← Remove routing
3. Security Zones         ← Remove zones (they reference interfaces)
4. SNMP Hosts & Users     ← Remove SNMP config (hosts reference interfaces and network objects)
5. Subinterfaces          ← Remove VLAN interfaces
6. EtherChannels          ← Remove port-channels
7. Bridge Groups          ← Remove bridge groups
8. Physical Interfaces    ← Reset only (cannot delete)
9. Service Groups         ← Remove port groups
10. Service Objects       ← Remove port objects
11. Address Groups        ← Remove network groups
12. Address Objects       ← Remove network objects
```

### Step 1: Preview Deletion (Dry Run)

Always preview before deleting:

```bash
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --dry-run
```

### Step 2: Execute Deletion

```bash
# Delete everything
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all

# Delete and deploy
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --deploy
```

### Selective Deletion

```bash
# Delete specific object types
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-rules
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-routes
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-service-objects
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-service-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-security-zones
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-bridge-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-subinterfaces
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-etherchannels
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-snmp
python FortiGateToFTDTool/ftd_api_cleanup.py --host 192.168.1.1 -u admin --reset-physical-interfaces
```

### Cleanup Password Protection

The cleanup feature is password-protected to prevent accidental deletion of firewall objects. A password prompt appears every time a user clicks **Start Cleanup** in the GUI.

**How it works:**

1. A **built-in default password** is baked into the application at build time (stored as a PBKDF2-HMAC-SHA256 hash - not plaintext).
2. If a user clicks **Change Cleanup Password** in the GUI, a `cleanup_auth.json` file is created next to the application. This override takes priority over the built-in default.
3. If `cleanup_auth.json` is deleted, the application automatically falls back to the built-in default password - users are never locked out.

**GUI buttons:**

| Button | Action |
|--------|--------|
| **Change Cleanup Password** | Change the active password (requires entering the current password first). Creates a `cleanup_auth.json` override file. |
| **Reset to Default Password** | Remove the `cleanup_auth.json` override and revert to the built-in default password (requires current password). |

### Changing the Built-in Default Password

To change the default password that is baked into the application before building:

```bash
python set_cleanup_password.py <new-password>
```

This updates the hash constants in `cleanup_auth.py`. You must **rebuild the exe** afterward for the change to take effect:

```bash
# Step 1: Set the new default password
python set_cleanup_password.py MyNewPassword

# Step 2: Rebuild the exe
build.bat
```

The script only modifies the hash - the plaintext password is never stored in the source code.

---

## SNMPv3 Configuration (FDM-Managed FTD)

FDM does not expose SNMPv3 in its GUI - locally managed FTDs must be configured through the REST API. The `ftd_snmp_config.py` script (and the **SNMP (FTD)** GUI tab) does this end to end, meeting STIG requirements CASA-ND-001050 / CASA-ND-001070.

### What It Creates

1. An **SNMPv3 user** with the chosen auth and privacy algorithms (Auth/Priv security level).
2. A **network object** and **SNMP host** entry per manager IP, bound to the source interface. Object names are suffixed with the manager IP, so pushes are **additive** - each management tool can get its own SNMPv3 user by running the push once per tool without overwriting earlier configs.
3. Optionally, the device-global **SNMP location and contact** (sysLocation / sysContact) via `--location` / `--contact`.

Re-running with new values updates the existing objects in place (idempotent).

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
| `-u`, `--username` | FDM username (required) |
| `-p`, `--password` | FDM password (prompted if omitted) |
| `--nms-ip` | SNMP manager / NMS IP. Repeat the flag or comma-separate for multiple managers (required) |
| `--snmp-user` | SNMPv3 user name, e.g. `FWADMIN` (required) |
| `--interface` | Logical name of the interface that sources SNMP traffic, e.g. `outside` - not `Ethernet1/1`. Physical interfaces, EtherChannels, and subinterfaces are supported (required) |
| `--auth-algorithm` | `SHA` or `SHA256` (default: `SHA`) |
| `--auth-password` | Authentication password, min 8 characters (prompted if omitted) |
| `--priv-algorithm` | `AES128`, `AES192`, or `AES256` (default: `AES256`; `AES128` is the STIG minimum) |
| `--priv-password` | Privacy/encryption password, min 8 characters (prompted if omitted) |
| `--location` | Device-global SNMP system location (sysLocation). Max 233 characters, no semicolons. Omitted = unchanged |
| `--contact` | Device-global SNMP system contact (sysContact). Max 234 characters, no semicolons. Omitted = unchanged |
| `--trap-events` | Device-global trap event types to enable. Comma-separate or repeat the flag; `none` disables all. Omitted = unchanged. Choices: `SNMP_AUTHENTICATION`, `SNMP_LINKUP`, `SNMP_LINKDOWN`, `SNMP_COLDSTART`, `SNMP_WARMSTART`, `SYSLOG`, `CONNECTION_LIMIT_REACHED`, `NAT_PACKET_DISCARD`, `CPU_THRESHOLD_RISING`, `MEM_THRESHOLD`, `FAILOVER`, `CLUSTER`, `PEER_FLAP`, `FRU_INSERT`, `FRU_REMOVE`, `CONFIG_CHANGE` |
| `--nms-object-name` | Base name for the NMS network object(s) (default: `snmpHost`) |
| `--host-object-name` | Base name for the SNMP host object(s) (default: `snmpv3-host`) |
| `--no-poll` | Disable SNMP polling (UDP 161) |
| `--no-trap` | Disable SNMP traps (UDP 162) |
| `--deploy` | Deploy the staged changes after configuring |
| `--debug` | Enable debug output |

### Notes

- **Credential hygiene:** `--auth-password` / `--priv-password` are redacted from the echoed command line and scrubbed from exception output, same as device passwords.
- **Trap events:** the per-host "Enable traps" toggle controls whether a manager *receives* traps; `--trap-events` controls which event types *fire* device-wide. Per the FDM model, if the device's trap-event list is empty, no traps are sent even when a host has traps enabled. ASA CLI traps not exposed by the FDM API (`ipsec`, `ikev2`, `interface-threshold`, `remote-access session-threshold`) cannot be set this way.
- **Removal:** use `ftd_api_cleanup.py --delete-snmp` (or the Cleanup tab's "SNMP Hosts & Users" checkbox) to remove SNMP hosts and users. SNMP cleanup is also included in `--delete-all`.
- The GUI equivalent is the **SNMP (FTD)** tab, visible only when the target platform is Cisco FTD (see [GUI How-To Guide](#gui-how-to-guide)).

---

## Performance and Concurrency

### What Is Multithreaded vs Sequential

Not all operations run in parallel. The table below summarizes which paths use a thread pool and which run one-at-a-time.

#### Importer (`ftd_api_importer.py`)

| Operation | Execution | Notes |
|-----------|-----------|-------|
| Address objects | **Multithreaded** | Bounded thread pool via `--workers` |
| Service objects | **Multithreaded** | Bounded thread pool via `--workers` |
| Address groups | Sequential | 0.2 s sleep between items |
| Service groups | Sequential | |
| Physical interfaces | Sequential | PUT updates to existing interfaces |
| EtherChannels | Sequential | |
| Bridge groups | Sequential | |
| Subinterfaces | Sequential | |
| Security zones | Sequential | |
| Static routes | Sequential | 0.2 s sleep between items |
| Access rules | Sequential | Order-dependent |

#### Cleanup (`ftd_api_cleanup.py`)

| Operation | Execution | Notes |
|-----------|-----------|-------|
| Custom object deletion | **Multithreaded** | Bounded thread pool via `--workers` |
| Static route deletion | **Multithreaded** | Bounded thread pool via `--workers` |
| Subinterface deletion | Sequential | 0.2 s sleep between items |
| EtherChannel deletion | Sequential | |
| Bridge group deletion | Sequential | |
| Physical interface reset | Sequential | Resets to defaults, cannot delete |

### The `--workers` Flag

Both the importer and cleanup accept `--workers N` to control the size of the thread pool.

| Setting | Value |
|---------|-------|
| Default | **6** |
| Minimum | 1 (enforced at runtime) |

**Guidance:**

- **Start with the default (6).** This is a safe baseline for most FTD appliances.
- **Lower to 2-3** if you see frequent 429 (Too Many Requests) or 503 (Service Unavailable) responses. The appliance is telling you to slow down.
- **Raise to 8-10** only if round-trip latency to the FTD is high (e.g., remote management over VPN) and the appliance is not rate-limiting.
- Going above 10 is rarely beneficial; the FDM API serializes writes internally.

**Examples:**

```bash
# Default (6 workers)
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin

# Conservative (high rate-limit environment)
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin --workers 2

# Aggressive (high-latency link, powerful appliance)
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin --workers 10

# Cleanup with fewer workers
python FortiGateToFTDTool/ftd_api_cleanup.py --host 10.0.0.1 -u admin --delete-all --workers 3
```

### Retry and Backoff Behavior

All multithreaded operations use automatic retry with exponential backoff and jitter (via `concurrency_utils.py`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| Max attempts | 4 | Total tries per API call (1 initial + 3 retries) |
| Base backoff | 0.3 s | Initial sleep after first failure |
| Max jitter | 0.25 s | Random delay added to each backoff to avoid thundering herd |
| Backoff growth | 2x | Doubles after each retry: 0.3 s → 0.6 s → 1.2 s |

**Retryable (transient) errors** are detected by matching the error message against these tokens (case-insensitive):
`429`, `too many`, `rate limit`, `timeout`, `temporarily`, `503`, `504`

Non-transient errors (e.g., 422 validation failures) fail immediately without retry.

### JSON Report Output

Both the importer and cleanup support `--json-report <path>` to write a machine-readable summary after a run. This is useful for CI/CD pipelines or scripted workflows.

```bash
# Importer report
python FortiGateToFTDTool/ftd_api_importer.py --host 10.0.0.1 -u admin --json-report import_results.json

# Cleanup report
python FortiGateToFTDTool/ftd_api_cleanup.py --host 10.0.0.1 -u admin --delete-all --json-report cleanup_results.json
```

---

## Troubleshooting

### Connection Issues

**Problem: Connection refused or timeout**
```
Connection error: Unable to connect to 192.168.1.1
```

**Solutions:**
1. Verify FTD management IP is correct
2. Ensure HTTPS (port 443) is accessible
3. Check if FDM is enabled (not managed by FMC)
4. Try from browser: `https://192.168.1.1`

**Problem: SSL certificate error**
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Solution:** The `--skip-verify` flag is enabled by default. If issues persist, ensure urllib3 is installed.

### HA Port Configuration Issues

**Problem:** `ERROR: Invalid HA port: 'Ethernet1/X'`

**Cause:** Specified HA port number exceeds model's port count

**Solution:**
```bash
# Check your model's port range
python FortiGateToFTDTool/fortigate_converter.py --list-models

# Example: FTD-3120 has 16 ports, so valid range is Ethernet1/1 through Ethernet1/16
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --ha-port Ethernet1/12 --pretty
```

---

**Problem:** `ERROR: Invalid HA port format`

**Cause:** HA port not in correct format

**Solution:**
```bash
# Correct format (case-sensitive)
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --ha-port Ethernet1/5

# WRONG formats (will error):
# --ha-port eth1/5
# --ha-port ethernet1/5
# --ha-port Eth1/5
# --ha-port 1/5
```

---

**Problem:** HA port warning: "Using Ethernet1/1 as HA port"

**Cause:** You specified Ethernet1/1, which is typically the first data port

**Impact:** No error, but may conflict with common network designs

**Solution:**
- Review your network design
- Consider if Ethernet1/1 should really be HA or if you need a different port
- Most HA deployments use Ethernet1/2 or higher-numbered ports

---

**Problem:** Converted config shows HA port assigned to data interface

**Cause:** Did not specify `--ha-port` and model default was not what you expected

**Solution:**
```bash
# Re-run conversion with explicit HA port
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --ha-port Ethernet1/8 --pretty

# Verify in generated files
grep -i "hardwareName" ftd_config_physical_interfaces.json
```

### Authentication Issues

**Problem: Invalid credentials**
```
Authentication failed: 401 Unauthorized
```

**Solutions:**
1. Verify username and password
2. Check if account is locked in FDM
3. Try logging into FDM web interface first

### Import Issues

**Problem: Object already exists**
```
Object 'Server1' already exists, skipping...
```

**This is normal.** The importer is idempotent and skips existing objects.

**Problem: Referenced object not found**
```
Referenced network 'Unknown_Net' not found
```

**Solutions:**
1. Import objects in correct dependency order
2. Check conversion warnings for unmatched objects
3. Create missing objects manually in FDM

**Problem: Import fails with API error**
```
API Error 422: Validation failed
```

**Solutions:**
1. Enable debug mode: `--debug`
2. Check the error message for specific field issues
3. Verify JSON file format matches FTD API requirements

### API Rate-Limit and Transient Errors

**Problem: Frequent 429 Too Many Requests**
```
[FAIL] address object "Server1": 429 Too Many Requests
```

**Solutions:**
1. Reduce worker count: `--workers 2` or `--workers 3`
2. The tool retries transient errors automatically (up to 4 attempts with exponential backoff), but sustained 429s mean you are exceeding the appliance's capacity
3. For very large imports (500+ objects), consider importing in batches using `--file`

---

**Problem: 503 Service Unavailable or 504 Gateway Timeout**
```
[FAIL] service object "HTTPS_TCP": 503 Service Temporarily Unavailable
```

**Solutions:**
1. The appliance may be under heavy load - wait a few minutes and retry
2. Reduce worker count: `--workers 2`
3. Check FDM System → Task Status for pending deployments or other background operations
4. If persistent, verify the appliance is healthy (CPU/memory usage)

---

**Problem: Timeout errors during large imports**
```
[FAIL] address object "LargeNet": timeout
```

**Solutions:**
1. These are automatically retried (up to 4 attempts)
2. If frequent, the management network may have latency or packet loss - check connectivity
3. Reduce parallelism with `--workers 2` to lower concurrent load on the appliance

---

### Deployment Issues

**Problem: Deployment fails**
```
Deployment validation failed
```

**Solutions:**
1. Check FDM **System → Task Status** for details
2. Common issues:
   - Invalid object references
   - Overlapping routes
   - Conflicting rules
3. Fix issues in FDM and redeploy

**Problem: Deployment stuck**

**Solutions:**
1. Wait 10-15 minutes (large deployments take time)
2. Check FDM **System → Task Status**
3. If stuck >15 minutes, cancel and review logs

---

## Best Practices

### Before Migration

1. **Test in Lab First**
   - Set up identical FTD in lab environment
   - Run full migration process
   - Test thoroughly before production

2. **Backup Everything**
   - FortiGate configuration (YAML)
   - FTD configuration (FDM backup)
   - All generated JSON files

3. **Plan Maintenance Window**
   - Schedule 2-4 hours for medium configs
   - Plan rollback procedure
   - Notify stakeholders

4. **Review Converted Config**
   - Check `ftd_config_summary.json` statistics
   - Review conversion warnings
   - Validate critical rules converted correctly

### During Migration

1. **Import in Phases**
   - Follow dependency order strictly
   - Verify each phase before proceeding
   - Test critical paths after each phase

2. **Monitor Progress**
   - Watch for errors during import
   - Check FDM logs
   - Validate objects after creation

3. **Document Issues**
   - Note any errors encountered
   - Track manual corrections needed
   - Record lessons learned

### After Migration

1. **Thorough Testing**
   - Test all critical traffic flows
   - Verify remote access works
   - Check routing tables
   - Validate NAT rules
   - Test logging

2. **Monitor Performance**
   - Check CPU/memory usage
   - Monitor connection counts
   - Review logs for errors

3. **Update Documentation**
   - Document new object names
   - Update network diagrams
   - Record configuration differences

---

## GUI How-To Guide

The Firewall Migration Tool includes a unified GUI application (`gui_app.py`) that wraps all conversion, import, and cleanup operations into a single window. This section walks through every part of the interface.

### Launching the GUI

**From source:**
```bash
python gui_app.py
```

**From compiled executable:**
Double-click `Firewall-Migration-Tool-v1.5.1.exe` (no Python installation required).

The application opens at 960x720 and is resizable (minimum 800x600).

---

### Top Toolbar

The toolbar at the top of the window contains three controls:

| Control | Location | Purpose |
|---------|----------|---------|
| **Source** dropdown | Left | Select source platform: **FortiGate**, **Cisco ASA**, **Palo Alto**, or **Cisco FTD** |
| **Target** dropdown | Center-left | Select target platform: **Cisco FTD**, **Palo Alto PAN-OS**, or **FortiGate** |
| **Theme** dropdown | Right | Switch between color themes (applied instantly) |

**Platform behavior:**
- The Target dropdown auto-narrows based on the Source: **Cisco ASA** locks the target to **Palo Alto PAN-OS**; **Palo Alto** and **Cisco FTD** sources lock the target to **FortiGate**.
- Selecting **FortiGate** as source restores the FTD and PAN-OS target options.
- When the target is **FortiGate**, the Import and Cleanup tabs are disabled - FortiGate output is a CLI `.conf` file you restore from the FortiGate GUI (System → Configuration → Restore).
- The **SNMP (FTD)** tab is visible only when the target is **Cisco FTD**.
- Changing the target platform updates model lists, labels, and default values across all tabs.

---

### Tab 1: Convert

This tab converts a source firewall configuration file into JSON files ready for API import.

#### Fields

| Field | Description |
|-------|-------------|
| **Input YAML / Input Config** | Path to the source configuration file. FortiGate uses YAML format; Cisco ASA uses plain text. Click **Browse...** to select. |
| **Output Directory** | Folder where generated JSON files will be saved. Defaults to the application directory. |
| **Output Base Name** | Prefix for all generated JSON files (e.g., `ftd_config` produces `ftd_config_address_objects.json`, etc.). Defaults to `ftd_config` for FTD or `pa_config` for PAN-OS. |
| **Target Model** | The specific hardware model you are migrating to. This controls port mapping and interface counts. |
| **HA Port (optional)** | The port reserved for High Availability (FTD only). Leave blank for no HA port. Format: `Ethernet1/X`. Disabled when targeting PAN-OS. |
| **Pretty-print JSON output** | When checked, output JSON is formatted with indentation for readability. Enabled by default. |

#### How to Run a Conversion

1. Click **Browse...** next to "Input YAML" and select your source configuration file.
2. Click **Browse...** next to "Output Directory" to choose where JSON files will be saved (or leave the default).
3. Optionally change the **Output Base Name** if you want a custom file prefix.
4. Select your **Target Model** from the dropdown.
5. For FTD targets, optionally enter an **HA Port** (e.g., `Ethernet1/5`).
6. Click **Run Conversion**.
7. Watch the output console at the bottom for progress and any warnings.
8. When complete, the console displays a summary of converted objects and the generated file list.

#### Buttons

| Button | Action |
|--------|--------|
| **Run Conversion** | Start the conversion process. Disabled while a conversion is running. |
| **Cancel** | Stop a running conversion. Only enabled during an active operation. |
| **Clear Output** | Clear the output console text. |

---

### Tab 2: Import to FTD / Import to PAN-OS

This tab imports the converted JSON files into the target firewall appliance via its API.

#### Connection Fields

| Field | Description |
|-------|-------------|
| **FTD Host / IP** or **PAN-OS Host / IP** | Management IP address or hostname of the target appliance. |
| **Username** | Admin username. Defaults to `admin`. |
| **Password** | Admin password (masked). |
| **Config Directory** | Folder containing the JSON files generated by the Convert tab. Click **Browse...** to select. |
| **JSON Base Name** | Must match the base name used during conversion (e.g., `ftd_config`). |
| **Workers** | Number of concurrent API threads (1-32, default 6). Higher values speed up large imports. FTD only; disabled for PAN-OS (which imports sequentially). |
| **Deploy after import** / **Commit after import** | When checked, automatically activates the imported configuration on the appliance after import completes. |
| **Debug mode** | When checked, prints full API request/response payloads to the output console. |

#### Selective Import

By default, all object types are imported. To import only specific types, check one or more boxes:

| Checkbox | What It Imports |
|----------|-----------------|
| Physical Interfaces | Physical port configurations (IP, name, enabled state) |
| EtherChannels | Port-channel / LACP bond configurations |
| Subinterfaces | VLAN subinterface configurations |
| Bridge Groups | Bridge group / BVI configurations |
| Security Zones | Security zone definitions |
| Address Objects | Host, network, range, and FQDN objects |
| Address Groups | Groups of address objects |
| Service Objects | TCP/UDP port objects |
| Service Groups | Groups of service objects |
| Static Routes | IPv4 static route entries |
| Access Rules | Firewall policy / access control rules |

**Tip:** If none of the checkboxes are selected, the tool imports everything in dependency order.

#### How to Run an Import

1. Enter the target appliance **Host / IP**, **Username**, and **Password**.
2. Set the **Config Directory** to the folder containing your converted JSON files.
3. Verify the **JSON Base Name** matches what was used during conversion.
4. Optionally adjust **Workers** (FTD only) for concurrency tuning.
5. Optionally check specific object types under **Selective Import**, or leave all unchecked to import everything.
6. Check **Deploy after import** if you want the configuration activated immediately.
7. Click **Start Import**.
8. Monitor progress in the output console. The tool reports each object as it is created or skipped (if it already exists).

#### Buttons

| Button | Action |
|--------|--------|
| **Start Import** | Begin the import process. |
| **Cancel** | Stop a running import. |
| **Clear Output** | Clear the output console. |

---

### Tab 3: Cleanup / Rollback

This tab deletes imported objects from the target appliance, useful for rollback or starting fresh.

#### Connection Fields

| Field | Description |
|-------|-------------|
| **FTD Host / IP** or **PAN-OS Host / IP** | Management IP of the target appliance. |
| **Username** | Admin username. |
| **Password** | Admin password. |
| **Target Model** | The model of the appliance being cleaned (affects API behavior). |
| **Workers** | Concurrent API threads for deletion (1-32, default 6). |

#### What to Delete

| Option | Description |
|--------|-------------|
| **Delete ALL custom objects** | Master checkbox: selects all object types for deletion. |
| Individual checkboxes | Delete specific object types: Access Rules, Static Routes, Subinterfaces, EtherChannels, Security Zones, Bridge Groups, Service Groups, Service Objects, Address Groups, Address Objects, SNMP Hosts & Users, Physical Interfaces (reset to defaults). |

#### Flags

| Flag | Description |
|------|-------------|
| **Dry run (preview only)** | Shows what would be deleted without actually deleting anything. Always use this first to verify. |
| **Deploy after cleanup** / **Commit after cleanup** | Activate the changes on the appliance after deletion completes. |

#### How to Run a Cleanup

1. Enter the target appliance **Host / IP**, **Username**, and **Password**.
2. Select the **Target Model**.
3. Choose what to delete:
   - Check **Delete ALL custom objects** for a full rollback, or
   - Check individual object types to delete selectively.
4. **Check "Dry run" first** to preview what will be deleted without making changes.
5. Click **Start Cleanup**.
6. Enter the **cleanup password** when prompted (see [Cleanup Password Protection](#cleanup-password-protection)).
7. A confirmation dialog will appear for destructive operations. Review and confirm.
8. Monitor the output console for progress and results.
9. Once satisfied with the dry-run output, uncheck "Dry run" and run again to perform the actual deletion.

**Important:** Objects are deleted in reverse dependency order (rules first, then routes, then interfaces, etc.) to avoid reference errors.

#### Buttons

| Button | Action |
|--------|--------|
| **Start Cleanup** | Begin the cleanup/deletion process (requires cleanup password). |
| **Cancel** | Stop a running cleanup. |
| **Clear Output** | Clear the output console. |
| **Change Cleanup Password** | Change the active cleanup password. Requires entering the current password first. |
| **Reset to Default Password** | Revert to the built-in default password. Requires entering the current password first. |

---

### Tab 4: SNMP (FTD)

This tab pushes a STIG-compliant SNMPv3 configuration to an FDM-managed FTD. FDM's GUI does not expose SNMPv3, so locally managed FTDs must be configured through the REST API - this tab does it end to end. **Only visible when the target platform is Cisco FTD.** See [SNMPv3 Configuration (FDM-Managed FTD)](#snmpv3-configuration-fdm-managed-ftd) for the CLI equivalent and full details.

#### Fields

| Field | Description |
|-------|-------------|
| **FTD Host / IP** | Management IP address or hostname of the FTD. |
| **Username** | Admin username. Defaults to `admin`. |
| **Password** | Admin password (masked). |
| **SNMP Manager IP(s)** | IP address(es) of your monitoring server(s). Comma-separated for multiple (e.g., `10.0.0.50, 10.1.0.50`). Each manager gets its own network object and SNMP host. |
| **SNMP Host Name (optional)** | Base name for the SNMP host object(s) created on the FTD; the manager IP is appended (e.g., `SolarWinds_10_0_0_50`). Defaults to `snmpv3-host`. |
| **SNMPv3 User Name** | Name of the SNMPv3 user to create. Defaults to `FWADMIN`. |
| **Auth Algorithm** | `SHA` or `SHA256`. |
| **Auth Password** | Authentication password (masked, minimum 8 characters). |
| **Privacy Algorithm** | `AES128`, `AES192`, or `AES256` (default `AES256`; `AES128` is the STIG minimum). |
| **Privacy Password** | Privacy/encryption password (masked, minimum 8 characters). |
| **Source Interface** | Logical name of the interface the managers reach the FTD through (e.g., `outside` - not `Ethernet1/1`). Physical interfaces, EtherChannels, and subinterfaces are supported. |
| **Location (optional)** | Device-global SNMP system location (sysLocation), e.g. a site or rack identifier. No semicolons. Left blank, the device's existing value is unchanged. |
| **Contact (optional)** | Device-global SNMP system contact (sysContact), e.g. an admin name or email. No semicolons. Left blank, the device's existing value is unchanged. |
| **Enable polling (UDP 161)** | Allow SNMP polling for this manager. On by default. |
| **Enable traps (UDP 162)** | Allow SNMP traps for this manager. On by default. |
| **Trap Events (device-wide)** | Which event types fire traps (link up/down, cold/warm start, syslog, failover, CPU/memory thresholds, etc.). Check **Configure trap event types** to set them; left unchecked, the device's current trap events are untouched. Defaults mirror the platform defaults (authentication, link up/down, cold/warm start). |
| **Deploy after push** | Deploy the staged changes on the FTD after the push completes. |

#### How to Run an SNMP Push

1. Set the target platform to **Cisco FTD** so the tab is visible.
2. Enter the FTD **Host / IP**, **Username**, and **Password**.
3. Enter the **SNMP Manager IP(s)** and **SNMPv3 User Name**.
4. Choose the auth/privacy algorithms and enter both passwords (minimum 8 characters each).
5. Enter the **Source Interface**'s logical name.
6. Optionally enter a **Location** and/or **Contact** to set the device-global sysLocation/sysContact.
7. Optionally check **Deploy after push** to activate immediately.
8. Click **Push SNMP Config** and monitor the output console.

**Notes:**
- Pushes are **additive** - object names are suffixed with the manager IP, so running once per management tool never overwrites earlier configs. Re-running with new values updates in place.
- Passwords are redacted from the echoed command line and error output.
- To remove SNMP config later, use the Cleanup tab's **SNMP Hosts & Users** checkbox.

#### Buttons

| Button | Action |
|--------|--------|
| **Push SNMP Config** | Begin the SNMP configuration push. |
| **Cancel** | Stop a running push. |
| **Clear Output** | Clear the output console. |

---

### Tab 5: Config Viewer

This tab lets you browse and search the generated JSON configuration files without leaving the application.

#### Fields

| Field | Description |
|-------|-------------|
| **Config Directory** | Folder containing JSON files. Click **Browse...** to select. |
| **JSON Base Name** | The base name prefix used during conversion (e.g., `ftd_config`). |

#### How to Use the Config Viewer

1. Set the **Config Directory** to the folder with your converted JSON files.
2. Enter the **JSON Base Name** (e.g., `ftd_config` or `pa_config`).
3. Click **Load Files**. The left pane populates with all matching `{base}_*.json` files.
4. Click any file in the left pane to display its contents (auto-formatted as pretty-printed JSON) in the right pane.
5. Use the **Search** bar to find text within the displayed file:
   - Type a search term and press **Enter** or click **Find Next**.
   - Click **Find Prev** to search backward.
   - The match counter (e.g., "3 of 7") shows your position in the results.
   - Search wraps around from end to beginning.

---

### Theme Selector

The theme dropdown in the top-right corner switches the entire application's color scheme instantly (no restart required).

| Theme | Description |
|-------|-------------|
| **Default** | Neutral dark gray background with light gray accents. Clean and understated. Default theme. |
| **Coral** | Dark teal background with coral accents. Professional and easy on the eyes. |
| **Sandstone** | Dark olive-green background with warm orange accents. Earthy and muted. |
| **Chris** | Hot pink background with neon green accents. High contrast, vibrant, and fun. |
| **Voyager** | Deep navy-blue background with gold accents. Bold and nautical. |
| **Light** | Light gray background with blue accents. Bright, for well-lit rooms. |

---

### Tips and Notes

- **One operation at a time:** Only one background operation (convert, import, cleanup, or SNMP push) can run at a time across all tabs. The active tab's Run button is disabled while an operation is in progress.
- **Cancel safely:** Clicking Cancel sends an interrupt to the running thread. The operation stops at the next safe point, which may take a few seconds.
- **Status bar:** The bottom of the window shows the current status (Ready, Running, Cancelled, or Done).
- **Output console:** Each tab has its own output console. Console text is read-only but can be selected and copied. Use **Clear Output** to reset it.
- **Config directory consistency:** The Convert tab's output directory and the Import tab's config directory should point to the same folder.
- **Base name consistency:** The output base name in the Convert tab must match the JSON base name in the Import and Config Viewer tabs.
- **Credential reuse:** The Import and Cleanup tabs have separate credential fields. Credentials are not shared between tabs.
- **Compiled executable:** When running from the `.exe`, all functionality is identical. No Python installation is needed on the target machine.

---

## Appendix

### A. Airgapped Network Installation

For networks without internet access:

**On Internet-Connected Machine:**

```bash
# Create package directory (from the repo root)
mkdir ftd_migration_packages

# Download packages
pip download -r requirements.txt -d ftd_migration_packages
```

**On Airgapped Machine:**

```bash
# From the tool directory (where requirements.txt lives)
python -m pip install --no-index --find-links=ftd_migration_packages -r requirements.txt

# Verify installation
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

### B. File Formats

**Address Object (FTD JSON):**
```json
{
  "name": "Server1",
  "description": "Web Server",
  "type": "networkobject",
  "subType": "HOST",
  "value": "10.0.0.10"
}
```

**Address Group (FTD JSON):**
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

**Port Object (FTD JSON):**
```json
{
  "name": "HTTP_TCP",
  "isSystemDefined": false,
  "port": "80",
  "type": "tcpportobject"
}
```

**Static Route (FTD JSON):**
```json
{
  "name": "Default_Route",
  "iface": {
    "name": "outside",
    "type": "physicalinterface"
  },
  "networks": [
    {"name": "any-ipv4", "type": "networkobject"}
  ],
  "gateway": {
    "name": "Gateway_192_168_1_1",
    "type": "networkobject"
  },
  "metricValue": 1,
  "ipType": "IPv4",
  "type": "staticrouteentry"
}
```

**Metadata (Conversion Settings):**
```json
{
  "target_model": "ftd-3120",
  "output_basename": "ftd_config",
  "ha_port": "Ethernet1/2",
  "schema_version": 1
}
```

### C. Complete Command Reference

All commands below assume the **repository root** as the working directory.

**Conversion Commands:**
```bash
# Basic conversion
python FortiGateToFTDTool/fortigate_converter.py config.yaml --pretty

# Specify target model
python FortiGateToFTDTool/fortigate_converter.py config.yaml --target-model ftd-3120 --pretty

# Custom output name
python FortiGateToFTDTool/fortigate_converter.py config.yaml -o prod_ftd --target-model ftd-3120 --pretty

# List supported models
python FortiGateToFTDTool/fortigate_converter.py --list-models

# Help
python FortiGateToFTDTool/fortigate_converter.py --help
```

**Import Commands:**
```bash
# Full import (auto-discovers metadata)
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin

# With explicit metadata file
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

# Import specific file
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --file custom.json --type address-objects

# Import and deploy
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --deploy

# Custom worker count
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --workers 3

# Generate JSON report
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --json-report import_results.json

# Validate connectivity without importing
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --validate-only

# Skip existing objects instead of updating them
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --skip-existing

# Debug mode
python FortiGateToFTDTool/ftd_api_importer.py --host IP -u admin --debug

# Help
python FortiGateToFTDTool/ftd_api_importer.py --help
```

**Cleanup Commands:**
```bash
# Dry run (preview)
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run

# Delete specific types
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-rules
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-routes
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-subinterfaces
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-etherchannels
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-security-zones
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-bridge-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-service-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-service-objects
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-address-groups
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-address-objects
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-snmp

# Delete everything
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all

# Delete everything without confirmation prompt
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --yes

# Delete and deploy
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --deploy

# Custom worker count
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --workers 3

# Generate JSON report
python FortiGateToFTDTool/ftd_api_cleanup.py --host IP -u admin --delete-all --json-report cleanup_results.json

# Help
python FortiGateToFTDTool/ftd_api_cleanup.py --help
```

**SNMP Configuration Commands (FDM-managed FTD):**
```bash
# Push SNMPv3 config (passwords prompted if omitted)
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside

# Multiple SNMP managers
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50,10.1.0.50 --snmp-user FWADMIN --interface outside

# With device-global location and contact (sysLocation / sysContact)
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside --location "DC-East Rack 12" --contact "netops@example.com"

# Push and deploy
python FortiGateToFTDTool/ftd_snmp_config.py --host IP -u admin --nms-ip 10.0.0.50 --snmp-user FWADMIN --interface outside --deploy

# Help
python FortiGateToFTDTool/ftd_snmp_config.py --help
```

### D. Support and Resources

**FTD FDM API Documentation:**
- Official Cisco FDM API Guide: Search "FTD FDM REST API" on Cisco.com
- API Explorer: `https://YOUR_FTD_IP/apiexplorer/`

**Python Resources:**
- PyYAML: https://pyyaml.org/
- Requests: https://docs.python-requests.org/

**FDM Troubleshooting:**
- Logs: System → Troubleshooting → Diagnostics
- Tasks: System → Task Status
- Audit: System → Audit → Audit Log

---

**Document Version:** 3.1
**Last Updated:** June 2026
**Compatible With:** FTD 7.4.x with FDM, PAN-OS 10.1+, Python 3.9+