from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from open_cinema_librespot.events import EventReceiver, relay_document


def send(path: Path, document: dict[str, object]) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(json.dumps(document).encode(), str(path))


def test_relay_document_is_bounded_and_drops_unknown_environment() -> None:
    value = relay_document(
        {
            "OPEN_CINEMA_LIBRESPOT_INSTANCE_ID": "source-1",
            "OPEN_CINEMA_LIBRESPOT_GENERATION": "g1",
            "PLAYER_EVENT": "playing",
            "TRACK_ID": "track-1",
            "ACCESS_TOKEN": "must-not-leak",
        }
    )

    assert value["event"] == "playing"
    assert value["fields"] == {"TRACK_ID": "track-1"}


def test_receiver_rejects_stale_generation(tmp_path: Path) -> None:
    receiver = EventReceiver(tmp_path / "events.sock", instance_id="source-1", generation="g2")
    receiver.start()
    try:
        stale = relay_document(
            {
                "OPEN_CINEMA_LIBRESPOT_INSTANCE_ID": "source-1",
                "OPEN_CINEMA_LIBRESPOT_GENERATION": "g1",
                "PLAYER_EVENT": "playing",
            }
        )
        fresh = {**stale, "generation": "g2"}
        send(receiver.path, stale)
        send(receiver.path, fresh)
        deadline = time.monotonic() + 1
        while receiver.state().last_sequence < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        state = receiver.state()
        assert state.last_sequence == 1
        assert state.dropped == 1
        assert state.last_event["event"] == "playing"
    finally:
        receiver.stop()


def test_receiver_keeps_playback_transition_when_a_volume_event_follows(tmp_path: Path) -> None:
    receiver = EventReceiver(tmp_path / "events.sock", instance_id="source-1", generation="g2")
    receiver.start()
    try:
        playing = relay_document(
            {
                "OPEN_CINEMA_LIBRESPOT_INSTANCE_ID": "source-1",
                "OPEN_CINEMA_LIBRESPOT_GENERATION": "g2",
                "PLAYER_EVENT": "playing",
            }
        )
        volume = relay_document(
            {
                "OPEN_CINEMA_LIBRESPOT_INSTANCE_ID": "source-1",
                "OPEN_CINEMA_LIBRESPOT_GENERATION": "g2",
                "PLAYER_EVENT": "volume_changed",
                "VOLUME": "32768",
            }
        )
        send(receiver.path, playing)
        send(receiver.path, volume)
        deadline = time.monotonic() + 1
        while receiver.state().last_sequence < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        state = receiver.state()

        assert state.last_event["event"] == "volume_changed"
        assert state.last_playback_event["event"] == "playing"
    finally:
        receiver.stop()
