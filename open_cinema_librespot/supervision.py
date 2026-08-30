from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import IO

from .events import EventReceiver, EventState
from .options import LaunchPlan


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class BoundedLogTail:
    def __init__(self, *, maximum_lines: int = 50, redactions: tuple[str, ...] = ()) -> None:
        self._lines: deque[str] = deque(maxlen=maximum_lines)
        self._redactions = tuple(item for item in redactions if item)
        self._lock = Lock()

    def append(self, value: bytes) -> None:
        line = value.decode("utf-8", errors="replace").rstrip()[:1024]
        for secret in self._redactions:
            line = line.replace(secret, "<redacted>")
        with self._lock:
            self._lines.append(line)

    def lines(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._lines)


@dataclass(frozen=True, slots=True)
class SupervisorObservation:
    desired: str
    lifecycle: str
    health: str
    generation: str | None
    started_at: str | None
    librespot_pid: int | None
    bridge_pid: int | None
    librespot_exit: int | None
    bridge_exit: int | None
    restart_count: int
    backoff_until: str | None
    last_error: str | None
    config_digest: str | None
    event_state: EventState
    librespot_log: tuple[str, ...]
    bridge_log: tuple[str, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "desiredState": self.desired,
            "lifecycle": self.lifecycle,
            "health": self.health,
            "generation": self.generation,
            "startedAt": self.started_at,
            "children": {
                "librespot": {"pid": self.librespot_pid, "exitCode": self.librespot_exit},
                "pipewireBridge": {"pid": self.bridge_pid, "exitCode": self.bridge_exit},
            },
            "restart": {
                "count": self.restart_count,
                "backoffUntil": self.backoff_until,
            },
            "lastError": self.last_error,
            "configurationDigest": self.config_digest,
            "events": {
                "lastSequence": self.event_state.last_sequence,
                "lastEvent": self.event_state.last_event,
                "lastPlaybackEvent": self.event_state.last_playback_event,
                "dropped": self.event_state.dropped,
            },
            "logs": {
                "librespot": list(self.librespot_log),
                "pipewireBridge": list(self.bridge_log),
            },
        }


