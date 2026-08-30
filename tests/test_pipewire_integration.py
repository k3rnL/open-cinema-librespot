from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from open_cinema_librespot.configuration import default_instance_configuration
from open_cinema_librespot.options import InstancePaths, build_launch_plan
from open_cinema_librespot.supervision import ResourceSupervisor

pytestmark = pytest.mark.pipewire_integration


def snapshot() -> list[dict[str, object]]:
    completed = subprocess.run(
        ["pw-dump"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, list)
    return [item for item in value if isinstance(item, dict)]


def matching_node(items: list[dict[str, object]], instance_id: str) -> dict[str, object] | None:
    for item in items:
        info = item.get("info")
        if not isinstance(info, dict):
            continue
        properties = info.get("props")
        if (
            item.get("type") == "PipeWire:Interface:Node"
            and isinstance(properties, dict)
            and properties.get("open-cinema.instance.id") == instance_id
        ):
            return item
    return None


def wait_for_node(instance_id: str, *, present: bool) -> dict[str, object] | None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        node = matching_node(snapshot(), instance_id)
        if (node is not None) is present:
            return node
        time.sleep(0.05)
    raise AssertionError(f"PipeWire node presence did not become {present}")


@pytest.mark.skipif(
    os.environ.get("OPEN_CINEMA_PIPEWIRE_INTEGRATION") != "1",
    reason="requires an explicitly selected live PipeWire server",
)
def test_real_bridge_is_unlinked_correlated_and_removed(tmp_path: Path) -> None:
    pw_cat = shutil.which("pw-cat")
    pw_dump = shutil.which("pw-dump")
    if not pw_cat or not pw_dump:
        pytest.skip("PipeWire command-line clients are unavailable")
    instance_id = "integration-source"
    relay = tmp_path / "event-relay"
    relay.write_text("fixture")
    paths = InstancePaths(
        tmp_path / "temporary",
        tmp_path / "audio-cache",
        tmp_path / "system-cache",
        relay,
        tmp_path / "events.sock",
    )
    fake_librespot = Path(__file__).parent / "fixtures" / "fake_librespot.py"
    plan = build_launch_plan(
        librespot_binary=fake_librespot,
        pw_cat_binary=pw_cat,
        instance_id=instance_id,
        generation="integration-generation",
        configuration=default_instance_configuration(name="Integration source"),
        paths=paths,
    )
    supervisor = ResourceSupervisor(stop_timeout_seconds=1)

    try:
        supervisor.start(
            plan,
            generation="integration-generation",
            event_socket=paths.event_socket,
        )
        node = wait_for_node(instance_id, present=True)
        assert node is not None
        info = node["info"]
        assert isinstance(info, dict)
        properties = info["props"]
        assert isinstance(properties, dict)
        assert properties["open-cinema.plugin.id"] == "open-cinema.librespot"
        assert properties["open-cinema.generation"] == "integration-generation"
        assert properties["node.autoconnect"] in {False, "false"}
        node_id = node["id"]
        links = [item for item in snapshot() if item.get("type") == "PipeWire:Interface:Link"]
        for link in links:
            link_info = link.get("info")
            assert not (
                isinstance(link_info, dict)
                and node_id in {link_info.get("output-node-id"), link_info.get("input-node-id")}
            )
    finally:
        supervisor.stop()

    assert wait_for_node(instance_id, present=False) is None
