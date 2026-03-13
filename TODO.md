# FortiGate to Cisco FTD Tool - Improvement TODO

This checklist tracks technical debt, performance hardening, and usability improvements.

## Legend
- [ ] Not started
- [~] In progress
- [x] Completed

---

## P0: Stability and Correctness

- [x] Centralize retry/backoff + worker logic
  - Scope: Extract shared helper for thread pool execution, retry policy, transient-error detection.
  - Done: `FortiGateToFTDTool/concurrency_utils.py` added and wired into importer/cleanup threaded paths.
  - Benefit: Less duplication, easier tuning, fewer regressions.

- [x] Add regression tests for threaded paths
  - Done:
    - `import_address_objects` retry/stat behavior
    - `import_service_objects` retry/stat behavior
    - `delete_all_custom_objects` retry/stat behavior
    - `delete_all_static_routes` retry/stat behavior
    - explicit 503 retry case
    - hard-failure case (max attempts exhausted) assertions
    - `run_with_retry` transient retry behavior
  - Benefit: Prevent silent regressions in concurrency refactors.

- [x] Tighten exception handling and typing in importer
  - Scope: Replace broad `except Exception` and reduce `# pyright: ignore` in `ftd_api_importer.py`.
  - Done:
    - Added `_extract_error_message` helper for safer API error parsing.
    - Tightened exception handling in `get_interface_by_hardware_name`, `get_physical_interface`, `update_physical_interface`, and `create_subinterface`.
    - Added explicit type guards (`isinstance(..., dict)`) at interface lookup call sites.
    - Updated return typing contracts for interface lookup helpers to match runtime behavior.
    - Hardened adjacent interface paths (`get_interface_by_name`, `_get_etherchannel_by_hardware`, `create_etherchannel`, `create_bridge_group`, `create_security_zone`) with stricter type guards and safer error parsing.
    - Replaced broad importer exception handlers in cache/lookup and metadata-loading paths with explicit exception sets.
    - Removed importer `# pyright: ignore` suppressions and validated clean diagnostics.
  - Focus first on:
    - `get_interface_by_hardware_name`
    - `get_physical_interface`
    - `update_physical_interface`
    - `create_subinterface`
  - Acceptance:
    - Narrow exception types (`requests.exceptions.RequestException`, `ValueError`, etc.)
    - Consistent typed return contracts
    - Fewer Pyright suppressions

- [x] Fix bare `except:` clauses in cleanup script
  - Done: Replaced bare `except:` in `delete_object()` with `except (ValueError, KeyError, IndexError, TypeError):`.

- [x] Fix thread-safety bug in `create_port_object`
  - Done: Replaced direct `self.stats[key] += 1` with `self.record_stat(key)` in
    `create_port_object()`, `create_static_route()`, and `create_access_rule()`.

- [x] Fix `AddressConverter.get_object_count()` returning stale data
  - Done: Added `self.ftd_network_objects = network_objects` before the return in `convert()`.

- [x] Handle FQDN address type in address converter
  - Done: Added FQDN detection in `_determine_address_type()` and `_extract_address_value()`.
    FQDN objects now produce `subType: "FQDN"` with the domain as value.
    IP validation is skipped for FQDN types.

---

## P1: Consistency and Maintainability

- [x] Normalize interface/media model logic
  - Scope: Move model family sets (`ftd_1000_series`, `ftd_3100_series`, etc.) to one shared module.
  - Candidate file: `FortiGateToFTDTool/platform_profiles.py`
  - Done:
    - Added shared model-family module: `FortiGateToFTDTool/platform_profiles.py`.
    - Replaced duplicated inline model sets in importer with `is_ftd_1000(...)` and `is_ftd_3100(...)` helpers.
    - Replaced duplicated inline model sets in cleanup with shared helpers.
  - Acceptance:
    - Single source of truth for model families
    - Importer and cleanup use shared constants/helpers
  - Benefit: Fewer drift bugs when tweaking platform behavior.

