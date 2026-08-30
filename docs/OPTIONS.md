# Librespot 0.8.0 option compatibility

This table is generated from the complete pinned option contract. CI compares both option types and
the normalized full help text so changed choices or semantics require an explicit review.

| Option | Kind | Open Cinema state | Representation |
| --- | --- | --- | --- |
| `--help` | flag | action | Show embedded option reference |
| `--version` | flag | action | Show verified binary identity |
| `--verbose` | flag | equivalent | Typed field `/logLevel` |
| `--quiet` | flag | equivalent | Typed field `/logLevel` |
| `--disable-audio-cache` | flag | equivalent | Typed field `/cache/audioEnabled` (inverted) |
| `--disable-credential-cache` | flag | equivalent | Typed field `/cache/credentialsEnabled` (inverted) |
| `--disable-discovery` | flag | equivalent | Typed field `/discovery/enabled` (inverted) |
| `--disable-gapless` | flag | equivalent | Typed field `/playback/gapless` (inverted) |
| `--emit-sink-events` | flag | equivalent | Typed field `/automations/includeSinkEvents` |
| `--enable-volume-normalisation` | flag | configurable | Typed field `/normalisation/enabled` |
| `--enable-oauth` | flag | action | Guided headless OAuth operation |
| `--group` | flag | configurable | Typed field `/group` |
| `--name` | option | configurable | Typed field `/name` |
| `--bitrate` | option | configurable | Typed field `/bitrate` |
| `--format` | option | managed | Stable Open Cinema source signal |
| `--dither` | option | managed | Dither is unnecessary for F32 output |
| `--device-type` | option | configurable | Typed field `/deviceType` |
| `--tmp` | option | managed | Fixed to `private instance temporary directory` |
| `--cache` | option | managed | Fixed to `private instance audio cache` |
| `--system-cache` | option | managed | Fixed to `private instance credential cache` |
| `--cache-size-limit` | option | configurable | Typed field `/cache/sizeLimit` |
| `--backend` | option | managed | Open Cinema owns routing |
| `--username` | option | configurable | Typed field `/authentication/username` |
| `--password` | option | unavailable | Password login is deprecated and unsupported upstream |
| `--access-token` | option | equivalent | Typed field `write-only instance secret` |
| `--oauth-port` | option | managed | Headless callback-paste flow |
| `--onevent` | option | managed | Fixed to `fixed authenticated event relay` |
| `--alsa-mixer-control` | option | unavailable | The plugin does not own physical ALSA controls |
| `--alsa-mixer-device` | option | unavailable | The plugin does not own physical ALSA devices |
| `--alsa-mixer-index` | option | unavailable | The plugin does not own physical ALSA controls |
| `--mixer` | option | managed | Fixed to `softvol` |
| `--device` | option | managed | Fixed to `stdout pipe` |
| `--initial-volume` | option | configurable | Typed field `/volume/initialPercent` |
| `--volume-ctrl` | option | configurable | Typed field `/volume/control` |
| `--volume-range` | option | configurable | Typed field `/volume/rangeDb` |
| `--volume-steps` | option | configurable | Typed field `/volume/steps` |
| `--normalisation-method` | option | configurable | Typed field `/normalisation/method` |
| `--normalisation-gain-type` | option | configurable | Typed field `/normalisation/gainType` |
| `--normalisation-pregain` | option | configurable | Typed field `/normalisation/pregainDb` |
| `--normalisation-threshold` | option | configurable | Typed field `/normalisation/thresholdDbfs` |
| `--normalisation-attack` | option | configurable | Typed field `/normalisation/attackMs` |
| `--normalisation-release` | option | configurable | Typed field `/normalisation/releaseMs` |
| `--normalisation-knee` | option | configurable | Typed field `/normalisation/kneeDb` |
| `--zeroconf-port` | option | configurable | Typed field `/discovery/port` |
| `--proxy` | option | configurable | Typed field `/proxy` |
| `--ap-port` | option | configurable | Typed field `/apPort` |
| `--autoplay` | option | configurable | Typed field `/playback/autoplay` |
| `--zeroconf-interface` | option | configurable | Typed field `/discovery/interfaces` |
| `--zeroconf-backend` | option | configurable | Typed field `/discovery/backend` |
| `--local-file-dir` | repeatable-option | configurable | Typed field `/localFileDirectories` |
| `--passthrough` | conditional-flag | unavailable | Not compiled; the public source contract is decoded F32 PCM |
