from pathlib import Path
from types import SimpleNamespace

import pytest
from api.models import PluginDesiredState
from core.plugin_system.storage import PluginInstallationRepository
from django.contrib.auth import get_user_model
from open_cinema_plugin_sdk import PluginInstanceStore, PluginSecretStore

from open_cinema_librespot.configuration import (
    default_instance_configuration,
    instance_schema,
)
from open_cinema_librespot.oauth import (
    OAuthOperations,
    oauth_refresh_secret_id,
    refresh_oauth_access_token,
)
from open_cinema_librespot.provider import access_token_secret_id


@pytest.mark.django_db
def test_guided_oauth_persists_only_public_state_and_write_only_secrets(
    monkeypatch,
    settings,
    tmp_path,
):
    settings.OPEN_CINEMA_PLUGIN_RUNTIME_DIR = str(tmp_path / "runtime")
    user = get_user_model().objects.create_user(username="oauth-owner")
    instances = PluginInstanceStore(
        plugin_id="open-cinema.librespot",
        capability_id="open-cinema.librespot.sources",
        schema_id="open-cinema.librespot.instance",
        schema_version=1,
        schema=instance_schema(),
    )
    secrets = PluginSecretStore("open-cinema.librespot")
    item = instances.create(
        instance_id="oauth-test",
        display_name="OAuth test",
        configuration=default_instance_configuration(name="OAuth test"),
        owner_id=user.pk,
    )
    operations = OAuthOperations(instances, secrets)
    helper = tmp_path / "oauth-helper"
    helper.write_text("fixture")
    monkeypatch.setattr(
        "open_cinema_librespot.oauth.load_runtime_assets",
        lambda: SimpleNamespace(oauth_helper=helper),
    )
    calls = []

    def run(arguments, *, input_value=None, timeout):
        calls.append((arguments, input_value, timeout))
        if arguments[1] == "begin":
            return {
                "schemaVersion": 1,
                "state": "waiting-for-callback",
                "authorizationUrl": "https://accounts.spotify.test/authorize?state=opaque",
                "expiresInSeconds": 600,
            }
        return {
            "schemaVersion": 1,
            "state": "succeeded",
            "accessToken": "access-secret",
            "refreshToken": "refresh-secret",
            "expiresInSeconds": 3600,
            "scopes": ["streaming"],
        }

    monkeypatch.setattr(operations, "_run", run)

    waiting = operations.begin(item.instance_id)
    succeeded = operations.exchange(
        item.instance_id,
        "http://127.0.0.1:0/login?code=very-secret&state=opaque",
    )

    assert waiting["state"] == "waiting-for-callback"
    assert succeeded["state"] == "succeeded"
    assert "accessToken" not in succeeded
    assert "refreshToken" not in succeeded
    assert secrets.presence(access_token_secret_id(item.instance_id))["configured"] is True
    updated = instances.get(item.instance_id)
    assert updated.configuration["authentication"]["mode"] == "oauth-cache"
    assert updated.configuration["cache"]["credentialsEnabled"] is True
    exchange_arguments, callback_stdin, _timeout = calls[-1]
    assert "very-secret" not in " ".join(exchange_arguments)
    assert callback_stdin.endswith("code=very-secret&state=opaque")


@pytest.mark.django_db
def test_oauth_cancel_removes_private_pending_state(monkeypatch, settings, tmp_path):
    settings.OPEN_CINEMA_PLUGIN_RUNTIME_DIR = str(tmp_path / "runtime")
    instances = PluginInstanceStore(
        plugin_id="open-cinema.librespot",
        capability_id="open-cinema.librespot.sources",
        schema_id="open-cinema.librespot.instance",
        schema_version=1,
        schema=instance_schema(),
    )
    item = instances.create(
        instance_id="oauth-cancel",
        display_name="OAuth cancel",
        configuration=default_instance_configuration(name="OAuth cancel"),
    )
    operations = OAuthOperations(instances, PluginSecretStore("open-cinema.librespot"))
    helper = Path(tmp_path / "oauth-helper")
    helper.write_text("fixture")
    monkeypatch.setattr(
        "open_cinema_librespot.oauth.load_runtime_assets",
        lambda: SimpleNamespace(oauth_helper=helper),
    )
    monkeypatch.setattr(
        operations,
        "_run",
        lambda *args, **kwargs: {
            "schemaVersion": 1,
            "state": "waiting-for-callback",
            "authorizationUrl": "https://accounts.spotify.test/authorize",
            "expiresInSeconds": 600,
        },
    )
    operations.begin(item.instance_id)
    state_path = operations._state_path(item.instance_id)
    state_path.write_text("private")

    cancelled = operations.cancel(item.instance_id)

    assert cancelled["state"] == "cancelled"
    assert not state_path.exists()


