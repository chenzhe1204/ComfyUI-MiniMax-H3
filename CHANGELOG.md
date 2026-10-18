# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-18

### Added

- `MiniMaxH3_FL2VA` node for text-to-video and first/last-frame conditioning.
- `MiniMaxH3_Ref2VA` node for ordered reference images and optional 2-15s
  reference audio.
- Self-save to `ComfyUI/output` plus a `VIDEO` output and a `saved_path` string.
- Configuration through `H3_DIR`, `H3_MODEL_DIR`, `H3_BIN`, `H3_FFMPEG`,
  `H3_FFPROBE`, `H3_CONFIG`, and a JSON config file.
- Preflight checks for macOS/arm64, ComfyUI version, ffmpeg/ffprobe, h3 binary,
  Metal shader, and model layout.
- A file lock that serializes H3 generations across processes.
- Progress parsing, cancellation, timeout, and partial-output cleanup.
- Unit tests with a fake h3 binary and optional ComfyUI integration tests.
- `scripts/bootstrap_h3.sh` pinned to a known h3.c commit.
- `scripts/doctor.py` for environment diagnostics.
- English README and Chinese README.

### Changed

- Removed `model_dir` and `h3_binary` from the node widgets. These are now
  administrator configuration, so an untrusted workflow cannot point the node at
  an arbitrary executable.
- Debug logging no longer includes the prompt or media paths.

### Security

- Local subprocess execution is documented in `SECURITY.md`; there is no
  sandbox around the native h3 process.
