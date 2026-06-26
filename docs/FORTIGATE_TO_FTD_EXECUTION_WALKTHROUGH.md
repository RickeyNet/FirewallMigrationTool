# FortiGate to Cisco FTD - Execution Walkthrough

This document traces **exactly what runs, in what order**, when you convert a FortiGate YAML backup and import it to FTD. Use it alongside `FORTIGATE_TO_FTD_CODE_GUIDE.md` (architecture reference).

**Example command used below:**

```bash
python FortiGateToFTDTool/fortigate_converter.py fortigate_config.yaml -m ftd-3120 --pretty
python FortiGateToFTDTool/ftd_api_importer.py --host 192.168.1.1 -u admin
```

---

## How you start the code

| Path | What runs | First function |
|------|-----------|----------------|
| CLI | `python FortiGateToFTDTool/fortigate_converter.py ...` | `fortigate_converter.main()` |
| CLI | `python FortiGateToFTDTool/ftd_api_importer.py ...` | `ftd_api_importer.main()` |
| GUI | Convert tab, FortiGate to FTD | `gui_app._run_convert()` builds `argv`, then `_run_in_thread(convert_main, argv, ...)` |
| GUI | Import tab, Cisco FTD | `_run_in_thread(import_main, argv, ...)` |

The GUI does **not** use a separate code path. It calls the same `main(argv)` functions in a background thread and redirects `stdout` to the output window.

---

# Part 1: Conversion (`fortigate_converter.py`)

## Phase 1.1 - Startup and arguments

| Step | What happens | Code location |
|------|----------------|---------------|
| 1 | Python loads `fortigate_converter.py` and its imports (`AddressConverter`, `InterfaceConverter`, etc.) | Lines 64-95 |
| 2 | `main(argv)` is called (from CLI or GUI) | Line 202 |
| 3 | `argparse` parses flags: input file, `-o`, `--pretty`, `-m`, `--ha-port`, `--list-models` | Lines 229-292 |
| 4 | If `--list-models`: print model table from `FTD_MODELS`, return 0 | Lines 295-298 |
| 5 | If no input file: print error, return 1 | Lines 301-302 |

**GUI note:** For FortiGate to FTD convert, `gui_app.py` builds argv like:

```python
[input_file, "-o", full_base, "-m", model, "--ha-port", ha_or_none, "--pretty"]
```

then calls `convert_main(argv)`.

---

## Phase 1.2 - Load FortiGate YAML

| Step | What happens | Code location |
|------|----------------|---------------|
| 6 | Print banner with target model | Lines 307-310 |
| 7 | **`preprocess_yaml_file(input_file)`** - read file as text, skip problematic sections (DLP, automation) by indentation | Lines 97-156, call 319 |
| 8 | **`yaml.safe_load(cleaned_yaml)`** - parse into nested `dict` (`fg_config`) | Line 323 |
| 9 | Delete same section keys again from dict (belt and suspenders) | Lines 333-349 |
| 10 | On failure: `FileNotFoundError`, `YAMLError`, or generic error, return 1 | Lines 351-372 |

**Result:** `fg_config` is a Python dict. Keys are FortiGate section names (`system_interface`, `firewall_address`, `firewall_policy`, ...).

---

## Phase 1.3 - Create converter objects (no conversion yet)

| Step | What happens | Code location |
|------|----------------|---------------|
| 11 | `AddressConverter(fg_config)` | Line 381 |
| 12 | `AddressGroupConverter(fg_config)` | Line 382 |
| 13 | `ServiceConverter(fg_config)` | Line 385 |
| 14 | `ServiceGroupConverter(fg_config)` | Line 386 |
| 15 | `PolicyConverter(fg_config)` | Line 389 |

`RouteConverter` and `InterfaceConverter` are created later (they need results from earlier steps).

---

## Phase 1.4 - Convert interfaces (first real work)

| Step | What happens | Code location |
|------|----------------|---------------|
| 16 | `InterfaceConverter(fg_config, target_model, custom_ha_port=...)` | Lines 405-409 |
| 17 | **`interface_results = interface_converter.convert()`** | Line 410 |

### Inside `InterfaceConverter.convert()` (summary)

| Sub-step | Action |
|----------|--------|
| 17a | Read `system_interface` and `system_switch-interface` from `fg_config` |
| 17b | Categorize: physical, aggregate (EtherChannel), switch (bridge), VLAN subinterface |
| 17c | Apply target model port map (`FTD_MODELS`), reserve HA port if configured |
| 17d | Assign FortiGate interfaces to FTD `Ethernet1/X` ports |
| 17e | Build PUT payloads for physical interfaces, POST payloads for etherchannels, bridge groups, subinterfaces |
| 17f | Build security zone objects from interface assignments |
| 17g | Return dict with keys: `physical_interfaces`, `etherchannels`, `bridge_groups`, `subinterfaces`, `security_zones` |

