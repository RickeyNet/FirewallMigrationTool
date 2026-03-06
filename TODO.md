# FortiGate to Cisco FTD Tool - Improvement TODO

This checklist tracks technical debt, performance hardening, and usability improvements.

## Legend
- [ ] Not started
- [~] In progress
- [x] Completed

## P0: Stability and Correctness

- [x] Centralize retry/backoff + worker logic
  - Scope: Extract shared helper for thread pool execution, retry policy, transient-error detection.
  - Done: `FortiGateToFTDTool/concurrency_utils.py` added and wired into importer/cleanup threaded paths.
  - Benefit: Less duplication, easier tuning, fewer regressions.

- [~] Add regression tests for threaded paths
  - Done:
    - `import_address_objects` retry/stat behavior
    - `delete_all_custom_objects` retry/stat behavior
    - `run_with_retry` transient retry behavior
  - Remaining:
    - `import_service_objects`
    - `delete_all_static_routes`
    - explicit 503 retry case
    - hard-failure case (max attempts exhausted) assertions
  - Benefit: Prevent silent regressions in concurrency refactors.

- [ ] Tighten exception handling and typing in importer
  - Scope: Replace broad `except Exception` and reduce `# pyright: ignore` in `ftd_api_importer.py`.
  - Focus first on:
    - `get_interface_by_hardware_name`
    - `get_physical_interface`
    - `update_physical_interface`
    - `create_subinterface`
  - Acceptance:
    - Narrow exception types (`requests.exceptions.RequestException`, `ValueError`, etc.)
    - Consistent typed return contracts
    - Fewer Pyright suppressions

## P1: Consistency and Maintainability

- [ ] Normalize interface/media model logic
  - Scope: Move model family sets (`ftd_1000_series`, `ftd_3100_series`, etc.) to one shared module.
  - Candidate file: `FortiGateToFTDTool/platform_profiles.py`
  - Acceptance:
    - Single source of truth for model families
    - Importer and cleanup use shared constants/helpers
  - Benefit: Fewer drift bugs when tweaking platform behavior.

- [ ] Standardize operator UX/logging
  - Scope:
    - Normalize statuses to `OK | SKIP | FAIL`
    - Ensure threaded progress output flushes consistently
    - Optional `--verbose` levels
    - Optional `--json-report <path>`
  - Acceptance:
    - Consistent message format across importer/cleanup
    - Machine-readable summary output option

- [ ] README operational docs refresh
  - Scope:
    - Document what is multithreaded vs sequential in importer and cleanup
    - Add `--workers` guidance and safe defaults
    - Add API rate-limit troubleshooting tips (429/503)
  - Acceptance:
    - New "Performance and Concurrency" section in `README.md`
    - Examples for common import/cleanup modes

## P2: Additional Improvements (Recommended)

- [ ] Add idempotency summary and exit codes
  - Goal: Distinguish outcomes (all success / partial failure / fatal error) with stable exit codes.
  - Benefit: Better automation in CI/CD and scripts.

- [ ] Add lightweight integration smoke mode
  - Goal: `--validate-only` option that authenticates, checks required endpoints, and prints capability checks.
  - Benefit: Fast preflight before a long import/cleanup run.

- [ ] Add configurable retry policy flags
  - Scope: `--max-attempts`, `--base-backoff`, optional jitter range.
  - Benefit: Easier tuning for different appliance loads.

- [ ] Add timing per phase to final report
  - Goal: Record duration for each import/cleanup phase and total runtime.
  - Benefit: Makes optimization work measurable.

- [ ] Add tests for concurrency helper edge cases
  - Cases:
    - `max_attempts=1` (no retry)
    - non-retryable error string
    - empty item list thread pool behavior

- [ ] Add pre-commit quality checks
  - Suggested: `ruff` (or `flake8`) + `black` + `pytest`.
  - Benefit: Catch style/type/test issues before commit.
