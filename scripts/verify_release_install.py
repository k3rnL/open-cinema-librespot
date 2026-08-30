#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from open_cinema_plugin_sdk import (
    SDK_CONTRACT_VERSION,
    validate_built_wheel,
    validate_runtime_plugin,
)
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from open_cinema_librespot.plugin import LibrespotPlugin
from open_cinema_librespot.runtime_assets import load_runtime_assets


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_wheel_digest(checksum_path: Path, wheel: Path) -> str:
    for raw_line in checksum_path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split(maxsplit=1)
        if len(fields) != 2:
            continue
        digest, filename = fields
        if Path(filename.lstrip("*")).name == wheel.name:
            return digest
    raise AssertionError(f"checksum file does not identify {wheel.name}")


def option_contract_summary(document: dict[str, Any], raw: bytes) -> dict[str, object]:
    options = document.get("options")
    if not isinstance(options, list):
        raise AssertionError("installed option contract has no options array")
    return {
        "schemaVersion": document.get("schemaVersion"),
        "librespotVersion": document.get("librespotVersion"),
        "sourceCommit": document.get("sourceCommit"),
        "normalizedHelpSha256": document.get("normalizedHelpSha256"),
        "optionCount": len(options),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def verify_release(
    *,
    wheel: Path,
    checksum: Path,
    provenance_path: Path,
    tag: str,
) -> dict[str, object]:
    expected_version = tag.removeprefix("v")
    if not expected_version or tag != f"v{expected_version}":
        raise AssertionError("release tag must use the v<version> form")

    digest = sha256(wheel)
    if digest != expected_wheel_digest(checksum, wheel):
        raise AssertionError("downloaded wheel digest does not match its checksum asset")

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("tag") != tag:
        raise AssertionError("release provenance tag does not match the requested release")
    if provenance.get("pluginVersion") != expected_version:
        raise AssertionError("release provenance plugin version does not match the tag")

    distribution_version = importlib.metadata.version("open-cinema-librespot")
    host_version = importlib.metadata.version("open-cinema")
    if distribution_version != expected_version:
        raise AssertionError("installed distribution version does not match the release tag")

    manifest = validate_built_wheel(wheel)
    if manifest.version != expected_version:
        raise AssertionError("wheel manifest version does not match the release tag")
    capabilities = validate_runtime_plugin(manifest, LibrespotPlugin())
    plugin_contract = manifest.compatibility.plugin_contract
    if plugin_contract.minimum > SDK_CONTRACT_VERSION or (
        plugin_contract.maximum < SDK_CONTRACT_VERSION
    ):
        raise AssertionError("installed Open Cinema SDK is outside the plugin contract range")

    manifest_raw = (
        resources.files("open_cinema_librespot").joinpath("open-cinema-plugin.toml").read_bytes()
    )
    manifest_document = tomllib.loads(manifest_raw.decode("utf-8"))
    compatibility = manifest_document["compatibility"]["open-cinema"]
    if Version(host_version) not in SpecifierSet(compatibility):
        raise AssertionError("installed Open Cinema version is outside plugin compatibility")

    assets = load_runtime_assets()
    if provenance.get("runtimeIdentity") != assets.identity:
        raise AssertionError("installed runtime identity differs from release provenance")
    if assets.identity.get("pluginVersion") != expected_version:
        raise AssertionError("runtime asset plugin version does not match the release tag")
    if assets.identity.get("librespotVersion") != assets.metadata.get("librespotVersion"):
        raise AssertionError("runtime and capability metadata disagree on librespot version")
    if assets.identity.get("librespotSourceCommit") != assets.metadata.get("sourceCommit"):
        raise AssertionError("runtime and capability metadata disagree on librespot source")

    version_probe = subprocess.run(
        [str(assets.librespot), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    observed_version = (version_probe.stdout or version_probe.stderr).strip()
    if f"librespot {assets.identity['librespotVersion']}" not in observed_version:
        raise AssertionError("installed librespot executable does not match runtime identity")

    option_resource = resources.files("open_cinema_librespot.runtime_assets").joinpath(
        "option-contract.json"
    )
    option_raw = option_resource.read_bytes()
    option_document = json.loads(option_raw)
    option_summary = option_contract_summary(option_document, option_raw)
    if provenance.get("optionContract") != option_summary:
        raise AssertionError("installed option map differs from release provenance")
    if option_summary["librespotVersion"] != assets.identity.get("librespotVersion"):
        raise AssertionError("option map and runtime identity disagree on librespot version")
    if option_summary["sourceCommit"] != assets.identity.get("librespotSourceCommit"):
        raise AssertionError("option map and runtime identity disagree on librespot source")

    return {
        "schemaVersion": 1,
        "tag": tag,
        "wheel": wheel.name,
        "wheelSha256": digest,
        "pluginVersion": distribution_version,
        "openCinemaVersion": host_version,
        "pluginContractVersion": SDK_CONTRACT_VERSION,
        "capabilityCount": len(capabilities),
        "runtimeIdentity": assets.identity,
        "optionContract": option_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--checksum", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    arguments = parser.parse_args()
    report = verify_release(
        wheel=arguments.wheel,
        checksum=arguments.checksum,
        provenance_path=arguments.provenance,
        tag=arguments.tag,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
