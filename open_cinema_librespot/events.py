from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Final

MAX_EVENT_BYTES: Final = 16 * 1024
ALLOWED_FIELDS: Final = {
    "PLAYER_EVENT",
    "TRACK_ID",
    "URI",
    "NAME",
    "DURATION_MS",
    "POSITION_MS",
    "ITEM_TYPE",
    "ALBUM",
    "ARTISTS",
    "USER_NAME",
    "CONNECTION_ID",
    "CLIENT_ID",
    "CLIENT_NAME",
    "CLIENT_BRAND_NAME",
    "CLIENT_MODEL_NAME",
    "VOLUME",
    "SINK_STATUS",
}

PLAYBACK_EVENTS: Final = {
    "playing",
    "paused",
    "stopped",
    "loading",
    "preloading",
    "end_of_track",
    "unavailable",
}


def playback_event_name(document: Mapping[str, object] | None) -> str | None:
    if document is None:
        return None
    name = document.get("event")
    if not isinstance(name, str):
        return None
    if name in PLAYBACK_EVENTS:
        return name
    if name != "sink":
        return None
    fields = document.get("fields")
    if not isinstance(fields, Mapping):
        return None
    status = fields.get("SINK_STATUS")
    if not isinstance(status, str):
        return None
    normalized = status.casefold()
    if normalized not in {"running", "temporarily-closed", "closed"}:
        return None
    return f"sink:{normalized}"


def relay_document(environment: dict[str, str] | None = None) -> dict[str, object]:
    values = environment if environment is not None else dict(os.environ)
    return {
        "schemaVersion": 1,
        "instanceId": values.get("OPEN_CINEMA_LIBRESPOT_INSTANCE_ID", ""),
        "generation": values.get("OPEN_CINEMA_LIBRESPOT_GENERATION", ""),
        "observedAtUnixMs": int(time.time() * 1000),
        "event": values.get("PLAYER_EVENT", "unknown")[:64],
        "fields": {
            key: values[key][:4096]
            for key in sorted(ALLOWED_FIELDS)
            if key in values and key != "PLAYER_EVENT"
        },
    }


def relay_main() -> int:
    target = os.environ.get("OPEN_CINEMA_LIBRESPOT_EVENT_SOCKET")
    if not target:
        return 64
    encoded = json.dumps(relay_document(), separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        return 65
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.settimeout(0.5)
            client.sendto(encoded, target)
    except OSError:
        return 69
    return 0


@dataclass(frozen=True, slots=True)
class EventState:
    last_sequence: int
    last_event: dict[str, object] | None
    dropped: int
    last_playback_event: dict[str, object] | None = None


class EventReceiver:
    def __init__(self, path: Path, *, instance_id: str, generation: str) -> None:
        self.path = path
        self.instance_id = instance_id
        self.generation = generation
        self._events: deque[dict[str, object]] = deque(maxlen=256)
        self._dropped = 0
        self._sequence = 0
        self._last_playback_event: dict[str, object] | None = None
        self._lock = Lock()
        self._stop = Event()
        self._socket: socket.socket | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self.path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        server.bind(str(self.path))
        self.path.chmod(0o600)
        server.settimeout(0.25)
        self._socket = server
        self._thread = Thread(target=self._run, name="librespot-events", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                encoded = self._socket.recv(MAX_EVENT_BYTES + 1)
            except TimeoutError:
                continue
            except OSError:
                break
            if len(encoded) > MAX_EVENT_BYTES:
                self._dropped += 1
                continue
            try:
                value = json.loads(encoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._dropped += 1
                continue
            if (
                not isinstance(value, dict)
                or value.get("schemaVersion") != 1
                or value.get("instanceId") != self.instance_id
                or value.get("generation") != self.generation
            ):
                self._dropped += 1
                continue
            with self._lock:
                self._sequence += 1
                value["sequence"] = self._sequence
                self._events.append(value)
                if playback_event_name(value) is not None:
                    self._last_playback_event = value

    def state(self) -> EventState:
        with self._lock:
            return EventState(
                self._sequence,
                dict(self._events[-1]) if self._events else None,
                self._dropped,
                dict(self._last_playback_event) if self._last_playback_event else None,
            )

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self.path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(relay_main())
