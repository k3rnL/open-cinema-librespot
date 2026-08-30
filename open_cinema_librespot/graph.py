from __future__ import annotations

from open_cinema_plugin_sdk import (
    AudioContent,
    ChannelLayout,
    MediaKind,
    NodePortDefinition,
    PortContract,
    PortDirection,
    ProcessingHookContext,
    ProcessingNodeTypeManifest,
    ProcessingPlan,
    ProcessingValidationIssue,
    SignalContract,
    managed_source_endpoint_id,
)

PLUGIN_ID = "open-cinema.librespot"
SOURCE_CAPABILITY_ID = "open-cinema.librespot.sources"

SOURCE_NODE = ProcessingNodeTypeManifest(
    type_id="plugin.open-cinema.librespot.source",
    version=1,
    configuration_version=1,
    display_name="Spotify Connect source",
    category="routing",
    description="Routes one configured Spotify Connect instance into this graph.",
    ports=(
        NodePortDefinition(
            PortContract(
                "audio",
                PortDirection.OUTPUT,
                SignalContract(
                    MediaKind.AUDIO,
                    AudioContent.PCM,
                    sample_formats=("FLOAT32LE",),
                    rates=(44100,),
                    layouts=(ChannelLayout(2, ("FL", "FR")),),
                ),
            ),
            description="Decoded stereo Spotify audio from the selected stable instance.",
        ),
    ),
    configuration_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "x-open-cinema-managed-audio-source": {
            "pluginId": PLUGIN_ID,
            "capabilityId": SOURCE_CAPABILITY_ID,
            "instanceProperty": "instanceId",
        },
        "type": "object",
        "additionalProperties": False,
        "required": ["instanceId"],
        "properties": {
            "instanceId": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "x-open-cinema-widget": "plugin-instance-select",
                "x-open-cinema-plugin": "open-cinema.librespot",
                "x-open-cinema-capability": "open-cinema.librespot.sources",
            }
        },
    },
    editable_fields=("/instanceId",),
)


def validate_source(context: ProcessingHookContext) -> tuple[ProcessingValidationIssue, ...]:
    instance_id = context.configuration.get("instanceId")
    if not isinstance(instance_id, str) or not instance_id:
        return (
            ProcessingValidationIssue(
                "/instanceId", "librespot-instance-required", "Select a Spotify Connect instance."
            ),
        )
    return ()


def plan_source(context: ProcessingHookContext) -> ProcessingPlan:
    instance_id = str(context.configuration["instanceId"])
    availability = context.observed_facts.get("routeAvailable")
    return ProcessingPlan(
        context.node_instance_id,
        resource_requests=(
            {
                "kind": "logical-endpoint",
                "endpointId": managed_source_endpoint_id(
                    PLUGIN_ID,
                    SOURCE_CAPABILITY_ID,
                    instance_id,
                ),
                "direction": "input",
            },
        ),
        explanation={
            "summary": "Spotify Connect source selected",
            "instanceId": instance_id,
            "routeAvailable": availability,
        },
    )