| Step | What happens | Code location |
|------|----------------|---------------|
| 18 | **`interface_name_mapping = interface_converter.get_interface_mapping()`** | Line 413 |
| 19 | **`intf_stats = interface_converter.get_statistics()`** | Line 416 |

**Outputs kept in memory:** `interface_results`, `interface_name_mapping` (used by routes and policies).

### Optional: EtherChannel (port-channel) expansion

By default, an aggregate interface is migrated **1:1** - if the FortiGate
port-channel has one 10G member, the FTD EtherChannel gets one member. When you
are scaling up bandwidth/redundancy on the Cisco side (e.g. growing WAN and
server port-channels to several 10G links), you can ask the converter to add
extra members.

| Concept | Detail |
|---------|--------|
| Where it is configured | `InterfaceConverter.set_etherchannel_expansion(mapping)` (called from `fortigate_converter.py` right after the converter is built, before `convert()`) |
| Applied in | `_convert_aggregate_interface()` -> `_apply_etherchannel_expansion()` |
| Matching | Port-channel identifier matches the FortiGate interface name, alias, or sanitized FTD name (case-insensitive) |

Two spec forms:

- **Target total count** - `WAN_LAG=4` grows the channel to 4 total members,
  auto-assigning the extra ports from the model's free port pool (highest port
  number down).
- **Explicit ports** - `SRV_LAG=Ethernet1/5,Ethernet1/6` adds those specific FTD
  ports as members on top of the source members.

CLI (the `--expand-portchannel` flag is repeatable, parsed by
`parse_expansion_specs()`):

```
python fortigate_converter.py config.yaml -m ftd-3130 \
    --expand-portchannel "WAN_LAG=4" \
    --expand-portchannel "SRV_LAG=Ethernet1/5,Ethernet1/6"
```

GUI: the **"Expand Port-Channels (optional)"** field on the Convert tab. Enter
specs separated by `;` or newlines (e.g. `WAN_LAG=4; SRV_LAG=Ethernet1/5,Ethernet1/6`).
Blank keeps the source member count. Only the FortiGate->FTD path consumes it.

Guardrails (each emits a `[WARNING]` and skips the offending port, never aborts):
out-of-range ports for the target model, malformed ports (not `Ethernet1/X`),
ports already reserved (HA) or assigned to another interface, a count target at
or below the existing member count (no-op), and running out of free ports before
reaching the target. The Port Analysis summary prints an
`EtherChannel expansion (extra members)` line so the total-ports check stays
accurate.

> Tip: with **explicit-port** mode, avoid ports that auto-assignment gives the
> channel's original members (it fills from the highest-numbered port down).
> **Count** mode sidesteps the collision entirely - prefer it for the common
> "just give me 4x 10G" case.

### Optional: promote a physical interface to an EtherChannel

The expansion feature above only grows interfaces that are **already** aggregates
in FortiGate. If a source interface is a plain physical port but you want it to
become a port-channel on the FTD (e.g. give a single WAN or server port two 10G
links), use **promotion**.

| Concept | Detail |
|---------|--------|
| Where it is configured | `InterfaceConverter.set_etherchannel_promotion(mapping)` (called from `fortigate_converter.py` before `convert()`) |
| Applied in | `_promote_physical_to_etherchannel()`, dispatched from the Priority 4 standalone-physical loop |
| Matching | Physical-interface identifier matches the FortiGate interface name or alias (case-insensitive) |
| L3 config | The interface's name and MTU move onto the new port-channel; the original FTD port becomes member #1. The port-channel gets **no IP** - addresses belong on VLAN subinterfaces riding on the channel. A source interface with a direct IP prints a note so the IP can be placed on a subinterface |

Two spec forms (same grammar as expansion):

- **Target total count** - `wan1=2` makes a port-channel with 2 total members
  (the original port + 1 auto-assigned from the free pool).
- **Explicit ports** - `srv1=Ethernet1/6` adds those specific FTD ports as members
  alongside the original port.

CLI (`--promote-portchannel` is repeatable):

```
python fortigate_converter.py config.yaml -m ftd-3130 \
    --promote-portchannel "wan1=2" \
    --promote-portchannel "srv1=Ethernet1/6"
```

GUI: the **"Promote to Port-Channel (optional)"** field on the Convert tab; specs
separated by `;` or newlines. Blank keeps the interface as a plain physical port.

