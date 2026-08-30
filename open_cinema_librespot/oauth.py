from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from open_cinema_plugin_sdk import (
    ManagedResourceContext,
    PluginDocumentStore,
    PluginInstanceStore,
    PluginSecretStore,
)

from .provider import access_token_secret_id
from .runtime_assets import load_runtime_assets

PLUGIN_ID = "open-cinema.librespot"
OAUTH_COLLECTION = "open-cinema.librespot.oauth-operations"
OAUTH_SCHEMA_ID = "open-cinema.librespot.oauth-operation"

OAUTH_OPERATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["instanceId", "state", "createdAtUnix", "expiresAtUnix"],
    "properties": {
        "instanceId": {"type": "string", "minLength": 1, "maxLength": 128},
        "state": {
            "enum": [
                "waiting-for-callback",
                "validating",
                "succeeded",
                "failed",
                "cancelled",
                "expired",
            ]
        },
        "authorizationUrl": {"type": "string", "maxLength": 4096},
        "createdAtUnix": {"type": "integer", "minimum": 0},
        "expiresAtUnix": {"type": "integer", "minimum": 0},
        "message": {"type": "string", "maxLength": 512},
        "scopes": {
            "type": "array",
            "maxItems": 32,
            "items": {"type": "string", "maxLength": 128},
        },
        "tokenExpiresInSeconds": {"type": ["integer", "null"], "minimum": 0},
    },
}


def oauth_refresh_secret_id(instance_id: str) -> str:
    return f"open-cinema.librespot.oauth-refresh.{instance_id}"


def refresh_oauth_access_token(context: ManagedResourceContext) -> str | None:
    """Refresh OAuth credentials without exposing either token in process arguments."""

    services = context.host_services
    if services is None:
        raise RuntimeError("Open Cinema host services are unavailable")
    refresh_id = oauth_refresh_secret_id(context.instance_id)
    if not services.secret_presence(refresh_id):
        return None
    refresh_token = services.resolve_secret(refresh_id).decode("utf-8")
    response = OAuthOperations._run(
        [str(load_runtime_assets().oauth_helper), "refresh", "--token-stdin"],
        input_value=refresh_token,
        timeout=25,
    )
    access_token = response.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("Spotify did not return a refreshed access token")
    secrets = PluginSecretStore(PLUGIN_ID)
    OAuthOperations._replace_owned_secret(
        secrets,
        access_token_secret_id(context.instance_id),
        access_token,
    )
    rotated_refresh = response.get("refreshToken")
    if isinstance(rotated_refresh, str) and rotated_refresh:
        OAuthOperations._replace_owned_secret(secrets, refresh_id, rotated_refresh)
    return access_token


