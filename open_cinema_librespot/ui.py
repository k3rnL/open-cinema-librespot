from __future__ import annotations

from typing import Any

PLUGIN_ID = "open-cinema.librespot"
PREFIX = f"/api/plugins/{PLUGIN_ID}"


def _field(
    name: str,
    path: str,
    label: str,
    widget: str,
    **values: Any,
) -> dict[str, object]:
    return {
        "id": f"{PLUGIN_ID}.{name}",
        "path": path,
        "label": label,
        "widget": widget,
        **values,
    }


DEVICE_TYPES = [
    ("computer", "Computer"),
    ("tablet", "Tablet"),
    ("smartphone", "Smartphone"),
    ("speaker", "Speaker"),
    ("tv", "TV"),
    ("avr", "Audio/video receiver"),
    ("stb", "Set-top box"),
    ("audiodongle", "Audio dongle"),
    ("gameconsole", "Game console"),
    ("castaudio", "Cast audio"),
    ("castvideo", "Cast video"),
    ("automobile", "Automobile"),
    ("smartwatch", "Smartwatch"),
    ("chromebook", "Chromebook"),
    ("carthing", "Car Thing"),
]


CREATE_SECTIONS: list[dict[str, object]] = [
    {
        "id": f"{PLUGIN_ID}.essential",
        "title": "Essential setup",
        "description": "A name is enough for the normal Spotify Connect discovery flow.",
        "presentation": "card",
        "emphasis": "primary",
        "width": "full",
        "fields": [
            _field(
                "name",
                "/name",
                "Connect name",
                "text",
                required=True,
                constraints={"minLength": 1, "maxLength": 64},
                help="The name shown in Spotify's device picker. It must be unique.",
            ),
            _field(
                "device-type",
                "/deviceType",
                "Device type",
                "enum",
                choices=[{"value": value, "label": label} for value, label in DEVICE_TYPES],
            ),
            _field(
                "bitrate",
                "/bitrate",
                "Spotify quality",
                "enum",
                choices=[
                    {"value": 96, "label": "96 kbps"},
                    {"value": 160, "label": "160 kbps"},
                    {"value": 320, "label": "320 kbps"},
                ],
            ),
        ],
    },
    {
        "id": f"{PLUGIN_ID}.authentication",
        "title": "Identity and authentication",
        "presentation": "tab",
        "fields": [
            _field(
                "authentication-mode",
                "/authentication/mode",
                "Authentication",
                "enum",
                choices=[
                    {
                        "value": "discovery",
                        "label": "Spotify Connect discovery",
                        "help": (
                            "Recommended. Pair from a Spotify Premium client without "
                            "storing a secret."
                        ),
                    },
                    {"value": "access-token", "label": "Access token"},
                    {"value": "oauth-cache", "label": "Guided OAuth credentials"},
                ],
            ),
            _field(
                "access-token",
                "/accessToken",
                "Spotify access token",
                "secret",
                placeholder="Token with the streaming scope",
                visibleWhen={"path": "/authentication/mode", "equals": "access-token"},
                help="Write-only. Open Cinema never returns this value to the browser.",
            ),
            _field(
                "username",
                "/authentication/username",
                "Cached credential username",
                "text",
                visibleWhen={"path": "/authentication/mode", "equals": "oauth-cache"},
            ),
            _field(
                "group",
                "/group",
                "Present as a speaker group",
                "boolean",
                help="Changes how this receiver is described to Spotify clients.",
            ),
        ],
    },
    {
        "id": f"{PLUGIN_ID}.audio-volume",
        "title": "Spotify volume",
        "description": "These values control Spotify/librespot volume, not Open Cinema input trim.",
        "presentation": "tab",
        "fields": [
            _field(
                "initial-volume",
                "/volume/initialPercent",
                "Initial volume",
                "number",
                constraints={"minimum": 0, "maximum": 100, "step": 1},
            ),
            _field(
                "volume-control",
                "/volume/control",
                "Volume curve",
                "enum",
                choices=[
                    {"value": "log", "label": "Logarithmic"},
                    {"value": "linear", "label": "Linear"},
                    {"value": "cubic", "label": "Cubic"},
                    {"value": "fixed", "label": "Fixed"},
                ],
            ),
            _field(
                "volume-range",
                "/volume/rangeDb",
                "Volume range (dB)",
                "number",
                constraints={"minimum": 0, "maximum": 100, "step": 1},
            ),
            _field(
                "volume-steps",
                "/volume/steps",
                "Remote volume steps",
                "number",
                constraints={"minimum": 1, "maximum": 65535, "step": 1},
            ),
        ],
    },
    {
        "id": f"{PLUGIN_ID}.discovery-network",
        "title": "Discovery and network",
        "presentation": "tab",
        "fields": [
            _field("discovery-enabled", "/discovery/enabled", "Enable discovery", "boolean"),
            _field(
                "zeroconf-backend",
                "/discovery/backend",
                "Discovery backend",
                "enum",
                choices=[{"value": "libmdns", "label": "Built-in libmdns"}],
                readOnly=True,
                help="This wheel is compiled with the portable libmdns backend.",
            ),
            _field(
                "zeroconf-port",
                "/discovery/port",
                "Discovery port",
                "number",
                constraints={"minimum": 1, "maximum": 65535},
                help="Leave empty to let librespot select a port.",
            ),
            _field(
                "interfaces",
                "/discovery/interfaces",
                "Bind interface addresses",
                "repeatable",
                item=_field("interface-item", "/value", "Address", "text"),
                help="Leave empty to bind all interfaces.",
            ),
            _field("proxy", "/proxy", "HTTP proxy", "url", placeholder="http://proxy:8080"),
            _field(
                "ap-port",
                "/apPort",
                "Spotify access-point port",
                "number",
                constraints={"minimum": 1, "maximum": 65535},
            ),
        ],
    },
    {
        "id": f"{PLUGIN_ID}.normalisation-playback",
        "title": "Normalisation and playback",
        "presentation": "tab",
        "fields": [
            _field(
                "normalisation-enabled",
                "/normalisation/enabled",
                "Enable volume normalisation",
                "boolean",
            ),
            _field(
                "normalisation-method",
                "/normalisation/method",
                "Method",
                "enum",
                choices=[
                    {"value": "dynamic", "label": "Dynamic limiter"},
                    {"value": "basic", "label": "Basic gain"},
                ],
                visibleWhen={"path": "/normalisation/enabled", "equals": True},
            ),
            _field(
                "normalisation-gain-type",
                "/normalisation/gainType",
                "Gain reference",
                "enum",
                choices=[
                    {"value": "auto", "label": "Automatic"},
                    {"value": "track", "label": "Track"},
                    {"value": "album", "label": "Album"},
                ],
                visibleWhen={"path": "/normalisation/enabled", "equals": True},
            ),
            _field(
                "normalisation-pregain",
                "/normalisation/pregainDb",
                "Pregain (dB)",
                "number",
                constraints={"minimum": -10, "maximum": 10, "step": 0.1},
                visibleWhen={"path": "/normalisation/enabled", "equals": True},
            ),
            _field(
                "normalisation-threshold",
                "/normalisation/thresholdDbfs",
                "Limiter threshold (dBFS)",
                "number",
                constraints={"minimum": -10, "maximum": 0, "step": 0.1},
                visibleWhen={"path": "/normalisation/method", "equals": "dynamic"},
            ),
            _field(
                "normalisation-attack",
                "/normalisation/attackMs",
                "Limiter attack",
                "duration",
                constraints={"minimum": 1, "maximum": 500},
                visibleWhen={"path": "/normalisation/method", "equals": "dynamic"},
            ),
            _field(
                "normalisation-release",
                "/normalisation/releaseMs",
                "Limiter release",
                "duration",
                constraints={"minimum": 1, "maximum": 1000},
                visibleWhen={"path": "/normalisation/method", "equals": "dynamic"},
            ),
            _field(
                "normalisation-knee",
                "/normalisation/kneeDb",
                "Limiter knee (dB)",
                "number",
                constraints={"minimum": 0, "maximum": 10, "step": 0.1},
                visibleWhen={"path": "/normalisation/method", "equals": "dynamic"},
            ),
            _field(
                "autoplay",
                "/playback/autoplay",
                "Autoplay similar music",
                "enum",
                choices=[
                    {"value": "client", "label": "Follow Spotify client"},
                    {"value": "on", "label": "Always on"},
                    {"value": "off", "label": "Always off"},
                ],
            ),
            _field("gapless", "/playback/gapless", "Gapless playback", "boolean"),
        ],
    },
    {
        "id": f"{PLUGIN_ID}.cache-local-files",
        "title": "Cache and local files",
        "presentation": "tab",
        "fields": [
            _field("audio-cache", "/cache/audioEnabled", "Cache audio", "boolean"),
            _field(
                "credential-cache",
                "/cache/credentialsEnabled",
                "Persist credentials",
                "boolean",
                help="Required for reusable OAuth credentials.",
            ),
            _field(
                "cache-limit",
                "/cache/sizeLimit",
                "Audio cache limit",
                "text",
                placeholder="2G",
                constraints={"pattern": "^[1-9][0-9]*[KMG]?$"},
            ),
            _field(
                "local-files",
                "/localFileDirectories",
                "Local-file directories",
                "repeatable",
                item=_field("local-file-item", "/value", "Directory", "path"),
                help="Directories must be inside the appliance's configured media roots.",
            ),
        ],
    },
    {
        "id": f"{PLUGIN_ID}.automations-advanced",
        "title": "Automations and advanced behavior",
        "presentation": "tab",
        "fields": [
            _field(
                "automation-events",
                "/automations/eventIds",
                "Automation IDs",
                "repeatable",
                item=_field("automation-item", "/value", "Automation ID", "text"),
            ),
            _field(
                "sink-events",
                "/automations/includeSinkEvents",
                "Include sink open/close events",
                "boolean",
            ),
            _field(
                "activity-hold",
                "/activityHoldMs",
                "Activity hold",
                "duration",
                constraints={"minimum": 0, "maximum": 30000, "step": 100},
                help="Keeps Spotify eligible briefly across pauses and track transitions.",
            ),
            _field(
                "log-level",
                "/logLevel",
                "Log level",
                "enum",
                choices=[
                    {"value": "standard", "label": "Standard"},
                    {"value": "quiet", "label": "Warnings and errors"},
                    {"value": "verbose", "label": "Verbose diagnostics"},
                ],
            ),
        ],
    },
]