Not eligible: an interface that carries VLAN subinterfaces (the subinterfaces
would have to move onto the EtherChannel too). Such a request prints a `[WARNING]`
and the interface converts normally as a physical interface. The same out-of-range
/ malformed / already-assigned port guardrails as expansion apply, and the Port
Analysis summary prints a `Physical->EtherChannel promotion (extra members)` line.

---

## Phase 1.5 - Convert address objects

| Step | What happens | Code location |
|------|----------------|---------------|
| 20 | **`network_objects = address_converter.convert()`** | Line 435 |

### Inside `AddressConverter.convert()` (per object)

| Sub-step | Action |
|----------|--------|
| 20a | Read list `fg_config['firewall_address']` |
| 20b | For each entry `{name: properties}`: |
| 20c | Skip invalid names (e.g. `none`) |
| 20d | **`_determine_address_type(properties)`** - HOST, NETWORK, or RANGE |
| 20e | Format value (CIDR, single IP, or range string) |
| 20f | **`sanitize_name(name)`** via `common.py` |
| 20g | Append FTD dict: `{name, type: networkobject, subType, value, ...}` |
| 20h | Return full list |

---

## Phase 1.6 - Initialize route converter (convert later)

| Step | What happens | Code location |
|------|----------------|---------------|
| 21 | Build `converted_interfaces` dict from `interface_results` | Lines 446-451 |
| 22 | **`RouteConverter(fg_config, network_objects, interface_name_mapping, converted_interfaces)`** | Lines 455-461 |

Route converter is **constructed** here so it can look up addresses and interfaces, but **`route_converter.convert()` is not called until step 30**.

---

## Phase 1.7 - Convert address groups

| Step | What happens | Code location |
|------|----------------|---------------|
| 23 | **`network_groups = address_group_converter.convert()`** | Line 472 |
| 24 | Build `address_groups` set of group names for policy converter | Lines 477-479 |

### Inside `AddressGroupConverter.convert()` (summary)

- Read `firewall_addrgrp`
- **`build_group_lookup()`** and **`flatten_group_members()`** from `common.py`
- Emit FTD network group dicts with member references

---

## Phase 1.8 - Convert service objects

| Step | What happens | Code location |
|------|----------------|---------------|
| 25 | **`port_objects = service_converter.convert()`** | Line 490 |
| 26 | **`service_stats = service_converter.get_statistics()`** | Line 493 |
| 27 | **`service_name_mapping = service_converter.get_service_name_mapping()`** | Line 510 |
| 28 | Build `split_services` and `skipped_services` sets | Lines 513-524 |

### Inside `ServiceConverter.convert()` (summary)

- Read `firewall_service_custom`
- If service has **both TCP and UDP**: create two FTD objects (`name_tcp`, `name_udp`)
- If multiple ports on one protocol: may split into multiple objects
- Skip ICMP and port-less services
- Record mapping: FortiGate name to list of `(ftd_name, tcpportobject|udpportobject)`

---

## Phase 1.9 - Convert service groups

| Step | What happens | Code location |
|------|----------------|---------------|
| 29 | **`service_group_converter.set_split_services(...)`** - pass mappings from step 28 | Lines 534-538 |
| 30 | **`port_groups = service_group_converter.convert()`** | Line 541 |
| 31 | Build `service_groups` set for policy converter | Lines 546-548 |

---

## Phase 1.10 - Convert firewall policies to access rules

| Step | What happens | Code location |
|------|----------------|---------------|
| 32 | **`policy_converter.set_split_services(...)`** - inject address groups, service groups, interface mapping | Lines 558-565 |
| 33 | **`access_rules = policy_converter.convert()`** | Line 568 |
| 34 | **`policy_stats = policy_converter.get_statistics()`** | Line 571 |

### Inside `PolicyConverter.convert()` (per policy)

| Sub-step | Action |
|----------|--------|
| 34a | Read `firewall_policy` from `fg_config` |
| 34b | Map `srcintf` / `dstintf` to FTD security zones (via interface mapping) |
| 34c | Map `srcaddr` / `dstaddr` to network object references |
| 34d | Map `service` to port object references (using split service mapping) |
| 34e | Map `accept` to `PERMIT`, `deny` to `DENY` |
| 34f | Assign sequential `ruleId` |
| 34g | Append FTD `accessrule` dict |

---

## Phase 1.11 - Convert static routes (last converter)

| Step | What happens | Code location |
|------|----------------|---------------|
| 35 | **`static_routes = route_converter.convert()`** | Line 584 |
| 36 | **`route_stats = route_converter.get_statistics()`** | Line 587 |

