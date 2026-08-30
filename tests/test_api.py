from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from open_cinema_plugin_sdk import PluginConcurrencyError

from open_cinema_librespot.api import LibrespotAPI
from open_cinema_librespot.configuration import default_instance_configuration


def document(response) -> dict[str, object]:
    value = json.loads(response.content)
    assert isinstance(value, dict)
    return value


@pytest.mark.django_db
def test_multi_instance_crud_actions_and_concurrency_are_isolated() -> None:
    api = LibrespotAPI()
    factory = RequestFactory()
    user = get_user_model().objects.create_user(username="spotify-admin")

    def request(method: str, path: str, body: dict[str, object] | None = None):
        value = getattr(factory, method.lower())(
            path,
            data=json.dumps(body) if body is not None else None,
            content_type="application/json",
        )
        value.user = user
        return value

    first_config = default_instance_configuration(name="Living room")
    second_config = default_instance_configuration(name="Kitchen")
    first = document(api.create(request("PUT", "/create", first_config)))["data"]
    second = document(api.create(request("PUT", "/create", second_config)))["data"]
    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["id"] != second["id"]
    assert len(document(api.list_instances(request("GET", "/")))["items"]) == 2

    instance_id = str(first["id"])
    version = int(first["updateVersion"])
    updated_config = dict(first_config)
    updated_config["bitrate"] = 160
    updated_config["updateVersion"] = version
    updated = document(api.detail(request("PUT", f"/{instance_id}", updated_config), instance_id))[
        "data"
    ]
    assert isinstance(updated, dict)
    assert updated["configuration"]["bitrate"] == 160

    with pytest.raises(PluginConcurrencyError, match="refresh and retry"):
        api.action(
            request("POST", f"/{instance_id}/stop", {"concurrencyToken": str(version)}),
            instance_id,
            "stop",
        )

    current_version = int(updated["updateVersion"])
    stopped = document(
        api.action(
            request(
                "POST",
                f"/{instance_id}/stop",
                {"concurrencyToken": str(current_version)},
            ),
            instance_id,
            "stop",
        )
    )["data"]
    assert isinstance(stopped, dict)
    assert stopped["desiredState"] == "disabled"
    assert second["desiredState"] == "enabled"

    deleted = document(
        api.detail(
            request(
                "DELETE",
                f"/{instance_id}",
                {"concurrencyToken": str(stopped["updateVersion"])},
            ),
            instance_id,
        )
    )
    remaining = document(api.list_instances(request("GET", "/")))["items"]
    assert deleted == {"deleted": True}
    assert isinstance(remaining, list)
    assert [item["id"] for item in remaining] == [second["id"]]


@pytest.mark.django_db
def test_access_token_is_write_only_in_every_instance_document() -> None:
    api = LibrespotAPI()
    factory = RequestFactory()
    user = get_user_model().objects.create_user(username="token-admin")
    config = default_instance_configuration(name="Token source")
    config["authentication"]["mode"] = "access-token"
    config["accessToken"] = "spotify-secret-value"
    request = factory.put(
        "/create",
        data=json.dumps(config),
        content_type="application/json",
    )
    request.user = user

    created = document(api.create(request))["data"]
    encoded = json.dumps(created)

    assert "spotify-secret-value" not in encoded
    assert '"configured": true' in encoded


@pytest.mark.django_db
def test_non_staff_users_only_access_their_own_sources() -> None:
    api = LibrespotAPI()
    factory = RequestFactory()
    owner = get_user_model().objects.create_user(username="source-owner")
    visitor = get_user_model().objects.create_user(username="source-visitor")
    create_request = factory.put(
        "/create",
        data=json.dumps(default_instance_configuration(name="Private source")),
        content_type="application/json",
    )
    create_request.user = owner
    created = document(api.create(create_request))["data"]
    assert isinstance(created, dict)

    list_request = factory.get("/")
    list_request.user = visitor
    assert document(api.list_instances(list_request))["items"] == []

    detail_request = factory.get(f"/{created['id']}")
    detail_request.user = visitor
    with pytest.raises(PermissionError, match="another user"):
        api.detail(detail_request, str(created["id"]))
