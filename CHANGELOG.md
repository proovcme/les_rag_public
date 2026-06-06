# Changelog

## 0.1.1.dev0 - unreleased

- Development version after the first boxed install stress release.
- Next patch target: Linux Docker smoke, Windows smoke, demo corpus/index flow,
  and release automation.

## 0.1.0 - 2026-06-06

- First private boxed LES release.
- Published GitHub release `v0.1.0` for `proovcme/les_rag`.
- Attached boxed artifacts for:
  - macOS native;
  - Linux Docker;
  - Linux systemd;
  - Windows Docker;
  - Windows lite.
- Completed destructive macOS reinstall stress test from fresh clone.
- Fixed clean-clone launchd plist root rendering.
- Fixed missing `proxy/storage` package in clean clones.
- Fixed Sovushka startup without a pre-existing `static/` directory.
- Made MLX tokenizer preload lazy by default so health endpoints open before
  model/tokenizer warmup.
- Added empty-dataset retrieval short-circuit so fresh installs return fast
  empty search responses.
- Documented reinstall stress results in `docs/MAC_REINSTALL_STRESS.md`.

Known release scope:

- macOS native was hardware-smoked on Apple Silicon.
- Linux and Windows artifacts were packaged but not hardware-smoked.
- Fresh install starts empty; operators must add/index their own corpus.
