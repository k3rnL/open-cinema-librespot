from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from open_cinema_plugin_sdk import PluginInstanceStore, RuntimeStatus

from open_cinema_librespot.configuration import (
    default_instance_configuration,
    instance_schema,
)
from open_cinema_librespot.events import EventState
from open_cinema_librespot.provider import LibrespotProvider
from open_cinema_librespot.supervision import SupervisorObservation


def supervisor_observation(
    *,
    event: dict[str, object] | None,
    playback_event: dict[str, object] | None = None,
    sequence: int = 1,
    started_at: str = "2026-08-30T00:00:00+00:00",
) -> SupervisorObservation:
    return SupervisorObservation(
        "running",
        "running",
        "healthy",
        "generation-1",
        started_at,
        10,
        11,
        None,
        None,
        0,
        None,
        None,
        "digest",
        EventState(sequence, event, 0, playback_event),
        (),
        (),
    )


def test_activity_hold_expires_instead_of_leaving_source_active() -> None:
    provider = LibrespotProvider()
    recent_pause = {
        "event": "paused",
        "observedAtUnixMs": int(time.time() * 1000) - 50,
    }
    stale_pause = {
        "event": "paused",
        "observedAtUnixMs": int(time.time() * 1000) - 2_000,
    }

    held = provider._playback_facts(supervisor_observation(event=recent_pause), 500)
    expired = provider._playback_facts(supervisor_observation(event=stale_pause), 500)

    assert held["activeSignal"] is True
    assert held["activityHeld"] is True
    assert expired["activeSignal"] is False
    assert expired["activityHeld"] is False


def test_running_sink_event_is_active_playback() -> None:
    provider = LibrespotProvider()
    sink = {
        "event": "sink",
        "observedAtUnixMs": int(time.time() * 1000),
        "fields": {"SINK_STATUS": "running"},
    }

    facts = provider._playback_facts(supervisor_observation(event=sink), 500)

    assert facts == {
        "playbackState": "playing",
        "activeSignal": True,
        "activityHeld": False,
        "lastPlaybackEvent": "sink:running",
    }


def test_preloading_keeps_current_programme_active() -> None:
    provider = LibrespotProvider()
    preload = {
        "event": "preloading",
        # Keep this outside the activity hold to prove preloading itself stays
        # active rather than passing through the generic transition hold.
        "observedAtUnixMs": int(time.time() * 1000) - 30_000,
    }

    facts = provider._playback_facts(supervisor_observation(event=preload), 500)

    assert facts == {
        "playbackState": "playing",
        "activeSignal": True,
        "activityHeld": False,
        "lastPlaybackEvent": "preloading",
    }


def test_volume_event_does_not_replace_playing_state() -> None:
    provider = LibrespotProvider()
    playing = {
        "event": "playing",
        "observedAtUnixMs": int(time.time() * 1000),
    }
    volume = {
        "event": "volume_changed",
        "observedAtUnixMs": int(time.time() * 1000),
        "fields": {"VOLUME": "32768"},
    }

    facts = provider._playback_facts(
        supervisor_observation(event=volume, playback_event=playing, sequence=2),
        500,
    )

    assert facts["playbackState"] == "playing"
    assert facts["activeSignal"] is True
    assert facts["lastPlaybackEvent"] == "playing"


def test_automation_failure_is_isolated_and_event_is_dispatched_once() -> None:
    calls: list[str] = []

    class Services:
        def invoke_automation(self, automation_id, payload):
            calls.append(automation_id)
            assert payload["generation"] == "generation-1"
            if automation_id == "broken":
                raise RuntimeError("fixture failure")

    context = SimpleNamespace(
        instance_id="source-1",
        plugin_id="open-cinema.librespot",
        configuration={"automations": {"eventIds": ["broken", "working"]}},
        host_services=Services(),
    )
    observation = supervisor_observation(
        event={"event": "playing", "observedAtUnixMs": int(time.time() * 1000)},
    )
    provider = LibrespotProvider()

    provider._dispatch_events(context, observation)
    provider._dispatch_events(context, observation)

    assert calls == ["broken", "working"]
    assert provider._automation_errors["source-1"] == [
        {
            "automationId": "broken",
            "exception": "RuntimeError",
            "message": "fixture failure",
        }
    ]


