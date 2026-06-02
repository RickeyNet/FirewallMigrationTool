#!/usr/bin/env python3
"""
Build Firewall Migration Tool executables from named profiles.

Profiles live in build_profiles.json. Each profile controls:
  - which converter directories PyInstaller can import from
  - which hidden imports are bundled
  - which source/target choices the GUI exposes at runtime
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GUI_FILE = ROOT / "gui_app.py"
PROFILES_FILE = ROOT / "build_profiles.json"
RUNTIME_PROFILE_NAME = "build_profile_runtime.json"


def load_profiles() -> dict:
    with PROFILES_FILE.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("build_profiles.json must contain a JSON object")
    return data


def read_app_version() -> str:
    text = GUI_FILE.read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("Could not find APP_VERSION in gui_app.py")
    return match.group(1)


def patch_app_version(version: str) -> str:
    original = GUI_FILE.read_text(encoding="utf-8")
    patched, count = re.subn(
        r'^APP_VERSION\s*=\s*"[^"]+"',
        f'APP_VERSION = "{version}"',
        original,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("Could not patch APP_VERSION in gui_app.py")
    GUI_FILE.write_text(patched, encoding="utf-8")
    return original


def validate_profile(profile_name: str, profile: dict) -> None:
    if not isinstance(profile, dict):
        raise ValueError(f"Profile {profile_name!r} must be a JSON object")
    for key in ("exe_name", "source_platforms", "target_platforms", "tool_dirs", "hidden_imports"):
        if key not in profile:
            raise ValueError(f"Profile {profile_name!r} is missing {key!r}")
    for tool_dir in profile["tool_dirs"]:
        path = ROOT / tool_dir
        if not path.is_dir():
            raise FileNotFoundError(f"Profile {profile_name!r} references missing directory: {tool_dir}")


def write_runtime_profile(profile_name: str, profile: dict) -> Path:
    runtime_dir = ROOT / "build" / "runtime_profiles" / profile_name
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / RUNTIME_PROFILE_NAME
    runtime = {
        "profile": profile_name,
        "app_title": profile.get("app_title", ""),
        "source_platforms": profile["source_platforms"],
        "target_platforms": profile["target_platforms"],
        "supported_pairs_text": profile.get("supported_pairs_text", ""),
        "tool_dirs": profile["tool_dirs"],
    }
    runtime_path.write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    return runtime_path


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = []
    for token in version.split("."):
        match = re.match(r"(\d+)", token)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def write_version_info(version: str, profile: dict) -> Path:
    file_version = version_tuple(version)
    product_name = profile.get("product_name", "Firewall Migration Tool")
    description = profile.get("file_description", product_name)
    original_filename = f"{profile['exe_name'].format(version=version)}.exe"
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={file_version},
    prodvers={file_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u''),
            StringStruct(u'FileDescription', u'{description}'),
            StringStruct(u'FileVersion', u'{version}'),
            StringStruct(u'InternalName', u'{profile["exe_name"].format(version=version)}'),
            StringStruct(u'OriginalFilename', u'{original_filename}'),
            StringStruct(u'ProductName', u'{product_name}'),
            StringStruct(u'ProductVersion', u'{version}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    path = ROOT / "version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


def install_build_dependencies() -> None:
    print("[1/3] Installing build dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyyaml", "requests", "urllib3", "pyinstaller"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        print("[WARN] pip install returned a non-zero exit code; continuing to PyInstaller.")


def build_command(profile: dict, version: str, runtime_profile: Path, version_info: Path) -> list[str]:
    add_data_sep = ";" if os.name == "nt" else ":"
    exe_name = profile["exe_name"].format(version=version)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        exe_name,
        "--icon",
        str(ROOT / "app_icon.ico"),
        "--add-data",
        f"{ROOT / 'app_icon.ico'}{add_data_sep}.",
        "--add-data",
        f"{runtime_profile}{add_data_sep}.",
        "--version-file",
        str(version_info),
    ]

    for tool_dir in profile["tool_dirs"]:
        cmd.extend(["--paths", str(ROOT / tool_dir)])
    for hidden_import in profile["hidden_imports"]:
        cmd.extend(["--hidden-import", hidden_import])

    cmd.extend(["--clean", str(GUI_FILE)])
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Firewall Migration Tool profile.")
    parser.add_argument(
        "profile",
        nargs="?",
        default="fortigate_to_ftd",
        help="Profile name from build_profiles.json (default: fortigate_to_ftd)",
    )
    parser.add_argument(
        "--version",
        help="Version to embed in the GUI and executable metadata. Defaults to gui_app.py APP_VERSION.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available profiles and exit.",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Skip pip install of build dependencies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write generated build metadata and print the PyInstaller command without building.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profiles = load_profiles()

    if args.list:
        print("Available build profiles:")
        for name, profile in profiles.items():
            print(f"  {name}: {profile.get('description', '')}")
        return 0

    if args.profile not in profiles:
        print(f"[ERROR] Unknown profile: {args.profile}")
        print("Run build_profile.py --list to see available profiles.")
        return 2

    profile = profiles[args.profile]
    validate_profile(args.profile, profile)

    original_gui = None
    version = args.version or read_app_version()

    print()
    print("============================================================")
    print("  Firewall Migration Tool - Profile Build")
    print("============================================================")
    print(f"  Profile: {args.profile}")
    print(f"  Version: {version}")
    print(f"  Output:  dist\\{profile['exe_name'].format(version=version)}.exe")
    print()

    try:
        if args.version and not args.dry_run:
            print("[0/3] Temporarily setting gui_app.py APP_VERSION...")
            original_gui = patch_app_version(version)

        if not args.skip_pip and not args.dry_run:
            install_build_dependencies()

        print("[2/3] Writing runtime profile and version metadata...")
        runtime_profile = write_runtime_profile(args.profile, profile)
        version_info = write_version_info(version, profile)

        cmd = build_command(profile, version, runtime_profile, version_info)
        if args.dry_run:
            print("[3/3] Dry run - PyInstaller command:")
            print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
            return 0

        print("[3/3] Building executable with PyInstaller...")
        result = subprocess.run(cmd, cwd=ROOT, check=False)
        return result.returncode
    finally:
        if original_gui is not None:
            GUI_FILE.write_text(original_gui, encoding="utf-8")
            print("Restored gui_app.py APP_VERSION.")


if __name__ == "__main__":
    raise SystemExit(main())
