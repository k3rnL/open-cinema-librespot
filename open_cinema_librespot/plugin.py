from __future__ import annotations

from collections.abc import Sequence

from open_cinema_plugin_sdk import (
    AdminUICapability,
    ApiCapability,
    AutomationCapability,
    DistributionLifecycleContext,
    ManagedAudioSourceCapability,
    ManagedResourceCapability,
    OpenCinemaPlugin,
    PluginCapabilityContribution,
    PluginRuntimeResult,
    ProcessingCapability,
    RuntimePluginIdentity,
    RuntimeStatus,
)

from .api import API
from .configuration import instance_schema
from .graph import SOURCE_NODE, plan_source, validate_source
from .provider import PROVIDER
from .ui import ADMIN_UI
from .version import __version__

PLUGIN_ID = "open-cinema.librespot"


class LibrespotPlugin(OpenCinemaPlugin):
    @property
    def identity(self) -> RuntimePluginIdentity:
        return RuntimePluginIdentity(PLUGIN_ID, "open-cinema-librespot", __version__)

    def capabilities(self) -> Sequence[PluginCapabilityContribution]:
        schema = instance_schema()
        return (
            ApiCapability(f"{PLUGIN_ID}.api", routes=API.urls),
            AutomationCapability(
                f"{PLUGIN_ID}.automations",
                hooks={
                    f"{PLUGIN_ID}.source-status": self.source_status,
                    f"{PLUGIN_ID}.restart-source": self.restart_source,
                },
            ),
            ProcessingCapability(
                f"{PLUGIN_ID}.graph",
                node_types=(SOURCE_NODE,),
                validate_hook=validate_source,
                plan_hook=plan_source,
            ),
            ManagedResourceCapability(
                f"{PLUGIN_ID}.resources",
                resource_type=f"{PLUGIN_ID}.resource",
                provider=PROVIDER,
                instance_schema=schema,
            ),
            ManagedAudioSourceCapability(
                f"{PLUGIN_ID}.sources",
                source_type=f"{PLUGIN_ID}.source",
                provider=PROVIDER,
                instance_schema=schema,
                signal_contract={
                    "mediaKind": "audio",
                    "content": "pcm",
                    "sampleFormats": ["FLOAT32LE"],
                    "rates": [44100],
                    "layouts": [{"channels": 2, "positions": ["FL", "FR"]}],
                },
                correlation_keys=(
                    "open-cinema.plugin.id",
                    "open-cinema.instance.id",
                    "open-cinema.generation",
                ),
            ),
            AdminUICapability(f"{PLUGIN_ID}.admin", descriptor=ADMIN_UI),
        )

    @staticmethod
    def source_status(instance_id: str) -> dict[str, object]:
        return API._observe(API.instances.get(instance_id))

    @staticmethod
    def restart_source(instance_id: str) -> dict[str, object]:
        item = API.instances.get(instance_id)
        if item.desired_state != "enabled":
            raise ValueError("enable this source before restarting it")
        return API._observe(
            API.instances.update(
                instance_id,
                configuration=item.configuration,
                expected_version=item.update_version,
            )
        )

    def start(self, context: DistributionLifecycleContext) -> PluginRuntimeResult:
        # Long-lived instances are reconciled only by the dedicated Open Cinema orchestrator.
        return PluginRuntimeResult(
            RuntimeStatus.READY,
            facts={"pluginVersion": __version__, "instanceCount": len(API.instances.list())},
        )

    def stop(self, context: DistributionLifecycleContext) -> PluginRuntimeResult:
        PROVIDER.supervisors.stop_all()
        return PluginRuntimeResult(RuntimeStatus.READY)
