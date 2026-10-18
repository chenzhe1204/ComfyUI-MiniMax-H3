# Security policy

## Supported versions

Security fixes are applied to the latest `0.1.x` release. This project is
macOS/Apple-Silicon only and requires a locally built h3.c and separately
downloaded model weights.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (Security → Report a
vulnerability) instead of opening a public issue. Include:

- affected node version and commit;
- ComfyUI version;
- h3.c commit;
- steps to reproduce;
- whether the issue requires running an untrusted workflow.

Do not include model weights, private prompts, or personal media in a report.

## Threat model

These nodes intentionally run a local native executable (`h3`) with the user's
privileges. They do not provide a sandbox.

- **Binary path is configuration, not a workflow input.** `h3_binary` is read
  from `H3_BIN`, `H3_DIR`, or the configuration file. It is deliberately not a
  node widget, so importing an untrusted workflow cannot point the node at an
  arbitrary executable.
- **Prompts, images, and audio are untrusted data.** They are passed as separate
  argv entries (no shell), written to a private temporary directory, and removed
  after the run unless `H3_KEEP_TEMP=1`.
- **Model files are untrusted input.** Only download weights from the official
  MiniMax source and verify what you are loading.
- **No network access or telemetry.** The nodes do not phone home. Network access
  is only involved if the user separately downloads weights.
- **Output paths are constrained by ComfyUI.** `filename_prefix` is resolved by
  `folder_paths.get_save_image_path`, which rejects paths outside the output
  directory.
- **Temporary files may contain private media.** Set `H3_KEEP_TEMP=0` (default)
  or clean the temporary directory manually if a run is interrupted in an
  unusual way.
- **Debug logs are redacted.** The H3 argv debug line replaces the prompt and
  media paths with `<redacted>`.

## Dependency and supply-chain notes

- h3.c is built from a pinned upstream commit; see `scripts/bootstrap_h3.sh`.
- Python runtime dependencies are provided by ComfyUI. This project does not pin
  or vendor PyTorch, NumPy, Pillow, or FFmpeg.
- Model weights are not distributed with this project and are subject to the
  MiniMax H3 Community License, including its territorial restrictions.