class ResourceSupervisor:
    def __init__(
        self,
        *,
        stop_timeout_seconds: float = 3.0,
        restart_limit: int = 5,
        restart_window_seconds: float = 60.0,
    ) -> None:
        self.stop_timeout_seconds = stop_timeout_seconds
        self.restart_limit = restart_limit
        self.restart_window_seconds = restart_window_seconds
        self._lock = Lock()
        self._desired_running = False
        self._explicitly_stopped = True
        self._plan: LaunchPlan | None = None
        self._generation: str | None = None
        self._started_at: str | None = None
        self._librespot: subprocess.Popen[bytes] | None = None
        self._bridge: subprocess.Popen[bytes] | None = None
        self._receiver: EventReceiver | None = None
        self._librespot_log = BoundedLogTail()
        self._bridge_log = BoundedLogTail()
        self._restart_times: deque[float] = deque()
        self._backoff_until: float | None = None
        self._last_error: str | None = None
        self._config_digest: str | None = None

    @staticmethod
    def configuration_digest(plan: LaunchPlan) -> str:
        encoded = json.dumps(
            {
                "argv": plan.librespot_argv,
                "bridge": plan.bridge_argv,
                "environment": plan.redacted_environment,
                "properties": plan.pipewire_properties,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _bounded_environment(plan: LaunchPlan) -> dict[str, str]:
        allowed = {
            name: value
            for name in (
                "PATH",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "LANG",
                "LC_ALL",
                "TZ",
            )
            if (value := os.environ.get(name)) is not None
        }
        allowed.update(plan.environment)
        return allowed

    def start(self, plan: LaunchPlan, *, generation: str, event_socket: Path) -> None:
        digest = self.configuration_digest(plan)
        with self._lock:
            if (
                self._desired_running
                and self._config_digest == digest
                and self._librespot is not None
                and self._librespot.poll() is None
                and self._bridge is not None
                and self._bridge.poll() is None
            ):
                return
        self.stop()
        redactions = tuple(
            value for key, value in plan.environment.items() if key in {"LIBRESPOT_ACCESS_TOKEN"}
        )
        libre_log = BoundedLogTail(redactions=redactions)
        bridge_log = BoundedLogTail(redactions=redactions)
        receiver = EventReceiver(
            event_socket,
            instance_id=plan.environment["OPEN_CINEMA_LIBRESPOT_INSTANCE_ID"],
            generation=generation,
        )
        receiver.start()
        environment = self._bounded_environment(plan)
        try:
            librespot = subprocess.Popen(
                list(plan.librespot_argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                close_fds=True,
                process_group=0,
            )
            assert librespot.stdout is not None
            bridge = subprocess.Popen(
                list(plan.bridge_argv),
                stdin=librespot.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=environment,
                close_fds=True,
                process_group=librespot.pid,
            )
            librespot.stdout.close()
        except Exception:
            receiver.stop()
            if "librespot" in locals() and librespot.poll() is None:
                os.killpg(librespot.pid, signal.SIGKILL)
                librespot.wait(timeout=1)
            raise
        with self._lock:
            self._desired_running = True
            self._explicitly_stopped = False
            self._plan = plan
            self._generation = generation
            self._started_at = _utc_now()
            self._librespot = librespot
            self._bridge = bridge
            self._receiver = receiver
            self._librespot_log = libre_log
            self._bridge_log = bridge_log
            self._config_digest = digest
            self._last_error = None
        self._capture(librespot.stderr, libre_log, "librespot-stderr")
        self._capture(bridge.stderr, bridge_log, "pw-cat-stderr")
        Thread(
            target=self._monitor, args=(generation,), name="librespot-supervisor", daemon=True
        ).start()

    @staticmethod
    def _capture(stream: IO[bytes] | None, tail: BoundedLogTail, name: str) -> None:
        if stream is None:
            return

        def read() -> None:
            try:
                for line in iter(stream.readline, b""):
                    tail.append(line)
            finally:
                stream.close()

        Thread(target=read, name=name, daemon=True).start()

    def _monitor(self, generation: str) -> None:
        while True:
            time.sleep(0.1)
            with self._lock:
                if generation != self._generation or not self._desired_running:
                    return
                librespot = self._librespot
                bridge = self._bridge
                if librespot is None or bridge is None:
                    return
                libre_exit = librespot.poll()
                bridge_exit = bridge.poll()
                if libre_exit is None and bridge_exit is None:
                    continue
                self._last_error = (
                    f"managed process exited: librespot={libre_exit}, pw-cat={bridge_exit}"
                )
                plan = self._plan
                event_socket = self._receiver.path if self._receiver is not None else None
                now = time.monotonic()
                while (
                    self._restart_times
                    and now - self._restart_times[0] > self.restart_window_seconds
                ):
                    self._restart_times.popleft()
                self._restart_times.append(now)
                exhausted = len(self._restart_times) > self.restart_limit
                delay = min(0.25 * (2 ** max(len(self._restart_times) - 1, 0)), 8.0)
                self._backoff_until = None if exhausted else now + delay
            self._terminate_group(librespot)
            if exhausted or plan is None or event_socket is None:
                with self._lock:
                    self._desired_running = False
                return
            time.sleep(delay)
            try:
                self.start(plan, generation=generation, event_socket=event_socket)
            except Exception as error:
                with self._lock:
                    self._last_error = f"restart failed: {type(error).__name__}: {error}"
                    self._desired_running = False
            return

    def _terminate_group(self, leader: subprocess.Popen[bytes]) -> None:
        with suppress(ProcessLookupError):
            os.killpg(leader.pid, signal.SIGTERM)
        deadline = time.monotonic() + self.stop_timeout_seconds
        while time.monotonic() < deadline:
            with self._lock:
                children = tuple(
                    child for child in (self._librespot, self._bridge) if child is not None
                )
            if all(child.poll() is not None for child in children):
                break
            time.sleep(0.05)
        else:
            with suppress(ProcessLookupError):
                os.killpg(leader.pid, signal.SIGKILL)
        for child in children:
            with suppress(subprocess.TimeoutExpired):
                child.wait(timeout=1)

    def stop(self) -> None:
        with self._lock:
            self._desired_running = False
            self._explicitly_stopped = True
            leader = self._librespot
            receiver = self._receiver
        if leader is not None:
            self._terminate_group(leader)
        if receiver is not None:
            receiver.stop()
        with self._lock:
            self._librespot = None
            self._bridge = None
            self._receiver = None
            self._generation = None
            self._started_at = None
            self._backoff_until = None

    def observation(self) -> SupervisorObservation:
        with self._lock:
            librespot = self._librespot
            bridge = self._bridge
            running = (
                librespot is not None
                and bridge is not None
                and librespot.poll() is None
                and bridge.poll() is None
            )
            desired = "running" if self._desired_running else "stopped"
            if running:
                lifecycle, health = "running", "healthy"
            elif self._explicitly_stopped:
                lifecycle, health = "stopped", "healthy"
            elif self._last_error:
                lifecycle, health = "failed", "failed"
            else:
                lifecycle, health = "stopped", "healthy"
            backoff_until = None
            if self._backoff_until is not None:
                seconds = max(self._backoff_until - time.monotonic(), 0)
                backoff_until = datetime.fromtimestamp(time.time() + seconds, UTC).isoformat()
            event_state = (
                self._receiver.state() if self._receiver is not None else EventState(0, None, 0)
            )
            return SupervisorObservation(
                desired,
                lifecycle,
                health,
                self._generation,
                self._started_at,
                librespot.pid if librespot is not None else None,
                bridge.pid if bridge is not None else None,
                librespot.poll() if librespot is not None else None,
                bridge.poll() if bridge is not None else None,
                len(self._restart_times),
                backoff_until,
                self._last_error,
                self._config_digest,
                event_state,
                self._librespot_log.lines(),
                self._bridge_log.lines(),
            )


class SupervisorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ResourceSupervisor] = {}
        self._lock = Lock()

    def get(self, instance_id: str) -> ResourceSupervisor:
        with self._lock:
            return self._items.setdefault(instance_id, ResourceSupervisor())

    def stop(self, instance_id: str, *, remove: bool = False) -> None:
        with self._lock:
            supervisor = self._items.get(instance_id)
        if supervisor is not None:
            supervisor.stop()
        if remove:
            with self._lock:
                self._items.pop(instance_id, None)

    def stop_all(self) -> None:
        with self._lock:
            supervisors = tuple(self._items.values())
        for supervisor in supervisors:
            supervisor.stop()
