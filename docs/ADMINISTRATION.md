# Spotify Connect administration

## Create and discover a receiver

Open **Spotify Connect** and choose **Create receiver**. Give it a unique Connect name, then keep
**Spotify Connect discovery** unless the network requires another authentication method. Device
type and bitrate only affect how Spotify presents the receiver and the requested upstream quality;
Open Cinema always exposes decoded 44.1-kHz stereo floating-point PCM to the graph.

After creation, the detail drawer keeps its layout stable while status refreshes. **Desired state**
records whether Open Cinema should run the receiver. **Observed state**, health, Spotify session,
playback, and PipeWire correlation describe what is actually running. Start, stop, restart, delete,
and authentication actions are shown only when currently safe. A stale edit or action asks you to
refresh instead of overwriting a concurrent change.

In discovery mode, open Spotify on the same network and select the configured Connect name. A
receiver can remain healthy and idle: route availability means its exact PipeWire stream exists;
active signal means Spotify is playing or remains inside the configured short activity hold.

## Authentication

- **Discovery** stores no Spotify secret and is the recommended default.
- **Access token** is write-only. Reopening the form shows only whether a token is configured. To
  remove it, first switch the instance to discovery or OAuth, save, then use **Remove stored access
  token**.
- **Guided OAuth** opens Spotify authorization in a new page. Paste the complete callback URL into
  the guided operation. The authorization operation can expire, fail, be retried, or be cancelled
  without exposing tokens. Successful refresh credentials are kept in the private secret store and
  refreshed over stdin on later starts.
- **OAuth/cached username** optionally selects a previously cached Spotify credential. Reauthorize
  if Spotify rejects or expires it.

## Audio, cache, files, and upstream options

Spotify initial volume, volume curve, range, and remote steps alter librespot's samples. They are
not the Open Cinema input trim and mute controls shown for the logical device; those operate on the
fresh correlated PipeWire stream.

Audio and credential caches are private to each instance. The detail summary reports cache size and
credential-persistence warnings. Local-file directories are ordered, must sit under administrator-
configured media roots, and cause a receiver restart. Arbitrary executable paths and command-line
arguments are never accepted.

Every pinned librespot option is present in the UI contract or the option reference. **Managed
automatically** explains fixed product-owned values such as the pipe backend and F32 output.
**Unavailable in this integration** explains unsafe or incompatible upstream options. See
[OPTIONS.md](OPTIONS.md) for the exhaustive classification.

## Graph routing and multiple instances

Each receiver owns one durable logical input and one independently selectable **Spotify Connect
source** graph node. The saved node contains the stable instance identity, never a PipeWire numeric
ID. Disabled, deleted, failed, stale, or ambiguous instances leave the graph structurally intact
and visibly unavailable.

For automatic fallback, put the Spotify endpoint before TV in an ordered input selector and require
its `activeSignal` fact. Continue through decoder/CamillaDSP, then put the headset before main
speakers in an ordered output selector. Applying or deactivating the graph changes routes only; it
does not start or stop the receiver process.

Multiple receivers have separate names, authentication, cache, processes, generations, endpoints,
health, and graph selection. One failed or restarted receiver must not disturb another.

## Disable, uninstall, troubleshoot, and roll back

Stopping an instance preserves its settings and endpoint. Disabling the plugin stops all plugin
capabilities while retaining data. Uninstall normally retains settings and secrets for a later
reinstall; explicit plugin-data deletion is destructive. Open Cinema preserves graph references as
unavailable throughout these operations. Marketplace rollback restores the last complete verified
plugin overlay.

If audio is unavailable, check in this order:

1. Desired versus observed process state and the last bounded process error.
2. Spotify session/playback state and authentication recovery message.
3. PipeWire correlation: missing, stale, mismatched, or duplicate streams are distinct failures.
4. The logical endpoint's route availability and graph explanation.
5. The graph's selected input/output and CamillaDSP health.

Use **Restart** for an isolated receiver failure. Repeated crashes use bounded backoff and cooldown;
they never trigger an unbounded restart storm. Use the Plugins page for distribution-level restart,
disable, update, uninstall, and rollback operations.
