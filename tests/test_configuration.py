from __future__ import annotations

from pathlib import Path

import pytest
from open_cinema_plugin_sdk import ManagedResourceContext

from open_cinema_librespot.configuration import (
    default_instance_configuration,
    ensure_unique_connect_names,
    validate_instance_configuration,
)


def test_defaults_are_valid_and_independent() -> None:
    first = default_instance_configuration(name="Living room")
    second = default_instance_configuration(name="Kitchen")

    assert validate_instance_configuration(first)["bitrate"] == 320
    assert second["name"] == "Kitchen"
    assert first["authentication"] is not second["authentication"]


def test_sdk_frozen_configuration_can_be_validated_without_mutation() -> None:
    context = ManagedResourceContext(
        "open-cinema.librespot",
        "open-cinema.librespot.sources",
        "source-1",
        default_instance_configuration(name="Frozen source"),
        1,
    )

    validated = validate_instance_configuration(context.configuration)

    assert validated["name"] == "Frozen source"
    assert isinstance(validated["authentication"], dict)


def test_discovery_authentication_requires_discovery() -> None:
    value = default_instance_configuration()
    value["discovery"]["enabled"] = False

    with pytest.raises(ValueError, match="discovery authentication requires discovery"):
        validate_instance_configuration(value)


def test_oauth_requires_credential_cache() -> None:
    value = default_instance_configuration()
    value["authentication"]["mode"] = "oauth-cache"
    value["cache"]["credentialsEnabled"] = False

    with pytest.raises(ValueError, match="OAuth requires persistent credentials"):
        validate_instance_configuration(value)


def test_proxy_credentials_are_rejected_for_log_safety() -> None:
    value = default_instance_configuration()
    value["proxy"] = "http://user:secret@proxy.example:8080"

    with pytest.raises(ValueError, match="credentials are not accepted"):
        validate_instance_configuration(value)


def test_local_files_are_ordered_and_restricted_to_media_roots(tmp_path: Path) -> None:
    media = tmp_path / "media"
    album = media / "album"
    album.mkdir(parents=True)
    value = default_instance_configuration()
    value["localFileDirectories"] = [str(album)]

    result = validate_instance_configuration(value, media_roots=(media,))

    assert result["localFileDirectories"] == [str(album)]
    value["localFileDirectories"] = [str(tmp_path)]
    with pytest.raises(ValueError, match="outside configured media roots"):
        validate_instance_configuration(value, media_roots=(media,))


def test_connect_names_are_case_insensitively_unique() -> None:
    first = default_instance_configuration(name="Living Room")
    second = default_instance_configuration(name="living room")

    with pytest.raises(ValueError, match="must be unique"):
        ensure_unique_connect_names((first, second))
