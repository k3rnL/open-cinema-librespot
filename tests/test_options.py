from __future__ import annotations

from pathlib import Path

import pytest

from open_cinema_librespot.configuration import default_instance_configuration
from open_cinema_librespot.options import (
    InstancePaths,
    build_launch_plan,
    detect_pw_cat_raw_mode,
    option_contract,
)


def paths(tmp_path: Path) -> InstancePaths:
    tmp_path.mkdir(parents=True, exist_ok=True)
    relay = tmp_path / "relay"
    relay.touch(mode=0o700)
    return InstancePaths(
        tmp_path / "tmp",
        tmp_path / "audio",
        tmp_path / "system",
        relay,
        tmp_path / "events.sock",
    )


def test_every_option_has_one_explicit_classification() -> None:
    options = option_contract()["options"]
    names = [item["name"] for item in options]

    assert len(names) == len(set(names)) == 51
    assert {item["classification"] for item in options} == {
        "action",
        "configurable",
        "equivalent",
        "managed",
        "unavailable",
    }


def test_launch_plan_has_fixed_pcm_boundary_and_no_secret_in_argv(tmp_path: Path) -> None:
    config = default_instance_configuration(name="Cinema Spotify")
    config["authentication"]["mode"] = "access-token"
    plan = build_launch_plan(
        librespot_binary="/verified/librespot",
        pw_cat_binary="/usr/bin/pw-cat",
        instance_id="11111111-1111-1111-1111-111111111111",
        generation="generation-1",
        configuration=config,
        paths=paths(tmp_path),
        access_token="very-secret-token",
        pw_cat_raw_mode=True,
    )

    argv = list(plan.librespot_argv)
    assert argv[argv.index("--backend") + 1] == "pipe"
    assert argv[argv.index("--format") + 1] == "F32"
    assert argv[argv.index("--dither") + 1] == "none"
    assert argv[argv.index("--mixer") + 1] == "softvol"
    assert "very-secret-token" not in argv
    assert plan.environment["LIBRESPOT_ACCESS_TOKEN"] == "very-secret-token"
    assert plan.redacted_environment["LIBRESPOT_ACCESS_TOKEN"] == "<redacted>"
    assert plan.bridge_argv[-1] == "-"
    assert "--raw" in plan.bridge_argv
    assert plan.bridge_argv[plan.bridge_argv.index("--target") + 1] == "0"
    assert plan.bridge_argv[plan.bridge_argv.index("--rate") + 1] == "44100"
    assert plan.pipewire_properties["node.autoconnect"] == "false"
    assert plan.librespot_argv[plan.librespot_argv.index("--zeroconf-backend") + 1] == "libmdns"
    assert "--emit-sink-events" in plan.librespot_argv

    config["automations"]["includeSinkEvents"] = False
    without_sink_events = build_launch_plan(
        librespot_binary="/verified/librespot",
        pw_cat_binary="/usr/bin/pw-cat",
        instance_id="11111111-1111-1111-1111-111111111111",
        generation="generation-2",
        configuration=config,
        paths=paths(tmp_path / "without-sink-events"),
        access_token="very-secret-token",
    )
    assert "--emit-sink-events" not in without_sink_events.librespot_argv


def test_overlay_event_relay_receives_its_immutable_python_path(tmp_path: Path) -> None:
    instance_paths = paths(tmp_path)
    overlay = tmp_path / "generation" / "site-packages"
    instance_paths = InstancePaths(
        instance_paths.temporary,
        instance_paths.audio_cache,
        instance_paths.system_cache,
        instance_paths.event_relay,
        instance_paths.event_socket,
        overlay,
    )

    plan = build_launch_plan(
        librespot_binary="/verified/librespot",
        pw_cat_binary="/usr/bin/pw-cat",
        instance_id="source-1",
        generation="generation-1",
        configuration=default_instance_configuration(),
        paths=instance_paths,
    )

    assert plan.environment["PYTHONPATH"] == str(overlay)
    assert plan.redacted_environment["PYTHONPATH"] == str(overlay)


def test_pw_cat_raw_mode_is_enabled_only_when_supported(tmp_path: Path) -> None:
    modern = tmp_path / "pw-cat-modern"
    modern.write_text("#!/bin/sh\necho '  -a, --raw  RAW mode'\necho '  -p, --playback'\n")
    modern.chmod(0o700)
    legacy = tmp_path / "pw-cat-legacy"
    legacy.write_text("#!/bin/sh\necho '  -p, --playback  Playback mode'\n")
    legacy.chmod(0o700)

    assert detect_pw_cat_raw_mode(modern) is True
    assert detect_pw_cat_raw_mode(legacy) is False


def test_all_typed_values_serialize_deterministically(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    config = default_instance_configuration()
    config["logLevel"] = "verbose"
    config["group"] = True
    config["normalisation"]["enabled"] = True
    config["playback"] = {"autoplay": "off", "gapless": False}
    config["cache"] = {
        "audioEnabled": False,
        "credentialsEnabled": False,
        "sizeLimit": "512M",
    }
    config["localFileDirectories"] = [str(media)]

    first = build_launch_plan(
        librespot_binary="/verified/librespot",
        pw_cat_binary="/usr/bin/pw-cat",
        instance_id="source-1",
        generation="g1",
        configuration=config,
        paths=paths(tmp_path / "first"),
        media_roots=(media,),
    )
    second = build_launch_plan(
        librespot_binary="/verified/librespot",
        pw_cat_binary="/usr/bin/pw-cat",
        instance_id="source-1",
        generation="g1",
        configuration=config,
        paths=paths(tmp_path / "first"),
        media_roots=(media,),
    )

    assert first == second
    assert "--verbose" in first.librespot_argv
    assert "--enable-volume-normalisation" in first.librespot_argv
    assert "--disable-gapless" in first.librespot_argv
    assert "--disable-audio-cache" in first.librespot_argv


@pytest.mark.parametrize("name", ["backend", "device", "format", "dither", "mixer", "passthrough"])
def test_unsafe_audio_ownership_options_are_not_configurable(name: str) -> None:
    item = next(item for item in option_contract()["options"] if item["name"] == name)
    assert item["classification"] in {"managed", "unavailable"}
