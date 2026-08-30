from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from .configuration import validate_instance_configuration


@dataclass(frozen=True, slots=True)
class InstancePaths:
    temporary: Path
    audio_cache: Path
    system_cache: Path
    event_relay: Path
    event_socket: Path
    event_python_path: Path | None = None

    def ensure_private(self) -> None:
        for directory in (self.temporary, self.audio_cache, self.system_cache):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    librespot_argv: tuple[str, ...]
    bridge_argv: tuple[str, ...]
    environment: Mapping[str, str]
    redacted_environment: Mapping[str, str]
    pipewire_properties: Mapping[str, str]


def option_contract() -> dict[str, Any]:
    source = Path(__file__).resolve().parent.parent / "option-contract" / "librespot-v0.8.0.json"
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Installed wheels carry the normalized copy next to the runtime assets.
        text = (
            resources.files("open_cinema_librespot.runtime_assets")
            .joinpath("option-contract.json")
            .read_text()
        )
    value = json.loads(text)
    if not isinstance(value, dict):
        raise TypeError("option contract must be an object")
    return value


def detect_pw_cat_raw_mode(pw_cat_binary: str | Path) -> bool:
    try:
        completed = subprocess.run(
            [str(Path(pw_cat_binary)), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"could not inspect pw-cat capabilities: {error}") from error
    help_output = completed.stdout + completed.stderr
    if completed.returncode != 0 or "--playback" not in help_output:
        raise RuntimeError("pw-cat did not return a recognizable capability summary")
    return "--raw" in help_output


def _append_option(argv: list[str], name: str, value: Any) -> None:
    if value is None:
        return
    argv.extend((f"--{name}", str(value)))


def build_launch_plan(
    *,
    librespot_binary: str | Path,
    pw_cat_binary: str | Path,
    instance_id: str,
    generation: str,
    configuration: Mapping[str, Any],
    paths: InstancePaths,
    access_token: str | None = None,
    media_roots: tuple[str | Path, ...] = (),
    latency: str = "10ms",
    pw_cat_raw_mode: bool = False,
) -> LaunchPlan:
    config = validate_instance_configuration(configuration, media_roots=media_roots)
    paths.ensure_private()
    argv = [
        str(Path(librespot_binary)),
        "--backend",
        "pipe",
        "--format",
        "F32",
        "--dither",
        "none",
        "--mixer",
        "softvol",
        "--tmp",
        str(paths.temporary),
        "--cache",
        str(paths.audio_cache),
        "--system-cache",
        str(paths.system_cache),
        "--name",
        str(config["name"]),
        "--device-type",
        str(config["deviceType"]),
        "--bitrate",
        str(config["bitrate"]),
        "--onevent",
        str(paths.event_relay),
    ]
    if config["group"]:
        argv.append("--group")
    if config["logLevel"] == "quiet":
        argv.append("--quiet")
    elif config["logLevel"] == "verbose":
        argv.append("--verbose")

    authentication = config["authentication"]
    discovery = config["discovery"]
    volume = config["volume"]
    normalisation = config["normalisation"]
    playback = config["playback"]
    cache = config["cache"]
    automations = config["automations"]
    assert all(
        isinstance(value, dict)
        for value in (
            authentication,
            discovery,
            volume,
            normalisation,
            playback,
            cache,
            automations,
        )
    )
    if authentication["mode"] != "discovery" and authentication.get("username"):
        _append_option(argv, "username", authentication["username"])
    if not discovery["enabled"]:
        argv.append("--disable-discovery")
    _append_option(argv, "zeroconf-backend", discovery["backend"])
    _append_option(argv, "zeroconf-port", discovery["port"])
    if discovery["interfaces"]:
        _append_option(argv, "zeroconf-interface", ",".join(discovery["interfaces"]))
    _append_option(argv, "proxy", config["proxy"])
    _append_option(argv, "ap-port", config["apPort"])

    _append_option(argv, "initial-volume", volume["initialPercent"])
    _append_option(argv, "volume-ctrl", volume["control"])
    _append_option(argv, "volume-range", volume["rangeDb"])
    _append_option(argv, "volume-steps", volume["steps"])
    if normalisation["enabled"]:
        argv.append("--enable-volume-normalisation")
        for option, field in (
            ("normalisation-method", "method"),
            ("normalisation-gain-type", "gainType"),
            ("normalisation-pregain", "pregainDb"),
            ("normalisation-threshold", "thresholdDbfs"),
            ("normalisation-attack", "attackMs"),
            ("normalisation-release", "releaseMs"),
            ("normalisation-knee", "kneeDb"),
        ):
            _append_option(argv, option, normalisation[field])
    if playback["autoplay"] != "client":
        _append_option(argv, "autoplay", playback["autoplay"])
    if not playback["gapless"]:
        argv.append("--disable-gapless")
    if not cache["audioEnabled"]:
        argv.append("--disable-audio-cache")
    if not cache["credentialsEnabled"]:
        argv.append("--disable-credential-cache")
    _append_option(argv, "cache-size-limit", cache["sizeLimit"])
    for directory in config["localFileDirectories"]:
        _append_option(argv, "local-file-dir", directory)
    if automations["includeSinkEvents"]:
        argv.append("--emit-sink-events")

    properties = {
        "media.class": "Stream/Output/Audio",
        "media.role": "Music",
        "node.name": f"open-cinema-librespot-{instance_id}",
        "node.description": str(config["name"]),
        "node.autoconnect": "false",
        "open-cinema.provider": "librespot",
        "open-cinema.plugin.id": "open-cinema.librespot",
        "open-cinema.instance.id": instance_id,
        "open-cinema.generation": generation,
    }
    property_argument = " ".join(f"{key}={json.dumps(value)}" for key, value in properties.items())
    bridge = [
        str(Path(pw_cat_binary)),
        "--playback",
    ]
    if pw_cat_raw_mode:
        bridge.append("--raw")
    bridge.extend(
        (
            "--target",
            "0",
            "--latency",
            latency,
            "--rate",
            "44100",
            "--channels",
            "2",
            "--channel-map",
            "stereo",
            "--format",
            "f32",
            "--media-role",
            "Music",
            "--properties",
            property_argument,
            "-",
        )
    )
    environment = {
        "OPEN_CINEMA_LIBRESPOT_INSTANCE_ID": instance_id,
        "OPEN_CINEMA_LIBRESPOT_GENERATION": generation,
        "OPEN_CINEMA_LIBRESPOT_EVENT_SOCKET": str(paths.event_socket),
    }
    if paths.event_python_path is not None:
        environment["PYTHONPATH"] = str(paths.event_python_path)
    if access_token is not None:
        environment["LIBRESPOT_ACCESS_TOKEN"] = access_token
    redacted = {
        key: "<redacted>" if key == "LIBRESPOT_ACCESS_TOKEN" else value
        for key, value in environment.items()
    }
    return LaunchPlan(tuple(argv), tuple(bridge), environment, redacted, properties)