- [~] Standardize operator UX/logging
  - Scope:
    - Normalize statuses to `OK | SKIP | FAIL`
    - Ensure threaded progress output flushes consistently
    - Optional `--verbose` levels
    - Optional `--json-report <path>`
  - Done:
    - Standardized many importer/cleanup action outcomes to `[OK] | [SKIP] | [FAIL]`.
    - Added `flush=True` to threaded progress prints for more reliable live output.
    - Added `--json-report` to both importer and cleanup CLIs with machine-readable summaries.
    - Fixed `import_access_rules` `[Success!]` -> `[OK]`.
    - Fixed `authenticate()` `FAIL` -> `[FAIL]` with brackets.
  - Remaining:
    - Add configurable `--verbose` levels and gate non-essential output by verbosity.
  - Acceptance:
    - Consistent message format across importer/cleanup
    - Machine-readable summary output option

- [x] README operational docs refresh
  - Done: Performance/concurrency section, `--workers` guidance, API rate-limit troubleshooting.

- [ ] Extract shared API base class for importer and cleanup
  - Scope: `FTDAPIClient` and `FTDBulkDelete` share substantial duplicated code:
    - `authenticate()` (~40 lines, identical)
    - `get_default_virtual_router_id()` (~25 lines, identical)
    - `validate_endpoints()` (~40 lines, identical)
    - `compute_outcome()` (similar logic)
  - Fix: Create `FTDBaseClient` in a shared module (e.g., `ftd_api_base.py`) with these methods,
    then have both `FTDAPIClient` and `FTDBulkDelete` inherit from it.
  - Benefit: Single point of change for auth, endpoint validation, and VR discovery.

- [ ] Use `write_json_file()` helper consistently in converter
  - Location: `fortigate_converter.py` lines 666-814
  - Issue: The `write_json_file()` helper exists at line 183 but is only used once (for metadata).
    The remaining 11 JSON writes repeat the `if args.pretty / json.dump` pattern inline.
  - Fix: Replace all inline `json.dump` blocks with `write_json_file(path, data, args.pretty)`.
  - Benefit: ~100 lines removed, single place to change JSON output behavior.

- [ ] Extract duplicated group-flattening logic to a shared base or utility
  - Location: `address_group_converter.py` and `service_group_converter.py`
  - Issue: `_build_group_lookup()`, `_is_group()`, and `_flatten_members()` are near-identical
    (copy-pasted) between both modules.
  - Fix: Extract to a `GroupFlatteningMixin` or shared function in `common.py`.
  - Benefit: Single implementation to maintain and test.

- [ ] Extract duplicated API create/error pattern in importer
  - Location: `ftd_api_importer.py`
  - Issue: `create_network_object`, `create_network_group`, `create_port_object`, `create_port_group`,
    `create_access_rule`, `create_static_route` all repeat the same ~30-line pattern:
    POST -> check 200/201 -> check 422 duplicate -> record stat -> handle error.
  - Fix: Extract a generic `_create_api_object(endpoint, payload, stat_prefix)` method.
  - Benefit: ~150 lines removed, consistent error handling, easier to add new object types.

- [x] Remove large commented-out block in converter
  - Done: Deleted 35-line commented-out "Method 1 vs Method 2" block from `fortigate_converter.py`.

- [x] Remove `_validate_group()` dead code
  - Done: Deleted unused `_validate_group()` method from `address_group_converter.py`.

- [x] Clean up remaining `# pyright: ignore` suppressions in converters
  - Done: Replaced `param: Set[str] = None` with `param: Optional[Set[str]] = None` and
    added `Optional` to imports in `address_group_converter.py`, `service_group_converter.py`,
    `policy_converter.py`, and removed the suppression in `fortigate_converter.py`.

- [x] Fix step-number comment drift in importer
  - Done: Renumbered import step comments in `ftd_api_importer.py` from 5-10 to 7-12 to match
    the printed step list.

---

## P2: Additional Improvements (Recommended)

- [x] Add idempotency summary and exit codes
  - Done: Exit codes 0/1/2/3, `compute_outcome()`, JSON report fields.

