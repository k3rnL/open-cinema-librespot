from __future__ import annotations

import json
from pathlib import Path

from open_cinema_plugin_sdk import (
    managed_source_endpoint_id,
    validate_runtime_plugin,
    validate_source_checkout,
)

from open_cinema_librespot.plugin import LibrespotPlugin
from open_cinema_librespot.ui import ADMIN_UI


def test_source_and_runtime_match_public_plugin_contract() -> None:
    root = Path(__file__).resolve().parent.parent
    manifest = validate_source_checkout(root)

    identifiers = validate_runtime_plugin(manifest, LibrespotPlugin())

    assert manifest.plugin_id == "open-cinema.librespot"
    assert len(identifiers) == 6


def test_declarative_ui_has_no_raw_json_or_private_frontend_code() -> None:
    widgets = {
        field["widget"]
        for page in ADMIN_UI["pages"]
        for section in page["sections"]
        for field in section["fields"]
    }

    assert "json" not in widgets
    assert {item["template"] for item in ADMIN_UI["pages"]} == {
        "resource-list",
        "guided-flow",
    }


def test_acceptance_graph_uses_only_the_stable_managed_source_identity() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "spotify_tv_headset_graph.json"
    fixture = json.loads(fixture_path.read_text())
    endpoint_id = managed_source_endpoint_id(
        "open-cinema.librespot",
        "open-cinema.librespot.sources",
        fixture["librespotInstanceId"],
    )

    assert fixture["logicalEndpoints"][0]["id"] == endpoint_id
    encoded = json.dumps(fixture)
    assert "runtime:" not in encoded
    assert "nodeId" not in encoded