### Inside `RouteConverter.convert()` (summary)

- Read `router static` (or equivalent section) from `fg_config`
- Resolve gateway and destination using `network_objects` and `interface_name_mapping`
- Skip blackhole and unmappable routes
- May add **`generated_network_objects`** (extra address objects for gateways) merged into address output at write time

---

## Phase 1.12 - Write JSON files to disk

| Step | What happens | Code location |
|------|----------------|---------------|
| 37 | **`build_conversion_metadata(args)`** then write `{output}_metadata.json` | Lines 625-628 |
| 38 | Merge any route-generated address objects into `network_objects` | Lines 631-639 |
| 39 | **`write_json_file()`** for each output (13 files) | Lines 642-673 |
| 40 | Build **`summary` dict** with stats and `conversion_failures` | Lines 693-726 |
| 41 | Write `{output}_summary.json` | Line 727 |
| 42 | Print final summary and import order hint, **return 0** | Lines 740-774 |

**Files on disk (default base `ftd_config`):**

```
ftd_config_metadata.json
ftd_config_physical_interfaces.json
ftd_config_subinterfaces.json
ftd_config_etherchannels.json
ftd_config_bridge_groups.json
ftd_config_security_zones.json
ftd_config_address_objects.json
ftd_config_address_groups.json
ftd_config_service_objects.json
ftd_config_service_groups.json
ftd_config_static_routes.json
ftd_config_access_rules.json
ftd_config_summary.json
```

Conversion phase **ends**. No network traffic to FTD yet.

---

# Part 2: Import (`ftd_api_importer.py`)

## Phase 2.1 - Startup and arguments

| Step | What happens | Code location |
|------|----------------|---------------|
| 1 | `main(argv)` called | ~line 3038 |
| 2 | Parse `--host`, `-u`, `-p`, `--base`, `--deploy`, `--only-*`, `--workers`, etc. | ~3060-3129 |
| 3 | If password omitted: **`getpass.getpass()`** prompt | Lines 3137-3139 |
| 4 | **`FTDAPIClient(host, username, password, verify_ssl=...)`** | Lines 3142-3148 |

---

## Phase 2.2 - Metadata and authentication

| Step | What happens | Code location |
|------|----------------|---------------|
| 5 | Load metadata: `--metadata-file` or auto `{base}_metadata.json` | Lines 3187-3193 |
| 6 | Set **`client.appliance_model`** from metadata `target_model` | Lines 3196-3200 |
| 7 | **`client.authenticate()`** | Line 3213 |

### Inside `FTDBaseClient.authenticate()`

| Sub-step | Action |
|----------|--------|
| 7a | POST `https://{host}/api/fdm/latest/fdm/token` with username/password |
| 7b | Store `access_token` and `refresh_token` |
| 7c | Set session header `Authorization: Bearer ...` |
| 7d | On 401 later: **`_auto_refresh_hook`** refreshes token and retries once |

| Step | What happens | Code location |
|------|----------------|---------------|
| 8 | If `--validate-only`: probe endpoints, exit | Lines 3217-3220 |
| 9 | **`client.populate_physical_interface_cache()`** - GET existing physical interfaces | Line 3223 |

---

## Phase 2.3 - Choose import mode

Three modes (mutually exclusive):

| Mode | Condition | Behavior |
|------|-----------|----------|
| Single file | `--file` + `--type` | One JSON file, one import function |
| Selective | any `--only-*` flag | Named categories only |
| Full | default | All 12 steps below |

---

## Phase 2.4 - Full import sequence (default)

Each step: load JSON, loop objects, call API, update stats. Steps wrapped in **`record_phase()`** for timing.

| Step | Function called | JSON file | API style |
|------|-----------------|-----------|-----------|
| 10 | `import_physical_interfaces()` | `{base}_physical_interfaces.json` | PUT (update existing) |
| 11 | `import_subinterfaces(..., parent_type_filter='physical')` | `{base}_subinterfaces.json` | POST |
| 12 | `import_etherchannels()` | `{base}_etherchannels.json` | POST |
| 13 | `import_subinterfaces(..., parent_type_filter='etherchannel')` | `{base}_subinterfaces.json` | POST |
| 14 | `import_bridge_groups()` | `{base}_bridge_groups.json` | POST |
| 15 | `import_security_zones()` | `{base}_security_zones.json` | POST |
| 16 | `import_address_objects(..., workers=N)` | `{base}_address_objects.json` | POST/PUT, **parallel** |
| 17 | `import_address_groups()` | `{base}_address_groups.json` | POST/PUT, sequential |
| 18 | `import_service_objects(..., workers=N)` | `{base}_service_objects.json` | POST/PUT, **parallel** |
| 19 | `import_service_groups()` | `{base}_service_groups.json` | POST/PUT, sequential |
| 20 | `import_static_routes()` | `{base}_static_routes.json` | POST/PUT, sequential |
| 21 | `import_access_rules()` | `{base}_access_rules.json` | POST/PUT, sequential |

