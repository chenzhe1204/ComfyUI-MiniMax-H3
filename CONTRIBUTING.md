# Contributing

Thanks for helping improve the unofficial ComfyUI MiniMax H3 nodes.

## Scope

This repository is an adapter around the native h3.c CLI. It does not contain
the model weights and does not fork h3.c. Please report model-quality questions
to the upstream model project and CLI changes to the h3.c project.

## Development setup

Requirements:

- macOS on Apple Silicon (M-series).
- Python 3.10+.
- ComfyUI checkout (tested with 0.41.2).
- `ffmpeg` and `ffprobe` on `PATH` (or configured via `H3_FFMPEG`/`H3_FFPROBE`).
- h3.c built at the pinned commit (see below).
- Model weights downloaded from the official MiniMax source.

Build h3.c into `third_party/h3.c`:

```sh
./scripts/bootstrap_h3.sh
```

Download the weights (accept the MiniMax H3 Community License first):

```sh
hf download MiniMaxAI/MiniMax-H3 \
  --include "model_index.json" "FL2VA/*" "Ref2VA/*" \
  --local-dir MiniMax-H3
```

Configure the paths:

```sh
export H3_MODEL_DIR="$PWD/MiniMax-H3"
export H3_BIN="$PWD/third_party/h3.c/h3"
```

or create `ComfyUI/user/default/comfyui-minimax-h3.json`:

```json
{
  "h3_dir": "/absolute/path/to/h3.c",
  "model_dir": "/absolute/path/to/MiniMax-H3"
}
```

Run the doctor:

```sh
python scripts/doctor.py --mode ref2va
```

## Tests

Unit tests use a fake h3 binary and do not load the model. Run them with
ComfyUI's Python (or another environment with `torch`, `numpy`, and `Pillow`) so
the IMAGE/AUDIO tests can import their dependencies:

```sh
python -m unittest discover -s tests -t . -v
```

ComfyUI node integration tests (fake h3, real ComfyUI imports):

```sh
COMFYUI_DIR=/path/to/ComfyUI \
  python -m unittest tests.check_nodes_integration -v
```

Optional real-model smoke test (heavy, uses the GPU and unified memory):

```sh
python tests/smoke_generate.py --frames 22 --steps 4
```

## Pull requests

- Keep changes focused and add tests for new validation or process behavior.
- Run `ruff check .` and the unit tests before submitting.
- Do not commit model weights, generated media, build artifacts, or local paths.
- Do not add a node input that executes an arbitrary filesystem path. Binary and
  model paths belong in configuration.
- Use English for code, identifiers, node labels, tooltips, and logs. Chinese
  documentation lives in `README.zh-CN.md`.
- Add an SPDX header to new Python/shell files:
  `SPDX-License-Identifier: GPL-3.0-or-later`.

## License

By contributing, you agree that your contributions are licensed under the
GNU General Public License v3.0 or later, matching this project. Model weights
and upstream h3.c remain under their own licenses; see `NOTICE` and
`THIRD_PARTY_NOTICES.md`.
