from __future__ import annotations

import os
import shutil
import sys
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from open_cinema_plugin_sdk import (
    ActionConfirmation,
    LifecycleImpact,
    ManagedResourceContext,
    ManagedResourceObservation,
    PluginActionDescriptor,
    PluginRuntimeResult,
    RuntimeStatus,
    managed_source_endpoint_id,
)

from .events import playback_event_name
from .options import InstancePaths, build_launch_plan, detect_pw_cat_raw_mode
from .runtime_assets import RuntimeAssetError, load_runtime_assets
from .supervision import SupervisorObservation, SupervisorRegistry


def _now() -> str:
    return datetime.now(UTC).isoformat()


def access_token_secret_id(instance_id: str) -> str:
    return f"open-cinema.librespot.access-token.{instance_id}"


class LibrespotProvider:
    def __init__(self) -> None:
        self.supervisors = SupervisorRegistry()
        self._event_lock = Lock()
        self._dispatched_sequences: dict[tuple[str, str | None, str | None], int] = {}
        self._automation_errors: dict[str, list[dict[str, str]]] = {}

    def _dispatch_events(
        self,
        context: ManagedResourceContext,
        observation: SupervisorObservation,
    ) -> None:
        event = observation.event_state.last_event
        services = context.host_services
        generation = observation.generation
        sequence = observation.event_state.last_sequence
        if event is None or services is None or sequence <= 0:
            return
        key = (context.instance_id, generation, observation.started_at)
        with self._event_lock:
            for previous_key in tuple(self._dispatched_sequences):
                if previous_key[0] == context.instance_id and previous_key != key:
                    self._dispatched_sequences.pop(previous_key, None)
            if sequence <= self._dispatched_sequences.get(key, 0):
                return
            self._dispatched_sequences[key] = sequence
        automations = context.configuration.get("automations", {})
        event_ids = automations.get("eventIds", []) if isinstance(automations, Mapping) else []
        errors = []
        for automation_id in event_ids:
            if not isinstance(automation_id, str):
                continue
            try:
                services.invoke_automation(
                    automation_id,
                    {
                        "pluginId": context.plugin_id,
                        "instanceId": context.instance_id,
                        "generation": generation,
                        "sequence": sequence,
                        "event": event,
                    },
                )
            except Exception as error:
                errors.append(
                    {
                        "automationId": automation_id,
                        "exception": type(error).__name__,
                        "message": str(error)[:256],
                    }
                )
        with self._event_lock:
            self._automation_errors[context.instance_id] = errors

    @staticmethod
    def _paths(context: ManagedResourceContext) -> InstancePaths:
        services = context.host_services
        if services is None:
            raise RuntimeError("Open Cinema host services are unavailable")
        # Keep the virtual-environment path. Resolving the Python symlink would jump
        # to /usr/bin and lose the console scripts installed beside the interpreter.
        event_relay = Path(sys.executable).parent / "open-cinema-librespot-event-relay"
        socket_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{context.plugin_id}:{context.instance_id}",
        ).hex[:24]
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        socket_root = (
            Path(xdg_runtime) / "open-cinema" / "librespot"
            if xdg_runtime
            else Path("/tmp") / f"open-cinema-{os.getuid()}" / "librespot"
        )
        event_socket = socket_root / f"{socket_id}.sock"
        if len(os.fsencode(event_socket)) >= 100:
            event_socket = (
                Path("/tmp") / f"open-cinema-{os.getuid()}" / "librespot" / f"{socket_id}.sock"
            )
        return InstancePaths(
            Path(services.private_directory("temporary")),
            Path(services.private_directory("audio-cache")),
            Path(services.private_directory("system-cache")),
            event_relay,
            event_socket,
        )

    @staticmethod
    def _playback_facts(observation: SupervisorObservation, hold_ms: int) -> dict[str, object]:
        event = observation.event_state.last_playback_event
        if event is None and playback_event_name(observation.event_state.last_event) is not None:
            event = observation.event_state.last_event
        name = playback_event_name(event) or "unknown"
        playback = {
            "playing": "playing",
            "paused": "paused",
            "stopped": "stopped",
            "loading": "loading",
            "preloading": "loading",
            "end_of_track": "stopped",
            "unavailable": "error",
            "sink:running": "playing",
            "sink:temporarily-closed": "paused",
            "sink:closed": "stopped",
        }.get(name, "idle" if observation.health == "healthy" else "unknown")
        active = playback == "playing"
        held = False
        if not active and event is not None and playback in {"paused", "stopped", "loading"}:
            observed_at = event.get("observedAtUnixMs")
            if isinstance(observed_at, int):
                age_ms = max(int(time.time() * 1000) - observed_at, 0)
                held = age_ms <= hold_ms
                active = held
        return {
            "playbackState": playback,
            "activeSignal": active,
            "activityHeld": held,
            "lastPlaybackEvent": name,
        }

    @staticmethod
    def _directory_size(path: Path, *, maximum_entries: int = 10_000) -> int:
        total = 0
        visited = 0
        try:
            for candidate in path.rglob("*"):
                if visited >= maximum_entries:
                    break
                visited += 1
                try:
                    if candidate.is_file():
                        total += candidate.stat().st_size
                except OSError:
                    continue
        except OSError:
            return 0
        return total

    def _runtime_result(self, context: ManagedResourceContext) -> PluginRuntimeResult:
        observation = self.supervisors.get(context.instance_id).observation()
        hold = int(context.configuration.get("activityHoldMs", 1500))
        playback = self._playback_facts(observation, hold)
        paths = self._paths(context)
        try:
            runtime_metadata = load_runtime_assets().metadata
        except RuntimeAssetError:
            runtime_metadata = {}
        status = {
            "healthy": RuntimeStatus.READY,
            "degraded": RuntimeStatus.DEGRADED,
            "failed": RuntimeStatus.FAILED,
        }.get(observation.health, RuntimeStatus.UNAVAILABLE)
        facts = {
            **observation.to_document(),
            **playback,
            "instanceId": context.instance_id,
            "connectName": context.configuration.get("name"),
            "authenticationMode": context.configuration.get("authentication", {}).get("mode"),
            "routeAvailable": observation.lifecycle == "running",
            "pipewireCorrelation": "pending" if observation.lifecycle == "running" else "missing",
            "logicalEndpointId": managed_source_endpoint_id(
                context.plugin_id,
                context.capability_id,
                context.instance_id,
            ),
            "signal": {
                "content": "pcm",
                "format": "FLOAT32LE",
                "rate": 44100,
                "channels": 2,
                "positions": ["FL", "FR"],
            },
            "librespotVersion": runtime_metadata.get("librespotVersion"),
            "pluginVersion": runtime_metadata.get("pluginVersion"),
            "cache": {
                "audioBytes": self._directory_size(paths.audio_cache),
                "systemBytes": self._directory_size(paths.system_cache),
            },
            "automationErrors": list(self._automation_errors.get(context.instance_id, [])),
        }
        return PluginRuntimeResult(
            status,
            facts=facts,
            details={"effectiveConfiguration": context.configuration.to_dict()},
            concurrency_token=context.concurrency_token,
        )

    def actions(self, context: ManagedResourceContext) -> tuple[PluginActionDescriptor, ...]:
        observation = self.supervisors.get(context.instance_id).observation()
        running = observation.lifecycle == "running"
        return (
            PluginActionDescriptor(
                "start",
                "Start",
                not running,
                LifecycleImpact.HOT,
                reason="The instance is already running." if running else None,
                concurrency_token=context.concurrency_token,
            ),
            PluginActionDescriptor(
                "stop",
                "Stop",
                running,
                LifecycleImpact.HOT,
                ActionConfirmation.DISCONNECTING,
                reason="The instance is already stopped." if not running else None,
                concurrency_token=context.concurrency_token,
            ),
            PluginActionDescriptor(
                "restart",
                "Restart",
                running,
                LifecycleImpact.HOT,
                ActionConfirmation.DISCONNECTING,
                reason="Start the instance before restarting it." if not running else None,
                concurrency_token=context.concurrency_token,
            ),
        )

    def observe(self, context: ManagedResourceContext) -> ManagedResourceObservation:
        supervisor_observation = self.supervisors.get(context.instance_id).observation()
        self._dispatch_events(context, supervisor_observation)
        return ManagedResourceObservation(
            self._runtime_result(context),
            _now(),
            1000,
            tuple(self.actions(context)),
        )

    def prepare(self, context: ManagedResourceContext) -> PluginRuntimeResult:
        try:
            assets = load_runtime_assets()
            paths = self._paths(context)
            if not paths.event_relay.is_file():
                raise RuntimeAssetError("the fixed event relay executable is unavailable")
            pw_cat = shutil.which("pw-cat")
            if pw_cat is None:
                raise RuntimeAssetError("pw-cat is unavailable")
            return PluginRuntimeResult(
                RuntimeStatus.READY,
                facts={
                    "librespotVersion": assets.metadata["librespotVersion"],
                    "librespotBinary": str(assets.librespot),
                    "pwCatBinary": pw_cat,
                    "pwCatRawMode": detect_pw_cat_raw_mode(pw_cat),
                },
            )
        except (OSError, RuntimeAssetError, RuntimeError) as error:
            return PluginRuntimeResult(
                RuntimeStatus.UNAVAILABLE,
                details={"code": "runtime-prerequisite-unavailable", "message": str(error)},
            )

    def activate(self, context: ManagedResourceContext) -> PluginRuntimeResult:
        prepared = self.prepare(context)
        if prepared.status is not RuntimeStatus.READY:
            return prepared
        assert context.host_services is not None
        assets = load_runtime_assets()
        paths = self._paths(context)
        token = None
        authentication = context.configuration.get("authentication", {})
        if authentication.get("mode") in {"access-token", "oauth-cache"}:
            secret_id = access_token_secret_id(context.instance_id)
            if authentication.get("mode") == "oauth-cache":
                try:
                    from .oauth import refresh_oauth_access_token

                    token = refresh_oauth_access_token(context)
                except (OSError, RuntimeError, UnicodeError, ValueError) as error:
                    return PluginRuntimeResult(
                        RuntimeStatus.UNAVAILABLE,
                        details={
                            "code": "oauth-refresh-failed",
                            "message": f"Spotify authorization must be renewed: {error}",
                        },
                    )
            token_present = context.host_services.secret_presence(secret_id)
            if authentication.get("mode") == "access-token" and not token_present:
                return PluginRuntimeResult(
                    RuntimeStatus.UNAVAILABLE,
                    details={
                        "code": "access-token-required",
                        "message": "Configure an access token.",
                    },
                )
            if token is None and token_present:
                token = context.host_services.resolve_secret(secret_id).decode("utf-8")
        generation = uuid.uuid4().hex
        plan = build_launch_plan(
            librespot_binary=assets.librespot,
            pw_cat_binary=str(prepared.facts["pwCatBinary"]),
            instance_id=context.instance_id,
            generation=generation,
            configuration=context.configuration,
            paths=paths,
            access_token=token,
            pw_cat_raw_mode=bool(prepared.facts["pwCatRawMode"]),
        )
        self.supervisors.get(context.instance_id).start(
            plan, generation=generation, event_socket=paths.event_socket
        )
        return self._runtime_result(context)

    def reconfigure(self, context: ManagedResourceContext) -> PluginRuntimeResult:
        self.supervisors.stop(context.instance_id)
        return self.activate(context)

    def deactivate(self, context: ManagedResourceContext) -> PluginRuntimeResult:
        self.supervisors.stop(context.instance_id)
        return self._runtime_result(context)

    def cleanup(self, context: ManagedResourceContext) -> PluginRuntimeResult:
        self.supervisors.stop(context.instance_id, remove=True)
        services = context.host_services
        if services is None:
            raise RuntimeError("Open Cinema host services are unavailable")
        removed = []
        for purpose in ("temporary", "audio-cache", "system-cache", "runtime", "oauth"):
            directory = Path(services.private_directory(purpose))
            shutil.rmtree(directory)
            removed.append(purpose)
        return PluginRuntimeResult(
            RuntimeStatus.READY,
            facts={
                "desiredState": "stopped",
                "lifecycle": "stopped",
                "health": "healthy",
                "routeAvailable": False,
                "cleanedPrivateDirectories": removed,
            },
            concurrency_token=context.concurrency_token,
        )

    def execute(self, action_id: str, context: ManagedResourceContext) -> PluginRuntimeResult:
        if action_id == "start":
            return self.activate(context)
        if action_id == "stop":
            return self.deactivate(context)
        if action_id == "restart":
            return self.reconfigure(context)
        raise ValueError(f"unsupported librespot action {action_id!r}")


PROVIDER = LibrespotProvider()
