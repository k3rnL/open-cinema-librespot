#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def build_provenance(
    *,
    architecture: str,
    repository: str,
    commit: str,
    tag: str,
    workflow_run: str,
    root: Path,
) -> dict[str, object]:
    identity_path = (
        root / "open_cinema_librespot" / "runtime_assets" / "bin" / architecture / "identity.json"
    )
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    option_path = root / "option-contract" / "librespot-v0.8.0.json"
    option_raw = option_path.read_bytes()
    option_contract = json.loads(option_raw)
    version_match = re.search(
        r'__version__ = "([^"]+)',
        (root / "open_cinema_librespot" / "version.py").read_text(encoding="utf-8"),
    )
    if version_match is None:
        raise AssertionError("plugin version could not be read")
    version = version_match.group(1)
    if tag != f"v{version}":
        raise AssertionError("tag does not match plugin version")
    if identity.get("architecture") != architecture:
        raise AssertionError("runtime identity architecture does not match the build")
    if identity.get("pluginVersion") != version:
        raise AssertionError("runtime identity plugin version does not match the source")

    return {
        "schemaVersion": 1,
        "repository": repository,
        "commit": commit,
        "tag": tag,
        "pluginVersion": version,
        "workflowRun": workflow_run,
        "runtimeIdentity": identity,
        "optionContract": {
            "schemaVersion": option_contract["schemaVersion"],
            "librespotVersion": option_contract["librespotVersion"],
            "sourceCommit": option_contract["sourceCommit"],
            "normalizedHelpSha256": option_contract["normalizedHelpSha256"],
            "optionCount": len(option_contract["options"]),
            "sha256": hashlib.sha256(option_raw).hexdigest(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    document = build_provenance(
        architecture=arguments.architecture,
        repository=arguments.repository,
        commit=arguments.commit,
        tag=arguments.tag,
        workflow_run=arguments.workflow_run,
        root=Path(__file__).resolve().parent.parent,
    )
    arguments.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
