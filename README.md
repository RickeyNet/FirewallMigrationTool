# FortiGate to Cisco FTD Migration Tool - Complete User Guide

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [File Structure](#file-structure)
5. [Phase 1: Converting FortiGate Configuration](#phase-1-converting-fortigate-configuration)
6. [Phase 2: Importing to FTD](#phase-2-importing-to-ftd)
7. [Phase 3: Cleanup (Optional)](#phase-3-cleanup-optional)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)
10. [Appendix](#appendix)

---

## Overview

This toolset converts FortiGate firewall configurations to Cisco FTD (Firepower Threat Defense) format and imports them via the FDM (Firewall Device Manager) API.

**What gets converted:**
- ✅ Address Objects (network objects)
- ✅ Address Groups (network groups)
- ✅ Service Port Objects (TCP/UDP ports)
- ✅ Service Port Groups (port groups)
- ✅ Interfaces (physical, subinterfaces, etherchannels, bridge groups)
- ✅ Static Routes
- ✅ Firewall Policies (access rules)

**Additional Features:**
- ✅ Bulk cleanup/delete script for removing imported objects
- ✅ Automatic name sanitization (spaces converted to underscores)

---

## Prerequisites

### System Requirements
- **Python**: 3.6 or higher
- **Operating System**: Windows, macOS, or Linux
- **Network Access**: Connectivity to FTD management interface

### Python Libraries
```bash
pip install pyyaml requests urllib3
```

### FTD Requirements
- **Model**: FTD 3120 (or compatible model)
- **Management**: Local FDM (Firewall Device Manager)
- **Firmware**: 7.4.x (tested on 7.4.2.4-9)
- **Credentials**: Admin username and password

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

## Installation

### Step 1: Download All Script Files

### Your Working Directory Should Look Like:
`````
FortiGate-FTD-Migration/
├── fortigate_converter.py          # Main converter
├── address_converter.py            # Module
├── address_group_converter.py      # Module
├── service_converter.py            # Module
├── service_group_converter.py      # Module
├── policy_converter.py             # Module
├── route_converter.py              # Module
├── interface_converter.py          # Module - Interface conversion
├── ftd_api_importer.py            # API importer
├── ftd_api_cleanup.py             # Bulk delete/cleanup utility
├── fortigate_config.yaml          # Your FortiGate YAML (input)
└── ftd_config_*.json              # Generated FTD JSON files (output)
`````

### Step 2: Install Dependencies

Open terminal/command prompt in your working directory:

```bash
# Install required Python libraries
pip install pyyaml requests urllib3
```

### Step 3: Verify Installation

Test that Python can find the libraries:

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

---

## Download FortiGate YAML Config

1. Login to FortiGate
2. Click username in top right
3. Go to Configuration → Backup
4. Select YAML format
5. Click OK
6. Rename the downloaded config to `fortigate_config.yaml`


## Phase 1: Converting FortiGate Configuration

### Step 1: Prepare Your FortiGate Configuration

Export your FortiGate configuration as YAML format and save it in your working directory.

**Example filename:** `fortigate_config.yaml`

**Expected YAML structure:**
```yaml
firewall_address:
  - Server1:
      subnet: [10.0.0.10, 255.255.255.255]
      comment: "Web Server"

firewall_addrgrp:
  - Web_Servers:
      member: ["Server1", "Server2"]

firewall_service_custom:
  - HTTP:
      tcp-portrange: 80

firewall_service_group:
  - Web_Services:
      member: ["HTTP", "HTTPS"]

firewall_policy:
  - 1:
      name: "Allow_Web_Traffic"
      srcintf: "inside"
      dstintf: "outside"
      action: accept

router_static:
  - 1:
      dst: [0.0.0.0, 0.0.0.0]
      gateway: 192.168.1.1
      device: "port1"
```

### Step 2: Run the Conversion Script

**Basic conversion:**
```bash
python fortigate_converter.py fortigate_config.yaml --pretty
```

**Custom output name:**
```bash
python fortigate_converter.py fortigate_config.yaml -o my_ftd_config --pretty
```

**Command breakdown:**
- `fortigate_config.yaml` - Your input file
- `--pretty` - Makes JSON readable (recommended)
- `-o my_ftd_config` - Output base name (optional)

### Step 3: Review Generated Files

The converter generates the following JSON files:

- `{output}_physical_interfaces.json` - Physical interface configurations (PUT)
- `{output}_etherchannels.json` - EtherChannel/Port-channel configurations (POST)
- `{output}_bridge_groups.json` - Bridge group configurations (POST)
- `{output}_subinterfaces.json` - VLAN subinterface configurations (POST)
- `{output}_security_zones.json` - Security zone configurations (POST)
- `{output}_address_objects.json` - Network objects (hosts, subnets, ranges, FQDNs)
- `{output}_address_groups.json` - Network object groups
- `{output}_service_objects.json` - Port/protocol objects
- `{output}_service_groups.json` - Port object groups
- `{output}_static_routes.json` - Static route entries
- `{output}_access_rules.json` - Access control rules
- `{output}_summary.json` - Conversion statistics

### Step 4: Verify Conversion Output

**Check the summary file:**
```bash
# On Windows
type ftd_config_summary.json

# On Mac/Linux
cat ftd_config_summary.json
```

**Example summary:**
```json
{
  "conversion_summary": {
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

**Review console output for warnings:**
```
Converting Address Objects...
------------------------------------------------------------
  Converted: Bull_net -> NETWORK (10.0.20.0/24)
  Skipped: none (name is 'none')
  Skipped: 192.168.1.1 (name is just an IP address)
  Warning: No address object found for 10.0.50.0/24
```

### Common Conversion Issues

| Issue            | Message                                                 | Solution                                                   |
|------------------|---------------------------------------------------------|------------------------------------------------------------|
| Empty values     | `Skipped: Empty_Object (empty value)`                   | Automatically skipped. Review original FortiGate config.   |
| Split services   | `Split: DNS -> DNS_TCP and DNS_UDP`                     | Normal behavior. FTD requires separate TCP and UDP objects.|
| Unmatched routes | `Warning: No address object found for gateway 10.0.1.1` | Create the missing address object before importing routes. |

### Name Sanitization

FTD does not allow spaces in object names. The converter automatically replaces all spaces with underscores (`_`) in:

- Address object names
- Address group names
- Address group member references
- Service object names
- Service group names
- Service group member references
- Access rule names
- Zone names in access rules
- Network references in access rules
- Service references in access rules
- Static route names
- Interface names in routes
- Destination and gateway references in routes

**Example:**
```
FortiGate: "Blocked IPs"      -> FTD: "Blocked_IPs"
FortiGate: "Web Access Group" -> FTD: "Web_Access_Group"
FortiGate: "My Custom Rule"   -> FTD: "My_Custom_Rule"
```

When a name is sanitized, the console output will show the transformation:
```
Converted: Blocked IPs -> Blocked_IPs (3 members)
Converted: My Custom Rule -> My_Custom_Rule [PERMIT] (Src:2 Dst:1 Svc:3)
```
### Step 5: Review Interface Conversion

The interface converter maps FortiGate interfaces to FTD interfaces:

**Interface Type Mapping:**

| FortiGate Type               | FTD Type              | API Method    |
|------------------------------|-----------------------|---------------|
| Physical port (port1, port2) | physicalinterface     | PUT (update)  |
| Aggregate (type: aggregate)  | etherchannelinterface | POST (create) |
| Switch (type: switch)        | bridgegroupinterface  | POST (create) |
| VLAN (has vlanid:)           | subinterface          | POST (create) |

**Port Mapping (FortiGate 500E to FTD 3120):**
- port2 → Ethernet1/1
- port6 → Ethernet1/3
- port5 → Ethernet1/13
- port7 → Ethernet1/14
- x1 → Ethernet1/15
- x2 → Ethernet1/16

**Note:** Ethernet1/2 is reserved for HA and is skipped.

**Skipped Interfaces:**
- ha, mgmt, modem (system interfaces)
- ssl.root, naf.root, l2t.root (virtual interfaces)
- s1, s2, vw1, vw2 (FortiGate-specific)

---

## Phase 2: Importing to FTD

### Before You Begin

**⚠️ CRITICAL: Backup Your FTD Configuration**

1. Log into FDM web interface
2. Navigate to **System > Backup**
3. Create a full backup
4. Download and save the backup file

## Import Order

The importer processes objects in dependency order:

| Step | Object Type                          | API Method | Dependency                              |
|------|--------------------------------------|------------|-----------------------------------------|
| 1    | Physical Interfaces                  | PUT        | None                                    |
| 2    | Subinterfaces (physical parents)     | POST       | Physical Interfaces                     |
| 3    | EtherChannels                        | POST       | Physical Interfaces                     |
| 4    | Subinterfaces (etherchannel parents) | POST       | EtherChannels                           |
| 5    | Bridge Groups                        | POST       | Physical Interfaces                     |
| 6    | Security Zones                       | POST       | All Interfaces                          |
| 7    | Address Objects                      | POST       | None                                    |
| 8    | Address Groups                       | POST       | Address Objects                         |
| 9    | Service Objects                      | POST       | None                                    |
| 10   | Service Groups                       | POST       | Service Objects                         |
| 11   | Static Routes                        | POST       | Interfaces, Address Objects             |
| 12   | Access Rules                         | POST       | Security Zones, Address/Service Objects |

### Step 1: Test Connectivity

**Verify you can reach FTD:**
```bash
# Test connectivity
ping 192.168.1.1

# Test HTTPS access (certificate error is normal for self-signed certs)
curl -k https://192.168.1.1
```

### Step 2: Import Options

You have **4 import strategies**:

#### Option A: All-at-Once Import (Fastest)

Import everything in one run:

```bash
python ftd_api_importer.py --host 192.168.1.1 --username admin --deploy
```

**Pros:** Fast, simple  
**Cons:** Harder to troubleshoot if errors occur  
**Best for:** Small configs, lab environments

---

#### Option B: Step-by-Step Import (Recommended for Production)
```bash
# Selective imports - Interfaces
python ftd_api_importer.py --host IP -u admin --only-physical-interfaces
python ftd_api_importer.py --host IP -u admin --only-etherchannels
python ftd_api_importer.py --host IP -u admin --only-bridge-groups
python ftd_api_importer.py --host IP -u admin --only-subinterfaces
python ftd_api_importer.py --host IP -u admin --only-security-zones

# Selective imports - Objects
python ftd_api_importer.py --host IP -u admin --only-address-objects
python ftd_api_importer.py --host IP -u admin --only-address-groups
python ftd_api_importer.py --host IP -u admin --only-service-objects
python ftd_api_importer.py --host IP -u admin --only-service-groups
python ftd_api_importer.py --host IP -u admin --only-routes
python ftd_api_importer.py --host IP -u admin --only-rules
````

**Pros:** Maximum control, easy to troubleshoot  
**Cons:** More time-consuming  
**Best for:** Production environments, large configs

---

#### Option C: Batch Import (Balanced)

Import related objects together:

```bash
# Import all address-related objects
python ftd_api_importer.py --host 192.168.1.1 -u admin \
  --only-address-objects --only-address-groups

# Import all service-related objects
python ftd_api_importer.py --host 192.168.1.1 -u admin \
  --only-service-objects --only-service-groups

# Import routing and policies
python ftd_api_importer.py --host 192.168.1.1 -u admin \
  --only-routes --only-rules

# Deploy
python ftd_api_importer.py --host 192.168.1.1 -u admin --deploy
```

**Pros:** Faster than step-by-step, more control than all-at-once  
**Cons:** Still requires verification between steps  
**Best for:** Medium-sized configs

---

#### Option D: Test Subset First

Test with a small subset before full import:

```bash
# Create a test file with 5-10 objects
# Edit ftd_config_address_objects.json and save first 10 objects to test_addresses.json

# Import test file
python ftd_api_importer.py --host 192.168.1.1 -u admin \
  --file test_addresses.json --type address-objects

# Verify in FDM, then import the full file
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-objects
```

**Pros:** Safest, validates process works  
**Cons:** Requires manual file editing  
**Best for:** First-time migrations, critical environments

---

### Step 3: Monitor Import Progress

**During import, you'll see:**

```
============================================================
FortiGate to Cisco FTD Configuration Importer
============================================================

Authenticating to FTD at 192.168.1.1
============================================================
✓ Authentication successful

============================================================
Starting Import Process
============================================================

Selective Import Mode:
  - Address Objects

------------------------------------------------------------
Importing Address Objects from ftd_config_address_objects.json
------------------------------------------------------------
  [1/48] Creating: Bull_net... ✓
  [2/48] Creating: Bear_Gateway... ✓
  [3/48] Creating: Server1... ⊘ (already exists)
  [4/48] Creating: Network_DMZ... ✗
      Error: Invalid CIDR notation in value
  [5/48] Creating: Gateway_10_0_1_1... ✓
  ...

============================================================
IMPORT STATISTICS
============================================================

Address Objects:
  Created: 45
  Skipped: 2 (already exist)
  Failed:  1
```
### Step 4: Handle Import Errors

**Common errors and solutions:**

| Error                             | Cause                 | Solution                                      |
|-----------------------------------|-----------------------|-----------------------------------------------|
| ` (already exists)`               | Object already in FTD | Normal - script continues automatically       |
| `Authentication failed: 401`      | Bad credentials       | Verify username/password and admin privileges |
| `Referenced object 'X' not found` | Missing dependency    | Import address objects before routes/rules    |
| `Connection error: ReadTimeout`   | Network issue         | Check connectivity, wait and retry            |

### Step 5: Deploy Changes

After successful import, deploy to activate changes:

```bash
# Deploy via script
python ftd_api_importer.py --host 192.168.1.1 -u admin --deploy

# OR deploy via FDM web interface:
# 1. Log into FDM
# 2. Click "Deploy" button (top right)
# 3. Review changes
# 4. Click "Deploy Now"
```

**Deployment typically takes 2-5 minutes.**

### Step 6: Verify Configuration

**Check each object type in FDM:**

| Object Type     | FDM Location                             |
|-----------------|------------------------------------------|
| Network Objects | Objects > Network > Networks             |
| Network Groups  | Objects > Network > Network Groups       |
| Port Objects    | Objects > Ports > TCP Ports / UDP Ports  |
| Port Groups     | Objects > Ports > Port Groups            |
| Static Routes   | Routing > Static Routes                  |
| Access Rules    | Policies > Access Control > Access Rules |

---

## Phase 3: Cleanup (Optional)

The `ftd_api_cleanup.py` script allows you to bulk delete custom objects from FTD. This is useful for:
- Removing failed/partial imports
- Resetting FTD to clean state before re-importing
- Testing migration in lab environments

### ⚠️ WARNING

**This script DELETES ALL CUSTOM OBJECTS of selected types!**
- It does NOT use import files - it deletes EVERYTHING it finds
- Only deletes custom objects (system-defined objects are protected)
- Cannot be undone without restoring from backup
- **Always backup your FTD configuration before running**

### Cleanup Commands

#### Cleanup Commands
```bash
# Dry run - preview what would be deleted
python ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run

# Delete all custom objects (everything)
python ftd_api_cleanup.py --host IP -u admin --delete-all

# Delete specific object types
python ftd_api_cleanup.py --host IP -u admin --delete-address-objects
python ftd_api_cleanup.py --host IP -u admin --delete-address-groups
python ftd_api_cleanup.py --host IP -u admin --delete-service-objects
python ftd_api_cleanup.py --host IP -u admin --delete-service-groups
python ftd_api_cleanup.py --host IP -u admin --delete-routes
python ftd_api_cleanup.py --host IP -u admin --delete-rules

# Delete/reset interfaces
python ftd_api_cleanup.py --host IP -u admin --delete-all-interfaces
python ftd_api_cleanup.py --host IP -u admin --delete-subinterfaces
python ftd_api_cleanup.py --host IP -u admin --delete-etherchannels
python ftd_api_cleanup.py --host IP -u admin --delete-bridge-groups
python ftd_api_cleanup.py --host IP -u admin --delete-security-zones
python ftd_api_cleanup.py --host IP -u admin --reset-physical-interfaces

# Delete and deploy
python ftd_api_cleanup.py --host IP -u admin --delete-all --deploy
```

#### Delete Everything

```bash
# Delete ALL custom objects (use with extreme caution!)
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all
```

#### Delete and Deploy

```bash
# Delete and automatically deploy changes
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --deploy
```

#### Skip Confirmation Prompt

```bash
# Skip the safety confirmation (for automation)
python ftd_api_cleanup.py --host 192.168.1.1 -u admin --delete-all --yes
```

### Cleanup Options Reference

| Option                     | Description                                |
|----------------------------|--------------------------------------------|
| `--host`                   | FTD management IP (required)               |
| `-u, --username`           | FDM username (required)                    |
| `-p, --password`           | FDM password (will prompt if not provided) |
| `--dry-run`                | Preview without deleting                   |
| `--deploy`                 | Deploy changes after deletion              |
| `--debug`                  | Enable debug output                        |
| `--yes`                    | Skip confirmation prompt                   |
| `--delete-address-objects` | Delete all address objects                 |
| `--delete-address-groups`  | Delete all address groups                  |
| `--delete-service-objects` | Delete all service objects                 |
| `--delete-service-groups`  | Delete all service groups                  |
| `--delete-routes`          | Delete all static routes                   |
| `--delete-rules`           | Delete all access rules                    |
| `--delete-all`             | Delete ALL custom objects                  |

### Cleanup Deletion Order

The script deletes objects in reverse dependency order to avoid reference errors:

1. Access Rules (references everything)
2. Static Routes (references address objects)
3. Service Groups (references service objects)
4. Service Objects (TCP and UDP)
5. Address Groups (references address objects)
6. Address Objects (no dependencies)

---

## Troubleshooting

### Conversion Issues

#### Problem: Script can't find converter modules
```
ERROR: Missing converter module files!
```
**Solution:**
1. Ensure all 9 .py files are in the same directory
2. Run script from that directory
3. Check for typos in filenames

#### Problem: YAML parsing errors
```
✗ ERROR: Could not parse YAML file!
```
**Solution:**
1. Validate YAML syntax online (yamllint.com)
2. Check for tabs (YAML requires spaces)
3. Verify file encoding (should be UTF-8)

#### Problem: Many objects skipped
```
Skipped: none (name is 'none')
Skipped: 192.168.1.1 (name is just an IP address)
```
**Solution:**
These validations are intentional:
- Objects named "none" are invalid
- Object names that are just IPs are invalid
- Objects with empty values are invalid

This prevents API errors. Review original FortiGate config.

### Import Issues

#### Problem: SSL certificate errors
```
SSLError: certificate verify failed
```
**Solution:**
Script disables SSL verification by default for self-signed certs. This is normal behavior.

#### Problem: Rate limiting
```
Too many requests
```
**Solution:**
Script includes 0.2s delays between requests. If you still hit limits:
1. Increase delay in script (change `time.sleep(0.2)` to `time.sleep(0.5)`)
2. Import in smaller batches

#### Problem: Objects reference missing objects
```
Referenced network 'Unknown_Net' not found
```
**Solution:**
1. Check conversion warnings for unmatched objects
2. Create missing objects manually in FDM
3. Re-run import for dependent objects

### Deployment Issues

#### Problem: Deployment fails
```
Deployment validation failed
```
**Solution:**
1. Check FDM System > Task Status for details
2. Common issues:
   - Invalid object references
   - Overlapping routes
   - Conflicting rules
3. Fix issues in FDM and redeploy

#### Problem: Deployment stuck
**Solution:**
1. Wait 10 minutes (deployments can be slow)
2. Check FDM System > Task Status
3. If stuck >15 minutes, cancel and review logs

---

## Best Practices

### Before Migration

1. **Test in Lab First**
   - Set up identical FTD in lab
   - Run full migration
   - Test thoroughly
   - Document issues and solutions

2. **Backup Everything**
   - FortiGate configuration
   - FTD configuration
   - All generated JSON files

3. **Plan Maintenance Window**
   - Schedule adequate time (2-4 hours for medium configs)
   - Plan rollback procedure
   - Notify stakeholders

4. **Review Converted Config**
   - Check summary.json statistics
   - Review conversion warnings
   - Validate critical rules converted correctly

### During Migration

1. **Import in Phases**
   - Use step-by-step approach
   - Verify each phase before proceeding
   - Test critical paths after each phase

2. **Monitor Closely**
   - Watch for errors during import
   - Check FDM logs
   - Validate objects after creation

3. **Document Issues**
   - Note any errors
   - Track manual corrections needed
   - Record lessons learned

### After Migration

1. **Thorough Testing**
   - Test all critical traffic flows
   - Verify remote access
   - Check routing
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

### A. Command Reference

#### Conversion Commands
```bash
# Basic conversion
python fortigate_converter.py config.yaml --pretty

# Custom output name
python fortigate_converter.py config.yaml -o prod_ftd --pretty

# Help
python fortigate_converter.py --help
```

#### Import Commands
```bash
# Full import
python ftd_api_importer.py --host IP -u admin

# Selective imports
python ftd_api_importer.py --host IP -u admin --only-address-objects
python ftd_api_importer.py --host IP -u admin --only-address-groups
python ftd_api_importer.py --host IP -u admin --only-service-objects
python ftd_api_importer.py --host IP -u admin --only-service-groups
python ftd_api_importer.py --host IP -u admin --only-routes
python ftd_api_importer.py --host IP -u admin --only-rules

# Import specific file
python ftd_api_importer.py --host IP -u admin \
  --file custom.json --type address-objects

# Import and deploy
python ftd_api_importer.py --host IP -u admin --deploy

# Help
python ftd_api_importer.py --help
```

#### Cleanup Commands
```bash
# Dry run (preview)
python ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run

# Delete specific types
python ftd_api_cleanup.py --host IP -u admin --delete-address-objects
python ftd_api_cleanup.py --host IP -u admin --delete-address-groups
python ftd_api_cleanup.py --host IP -u admin --delete-service-objects
python ftd_api_cleanup.py --host IP -u admin --delete-service-groups
python ftd_api_cleanup.py --host IP -u admin --delete-routes
python ftd_api_cleanup.py --host IP -u admin --delete-rules

# Delete everything
python ftd_api_cleanup.py --host IP -u admin --delete-all

# Delete and deploy
python ftd_api_cleanup.py --host IP -u admin --delete-all --deploy

# Help
python ftd_api_cleanup.py --help
```

### B. File Formats

#### Address Object (FTD JSON)
```json
{
  "name": "Server1",
  "description": "Web Server",
  "type": "networkobject",
  "subType": "HOST",
  "value": "10.0.0.10"
}
```

#### Address Group (FTD JSON)
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

#### Port Object (FTD JSON)
```json
{
  "name": "HTTP_TCP",
  "isSystemDefined": false,
  "port": "80",
  "type": "tcpportobject"
}
```

#### Static Route (FTD JSON)
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

### C. Object Dependencies

**Import Order Matters:**

```
Security zones must be imported after interfaces but before access rules:

1. Physical Interfaces (update)
2. Subinterfaces on Physical Interfaces (create)
3. EtherChannels (create)
4. Subinterfaces on EtherChannels (create)
5. Bridge Groups (create)
6. Security Zones (create)
7. Address Objects
8. Address Groups
9. Service Objects
10. Service Groups
11. Static Routes
12. Access Rules
```

**Deletion Order (reverse of import):**
`````
1. Access Rules
2. Static Routes
3. Subinterfaces
4. EtherChannels
5. Security Zones 
6. Bridge Groups
7. Physical Interfaces (reset only - cannot delete)
8. Service Groups
9. Service Objects
10. Address Groups
11. Address Objects
`````

### D. Support and Resources

**FTD FDM API Documentation:**
- Official Cisco FDM API Guide: Search "FTD FDM REST API" on Cisco.com
- API Explorer: `https://YOUR_FTD_IP/apiexplorer/`

**Python Resources:**
- PyYAML: https://pyyaml.org/
- Requests: https://docs.python-requests.org/

**Troubleshooting Resources:**
- FDM Logs: System > Troubleshooting > Diagnostics
- System Tasks: System > Task Status
- Audit Log: System > Audit > Audit Log

---

## Quick Start Checklist
`````
□ Install Python 3.6+
□ Install libraries: pip install pyyaml requests urllib3
□ Download all 9 script files to one folder
□ Export FortiGate config as YAML
□ Backup FTD configuration
□ Run conversion: python fortigate_converter.py config.yaml --pretty
□ Review generated JSON files and summary (11 files total)
□ Test import with subset (optional but recommended)
□ Import interfaces first: python ftd_api_importer.py --host IP -u admin --only-physical-interfaces
□ Import remaining objects: python ftd_api_importer.py --host IP -u admin
□ Verify objects in FDM web interface
□ Deploy configuration
□ Test traffic flows
□ Document any issues
□ Celebrate successful migration! 🎉
`````

**Cleanup (if needed to start over):**
`````
□ Run cleanup: python ftd_api_cleanup.py --host IP -u admin --delete-all --dry-run
□ Review what will be deleted
□ Execute cleanup: python ftd_api_cleanup.py --host IP -u admin --delete-all --deploy
`````

---

**Document Version:** 1.5  
**Last Updated:** December 2025 
**Compatible With:** FTD 7.4.x with FDM