def test_automation_sequence_restarts_with_a_restarted_process_group() -> None:
    calls: list[tuple[str, int]] = []

    class Services:
        def invoke_automation(self, automation_id, payload):
            calls.append((payload["event"]["event"], payload["sequence"]))

    context = SimpleNamespace(
        instance_id="source-1",
        plugin_id="open-cinema.librespot",
        configuration={"automations": {"eventIds": ["fixture"]}},
        host_services=Services(),
    )
    provider = LibrespotProvider()

    provider._dispatch_events(
        context,
        supervisor_observation(event={"event": "playing"}, sequence=4),
    )
    provider._dispatch_events(
        context,
        supervisor_observation(
            event={"event": "playing"},
            sequence=1,
            started_at="2026-08-30T00:01:00+00:00",
        ),
    )

    assert calls == [("playing", 4), ("playing", 1)]


def test_event_relay_is_resolved_beside_the_runtime_interpreter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_bin = tmp_path / "venv" / "bin"
    runtime_bin.mkdir(parents=True)
    interpreter = runtime_bin / "python"
    relay = runtime_bin / "open-cinema-librespot-event-relay"
    interpreter.symlink_to("/usr/bin/python3")
    relay.touch()
    monkeypatch.setattr("open_cinema_librespot.provider.sys.executable", str(interpreter))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    class Services:
        def private_directory(self, purpose):
            directory = tmp_path / "private" / purpose
            directory.mkdir(parents=True, exist_ok=True)
            return str(directory)

    context = SimpleNamespace(
        plugin_id="open-cinema.librespot",
        instance_id="relay-source",
        host_services=Services(),
    )

    paths = LibrespotProvider._paths(context)

    assert paths.event_relay == relay
    assert paths.event_python_path is None


def test_event_relay_is_resolved_inside_an_immutable_plugin_overlay(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_bin = tmp_path / "venv" / "bin"
    runtime_bin.mkdir(parents=True)
    interpreter = runtime_bin / "python"
    interpreter.symlink_to("/usr/bin/python3")
    overlay_package = tmp_path / "generation" / "site-packages" / "open_cinema_librespot"
    overlay_package.mkdir(parents=True)
    overlay_relay = overlay_package.parent / "bin" / "open-cinema-librespot-event-relay"
    overlay_relay.parent.mkdir()
    overlay_relay.touch()
    monkeypatch.setattr("open_cinema_librespot.provider.sys.executable", str(interpreter))
    monkeypatch.setattr(
        "open_cinema_librespot.provider.__file__",
        str(overlay_package / "provider.py"),
    )

    class Services:
        def private_directory(self, purpose):
            directory = tmp_path / "private" / purpose
            directory.mkdir(parents=True, exist_ok=True)
            return str(directory)

    context = SimpleNamespace(
        plugin_id="open-cinema.librespot",
        instance_id="overlay-relay-source",
        host_services=Services(),
    )

    paths = LibrespotProvider._paths(context)

    assert paths.event_relay == overlay_relay
    assert paths.event_python_path == overlay_package.parent


def test_event_socket_stays_below_the_linux_unix_path_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    class Services:
        def private_directory(self, purpose):
            directory = tmp_path / ("very-long-private-segment-" * 5) / purpose
            directory.mkdir(parents=True, exist_ok=True)
            return str(directory)

    context = SimpleNamespace(
        plugin_id="open-cinema.librespot",
        instance_id="dfc67dae-30f3-46d7-8536-dddc01a23f0b",
        host_services=Services(),
    )

    paths = LibrespotProvider._paths(context)

    assert len(str(paths.event_socket).encode()) < 100
    assert paths.event_socket.parent == Path("/run/user/1000/open-cinema/librespot")


@pytest.mark.django_db
def test_removed_instance_cleanup_is_bounded_to_its_private_directories(tmp_path: Path) -> None:
    runtime_root = tmp_path / "plugin-runtime"
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    owner = get_user_model().objects.create_user(username="cleanup-owner")
    store = PluginInstanceStore(
        plugin_id="open-cinema.librespot",
        capability_id="open-cinema.librespot.sources",
        schema_id="open-cinema.librespot.instance",
        schema_version=1,
        schema=instance_schema(),
    )
    instance = store.create(
        instance_id="cleanup-source",
        display_name="Cleanup source",
        configuration=default_instance_configuration(name="Cleanup source"),
        owner_id=owner.pk,
    )

    with override_settings(OPEN_CINEMA_PLUGIN_RUNTIME_DIR=runtime_root):
        context = store.context(instance.instance_id)
        assert context.host_services is not None
        private_paths = []
        for purpose in ("temporary", "audio-cache", "system-cache", "runtime", "oauth"):
            directory = Path(context.host_services.private_directory(purpose))
            (directory / "private.data").write_text("plugin data", encoding="utf-8")
            private_paths.append(directory)

        result = LibrespotProvider().cleanup(context)

    assert result.status is RuntimeStatus.READY
    assert all(not path.exists() for path in private_paths)
    assert outside.read_text(encoding="utf-8") == "preserve"
