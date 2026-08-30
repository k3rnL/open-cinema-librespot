from __future__ import annotations

import json
import uuid
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.urls import URLPattern, path
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from open_cinema_plugin_sdk import (
    PluginConcurrencyError,
    PluginInstanceDocument,
    PluginInstanceStore,
    PluginSecretStore,
    managed_source_endpoint_id,
)

from .configuration import (
    default_instance_configuration,
    ensure_unique_connect_names,
    instance_schema,
    validate_instance_configuration,
)
from .oauth import OAuthOperations, oauth_refresh_secret_id
from .options import option_contract
from .provider import access_token_secret_id

PLUGIN_ID = "open-cinema.librespot"
CAPABILITY_ID = "open-cinema.librespot.sources"
SCHEMA_ID = "open-cinema.librespot.instance"


class LibrespotAPI:
    def __init__(self) -> None:
        self.instances = PluginInstanceStore(
            plugin_id=PLUGIN_ID,
            capability_id=CAPABILITY_ID,
            schema_id=SCHEMA_ID,
            schema_version=1,
            schema=instance_schema(),
        )
        self.secrets = PluginSecretStore(PLUGIN_ID)
        self.oauth = OAuthOperations(self.instances, self.secrets)

    @staticmethod
    def _body(request: HttpRequest) -> dict[str, Any]:
        if not request.body:
            return {}
        value = json.loads(request.body)
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    @staticmethod
    def _media_roots() -> tuple[str, ...]:
        values = getattr(settings, "OPEN_CINEMA_MEDIA_ROOTS", ())
        return tuple(str(item) for item in values)

    @staticmethod
    def _expected_version(
        body: dict[str, Any],
        item: PluginInstanceDocument,
    ) -> int:
        value = body.pop("updateVersion", body.pop("concurrencyToken", None))
        if isinstance(value, str) and value.isascii() and value.isdigit():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("an updateVersion or concurrencyToken integer is required")
        if value != item.update_version:
            raise PluginConcurrencyError("source changed; refresh and retry")
        return int(value)

    @staticmethod
    def _authorize(request: HttpRequest, item: PluginInstanceDocument) -> None:
        user = request.user
        if getattr(user, "is_staff", False):
            return
        if item.owner_id is None or item.owner_id != getattr(user, "pk", None):
            raise PermissionError("this Spotify Connect source belongs to another user")

    def _visible_instances(self, request: HttpRequest) -> tuple[PluginInstanceDocument, ...]:
        items: tuple[PluginInstanceDocument, ...] = tuple(self.instances.list())
        if getattr(request.user, "is_staff", False):
            return items
        owner_id = getattr(request.user, "pk", None)
        return tuple(item for item in items if item.owner_id == owner_id)

    def _observe(self, item: PluginInstanceDocument) -> dict[str, object]:
        facts = dict(item.runtime_facts)
        health = str(facts.get("health", "unknown"))
        if item.observed_state == "failed":
            health = "failed"
        elif item.observed_state == "started" and health == "unknown":
            health = "healthy"
        raw_actions = facts.get("actions", [])
        actions = []
        if isinstance(raw_actions, list):
            for raw in raw_actions:
                if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                    continue
                action = dict(raw)
                action.update(
                    {
                        "method": "POST",
                        "href": (
                            f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}"
                            f"/actions/{raw['id']}"
                        ),
                    }
                )
                actions.append(action)
        if not actions:
            running = item.observed_state == "started"
            actions = [
                {
                    "id": "stop" if item.desired_state == "enabled" else "start",
                    "label": "Stop" if item.desired_state == "enabled" else "Start",
                    "available": True,
                    "reason": None,
                    "confirmation": "disconnecting" if running else "none",
                    "lifecycleImpact": "hot",
                    "concurrencyToken": str(item.update_version),
                    "method": "POST",
                    "href": (
                        f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}/actions/"
                        f"{'stop' if item.desired_state == 'enabled' else 'start'}"
                    ),
                }
            ]
        secret_presence = self.secrets.presence(access_token_secret_id(item.instance_id))
        oauth_status = self.oauth.status(item.instance_id)
        guided_operation = None
        if oauth_status is not None:
            guided_operation = {
                "kind": "external-authorization",
                "title": "Spotify authorization",
                "description": (
                    "Open the Spotify page, approve access, then paste the complete callback URL."
                ),
                **oauth_status,
                "callback": {
                    "label": "Callback URL",
                    "placeholder": "http://127.0.0.1:0/login?code=…&state=…",
                    "field": "callbackUrl",
                    "endpoint": (
                        f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}/oauth/callback"
                    ),
                },
                "cancel": {
                    "label": "Cancel authorization",
                    "endpoint": (
                        f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}/oauth/cancel"
                    ),
                },
            }
        authentication = item.configuration.get("authentication")
        authentication_mode = (
            authentication.get("mode") if isinstance(authentication, dict) else "unknown"
        )
        signal = facts.get("signal")
        signal_description = "44100 Hz · 2 channels · FLOAT32LE"
        if isinstance(signal, dict):
            signal_description = (
                f"{signal.get('rate', 44100)} Hz · {signal.get('channels', 2)} channels · "
                f"{signal.get('format', 'FLOAT32LE')}"
            )
        route_available = facts.get("routeAvailable") is True
        correlation = str(facts.get("pipewireCorrelation", "not observed"))
        diagnostics: list[object] = []
        last_error = facts.get("lastError")
        if last_error:
            diagnostics.append(last_error)
        automation_errors = facts.get("automationErrors")
        if isinstance(automation_errors, list):
            diagnostics.extend(automation_errors)
        if item.desired_state == "enabled" and correlation not in {"ready", "not observed"}:
            diagnostics.append(
                f"PipeWire correlation is {correlation}; the source cannot be routed yet."
            )
        if isinstance(authentication, dict) and authentication.get("mode") == "oauth-cache":
            oauth_active = bool(
                oauth_status and oauth_status.get("state") in {"waiting-for-callback", "validating"}
            )
            actions.append(
                {
                    "id": "oauth-begin",
                    "label": "Authorize Spotify",
                    "available": not oauth_active,
                    "reason": (
                        "Finish or cancel the current authorization first."
                        if oauth_active
                        else None
                    ),
                    "confirmation": "none",
                    "lifecycleImpact": "hot",
                    "concurrencyToken": str(item.update_version),
                    "method": "POST",
                    "href": (f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}/oauth/begin"),
                }
            )
        if secret_presence.get("configured") is True:
            removable = authentication_mode != "access-token"
            actions.append(
                {
                    "id": "clear-access-token",
                    "label": "Remove stored access token",
                    "available": removable,
                    "reason": (
                        None
                        if removable
                        else "Choose discovery or OAuth authentication before removing this token."
                    ),
                    "confirmation": "destructive",
                    "lifecycleImpact": "hot",
                    "concurrencyToken": str(item.update_version),
                    "method": "POST",
                    "href": (
                        f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}"
                        "/actions/clear-access-token"
                    ),
                }
            )
        deletable = item.desired_state == "disabled" and item.observed_state == "stopped"
        references: tuple[object, ...] = ()
        if deletable:
            context = self.instances.context(item.instance_id)
            if context.host_services is not None:
                endpoint_id = str(
                    managed_source_endpoint_id(
                        PLUGIN_ID,
                        CAPABILITY_ID,
                        item.instance_id,
                    )
                )
                references = tuple(context.host_services.logical_endpoint_references(endpoint_id))
                if references:
                    diagnostics.append(
                        {
                            "code": "saved-graph-references-preserved",
                            "message": (
                                f"{len(references)} saved graph revision(s) refer to this source. "
                                "Deleting it preserves those references as unavailable."
                            ),
                        }
                    )
        actions.append(
            {
                "id": "delete",
                "label": "Delete",
                "available": deletable,
                "reason": (
                    (
                        f"{len(references)} saved graph revision(s) will keep an unavailable "
                        "reference until edited."
                    )
                    if references
                    else None
                    if deletable
                    else "Stop this source before deleting it."
                ),
                "confirmation": "destructive",
                "lifecycleImpact": "hot",
                "concurrencyToken": str(item.update_version),
                "method": "DELETE",
                "href": f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}",
            }
        )
        return {
            **item.to_document(),
            "status": facts.get("playbackState", item.observed_state),
            "health": health,
            "runtime": {
                "status": health,
                "facts": facts,
            },
            "summary": [
                {"label": "Authentication", "value": authentication_mode},
                {
                    "label": "Spotify session",
                    "value": facts.get("sessionState", "waiting for client"),
                },
                {
                    "label": "Playback",
                    "value": facts.get("playbackState", item.observed_state),
                },
                {"label": "Audio source", "value": signal_description},
                {"label": "PipeWire", "value": correlation},
                {
                    "label": "Graph routing",
                    "value": "Ready to route" if route_available else "Unavailable",
                },
                {"label": "Librespot", "value": facts.get("librespotVersion", "not observed")},
                {"label": "Plugin", "value": facts.get("pluginVersion", "0.1.0")},
            ],
            "diagnostics": diagnostics,
            "graphReferences": list(references),
            "actions": actions,
            "oauth": oauth_status,
            "guidedOperation": guided_operation,
            "editor": {
                "href": f"/api/plugins/{PLUGIN_ID}/instances/{item.instance_id}",
                "document": {
                    **item.configuration,
                    "accessToken": secret_presence,
                    "updateVersion": item.update_version,
                },
            },
        }

    @method_decorator(require_http_methods(["GET"]))
    def list_instances(self, request: HttpRequest) -> JsonResponse:
        options = option_contract()["options"]
        return JsonResponse(
            {
                "schemaVersion": 1,
                "items": [self._observe(item) for item in self._visible_instances(request)],
                "managedOptions": [
                    f"--{item['name']}: {item.get('reason', item.get('value', 'managed'))}"
                    for item in options
                    if item["classification"] == "managed"
                ],
                "unavailableOptions": [
                    f"--{item['name']}: {item['reason']}"
                    for item in options
                    if item["classification"] == "unavailable"
                ],
            }
        )

    @method_decorator(require_http_methods(["GET"]))
    def defaults(self, request: HttpRequest) -> JsonResponse:
        document = default_instance_configuration()
        document["accessToken"] = {"configured": False}
        return JsonResponse(document)

    @method_decorator(require_http_methods(["PUT"]))
    def create(self, request: HttpRequest) -> JsonResponse:
        body = self._body(request)
        token = body.pop("accessToken", None)
        if isinstance(token, dict):
            token = None
        configuration = validate_instance_configuration(body, media_roots=self._media_roots())
        ensure_unique_connect_names(
            [*(item.configuration for item in self.instances.list()), configuration]
        )
        instance_id = str(uuid.uuid4())
        if configuration["authentication"]["mode"] == "access-token":
            if not isinstance(token, str) or not token.strip():
                raise ValueError("an access token is required for access-token authentication")
            self.secrets.set(access_token_secret_id(instance_id), token.strip())
        try:
            item = self.instances.create(
                instance_id=instance_id,
                display_name=str(configuration["name"]),
                configuration=configuration,
                enabled=True,
                owner_id=request.user.pk,
            )
        except Exception:
            presence = self.secrets.presence(access_token_secret_id(instance_id))
            if presence["configured"]:
                version = presence["updateVersion"]
                if not isinstance(version, int):
                    raise RuntimeError("configured secret has no update version") from None
                self.secrets.delete(
                    access_token_secret_id(instance_id),
                    expected_version=version,
                )
            raise
        return JsonResponse({"data": self._observe(item)}, status=201)

    @method_decorator(require_http_methods(["GET", "PUT", "DELETE"]))
    def detail(self, request: HttpRequest, instance_id: str) -> JsonResponse:
        item = self.instances.get(instance_id)
        self._authorize(request, item)
        if request.method == "GET":
            document = self._observe(item)
            document["accessToken"] = self.secrets.presence(access_token_secret_id(instance_id))
            return JsonResponse(document)
        body = self._body(request)
        expected = self._expected_version(body, item)
        if request.method == "DELETE":
            if item.desired_state != "disabled" or item.observed_state != "stopped":
                raise ValueError("stop this source and wait for it to stop before deleting it")
            self.oauth.clear(instance_id)
            self.instances.delete(instance_id, expected_version=expected)
            presence = self.secrets.presence(access_token_secret_id(instance_id))
            version = presence.get("updateVersion")
            if presence.get("configured") is True and isinstance(version, int):
                self.secrets.delete(access_token_secret_id(instance_id), expected_version=version)
            refresh_presence = self.secrets.presence(oauth_refresh_secret_id(instance_id))
            refresh_version = refresh_presence.get("updateVersion")
            if refresh_presence.get("configured") is True and isinstance(refresh_version, int):
                self.secrets.delete(
                    oauth_refresh_secret_id(instance_id),
                    expected_version=refresh_version,
                )
            return JsonResponse({"deleted": True})
        token = body.pop("accessToken", None)
        configuration = body.get("configuration", body)
        if not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")
        configuration = validate_instance_configuration(
            configuration,
            media_roots=self._media_roots(),
        )
        ensure_unique_connect_names(
            [
                configuration if current.instance_id == instance_id else current.configuration
                for current in self.instances.list()
            ]
        )
        if isinstance(token, str) and token:
            presence = self.secrets.presence(access_token_secret_id(instance_id))
            expected_secret_version = None
            secret_version = presence["updateVersion"]
            if presence["configured"] and not isinstance(secret_version, int):
                raise RuntimeError("configured secret has no update version")
            if isinstance(secret_version, int):
                expected_secret_version = secret_version
            self.secrets.set(
                access_token_secret_id(instance_id),
                token,
                expected_version=(expected_secret_version if presence["configured"] else None),
            )
        updated = self.instances.update(
            instance_id, configuration=configuration, expected_version=expected
        )
        return JsonResponse({"data": self._observe(updated)})

    @method_decorator(require_http_methods(["POST"]))
    def action(self, request: HttpRequest, instance_id: str, action_id: str) -> JsonResponse:
        item = self.instances.get(instance_id)
        self._authorize(request, item)
        expected = self._expected_version(self._body(request), item)
        if action_id in {"start", "stop"}:
            enabled = action_id == "start"
            if (item.desired_state == "enabled") != enabled:
                item = self.instances.set_enabled(
                    instance_id, enabled=enabled, expected_version=expected
                )
        elif action_id == "restart":
            if item.desired_state != "enabled":
                raise ValueError("enable this source before restarting it")
            item = self.instances.update(
                instance_id,
                configuration=item.configuration,
                expected_version=expected,
            )
        elif action_id == "clear-access-token":
            authentication = item.configuration.get("authentication")
            if isinstance(authentication, dict) and authentication.get("mode") == "access-token":
                raise ValueError(
                    "choose discovery or OAuth authentication before removing this token"
                )
            presence = self.secrets.presence(access_token_secret_id(instance_id))
            secret_version = presence.get("updateVersion")
            if presence.get("configured") is True and isinstance(secret_version, int):
                self.secrets.delete(
                    access_token_secret_id(instance_id),
                    expected_version=secret_version,
                )
        else:
            raise ValueError(f"unsupported action {action_id!r}")
        return JsonResponse({"data": self._observe(item)}, status=202)

    @method_decorator(require_http_methods(["GET", "POST"]))
    def oauth_operation(
        self,
        request: HttpRequest,
        instance_id: str,
        operation: str,
    ) -> JsonResponse:
        item = self.instances.get(instance_id)
        self._authorize(request, item)
        if request.method == "GET" and operation == "status":
            return JsonResponse({"data": self.oauth.status(instance_id)})
        if request.method != "POST":
            raise ValueError("this OAuth operation requires POST")
        body = self._body(request)
        self._expected_version(body, item)
        if operation == "begin":
            result = self.oauth.begin(instance_id)
        elif operation == "callback":
            result = self.oauth.exchange(
                instance_id,
                str(body.get("callbackUrl", "")),
            )
        elif operation == "cancel":
            result = self.oauth.cancel(instance_id)
        else:
            raise ValueError(f"unsupported OAuth operation {operation!r}")
        return JsonResponse({"data": result}, status=202)

    def urls(self) -> tuple[URLPattern, ...]:
        return (
            path("instances", self.list_instances, name="instances"),
            path("instances/defaults", self.defaults, name="instance-defaults"),
            path("instances/create", self.create, name="instance-create"),
            path("instances/<str:instance_id>", self.detail, name="instance-detail"),
            path(
                "instances/<str:instance_id>/actions/<str:action_id>",
                self.action,
                name="instance-action",
            ),
            path(
                "instances/<str:instance_id>/oauth/<str:operation>",
                self.oauth_operation,
                name="instance-oauth-operation",
            ),
        )


API = LibrespotAPI()
