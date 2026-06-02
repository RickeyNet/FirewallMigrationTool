# Build Profiles

Use `build_limited.bat` to build a scoped executable from `build_profiles.json`.

## Common Commands

```bat
build_limited.bat --list
build_limited.bat fortigate_to_ftd
build_limited.bat fortigate_to_ftd 1.7.6
build_limited.bat fortigate_to_ftd 1.7.6 --dry-run
```

The default profile is `fortigate_to_ftd`.

## Restricted FortiGate to FTD Build

The `fortigate_to_ftd` profile only enables:

- Source platform: `FortiGate`
- Target platform: `Cisco FTD`
- Tool directory: `FortiGateToFTDTool`
- FTD converter, importer, cleanup, and shared support modules

The generated executable is named:

```text
dist\FortiGate-to-Cisco-FTD-Tool-v<version>.exe
```

## Adding Profiles

Add another object to `build_profiles.json` with:

- `source_platforms` and `target_platforms` for the GUI
- `tool_dirs` for the converter folders PyInstaller may import from
- `hidden_imports` for the modules that should be bundled
- `exe_name`, `product_name`, and `app_title` for executable naming and UI text
