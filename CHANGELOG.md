# Changelog

## 0.1.6 - 2026-08-30

- Keep Open Cinema host compatibility in the plugin manifest instead of wheel
  runtime dependencies, allowing the marketplace overlay to resolve only
  plugin-owned dependencies.
- Install the complete clean Open Cinema host dependency set in release smoke
  fixtures before validating downloaded plugin wheels.

## 0.1.5 - 2026-08-30

- Correct the immutable release asset selector so both architecture provenance
  documents are published and smoke-tested with the wheels.

## 0.1.4 - 2026-08-30

- Preserve Git safe-directory trust across checkout and build-container home changes.

## 0.1.3 - 2026-08-30

- Make release-build Git checks use the explicit Actions workspace inside build containers.

## 0.1.2 - 2026-08-30

- Correct the source-tree version lookup used by dependency-free ARM64 asset builds.

## 0.1.1 - 2026-08-30

- Corrective first publication after the `0.1.0` tag stopped before artifact creation.
- Make release checkouts retain Git metadata inside the minimal build containers.
- Detect the PipeWire `pw-cat --raw` requirement across supported PipeWire versions.

## 0.1.0 - 2026-08-30

- Initial external Open Cinema Spotify Connect source plugin.
- Multi-instance managed librespot and PipeWire bridge contract.
- Declarative administration UI and desired-graph source contribution.
- Draft-gated x86-64 and ARM64 release workflow with clean downloaded-wheel verification.