class OAuthOperations:
    def __init__(
        self,
        instances: PluginInstanceStore,
        secrets: PluginSecretStore,
    ) -> None:
        self.instances = instances
        self.secrets = secrets
        self.operations = PluginDocumentStore(
            plugin_id=PLUGIN_ID,
            collection=OAUTH_COLLECTION,
            schema_id=OAUTH_SCHEMA_ID,
            schema_version=1,
            schema=OAUTH_OPERATION_SCHEMA,
        )

    def _state_path(self, instance_id: str) -> Path:
        context = self.instances.context(instance_id)
        if context.host_services is None:
            raise RuntimeError("Open Cinema host services are unavailable")
        directory = Path(context.host_services.private_directory("oauth"))
        return directory / "pending.json"

    @staticmethod
    def _run(
        arguments: list[str],
        *,
        input_value: str | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        completed = subprocess.run(
            arguments,
            input=input_value.encode("utf-8") if input_value is not None else None,
            capture_output=True,
            env={"LANG": os.environ.get("LANG", "C.UTF-8")},
            timeout=timeout,
            check=False,
        )
        if len(completed.stdout) > 64 * 1024 or len(completed.stderr) > 64 * 1024:
            raise ValueError("OAuth helper returned too much output")
        try:
            document = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("OAuth helper returned an invalid response") from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise ValueError("OAuth helper returned an incompatible response")
        if completed.returncode != 0 or document.get("state") == "failed":
            # Helper messages are deliberately not reflected because they can contain
            # callback parameters or token material supplied over stdin.
            raise ValueError("OAuth helper reported a failed operation")
        return document

    @staticmethod
    def _integer(document: Mapping[str, object], key: str) -> int:
        value = document.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"OAuth operation has an invalid {key}")
        return value

    @staticmethod
    def _public(document: dict[str, object], update_version: int) -> dict[str, object]:
        return {
            **document,
            "updateVersion": update_version,
            "expired": OAuthOperations._integer(document, "expiresAtUnix") <= int(time.time()),
        }

    def status(self, instance_id: str) -> dict[str, object] | None:
        operation = self.operations.get_optional(instance_id)
        if operation is None:
            return None
        document = dict(operation.document)
        if document["state"] in {
            "waiting-for-callback",
            "validating",
        } and self._integer(document, "expiresAtUnix") <= int(time.time()):
            document.update({"state": "expired", "message": "The OAuth operation expired."})
            operation = self.operations.put(
                instance_id,
                document,
                expected_version=operation.update_version,
            )
            self._state_path(instance_id).unlink(missing_ok=True)
        return self._public(dict(operation.document), operation.update_version)

    def begin(self, instance_id: str) -> dict[str, object]:
        self.instances.get(instance_id)
        current = self.operations.get_optional(instance_id)
        if current is not None:
            state = current.document.get("state")
            expires = current.document.get("expiresAtUnix")
            if (
                state in {"waiting-for-callback", "validating"}
                and isinstance(expires, int)
                and expires > int(time.time())
            ):
                raise ValueError("an OAuth operation is already waiting for this source")
        state_path = self._state_path(instance_id)
        state_path.unlink(missing_ok=True)
        helper = load_runtime_assets().oauth_helper
        response = self._run(
            [str(helper), "begin", "--state-file", str(state_path)],
            timeout=5,
        )
        authorization_url = response.get("authorizationUrl")
        expires_in = response.get("expiresInSeconds")
        if not isinstance(authorization_url, str) or not isinstance(expires_in, int):
            raise ValueError("OAuth helper omitted the authorization state")
        now = int(time.time())
        document: dict[str, object] = {
            "instanceId": instance_id,
            "state": "waiting-for-callback",
            "authorizationUrl": authorization_url,
            "createdAtUnix": now,
            "expiresAtUnix": now + expires_in,
        }
        operation = self.operations.put(
            instance_id,
            document,
            expected_version=current.update_version if current is not None else None,
        )
        return self._public(dict(operation.document), operation.update_version)

    def exchange(self, instance_id: str, callback_url: str) -> dict[str, object]:
        if not isinstance(callback_url, str) or not callback_url:
            raise ValueError("callbackUrl is required")
        if len(callback_url.encode("utf-8")) > 8192:
            raise ValueError("callbackUrl is too large")
        current = self.operations.get_optional(instance_id)
        if current is None or current.document.get("state") != "waiting-for-callback":
            raise ValueError("no OAuth operation is waiting for a callback")
        if self._integer(current.document, "expiresAtUnix") <= int(time.time()):
            self.status(instance_id)
            raise ValueError("the OAuth operation expired")
        validating = dict(current.document)
        validating["state"] = "validating"
        current = self.operations.put(
            instance_id,
            validating,
            expected_version=current.update_version,
        )
        helper = load_runtime_assets().oauth_helper
        try:
            response = self._run(
                [
                    str(helper),
                    "exchange",
                    "--state-file",
                    str(self._state_path(instance_id)),
                    "--callback-stdin",
                ],
                input_value=callback_url,
                timeout=25,
            )
            access_token = response.get("accessToken")
            refresh_token = response.get("refreshToken")
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("Spotify did not return an access token")
            self._replace_secret(access_token_secret_id(instance_id), access_token)
            if isinstance(refresh_token, str) and refresh_token:
                self._replace_secret(oauth_refresh_secret_id(instance_id), refresh_token)

            item = self.instances.get(instance_id)
            configuration = dict(item.configuration)
            raw_authentication = configuration["authentication"]
            raw_cache = configuration["cache"]
            if not isinstance(raw_authentication, Mapping) or not isinstance(raw_cache, Mapping):
                raise ValueError("saved authentication or cache settings are invalid")
            authentication = dict(raw_authentication)
            authentication["mode"] = "oauth-cache"
            configuration["authentication"] = authentication
            cache = dict(raw_cache)
            cache["credentialsEnabled"] = True
            configuration["cache"] = cache
            self.instances.update(
                instance_id,
                configuration=configuration,
                expected_version=item.update_version,
            )
            succeeded = {
                **current.document,
                "state": "succeeded",
                "message": "Authorization succeeded; the source will restart securely.",
                "scopes": [
                    str(item)[:128] for item in response.get("scopes", []) if isinstance(item, str)
                ][:32],
                "tokenExpiresInSeconds": response.get("expiresInSeconds"),
            }
            succeeded.pop("authorizationUrl", None)
            current = self.operations.put(
                instance_id,
                succeeded,
                expected_version=current.update_version,
            )
        except Exception:
            public_message = (
                "Spotify authorization failed. Check the callback URL and start a new "
                "authorization attempt."
            )
            failed = {
                **current.document,
                "state": "failed",
                "message": public_message,
            }
            failed.pop("authorizationUrl", None)
            current = self.operations.put(
                instance_id,
                failed,
                expected_version=current.update_version,
            )
            self._state_path(instance_id).unlink(missing_ok=True)
            raise ValueError(public_message) from None
        return self._public(dict(current.document), current.update_version)

    def cancel(self, instance_id: str) -> dict[str, object]:
        current = self.operations.get_optional(instance_id)
        if current is None or current.document.get("state") not in {
            "waiting-for-callback",
            "validating",
        }:
            raise ValueError("no active OAuth operation can be cancelled")
        document = dict(current.document)
        document.update({"state": "cancelled", "message": "Authorization was cancelled."})
        document.pop("authorizationUrl", None)
        current = self.operations.put(
            instance_id,
            document,
            expected_version=current.update_version,
        )
        self._state_path(instance_id).unlink(missing_ok=True)
        return self._public(dict(current.document), current.update_version)

    def clear(self, instance_id: str) -> None:
        """Remove private pending state and the persisted operation on instance deletion."""

        current = self.operations.get_optional(instance_id)
        if current is not None:
            self.operations.delete(instance_id, expected_version=current.update_version)
        self._state_path(instance_id).unlink(missing_ok=True)

    def _replace_secret(self, secret_id: str, value: str) -> None:
        self._replace_owned_secret(self.secrets, secret_id, value)

    @staticmethod
    def _replace_owned_secret(
        secrets: PluginSecretStore,
        secret_id: str,
        value: str,
    ) -> None:
        presence = secrets.presence(secret_id)
        version = presence.get("updateVersion")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
            raise RuntimeError("configured secret has no update version")
        secrets.set(
            secret_id,
            value,
            expected_version=version if presence.get("configured") is True else None,
        )
