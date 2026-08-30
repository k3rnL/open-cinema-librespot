#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_MATCH = re.search(
    r'__version__ = "([^"]+)"',
    (ROOT / "open_cinema_librespot" / "version.py").read_text(encoding="utf-8"),
)
if VERSION_MATCH is None:
    raise RuntimeError("plugin version could not be read")
PLUGIN_VERSION = VERSION_MATCH.group(1)
PIN = json.loads((ROOT / "runtime-assets" / "librespot-v0.8.0.json").read_text())
ARCHITECTURES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}
TARGETS = {
    "x86_64": "x86_64-unknown-linux-gnu",
    "aarch64": "aarch64-unknown-linux-gnu",
}


def run(*arguments: str, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return result.stdout if capture else ""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", choices=sorted(TARGETS))
    parser.add_argument("--output-root", type=Path)
    arguments = parser.parse_args()
    architecture = arguments.architecture or ARCHITECTURES.get(platform.machine().lower())
    if architecture is None:
        parser.error(f"unsupported build architecture: {platform.machine()}")
    target = TARGETS[architecture]
    if ARCHITECTURES.get(platform.machine().lower()) != architecture:
        parser.error("cross compilation is not implicit; use the matching native CI runner")
    output = arguments.output_root or (
        ROOT / "open_cinema_librespot" / "runtime_assets" / "bin" / architecture
    )
    output.mkdir(parents=True, exist_ok=True)
    # Upstream uses SOURCE_DATE_EPOCH for both its embedded build ID and date.
    # Pinning it to the verified commit timestamp makes equivalent source builds
    # byte reproducible instead of embedding the wall clock and a random ID.
    os.environ["SOURCE_DATE_EPOCH"] = str(PIN["sourceDateEpoch"])

    with tempfile.TemporaryDirectory(prefix="open-cinema-librespot-build-") as temporary:
        workspace = Path(temporary)
        upstream = workspace / "librespot"
        cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")).resolve()
        # Cargo and rustc otherwise preserve checkout and registry paths in panic
        # locations. CI and local builds use different directories, so remap all
        # three roots to stable virtual source locations before compiling.
        remaps = (
            f"--remap-path-prefix={workspace}=/usr/src/open-cinema-librespot-upstream",
            f"--remap-path-prefix={ROOT}=/usr/src/open-cinema-librespot-plugin",
            f"--remap-path-prefix={cargo_home}=/usr/local/cargo",
        )
        existing_rustflags = os.environ.get("RUSTFLAGS", "").strip()
        os.environ["RUSTFLAGS"] = " ".join((*remaps, existing_rustflags)).strip()
        run(
            "git",
            "clone",
            "--quiet",
            "--branch",
            PIN["tag"],
            "--depth",
            "1",
            PIN["repository"],
            str(upstream),
        )
        commit = run("git", "rev-parse", "HEAD", cwd=upstream, capture=True).strip()
        if commit != PIN["commit"]:
            raise RuntimeError(f"librespot commit mismatch: {commit}")
        for filename, key in (
            ("Cargo.lock", "cargoLockSha256"),
            ("rust-toolchain.toml", "rustToolchainFileSha256"),
        ):
            if sha256(upstream / filename) != PIN[key]:
                raise RuntimeError(f"pinned {filename} digest changed")

        run("rustup", "toolchain", "install", PIN["rustToolchain"], "--profile", "minimal")
        run("rustup", "target", "add", target, "--toolchain", PIN["rustToolchain"])
        cargo = f"+{PIN['rustToolchain']}"
        run(
            "cargo",
            cargo,
            "build",
            "--locked",
            "--release",
            "--target",
            target,
            "--no-default-features",
            "--features",
            ",".join(PIN["features"]),
            cwd=upstream,
        )
        helper = ROOT / "runtime-assets" / "oauth-helper"
        run(
            "cargo",
            cargo,
            "build",
            "--locked",
            "--release",
            "--target",
            target,
            cwd=helper,
        )
        librespot = upstream / "target" / target / "release" / "librespot"
        oauth = helper / "target" / target / "release" / "open-cinema-librespot-oauth"
        shutil.copy2(librespot, output / "librespot")
        shutil.copy2(oauth, output / "open-cinema-librespot-oauth")
        for path in (output / "librespot", output / "open-cinema-librespot-oauth"):
            path.chmod(0o755)

    help_output = run(str(output / "librespot"), "--help", capture=True)
    version_output = run(str(output / "librespot"), "--version", capture=True).strip()
    identity = {
        "schemaVersion": 1,
        "pluginVersion": PLUGIN_VERSION,
        "librespotVersion": "0.8.0",
        "librespotSourceCommit": PIN["commit"],
        "sourceDateEpoch": PIN["sourceDateEpoch"],
        "target": target,
        "architecture": architecture,
        "features": PIN["features"],
        "librespotSha256": sha256(output / "librespot"),
        "oauthHelperSha256": sha256(output / "open-cinema-librespot-oauth"),
        "librespotVersionOutput": version_output,
    }
    (output / "identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    help_path = output / "librespot-help.txt"
    help_path.write_text(help_output, encoding="utf-8")
    run(
        os.fspath(ROOT / "scripts" / "audit_options.py"),
        "--help-output",
        os.fspath(help_path),
    )
    print(json.dumps(identity, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
