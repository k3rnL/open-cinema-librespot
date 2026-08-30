#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    arguments = parser.parse_args()
    architecture = {"arm64": "aarch64", "amd64": "x86_64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    with zipfile.ZipFile(arguments.wheel) as archive:
        names = set(archive.namelist())
        prefix = f"open_cinema_librespot/runtime_assets/bin/{architecture}/"
        required = {
            prefix + "librespot",
            prefix + "open-cinema-librespot-oauth",
            prefix + "identity.json",
            "open_cinema_librespot/open-cinema-plugin.toml",
            "open_cinema_librespot/runtime_assets/option-contract.json",
        }
        missing = sorted(required - names)
        if missing:
            raise SystemExit(f"wheel is incomplete: {missing}")
        identity = json.loads(archive.read(prefix + "identity.json"))
        for filename, field in (
            ("librespot", "librespotSha256"),
            ("open-cinema-librespot-oauth", "oauthHelperSha256"),
        ):
            digest = hashlib.sha256(archive.read(prefix + filename)).hexdigest()
            if digest != identity[field]:
                raise SystemExit(f"wheel {filename} digest mismatch")
    print(f"verified {arguments.wheel.name} for {architecture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
