from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


class RuntimeAssetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeAssets:
    librespot: Path
    oauth_helper: Path
    metadata: dict[str, object]
    identity: dict[str, object]


def normalized_architecture(value: str | None = None) -> str:
    machine = (value or platform.machine()).lower()
    aliases = {"amd64": "x86_64", "arm64": "aarch64"}
    return aliases.get(machine, machine)


def load_runtime_assets(*, architecture: str | None = None) -> RuntimeAssets:
    arch = normalized_architecture(architecture)
    if arch not in {"x86_64", "aarch64"}:
        raise RuntimeAssetError(f"no librespot runtime is published for {arch}")
    root = resources.files(__package__)
    metadata_value = json.loads(root.joinpath("build-capabilities.json").read_text())
    if not isinstance(metadata_value, dict):
        raise RuntimeAssetError("runtime capability metadata is invalid")
    directory = root.joinpath("bin", arch)
    identity_value = json.loads(directory.joinpath("identity.json").read_text())
    if not isinstance(identity_value, dict) or identity_value.get("architecture") != arch:
        raise RuntimeAssetError("runtime binary identity is invalid")
    librespot = Path(str(directory.joinpath("librespot")))
    oauth_helper = Path(str(directory.joinpath("open-cinema-librespot-oauth")))
    for name, path in (("librespot", librespot), ("oauth helper", oauth_helper)):
        if not path.is_file():
            raise RuntimeAssetError(
                f"the installed wheel has no compatible {name} for {arch}; "
                "install a platform wheel instead of compiling on this host"
            )
        if not path.stat().st_mode & 0o111:
            raise RuntimeAssetError(f"packaged {name} is not executable")
    expected_digests = (
        (librespot, identity_value.get("librespotSha256")),
        (oauth_helper, identity_value.get("oauthHelperSha256")),
    )
    for path, digest in expected_digests:
        if not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeAssetError(f"runtime identity has no valid digest for {path.name}")
        verify_binary(path, digest)
    return RuntimeAssets(librespot, oauth_helper, metadata_value, identity_value)


def verify_binary(path: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise RuntimeAssetError(f"runtime asset digest mismatch for {path.name}")
