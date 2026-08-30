# Open Cinema Librespot

`open-cinema-librespot` adds one or more independently configured Spotify Connect receivers to
Open Cinema. Each enabled receiver is supervised by the dedicated Open Cinema orchestrator and
appears as a stable, routable stereo input; librespot never selects speakers or creates an
automatic physical-output link.

## Runtime architecture

The plugin pins librespot 0.8.0 at commit
`d36f9f1907e8cc9d68a93f8ebc6b627b1bf7267d`. A verified platform wheel contains the librespot
binary and a typed headless-OAuth helper. At runtime, the orchestrator starts one process group per
instance:

```text
librespot (pipe backend, F32 stereo 44.1 kHz)
    stdout -> pw-cat (unlinked PipeWire playback stream, target 0)
```

The bridge advertises immutable plugin, instance, and generation properties. Core WyrePlumber
observation performs the correlation, publishes the durable logical input, and controls graph
routing. The plugin does not import private Open Cinema models or orchestration services.

Supported production wheels target Linux x86-64 and ARM64. Spotify Premium is an upstream
librespot requirement. PulseAudio, ALSA output ownership, Spotify browsing, and Spotify Free are
not part of this plugin.

## Install and develop

Normal appliance installation uses the Open Cinema Plugins marketplace and a published,
digest-pinned platform wheel. A local checkout can be installed as an editable development source:

```bash
uv sync --all-groups
python scripts/build_runtime_assets.py --architecture x86_64
uv run pytest
```

The explicit asset build requires Rust 1.85 and Git. Production installation never invokes Cargo.
The host needs `pw-cat`; the Raspberry Pi deployment supplies it with PipeWire.

## Configuration and authentication

Create a receiver from the dedicated **Spotify Connect** menu. The essential flow asks for a unique
Connect name, a device type, and playback quality. Discovery is the zero-secret default: select the
receiver from a Spotify client on the same network.

The complete operator workflow is documented in [docs/ADMINISTRATION.md](docs/ADMINISTRATION.md).

Access tokens are write-only Open Cinema secrets and are passed through a bounded child-process
environment, never an argument. Guided OAuth uses the packaged helper and a pasted callback URL;
authorization codes and reusable credentials are never returned in diagnostics. Its refresh token
is submitted to the fixed helper over stdin before later starts, and rotated credentials are written
back through the secret store. Credential and audio caches live in private per-instance directories.

Spotify's initial/remote volume settings change samples inside librespot. The Devices page's input
trim and mute are separate PipeWire controls and are shown only when the correlated stream exposes
writable controls.

## Multiple instances and graph routing

Instances have independent UUIDs, names, authentication, caches, configuration generations,
processes, endpoints, and health. Their Connect names must be unique. Graphs save only the stable
instance/endpoint identity; a restart may replace PipeWire numeric IDs without changing the graph.

A common policy is an ordered input selector with an active Spotify instance ahead of TV, followed
by CamillaDSP and an ordered output selector with a connected headset ahead of main speakers.
Stopping playback clears the activity fact after the configured hold interval; it does not stop
the discoverable receiver.

## Upstream options

Every option from the pinned `librespot --help` is classified in
[`option-contract/librespot-v0.8.0.json`](option-contract/librespot-v0.8.0.json). Safe options are
typed fields, product-owned values remain visible as managed, and unsupported choices include an
explanation. There is deliberately no raw extra-arguments field. Run the drift audit with:

The generated human-readable table is available in [docs/OPTIONS.md](docs/OPTIONS.md).

```bash
python scripts/audit_options.py \
  --help-output open_cinema_librespot/runtime_assets/bin/x86_64/librespot-help.txt
```

## Validation and release

```bash
ruff format --check open_cinema_librespot tests
ruff check open_cinema_librespot tests
mypy open_cinema_librespot
pytest
python -m build
python scripts/verify_wheel.py dist/*.whl
twine check dist/*
```

Releases use tags matching `open_cinema_librespot/version.py` and build both Linux architectures.
The workflow first uploads an unpublished draft, downloads each wheel on its native runner, and
installs it with the pinned Open Cinema contract host and immutable WyrePlumber release. Runtime,
plugin, librespot, option-map, provenance, and checksum identities must all agree before the draft
is made public. A failed smoke gate leaves only a draft and never publishes the candidate as the
latest release.

## Troubleshooting and security

- **Receiver is absent in Spotify:** enable discovery, verify the selected interface/address, and
  confirm the client can reach the appliance multicast network.
- **Receiver exists but is unavailable in a graph:** inspect the instance's process health and
  PipeWire correlation. Missing, stale, mismatched, and duplicate streams are reported separately.
- **Authentication failed:** retry discovery, replace the write-only access token, or run guided
  OAuth again. Cached credentials can be disabled only when the selected auth mode permits it.
- **Local directory rejected:** configure an appliance media root first; arbitrary filesystem paths
  and executables are never accepted.
- **Repeated crash:** use the resource diagnostics. Restart storms are bounded and require a manual
  restart after cooldown/exhaustion.

Plugin code runs as the unprivileged Open Cinema service user and is trusted code, not a sandbox.
The supervisor uses fixed executable paths and argument arrays, a bounded environment, private
directories, no shell, separate bounded log tails, and secret redaction.

Licensed under the MIT License. See [LICENSE](LICENSE).
