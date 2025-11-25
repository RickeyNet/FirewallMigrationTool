# Fortinet-to-Cisco-firewall-config-tool
# FortiGate to Cisco FTD Migration Tool - Complete User Guide

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [File Structure](#file-structure)
5. [Phase 1: Converting FortiGate Configuration](#phase-1-converting-fortigate-configuration)
6. [Phase 2: Importing to FTD](#phase-2-importing-to-ftd)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)
9. [Appendix](#appendix)

---

## Overview

This toolset converts FortiGate firewall configurations to Cisco FTD (Firepower Threat Defense) format and imports them via the FDM (Firewall Device Manager) API.

**What gets converted:**
- ✅ Address Objects (network objects)
- ✅ Address Groups (network groups)
- ✅ Service Port Objects (TCP/UDP ports)
- ✅ Service Port Groups (port groups)
- ✅ Static Routes
- ✅ Firewall Policies (access rules)

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

---
#########################################################################################################
## For Airgapped networks

## Download required libraries from internet connected device using:
```bash
pip install pyyaml requests urllib3
```
# Test that Python can find the libraries:

```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

# Create a directory for the packages
mkdir ftd_migration_packages
cd ftd_migration_packages

# Download packages and their dependencies
pip download pyyaml requests urllib3

# This will download files like:
# - PyYAML-6.0.1-cp39-cp39-win_amd64.whl
# - requests-2.31.0-py3-none-any.whl
# - urllib3-2.0.7-py3-none-any.whl
# - certifi-2023.7.22-py3-none-any.whl (dependency)
# - charset-normalizer-3.3.2-cp39-cp39-win_amd64.whl (dependency)
# - idna-3.4-py3-none-any.whl (dependency)

!!!!!!!!!!!!! Airgapped side starting point:
## Move package folder and all scripts, including python 3.14 if not already installed, to airgapped machine
install python and select add to path on installer
check if C:\Program Files\python314 and C:\Program Files\python314\Scripts is added to path.
 ```bash
    echo %path%
```
# Option 2:
go to enviromental variables and add both to path manually "This may require a reboot or a logout and log back in"

# Test to see if python is there with powershell or command prompt:
```bash
python
#If installed it will display 
Python 3.14.0
>>>
#Then type exit
```

### Next:
## Navigate to the directory with the packages
cd path\to\your\package\folder
# Enter following command:
```bash
python -m pip install --no-index --find-links=. pyyaml requests urllib3
```

# Test that Python can find the libraries:
```bash
python -c "import yaml, requests, urllib3; print('All libraries installed!')"
```

#########################################################################################################
## Installation

### Step 1: Download All Script Files

Create a working directory and save all 8 Python files:

```
FortiGate-FTD-Migration/
├── fortigate_converter.py          # Main conversion script
├── address_converter.py            # Converts address objects
├── address_group_converter.py      # Converts address groups
├── service_converter.py            # Converts service objects
├── service_group_converter.py      # Converts service groups
├── policy_converter.py             # Converts firewall policies
├── route_converter.py              # Converts static routes
└── ftd_api_importer.py            # FTD API import script
```

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

## File Structure

### Your Working Directory Should Look Like:

```
FortiGate-FTD-Migration/
├── fortigate_converter.py          # Main converter
├── address_converter.py            # Module
├── address_group_converter.py      # Module
├── service_converter.py            # Module
├── service_group_converter.py      # Module
├── policy_converter.py             # Module
├── route_converter.py              # Module
├── ftd_api_importer.py            # API importer
├── fortigate_config.yaml          # Your FortiGate YAML (input)
└── ftd_config_*.json              # Generated FTD JSON files (output)
```

---

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

The script creates **7 JSON files**:

1. **`ftd_config_address_objects.json`**
   - Network objects (individual IPs, subnets)
   
2. **`ftd_config_address_groups.json`**
   - Network groups (collections of addresses)
   
3. **`ftd_config_service_objects.json`**
   - Port objects (TCP/UDP services)
   - Note: Services with both TCP and UDP are split into separate objects
   
4. **`ftd_config_service_groups.json`**
   - Port groups (collections of services)
   
5. **`ftd_config_static_routes.json`**
   - Static routes
   
6. **`ftd_config_access_rules.json`**
   - Firewall access rules (policies)
   
7. **`ftd_config_summary.json`**
   - Conversion statistics and summary

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

**Review console output:**
Look for any warnings or skipped objects:
```
Converting Address Objects...
------------------------------------------------------------
  Converted: Bull_net -> NETWORK (10.0.20.0/24)
  Skipped: none (name is 'none')
  Skipped: 192.168.1.1 (name is just an IP address)
  Warning: No address object found for 10.0.50.0/24
```

### Common Conversion Issues

**Issue 1: Objects with empty values**
```
Skipped: Empty_Object (empty value)
```
**Solution:** These are automatically skipped. Review original FortiGate config.

**Issue 2: Services split into TCP and UDP**
```
Split: DNS -> DNS_TCP and DNS_UDP
```
**Solution:** Normal behavior. FTD requires separate TCP and UDP objects.

**Issue 3: Unmatched routes**
```
Warning: No address object found for gateway 10.0.1.1
```
**Solution:** Create the missing address object before importing routes.

---

## Phase 2: Importing to FTD

### Before You Begin

**⚠️ CRITICAL: Backup Your FTD Configuration**

1. Log into FDM web interface
2. Navigate to **System > Backup**
3. Create a full backup
4. Download and save the backup file

### Step 1: Test Connectivity

**Verify you can reach FTD:**
```bash
# Test connectivity
ping 192.168.1.1

# Test HTTPS access (should see certificate error - this is normal)
curl -k https://192.168.1.1
```

### Step 2: Import Options

You have **4 import strategies**:

#### **Option A: All-at-Once Import (Fastest)**

Import everything in one run:

```bash
python ftd_api_importer.py --host 192.168.1.1 --username admin --deploy
```

**Pros:** Fast, simple
**Cons:** Harder to troubleshoot if errors occur
**Best for:** Small configs, lab environments

---

#### **Option B: Step-by-Step Import (Recommended for Production)**

Import one type at a time, verify each step:

```bash
# Step 1: Import address objects
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-objects
# ✓ Verify in FDM web interface: Objects > Network

# Step 2: Import address groups
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-address-groups
# ✓ Verify in FDM web interface: Objects > Network

# Step 3: Import service objects
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-objects
# ✓ Verify in FDM web interface: Objects > Ports

# Step 4: Import service groups
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-service-groups
# ✓ Verify in FDM web interface: Objects > Ports

# Step 5: Import static routes
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-routes
# ✓ Verify in FDM web interface: Routing > Static Routes

# Step 6: Import access rules
python ftd_api_importer.py --host 192.168.1.1 -u admin --only-rules
# ✓ Verify in FDM web interface: Policies > Access Control

# Step 7: Deploy all changes
python ftd_api_importer.py --host 192.168.1.1 -u admin --deploy
```

**Pros:** Maximum control, easy to troubleshoot
**Cons:** More time-consuming
**Best for:** Production environments, large configs

---

#### **Option C: Batch Import (Balanced)**

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

#### **Option D: Test Subset First**

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

**Symbol Legend:**
- ✓ = Successfully created
- ⊘ = Already exists (skipped, not an error)
- ✗ = Failed (see error message)

### Step 4: Handle Import Errors

**Common errors and solutions:**

#### Error: "Object already exists"
```
[5/50] Creating: Server1... ⊘ (already exists)
```
**Solution:** This is NORMAL. Object already exists in FTD. Script continues automatically.

#### Error: "Authentication failed"
```
✗ Authentication failed: 401
```
**Solution:** 
1. Verify username and password
2. Check FDM is accessible at the IP
3. Ensure account has admin privileges

#### Error: "Invalid reference"
```
✗ Referenced object 'Gateway_10_0_1_1' not found
```
**Solution:**
1. Import address objects before routes/rules
2. Check that referenced objects exist in FTD
3. Review conversion warnings for unmatched objects

#### Error: "Connection timeout"
```
✗ Connection error: ReadTimeout
```
**Solution:**
1. Check network connectivity
2. Increase timeout (modify script if needed)
3. FDM might be busy - wait and retry

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

**Deployment takes 2-5 minutes typically.**

### Step 6: Verify Configuration

**Check each object type in FDM:**

1. **Network Objects:** Objects > Network > Networks
2. **Network Groups:** Objects > Network > Network Groups
3. **Port Objects:** Objects > Ports > TCP Ports / UDP Ports
4. **Port Groups:** Objects > Ports > Port Groups
5. **Static Routes:** Routing > Static Routes
6. **Access Rules:** Policies > Access Control > Access Rules

**Sample verification checklist:**

```
□ All address objects imported
□ All address groups imported
□ All service objects imported
□ All service groups imported
□ All static routes imported
□ All access rules imported
□ Configuration deployed successfully
□ No unexpected errors in FDM
□ Sample traffic tests pass
```

---

## Troubleshooting

### Conversion Issues

#### Problem: Script can't find converter modules
```
ERROR: Missing converter module files!
```
**Solution:**
1. Ensure all 8 .py files are in the same directory
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
Script disables SSL verification by default for self-signed certs. If you still see this error:
```python
# The script should have this line:
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

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

**1. Test in Lab First**
- Set up identical FTD in lab
- Run full migration
- Test thoroughly
- Document issues and solutions

**2. Backup Everything**
- FortiGate configuration
- FTD configuration
- All generated JSON files

**3. Plan Maintenance Window**
- Schedule adequate time (2-4 hours for medium configs)
- Plan rollback procedure
- Notify stakeholders

**4. Review Converted Config**
- Check summary.json statistics
- Review conversion warnings
- Validate critical rules converted correctly

### During Migration

**1. Import in Phases**
- Use step-by-step approach
- Verify each phase before proceeding
- Test critical paths after each phase

**2. Monitor Closely**
- Watch for errors during import
- Check FDM logs
- Validate objects after creation

**3. Document Issues**
- Note any errors
- Track manual corrections needed
- Record lessons learned

### After Migration

**1. Thorough Testing**
- Test all critical traffic flows
- Verify remote access
- Check routing
- Validate NAT rules
- Test logging

**2. Monitor Performance**
- Check CPU/memory usage
- Monitor connection counts
- Review logs for errors

**3. Update Documentation**
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

### B. File Formats

#### Address Object (FTD JSON)
```json
{
  "name": "Server1",
  "description": "Web Server",
  "type": "networkobject",
  "subType": "HOST",
  "value": "10.0.0.10/32"
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
1. Address Objects (no dependencies)
   ↓
2. Address Groups (references Address Objects)
   ↓
3. Service Objects (no dependencies)
   ↓
4. Service Groups (references Service Objects)
   ↓
5. Static Routes (references Address Objects)
   ↓
6. Access Rules (references everything above)
```

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

```
□ Install Python 3.6+
□ Install libraries: pip install pyyaml requests urllib3
□ Download all 8 script files to one folder
□ Export FortiGate config as YAML
□ Backup FTD configuration
□ Run conversion: python fortigate_converter.py config.yaml --pretty
□ Review generated JSON files and summary
□ Test import with subset (optional but recommended)
□ Import to FTD: python ftd_api_importer.py --host IP -u admin
□ Verify objects in FDM web interface
□ Deploy configuration
□ Test traffic flows
□ Document any issues
□ Celebrate successful migration! 🎉
```

---

**Document Version:** 1.0  
**Last Updated:** November 2024  
**Compatible With:** FTD 7.4.x with FDM