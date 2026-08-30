from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

from open_cinema_librespot.options import LaunchPlan
from open_cinema_librespot.supervision import ResourceSupervisor, SupervisorRegistry

FIXTURES = Path(__file__).parent / "fixtures"


def plan(
    *,
    bridge_exit: int | None = None,
    librespot_exit: int | None = None,
    ignore_term: bool = False,
    node_name: str = "test-source",
) -> LaunchPlan:
    environment = {
        "OPEN_CINEMA_LIBRESPOT_INSTANCE_ID": "source-1",
        "OPEN_CINEMA_LIBRESPOT_GENERATION": "g1",
        "LIBRESPOT_ACCESS_TOKEN": "do-not-log-this",
    }
    if bridge_exit is not None:
        environment["FAKE_BRIDGE_EXIT"] = str(bridge_exit)
    if librespot_exit is not None:
        environment["FAKE_LIBRESPOT_EXIT"] = str(librespot_exit)
    if ignore_term:
        environment["FAKE_IGNORE_TERM"] = "1"
    return LaunchPlan(
        (sys.executable, str(FIXTURES / "fake_librespot.py")),
        (sys.executable, str(FIXTURES / "fake_pw_cat.py")),
        environment,
        {key: "<redacted>" if "TOKEN" in key else value for key, value in environment.items()},
        {"node.name": node_name},
    )


def wait_for(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not converge")


def test_supervisor_owns_both_children_and_redacts_logs(tmp_path: Path) -> None:
    supervisor = ResourceSupervisor(stop_timeout_seconds=0.5)
    supervisor.start(plan(), generation="g1", event_socket=tmp_path / "events.sock")
    wait_for(lambda: supervisor.observation().lifecycle == "running")
    wait_for(lambda: bool(supervisor.observation().librespot_log))
    observation = supervisor.observation()
    pids = (observation.librespot_pid, observation.bridge_pid)

    assert pids[0] and pids[1]
    assert "do-not-log-this" not in "\n".join(observation.librespot_log)
    assert "<redacted>" in "\n".join(observation.librespot_log)
    supervisor.stop()

    assert supervisor.observation().lifecycle == "stopped"
    for pid in pids:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            continue
        raise AssertionError(f"child {pid} survived supervisor stop")


def test_early_bridge_exit_stops_the_whole_generation(tmp_path: Path) -> None:
    supervisor = ResourceSupervisor(stop_timeout_seconds=0.3, restart_limit=0)
    supervisor.start(plan(bridge_exit=17), generation="g1", event_socket=tmp_path / "events.sock")
    wait_for(lambda: supervisor.observation().lifecycle == "failed")
    observation = supervisor.observation()

    assert observation.health == "failed"
    assert "pw-cat=17" in str(observation.last_error)
    assert observation.restart_count == 1
    supervisor.stop()


def test_restart_storm_after_early_librespot_exit_is_bounded(tmp_path: Path) -> None:
    supervisor = ResourceSupervisor(
        stop_timeout_seconds=0.2,
        restart_limit=1,
        restart_window_seconds=5,
    )
    supervisor.start(
        plan(librespot_exit=19),
        generation="failing-generation",
        event_socket=tmp_path / "events.sock",
    )

    wait_for(
        lambda: (
            supervisor.observation().lifecycle == "failed"
            and supervisor.observation().restart_count >= 2
        ),
        timeout=3,
    )
    observation = supervisor.observation()
    assert observation.desired == "stopped"
    assert "librespot=19" in str(observation.last_error)
    supervisor.stop()


def test_configuration_change_reaps_only_that_generation(tmp_path: Path) -> None:
    registry = SupervisorRegistry()
    living_room = registry.get("living-room")
    kitchen = registry.get("kitchen")
    living_room.start(
        plan(node_name="living-room-v1"),
        generation="living-room-v1",
        event_socket=tmp_path / "living-room-v1.sock",
    )
    kitchen.start(
        plan(node_name="kitchen"),
        generation="kitchen-v1",
        event_socket=tmp_path / "kitchen.sock",
    )
    wait_for(lambda: living_room.observation().lifecycle == "running")
    wait_for(lambda: kitchen.observation().lifecycle == "running")
    previous_pid = living_room.observation().librespot_pid
    kitchen_pid = kitchen.observation().librespot_pid

    living_room.start(
        plan(node_name="living-room-v2"),
        generation="living-room-v2",
        event_socket=tmp_path / "living-room-v2.sock",
    )
    wait_for(
        lambda: (
            living_room.observation().lifecycle == "running"
            and living_room.observation().librespot_pid != previous_pid
        )
    )

    assert kitchen.observation().lifecycle == "running"
    assert kitchen.observation().librespot_pid == kitchen_pid
    if previous_pid is not None:
        with pytest.raises(ProcessLookupError):
            os.kill(previous_pid, 0)

    living_room.restart_limit = 0
    current_pid = living_room.observation().librespot_pid
    assert current_pid is not None
    os.killpg(current_pid, signal.SIGTERM)
    wait_for(lambda: living_room.observation().lifecycle == "failed")
    assert kitchen.observation().lifecycle == "running"
    assert kitchen.observation().librespot_pid == kitchen_pid

    registry.stop_all()
    assert living_room.observation().lifecycle == "stopped"
    assert kitchen.observation().lifecycle == "stopped"


def test_forced_stop_reaps_children_that_ignore_sigterm(tmp_path: Path) -> None:
    supervisor = ResourceSupervisor(stop_timeout_seconds=0.05)
    supervisor.start(
        plan(ignore_term=True),
        generation="stalled-generation",
        event_socket=tmp_path / "events.sock",
    )
    wait_for(lambda: supervisor.observation().lifecycle == "running")
    pids = (
        supervisor.observation().librespot_pid,
        supervisor.observation().bridge_pid,
    )

    supervisor.stop()

    assert supervisor.observation().lifecycle == "stopped"
    for pid in pids:
        if pid is not None:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
