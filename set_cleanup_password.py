#!/usr/bin/env python3
"""
Set the built-in default cleanup password.

Usage:
    python set_cleanup_password.py <new-password>

This updates the _DEFAULT_SALT and _DEFAULT_HASH constants in
cleanup_auth.py so the new password is baked into the next build.
Rebuild the exe afterward for the change to take effect.
"""

import hashlib
import os
import re
import sys

_ITERATIONS = 600_000
_HASH_LEN = 32


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python set_cleanup_password.py <new-password>")
        sys.exit(1)

    password = sys.argv[1]
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
        dklen=_HASH_LEN,
    )

    salt_hex = salt.hex()
    hash_hex = dk.hex()

    # Update cleanup_auth.py in place
    auth_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cleanup_auth.py")

    if not os.path.isfile(auth_path):
        print(f"[ERROR] Cannot find {auth_path}")
        sys.exit(1)

    with open(auth_path, "r") as f:
        content = f.read()

    original = content

    content = re.sub(
        r'^_DEFAULT_SALT = ".*"',
        f'_DEFAULT_SALT = "{salt_hex}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r'^_DEFAULT_HASH = ".*"',
        f'_DEFAULT_HASH = "{hash_hex}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if content == original:
        print("[ERROR] Could not find _DEFAULT_SALT / _DEFAULT_HASH in cleanup_auth.py")
        sys.exit(1)

    with open(auth_path, "w") as f:
        f.write(content)

    print(f"Default cleanup password updated in cleanup_auth.py.")
    print(f"Rebuild the exe for the change to take effect.")


if __name__ == "__main__":
    main()