ADMIN_UI = {
    "schemaVersion": 1,
    "navigation": [
        {
            "id": f"{PLUGIN_ID}.navigation",
            "label": "Spotify Connect",
            "pageId": f"{PLUGIN_ID}.overview",
            "icon": "spotify",
            "order": 35,
        },
        {
            "id": f"{PLUGIN_ID}.add-navigation",
            "label": "Add Spotify source",
            "pageId": f"{PLUGIN_ID}.create",
            "icon": "plus-circle",
            "order": 36,
        },
    ],
    "pages": [
        {
            "id": f"{PLUGIN_ID}.overview",
            "title": "Spotify Connect",
            "description": (
                "Managed Spotify Connect receivers available as routable Open Cinema inputs."
            ),
            "template": "resource-list",
            "binding": {"read": f"{PREFIX}/instances", "freshnessMs": 2000},
            "sections": CREATE_SECTIONS,
        },
        {
            "id": f"{PLUGIN_ID}.create",
            "title": "Add Spotify Connect source",
            "description": "Create an independent receiver. Spotify Premium is required upstream.",
            "template": "guided-flow",
            "binding": {
                "read": f"{PREFIX}/instances/defaults",
                "write": f"{PREFIX}/instances/create",
                "successPageId": f"{PLUGIN_ID}.overview",
            },
            "sections": CREATE_SECTIONS,
        },
    ],
}
