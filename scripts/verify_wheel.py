#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement


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
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise SystemExit("wheel must contain exactly one METADATA file")
        metadata = Parser().parsestr(archive.read(metadata_files[0]).decode("utf-8"))
        dependencies = {
            Requirement(value).name.lower().replace("_", "-")
            for value in metadata.get_all("Requires-Dist", ())
        }
        if "open-cinema" in dependencies:
            raise SystemExit(
                "Open Cinema host compatibility belongs in the plugin manifest, "
                "not wheel runtime dependencies"
            )
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