@pytest.mark.django_db
def test_oauth_failure_never_reflects_malicious_callback_text(
    monkeypatch,
    settings,
    tmp_path,
):
    settings.OPEN_CINEMA_PLUGIN_RUNTIME_DIR = str(tmp_path / "runtime")
    instances = PluginInstanceStore(
        plugin_id="open-cinema.librespot",
        capability_id="open-cinema.librespot.sources",
        schema_id="open-cinema.librespot.instance",
        schema_version=1,
        schema=instance_schema(),
    )
    item = instances.create(
        instance_id="oauth-malicious-callback",
        display_name="OAuth malicious callback",
        configuration=default_instance_configuration(name="OAuth malicious callback"),
    )
    operations = OAuthOperations(instances, PluginSecretStore("open-cinema.librespot"))
    helper = tmp_path / "oauth-helper"
    helper.write_text("fixture")
    monkeypatch.setattr(
        "open_cinema_librespot.oauth.load_runtime_assets",
        lambda: SimpleNamespace(oauth_helper=helper),
    )
    callback_secret = "callback-code-that-must-not-leak"

    def run(arguments, *, input_value=None, timeout):
        if arguments[1] == "begin":
            return {
                "schemaVersion": 1,
                "state": "waiting-for-callback",
                "authorizationUrl": "https://accounts.spotify.test/authorize",
                "expiresInSeconds": 600,
            }
        raise ValueError(f"rejected callback: {input_value}")

    monkeypatch.setattr(operations, "_run", run)
    operations.begin(item.instance_id)

    with pytest.raises(ValueError, match="Spotify authorization failed") as error:
        operations.exchange(
            item.instance_id,
            f"http://127.0.0.1/login?code={callback_secret}",
        )

    status = operations.status(item.instance_id)
    assert status is not None
    assert status["state"] == "failed"
    assert callback_secret not in str(error.value)
    assert callback_secret not in str(status)


@pytest.mark.django_db
def test_oauth_refresh_rotates_write_only_tokens_via_stdin(monkeypatch, settings, tmp_path):
    settings.OPEN_CINEMA_PLUGIN_RUNTIME_DIR = str(tmp_path / "runtime")
    PluginInstallationRepository.save_snapshot(
        plugin_id="open-cinema.librespot",
        distribution_id="open-cinema-librespot",
        installed_version="0.1.0",
        manifest={"id": "open-cinema.librespot", "version": "0.1.0"},
        provenance={"sourceType": "test"},
        lifecycle_impact={"enable": "hot", "disable": "hot"},
        desired_state=PluginDesiredState.ENABLED,
    )
    instances = PluginInstanceStore(
        plugin_id="open-cinema.librespot",
        capability_id="open-cinema.librespot.sources",
        schema_id="open-cinema.librespot.instance",
        schema_version=1,
        schema=instance_schema(),
    )
    item = instances.create(
        instance_id="oauth-refresh",
        display_name="OAuth refresh",
        configuration=default_instance_configuration(name="OAuth refresh"),
    )
    secrets = PluginSecretStore("open-cinema.librespot")
    refresh_id = oauth_refresh_secret_id(item.instance_id)
    secrets.set(refresh_id, "old-refresh-secret")
    helper = tmp_path / "oauth-helper"
    helper.write_text("fixture")
    monkeypatch.setattr(
        "open_cinema_librespot.oauth.load_runtime_assets",
        lambda: SimpleNamespace(oauth_helper=helper),
    )
    calls = []

    def run(arguments, *, input_value=None, timeout):
        calls.append((arguments, input_value, timeout))
        return {
            "schemaVersion": 1,
            "state": "succeeded",
            "accessToken": "fresh-access-secret",
            "refreshToken": "fresh-refresh-secret",
        }

    monkeypatch.setattr(OAuthOperations, "_run", run)
    context = instances.context(item.instance_id)

    access_token = refresh_oauth_access_token(context)

    assert access_token == "fresh-access-secret"
    arguments, token_stdin, _timeout = calls[0]
    assert arguments[-2:] == ["refresh", "--token-stdin"]
    assert "old-refresh-secret" not in " ".join(arguments)
    assert token_stdin == "old-refresh-secret"
    assert context.host_services is not None
    assert context.host_services.resolve_secret(refresh_id) == b"fresh-refresh-secret"
    assert context.host_services.resolve_secret(access_token_secret_id(item.instance_id)) == (
        b"fresh-access-secret"
    )
