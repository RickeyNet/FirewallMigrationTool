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
8. [Performance and Concurrency](#performance-and-concurrency)
9. [Troubleshooting](#troubleshooting)
10. [Best Practices](#best-practices)
11. [Appendix](#appendix)

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
- **Multi-platform support** — Convert to Cisco FTD or Palo Alto PAN-OS from the same FortiGate source
- Model-aware interface port mapping with customizable HA port assignment (FTD)
- Flexible HA port configuration (override model defaults)
- Metadata file for seamless import workflow
- Bulk cleanup/delete script for rollback
- Idempotent imports (skip existing objects)
- Unified GUI with platform selector for Convert, Import, and Cleanup workflows

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
pip install pyyaml requests urllib3
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

### Step 1: Download All Script Files

Your working directory should contain:

```
FortiGate-Migration/
├── fortigate_converter.py              # Main FTD converter script
├── address_converter.py                # Address object module (FTD)
├── address_group_converter.py          # Address group module (FTD)
├── service_converter.py                # Service object module (FTD)
├── service_group_converter.py          # Service group module (FTD)
├── policy_converter.py                 # Access policy module (FTD)
├── route_converter.py                  # Static route module (FTD)
├── interface_converter.py              # Interface conversion module (FTD)
├── ftd_api_importer.py                 # FTD API importer script
├── ftd_api_cleanup.py                  # FTD bulk delete/cleanup utility
├── gui_app.py                          # Unified GUI application (FTD + PA)
├── FortiGateToPaloAltoTool/            # Palo Alto conversion modules
│   ├── pa_converter.py                 # Main PA converter script
│   ├── pa_address_converter.py         # Address object module (PA)
│   ├── pa_address_group_converter.py   # Address group module (PA)
│   ├── pa_service_converter.py         # Service object module (PA)
│   ├── pa_service_group_converter.py   # Service group module (PA)
│   ├── pa_policy_converter.py          # Security rule module (PA)
│   ├── pa_route_converter.py           # Static route module (PA)
│   ├── pa_interface_converter.py       # Interface & zone module (PA)
│   ├── pa_common.py                    # Shared PA utilities
│   ├── panos_api_base.py               # PAN-OS XML API client
│   ├── panos_api_importer.py           # PAN-OS API importer
│   └── panos_api_cleanup.py            # PAN-OS bulk cleanup
├── fortigate_config.yaml               # Your FortiGate YAML (input)
├── ftd_config_*.json                   # Generated FTD JSON files (output)
└── pa_config_*.json                    # Generated PA JSON files (output)
```

### Step 2: Install Dependencies

```bash
pip install pyyaml requests urllib3
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
pip install pyyaml requests urllib3
py -3.9 -m pip install pyyaml requests urllib3

```

### Test that Python can find the libraries:

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

### Create a directory for the packages and download them:

```bash
# Create a directory for the packages
mkdir ftd_migration_packages
cd ftd_migration_packages

# Download packages and their dependencies
pip download pyyaml requests urllib3
py -3.9 -m pip download pyyaml requests urllib3
```

This will download files like:
- PyYAML-6.0.1-cp39-cp39-win_amd64.whl
- requests-2.31.0-py3-none-any.whl
- urllib3-2.0.7-py3-none-any.whl
- certifi-2023.7.22-py3-none-any.whl (dependency)
- charset-normalizer-3.3.2-cp39-cp39-win_amd64.whl (dependency)
- idna-3.4-py3-none-any.whl (dependency)

### Airgapped Side Installation:

1. Move package folder and all scripts to airgapped machine (including Python 3.x installer if not already installed)

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

6. Navigate to the package directory and install:
```bash
cd path\to\your\package\folder
python -m pip install --no-index --find-links=. pyyaml requests urllib3
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
□ Install libraries: pip install pyyaml requests urllib3
□ Download all 10 script files to one folder
□ Export FortiGate config as YAML
□ Backup FTD configuration in FDM
□ Identify your target FTD model (e.g., ftd-3120)
```

### Conversion Phase

```
□ Run: python fortigate_converter.py config.yaml --target-model ftd-3120 --pretty
□ (Optional) Specify custom HA port: --ha-port Ethernet1/5
□ Review generated JSON files (13 files total including metadata)
□ Check summary.json for conversion statistics
□ Review any warnings in console output
□ Verify HA port assignment matches your design
```

### Import Phase

```
□ Import interfaces first (creates foundation):
    python ftd_api_importer.py --host IP -u admin --only-physical-interfaces
    python ftd_api_importer.py --host IP -u admin --only-etherchannels
    python ftd_api_importer.py --host IP -u admin --only-subinterfaces
    python ftd_api_importer.py --host IP -u admin --only-security-zones

□ Import objects and rules:
  # Use --workers to control concurrent address/service object creation (default 6)
  python ftd_api_importer.py --host IP -u admin --workers 6

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
□ Run cleanup: python ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run
□ Review what will be deleted
□ Execute: python ftd_api_cleanup.py --host IP -u admin --delete-all --deploy
□ Start over with corrected configuration
```

---

## Phase 1: Converting FortiGate Configuration

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
python fortigate_converter.py --list-models
```

**Supported models:**

| Model    | Ports | HA Port     | Description               |
|----------|-------|-------------|---------------------------|
| ftd-1010 | 8     | None        | Entry-level, no HA        |
| ftd-1120 | 12    | Ethernet1/2 | Small branch              |
| ftd-1140 | 12    | Ethernet1/2 | Small branch              |
| ftd-2110 | 12    | Ethernet1/2 | Mid-range                 |
| ftd-2120 | 12    | Ethernet1/2 | Mid-range                 |
| ftd-2130 | 16    | Ethernet1/2 | Mid-range                 |
| ftd-2140 | 16    | Ethernet1/2 | Mid-range                 |
| ftd-3105 | 8     | Ethernet1/2 | Secure Firewall           |
| ftd-3110 | 16    | Ethernet1/2 | Secure Firewall           |
| ftd-3120 | 16    | Ethernet1/2 | Secure Firewall (default) |
| ftd-3130 | 24    | Ethernet1/2 | Secure Firewall           |
| ftd-3140 | 24    | Ethernet1/2 | Secure Firewall           |
| ftd-4215 | 24    | Ethernet1/2 | Enterprise                |

**Note:** Default HA ports can be overridden using the `--ha-port` option. See [Customizing HA Port Configuration](#customizing-ha-port-configuration) for details.


### Step 2a: Customizing HA Port Configuration

By default, most FTD models reserve **Ethernet1/2** for High Availability (HA) connections. However, you can customize which port is used for HA using the `--ha-port` option.

#### When to Use a Custom HA Port

- **Port conflicts**: Your network design requires Ethernet1/2 for data traffic
- **Cable management**: Physical rack layout requires a different HA port location
- **Multi-chassis setup**: HA links use specific ports for cross-chassis connections
- **Compliance requirements**: Security policy mandates specific HA port placement

#### How HA Port Assignment Works

1. **Default behavior**: Models with HA support (all except FTD-1010) use Ethernet1/2
2. **Port reservation**: The HA port is automatically skipped during interface conversion
3. **Port validation**: Custom HA ports must be within the model's port range (1 to total_ports)
4. **Data port assignment**: All FortiGate interfaces are mapped to available FTD ports, excluding the HA port

#### Custom HA Port Syntax
```bash
python fortigate_converter.py config.yaml --target-model MODEL --ha-port EthernetX/Y
```

**Format Requirements:**
- Must be exactly `Ethernet1/X` where X is a port number
- Port number must be between 1 and the model's maximum port count
- Cannot use Management ports for HA
- Case-sensitive: use `Ethernet1/5` not `ethernet1/5`

#### Examples

**Example 1: Use Ethernet1/5 for HA on FTD-3120 (16-port model)**
```bash
python fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port Ethernet1/5 --pretty
```
**Result:**
- HA configured on: Ethernet1/5
- Available data ports: Ethernet1/1, 1/3, 1/4, 1/6-16 (Ethernet1/2 becomes available, 1/5 reserved)

---

**Example 2: Use Ethernet1/10 for HA on FTD-3140 (24-port model)**
```bash
python fortigate_converter.py fortigate.yaml --target-model ftd-3140 --ha-port Ethernet1/10 --pretty
```
**Result:**
- HA configured on: Ethernet1/10
- Available data ports: Ethernet1/1-9, 1/11-24 (Ethernet1/2 becomes available, 1/10 reserved)

---

**Example 3: Keep default HA port (Ethernet1/2)**
```bash
python fortigate_converter.py fortigate.yaml --target-model ftd-3120 --pretty
```
**Result:**
- HA configured on: Ethernet1/2 (default)
- Available data ports: Ethernet1/1, 1/3-16

---

**Example 4: Try invalid port number (will error)**
```bash
python fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port Ethernet1/99
```
**Result:**
```
ERROR: Invalid HA port: 'Ethernet1/99'. Model 'ftd-3120' only has ports 1-16.
Specify a port between Ethernet1/1 and Ethernet1/16.
```

---

**Example 5: Try invalid format (will error)**
```bash
python fortigate_converter.py fortigate.yaml --target-model ftd-3120 --ha-port eth1/5
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
| Default (Ethernet1/2) | Ethernet1/2           | Ethernet1/1, 1/3-16 (15 ports)            |
| Custom (Ethernet1/5)  | Ethernet1/5           | Ethernet1/1-4, 1/6-16 (15 ports)          |
| Custom (Ethernet1/10) | Ethernet1/10          | Ethernet1/1-9, 1/11-16 (15 ports)         |
| FTD-1010 (No HA)      | None                  | Ethernet1/1-8 (all 8 ports)               |

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
python fortigate_converter.py fortigate_config.yaml --pretty
```

**Specify target model (recommended):**
```bash
python fortigate_converter.py fortigate_config.yaml --target-model ftd-3120 --pretty
```

**Custom output name:**
```bash
python fortigate_converter.py fortigate_config.yaml -o prod_ftd --target-model ftd-3120 --pretty
```

**Command options:**

| Option           | Description                       | Default      |
|------------------|-----------------------------------|--------------|
| `input_file`     | FortiGate YAML configuration file | Required     |
| `-o, --output`   | Output base name for JSON files   | `ftd_config` |
| `--pretty`       | Format JSON with indentation      | Off          |
| `--target-model` | Target FTD firewall model         | `ftd-3120`   |
| `--list-models`  | Display supported models and exit | -            |
| `--ha-port`      | Specified HA port being used      | `Ethernet1/2`|
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
  "schema_version": 1
}
```

**Why this matters:**

| Field             | Purpose                                                              |
|-------------------|----------------------------------------------------------------------|
| `target_model`    | Tells importer which FTD model was targeted for correct port mapping |
| `output_basename` | Helps importer auto-discover related JSON files                      |
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

---

### Palo Alto PAN-OS Conversion

To convert for Palo Alto instead of Cisco FTD, use the `pa_converter.py` script in the `FortiGateToPaloAltoTool/` directory:

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
python ftd_api_importer.py --host 192.168.1.1 -u admin
```

### Step 2: Import Interfaces First

Interfaces form the foundation. Import them in this specific order:

```bash
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-physical-interfaces # Update physical interfaces
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-etherchannels # Create EtherChannels (port-channels)
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-subinterfaces # Create subinterfaces (VLANs)
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-bridge-groups # Create bridge groups
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-security-zones # Create security zones
```

### Step 3: Import Objects and Rules

After interfaces are configured, import remaining objects:

```bash
# Import everything else (skips already-imported interfaces)
python ftd_api_importer.py --host 192.168.1.1 -u admin
```

Or import selectively:

```bash
# Address objects and groups
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-objects
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-groups
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-objects
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-groups
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-routes
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-rules
```

### Step 4: Deploy Configuration

**Option A: Deploy via script**
```bash
python ftd_api_importer.py --host 192.168.1.1 -u admin --deploy
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
1. Zones                ← Foundation
2. Address Objects      ← Standalone
3. Address Groups       ← References address objects
4. Service Objects      ← Standalone
5. Service Groups       ← References service objects
6. Static Routes        ← References interfaces
7. Security Rules       ← References everything above
8. Commit (optional)    ← Activates configuration
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

The FTD cleanup script removes imported objects for rollback or fresh start.

### Important: Deletion Order

Objects must be deleted in reverse dependency order:

```
1. Access Rules           ← Remove policies first
2. Static Routes          ← Remove routing
3. Subinterfaces          ← Remove VLAN interfaces
4. EtherChannels          ← Remove port-channels
5. Security Zones         ← Remove zones
6. Bridge Groups          ← Remove bridge groups
7. Service Groups         ← Remove port groups
8. Service Objects        ← Remove port objects
9. Address Groups         ← Remove network groups
10. Address Objects       ← Remove network objects
11. Physical Interfaces   ← Reset only (cannot delete)
```

### Step 1: Preview Deletion (Dry Run)

Always preview before deleting:

```bash
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --dry-run
```

### Step 2: Execute Deletion

```bash
# Delete everything
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all

# Delete and deploy
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --deploy
```

### Selective Deletion

```bash
# Delete specific object types
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-rules
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-routes
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-objects
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-address-groups
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-service-objects
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-service-groups
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-security-zones
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-bridge-groups
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-subinterfaces
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-etherchannels
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --reset-physical-interfaces
```

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
python ftd_api_importer.py --host 10.0.0.1 -u admin

# Conservative (high rate-limit environment)
python ftd_api_importer.py --host 10.0.0.1 -u admin --workers 2

# Aggressive (high-latency link, powerful appliance)
python ftd_api_importer.py --host 10.0.0.1 -u admin --workers 10

# Cleanup with fewer workers
python ftd_api_cleanup.py --host 10.0.0.1 -u admin --delete-all --workers 3
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
python ftd_api_importer.py --host 10.0.0.1 -u admin --json-report import_results.json

# Cleanup report
python ftd_api_cleanup.py --host 10.0.0.1 -u admin --delete-all --json-report cleanup_results.json
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
python fortigate_converter.py --list-models

# Example: FTD-3120 has 16 ports, so valid range is Ethernet1/1 through Ethernet1/16
python fortigate_converter.py config.yaml --target-model ftd-3120 --ha-port Ethernet1/12 --pretty
```

---

**Problem:** `ERROR: Invalid HA port format`

**Cause:** HA port not in correct format

**Solution:**
```bash
# Correct format (case-sensitive)
python fortigate_converter.py config.yaml --target-model ftd-3120 --ha-port Ethernet1/5

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
python fortigate_converter.py config.yaml --target-model ftd-3120 --ha-port Ethernet1/8 --pretty

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
1. The appliance may be under heavy load — wait a few minutes and retry
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
2. If frequent, the management network may have latency or packet loss — check connectivity
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
   - Check summary.json statistics
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

## Appendix

### A. Airgapped Network Installation

For networks without internet access:

**On Internet-Connected Machine:**

```bash
# Create package directory
mkdir ftd_migration_packages
cd ftd_migration_packages

# Download packages
pip download pyyaml requests urllib3
```

**On Airgapped Machine:**

```bash
# Navigate to package directory
cd path\to\ftd_migration_packages

# Install from local files
python -m pip install --no-index --find-links=. pyyaml requests urllib3

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
  "schema_version": 1
}
```

### C. Complete Command Reference

**Conversion Commands:**
```bash
# Basic conversion
python fortigate_converter.py config.yaml --pretty

# Specify target model
python fortigate_converter.py config.yaml --target-model ftd-3120 --pretty

# Custom output name
python fortigate_converter.py config.yaml -o prod_ftd --target-model ftd-3120 --pretty

# List supported models
python fortigate_converter.py --list-models

# Help
python fortigate_converter.py --help
```

**Import Commands:**
```bash
# Full import (auto-discovers metadata)
python ftd_api_importer.py --host IP -u admin

# With explicit metadata file
python ftd_api_importer.py --host IP -u admin --metadata-file ftd_config_metadata.json

# Interface imports (in order)
python ftd_api_importer.py --host IP -u admin --only-physical-interfaces
python ftd_api_importer.py --host IP -u admin --only-etherchannels
python ftd_api_importer.py --host IP -u admin --only-subinterfaces
python ftd_api_importer.py --host IP -u admin --only-bridge-groups
python ftd_api_importer.py --host IP -u admin --only-security-zones

# Object imports
python ftd_api_importer.py --host IP -u admin --only-address-objects
python ftd_api_importer.py --host IP -u admin --only-address-groups
python ftd_api_importer.py --host IP -u admin --only-service-objects
python ftd_api_importer.py --host IP -u admin --only-service-groups
python ftd_api_importer.py --host IP -u admin --only-routes
python ftd_api_importer.py --host IP -u admin --only-rules

# Import specific file
python ftd_api_importer.py --host IP -u admin --file custom.json --type address-objects

# Import and deploy
python ftd_api_importer.py --host IP -u admin --deploy

# Custom worker count
python ftd_api_importer.py --host IP -u admin --workers 3

# Generate JSON report
python ftd_api_importer.py --host IP -u admin --json-report import_results.json

# Debug mode
python ftd_api_importer.py --host IP -u admin --debug

# Help
python ftd_api_importer.py --help
```

**Cleanup Commands:**
```bash
# Dry run (preview)
python ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run

# Delete specific types
python ftd_api_cleanup.py --host IP -u admin --delete-rules
python ftd_api_cleanup.py --host IP -u admin --delete-routes
python ftd_api_cleanup.py --host IP -u admin --delete-subinterfaces
python ftd_api_cleanup.py --host IP -u admin --delete-etherchannels
python ftd_api_cleanup.py --host IP -u admin --delete-security-zones
python ftd_api_cleanup.py --host IP -u admin --delete-bridge-groups
python ftd_api_cleanup.py --host IP -u admin --delete-service-groups
python ftd_api_cleanup.py --host IP -u admin --delete-service-objects
python ftd_api_cleanup.py --host IP -u admin --delete-address-groups
python ftd_api_cleanup.py --host IP -u admin --delete-address-objects

# Delete everything
python ftd_api_cleanup.py --host IP -u admin --delete-all

# Delete and deploy
python ftd_api_cleanup.py --host IP -u admin --delete-all --deploy

# Custom worker count
python ftd_api_cleanup.py --host IP -u admin --delete-all --workers 3

# Generate JSON report
python ftd_api_cleanup.py --host IP -u admin --delete-all --json-report cleanup_results.json

# Help
python ftd_api_cleanup.py --help
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

**Document Version:** 3.0
**Last Updated:** March 2026
**Compatible With:** FTD 7.4.x with FDM, PAN-OS 10.1+, Python 3.9+