- [x] Add lightweight integration smoke mode
  - Done: `--validate-only` for both importer and cleanup.

- [x] Add configurable retry policy flags
  - Done: Added `--max-attempts`, `--base-backoff`, `--max-jitter` to both importer and cleanup CLIs.
    Threaded through to `run_with_retry()` calls in all threaded import/delete paths.

- [x] Add timing per phase to final report (cleanup)
  - Done: Added `record_phase()` to cleanup `main()` with per-phase timing summary and
    `phase_timings`/`total_seconds` fields in JSON report output.

- [x] Add tests for concurrency helper edge cases
  - Done: Added 3 edge-case tests in `tests/test_concurrency_refactor.py`:
    - `test_run_with_retry_max_attempts_one` (no retry)
    - `test_run_with_retry_non_retryable_fails_immediately` (400 fails on first attempt)
    - `test_run_indexed_thread_pool_empty_list` (completes without error)

- [ ] Add pre-commit quality checks
  - Suggested: `ruff` (or `flake8`) + `black` + `pytest`.
  - Benefit: Catch style/type/test issues before commit.

- [x] Add `requirements.txt` or `pyproject.toml`
  - Done: Created `requirements.txt` with `pyyaml>=6.0`, `requests>=2.28.0`, `urllib3>=1.26.0`.

- [x] Add `__init__.py` to make `FortiGateToFTDTool` a proper package
  - Done: Added `FortiGateToFTDTool/__init__.py`.

- [x] Make hardcoded sleep delays configurable
  - Done: Added `--delay` CLI flag (default 0.2) to both importer and cleanup.
    All sequential import/cleanup functions accept a `delay` parameter.
    Cleanup etherchannels/bridge groups default to 0.3 for HA-related operations.

- [x] Add exception propagation to `run_indexed_thread_pool`
  - Done: Collected futures and called `.result()` via `as_completed()` to propagate
    unhandled worker exceptions.

- [x] Validate `--workers` CLI argument range
  - Done: Added `_positive_int` type validator (1-32) to `--workers` in both
    `ftd_api_importer.py` and `ftd_api_cleanup.py`.

- [x] Fix FTD-3105 model port count inconsistency
  - Done: Verified `total_ports: 16` is correct (8 RJ45 + 8 SFP = 16 data ports).
    No code change needed — the original values were accurate.

- [x] Remove unnecessary defensive guard in converter
  - Done: Replaced verbose `args.debug if 'args' in locals() ...` with `getattr(args, 'debug', False)`.

---

## P3: Test Coverage Expansion

- [ ] Add unit tests for address converter
  - Scope: Test HOST/NETWORK/RANGE/FQDN detection, netmask-to-CIDR conversion,
    IP-address-name filtering, name sanitization edge cases.
  - Priority: Medium - converter logic is core to correctness.

- [ ] Add unit tests for service converter
  - Scope: Test TCP/UDP splitting, multi-port expansion, ICMP skipping,
    FTD built-in name collision handling, colon-separated port parsing.
  - Priority: Medium - split logic is complex and error-prone.

- [ ] Add unit tests for policy converter
  - Scope: Test action mapping, zone lookup strategies, service expansion,
    address group type detection, "any"/"all" filtering.
  - Priority: Medium - policy conversion involves multiple lookup strategies.

- [ ] Add unit tests for interface converter
  - Scope: Test physical/aggregate/switch/VLAN detection, port mapping per model,
    HA port exclusion, name sanitization, security zone generation.
  - Priority: Medium - model-specific logic needs coverage.

- [ ] Add unit tests for group flattening (address & service groups)
  - Scope: Test circular reference detection, deep nesting, duplicate removal,
    single-member normalization, empty group handling.
  - Priority: Low - logic is straightforward but edge cases matter.

- [ ] Add integration-style test for `fortigate_converter.py` main()
  - Scope: Feed a small YAML config through `main()` and verify all 13 JSON output files
    are created with correct structure.
  - Priority: Low - would catch regressions in the orchestration layer.
