from __future__ import annotations

import copy
import ipaddress
import json
import os
from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

DEFAULT_INSTANCE_CONFIGURATION: dict[str, Any] = {
    "name": "Open Cinema",
    "deviceType": "avr",
    "group": False,
    "bitrate": 320,
    "logLevel": "standard",
    "authentication": {"mode": "discovery", "username": None},
    "proxy": None,
    "apPort": None,
    "discovery": {"enabled": True, "backend": "libmdns", "port": None, "interfaces": []},
    "volume": {"initialPercent": 50, "control": "log", "rangeDb": 60, "steps": 64},
    "normalisation": {
        "enabled": False,
        "method": "dynamic",
        "gainType": "auto",
        "pregainDb": 0,
        "thresholdDbfs": -2,
        "attackMs": 5,
        "releaseMs": 100,
        "kneeDb": 5,
    },
    "playback": {"autoplay": "client", "gapless": True},
    "cache": {"audioEnabled": True, "credentialsEnabled": True, "sizeLimit": "2G"},
    "localFileDirectories": [],
    "automations": {"eventIds": [], "includeSinkEvents": True},
    "activityHoldMs": 1500,
}


def instance_schema() -> dict[str, Any]:
    text = resources.files("open_cinema_librespot.schemas").joinpath("instance-v1.json").read_text()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise TypeError("instance schema must be an object")
    return value


def default_instance_configuration(*, name: str = "Open Cinema") -> dict[str, Any]:
    document = copy.deepcopy(DEFAULT_INSTANCE_CONFIGURATION)
    document["name"] = name
    return document


def _mutable_json(value: Any) -> Any:
    """Copy SDK-frozen JSON into ordinary validation data."""

    if isinstance(value, Mapping):
        return {str(key): _mutable_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_mutable_json(item) for item in value]
    return copy.deepcopy(value)


def validate_instance_configuration(
    value: Mapping[str, Any],
    *,
    media_roots: Sequence[str | os.PathLike[str]] = (),
) -> dict[str, Any]:
    document = _mutable_json(value)
    if not isinstance(document, dict):
        raise TypeError("instance configuration must be an object")
    errors = sorted(
        Draft202012Validator(instance_schema(), format_checker=FormatChecker()).iter_errors(
            document
        ),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        rendered = []
        for error in errors[:16]:
            path = "/" + "/".join(str(part) for part in error.absolute_path)
            rendered.append(f"{path}: {error.message}")
        raise ValueError("; ".join(rendered))

    authentication = document["authentication"]
    discovery = document["discovery"]
    cache = document["cache"]
    assert isinstance(authentication, dict)
    assert isinstance(discovery, dict)
    assert isinstance(cache, dict)
    if authentication["mode"] == "discovery" and not discovery["enabled"]:
        raise ValueError("/discovery/enabled: discovery authentication requires discovery")
    if authentication["mode"] == "oauth-cache" and not cache["credentialsEnabled"]:
        raise ValueError("/cache/credentialsEnabled: OAuth requires persistent credentials")

    proxy = document.get("proxy")
    if proxy is not None:
        parsed = urlparse(str(proxy))
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("/proxy: only an http:// proxy with a host is supported")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("/proxy: credentials are not accepted because librespot logs proxies")

    for interface in discovery["interfaces"]:
        try:
            ipaddress.ip_address(interface)
        except ValueError as error:
            raise ValueError(
                f"/discovery/interfaces: {interface!r} is not an IP address"
            ) from error

    roots = tuple(Path(item).expanduser().resolve() for item in media_roots)
    for raw in document["localFileDirectories"]:
        resolved_directory = Path(raw).expanduser().resolve()
        if not roots or not any(
            resolved_directory == root or root in resolved_directory.parents for root in roots
        ):
            raise ValueError(
                f"/localFileDirectories: {resolved_directory} is outside configured media roots"
            )
        if not resolved_directory.is_dir() or not os.access(resolved_directory, os.R_OK | os.X_OK):
            raise ValueError(
                f"/localFileDirectories: {resolved_directory} is not an accessible directory"
            )
    return document


def ensure_unique_connect_names(
    configurations: Sequence[Mapping[str, Any]],
) -> None:
    names = [str(item.get("name", "")).strip().casefold() for item in configurations]
    if any(not item for item in names):
        raise ValueError("every instance must have a Connect name")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError("Connect names must be unique: " + ", ".join(duplicates))