Code: lines 3345-3379.

---

## Phase 2.5 - What happens for one address object (representative)

Trace for **`import_address_objects()`** then **`client.create_network_object(obj)`**:

| Sub-step | Action |
|----------|--------|
| A | **`load_json_file(filename)`** - read JSON array |
| B | For each object, worker thread runs **`run_with_retry(lambda: client.create_network_object(obj))`** |
| C | **`create_network_object`** calls **`_create_api_object(/object/networks, ...)`** |
| D | GET collection filtered by name - object exists? |
| E | If exists and identical payload: return **`SKIPPED`** |
| F | If exists and different: **`_update_existing_object()`** - PUT with merged id/version |
| G | If not exists: POST to create |
| H | On transient error (429, 503): **`run_with_retry`** backs off and retries |
| I | **`record_stat()`** - increment created/updated/skipped/failed |
| J | Print line: `[3/48] Creating: Server1... OK` |

Service objects follow the same pattern but POST to `/object/tcpports` or `/object/udpports`.

Static routes and access rules add **`resolve_*_references()`** steps to attach FTD internal IDs to named references before POST/PUT.

---

## Phase 2.6 - Finish import

| Step | What happens | Code location |
|------|----------------|---------------|
| 22 | Print timing summary per phase | Lines 3381-3394 |
| 23 | **`client.print_statistics()`** | Line 3399 |
| 24 | **`client.print_failure_summary()`** | Line 3402 |
| 25 | Write `{base}_failed_imports.json` if any failures | Lines 3403-3412 |
| 26 | If `--deploy`: **`client.deploy_changes()`** | Lines 3415-3416 |
| 27 | Else: remind user to deploy in FDM UI | Lines 3417-3423 |
| 28 | **`client.compute_outcome()`**, optional `--json-report`, return exit code | Lines 3425-3458 |

Import phase **ends**. Configuration exists on FTD but may still be **pending deploy** until FDM deploys changes.

---

# Part 3: Cleanup (`ftd_api_cleanup.py`) - optional

Short trace when you run cleanup:

| Step | Action |
|------|--------|
| 1 | `main(argv)` - parse `--delete-*`, `--dry-run`, `--deploy` |
| 2 | **`FTDBulkDelete`** extends same **`FTDBaseClient`** |
| 3 | **`authenticate()`** |
| 4 | Delete in reverse dependency order (rules first, objects last) |
| 5 | Optional **`deploy_changes()`** |

GUI requires cleanup password from **`cleanup_auth.verify_password()`** before calling `cleanup_main(argv)`.

---

# Quick reference: conversion call order

```
main()
  preprocess_yaml_file()
  yaml.safe_load()
  AddressConverter.__init__
  AddressGroupConverter.__init__
  ServiceConverter.__init__
  ServiceGroupConverter.__init__
  PolicyConverter.__init__
  InterfaceConverter.__init__
  InterfaceConverter.convert()          # 1
  AddressConverter.convert()            # 2
  RouteConverter.__init__               # init only
  AddressGroupConverter.convert()       # 3
  ServiceConverter.convert()            # 4
  ServiceGroupConverter.set_split_services + convert()  # 5
  PolicyConverter.set_split_services + convert()        # 6
  RouteConverter.convert()              # 7
  build_conversion_metadata()
  write_json_file() x13
  return 0
```

---

# Quick reference: full import call order

```
main()
  FTDAPIClient.__init__
  authenticate()
  populate_physical_interface_cache()
  import_physical_interfaces()
  import_subinterfaces(physical)
  import_etherchannels()
  import_subinterfaces(etherchannel)
  import_bridge_groups()
  import_security_zones()
  import_address_objects()      # threaded
  import_address_groups()
  import_service_objects()      # threaded
  import_service_groups()
  import_static_routes()
  import_access_rules()
  print_statistics()
  deploy_changes()              # if --deploy
  return exit_code
```

---

# Related files

| Document | Purpose |
|----------|---------|
| `FORTIGATE_TO_FTD_CODE_GUIDE.md` | Module roles, class reference, diagrams |
| `fortigate_to_ftd_flow.html` | Browser-rendered pipeline diagram |
| `README.md` | Operator commands and prerequisites |
