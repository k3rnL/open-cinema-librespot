# Local acceptance evidence

## 2026-08-30 development checkout

The plugin was validated from the editable sibling checkout against the Open Cinema
contract host and the generic admin renderer.

- Open Cinema system check and migration drift check passed.
- 73 focused Open Cinema plugin, storage, managed-source, catalogue, resolver, and
  reconciliation tests passed.
- The full Open Cinema suite passed with 1,149 tests.
- The plugin suite passed with 35 tests; the ordinary run skips only the opt-in live
  PipeWire test.
- The explicit live PipeWire test passed and proved an unlinked 44.1-kHz stereo F32
  stream, exact correlation, core-controlled linking, and removal on stop.
- Strict mypy checking passed for all 14 plugin source modules. Ruff formatting and
  lint checks passed before the final package build.
- The complete UI type check, lint, shared tests (23), admin tests (56 after the
  state-matrix additions), screen UI test (1), and both production builds passed.
- The option audit classified all 50 options observed in the pinned executable help,
  plus the conditional contract entry, with no unclassified option.
- Cargo formatting, clippy, and tests passed for the pinned headless OAuth helper.
- Two clean x86-64 runtime builds produced the same librespot SHA-256:
  `3b150a07b173c8d1dfa265bb6fb7735b6c1aea59deb9f8a3f66933fec861cac2`.
- The final wheel was tagged `py3-none-linux_x86_64`, contained both verified native
  executables and their identity document, and passed the wheel verifier.
- A clean-wheel smoke environment reported plugin `0.1.0`, six capabilities, and
  librespot `0.8.0`.
- The local API, orchestrator, Redis, and Vite admin were started together; runtime
  readiness was green and the declarative Spotify Connect page and managed source
  graph node were discovered without plugin-specific frontend code.

The live development-server campaign then added the following acceptance evidence:

- A real Spotify client discovered, paired with, and played through the `Open Cinema`
  instance and the active Open Cinema graph.
- Spotify activity selected the managed source and stopping playback returned to the
  ROC fallback while leaving discovery running.
- Devices input trim and mute were changed through the public endpoint controls and
  reconciled back to the observed PipeWire values.
- An intentional bridge-process crash replaced the complete supervised process group,
  recreated one correlated PipeWire stream, restored the fallback, and selected Spotify
  again when playback resumed.
- Plugin restart and event-sequence reset retained activity updates and automatic route
  resolution.
- A second independent instance was created and both Connect names were simultaneously
  visible in the real Spotify client. Its processes and PipeWire stream disappeared on
  stop before the temporary instance was deleted.
- Final restoration retained the original enabled instance, active graph revision, and
  a converged stereo route with exactly the expected two Open Cinema-owned links.

This evidence does not claim ARM64 artifact publication, Raspberry Pi acceptance, or
downloaded-release testing. Those checks remain open in the OpenSpec task list.
