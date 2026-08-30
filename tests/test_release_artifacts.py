from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_release_provenance import build_provenance
from scripts.verify_release_install import expected_wheel_digest, option_contract_summary

ROOT = Path(__file__).resolve().parent.parent


def test_release_provenance_matches_source_runtime_and_option_contract() -> None:
    document = build_provenance(
        architecture="x86_64",
        repository="k3rnL/open-cinema-librespot",
        commit="0" * 40,
        tag="v0.1.3",
        workflow_run="https://example.invalid/actions/runs/test",
        root=ROOT,
    )
    identity = json.loads(
        (ROOT / "open_cinema_librespot/runtime_assets/bin/x86_64/identity.json").read_text(
            encoding="utf-8"
        )
    )
    option_raw = (ROOT / "option-contract/librespot-v0.8.0.json").read_bytes()

    assert document["pluginVersion"] == "0.1.3"
    assert document["runtimeIdentity"] == identity
    assert document["optionContract"] == option_contract_summary(json.loads(option_raw), option_raw)


def test_release_provenance_rejects_a_tag_version_mismatch() -> None:
    with pytest.raises(AssertionError, match="tag does not match"):
        build_provenance(
            architecture="x86_64",
            repository="k3rnL/open-cinema-librespot",
            commit="0" * 40,
            tag="v9.9.9",
            workflow_run="https://example.invalid/actions/runs/test",
            root=ROOT,
        )


def test_downloaded_checksum_uses_the_wheel_basename(tmp_path: Path) -> None:
    wheel = tmp_path / "open_cinema_librespot-0.1.3-py3-none-linux_x86_64.whl"
    wheel.write_bytes(b"release-wheel")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    checksum = tmp_path / "checksums-x86_64.sha256"
    checksum.write_text(f"{digest}  {wheel.name}\n", encoding="utf-8")

    assert expected_wheel_digest(checksum, wheel) == digest
