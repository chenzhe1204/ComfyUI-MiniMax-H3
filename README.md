# ComfyUI MiniMax H3 (Unofficial)

Unofficial ComfyUI nodes for running **MiniMax H3** video generation on Apple
Silicon through the native Metal [`h3.c`](https://github.com/antirez/h3.c) CLI.

> **Model license / territory notice**
>
> This repository does **not** contain MiniMax H3 model weights. Model weights
> are downloaded separately and are governed by the **MiniMax H3 Community
> License Agreement**, which excludes the **European Union, the United Kingdom,
> the Republic of Korea, and the United States of America** from its Applicable
> Territory. It also contains commercial-use, acceptable-use, and redistribution
> conditions. Review the official license before downloading or using the
> weights: <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE>.

> **Unofficial project.** Not affiliated with, endorsed by, or sponsored by
> MiniMax, ComfyUI, or the h3.c authors. "MiniMax H3" is used only to describe
> compatibility.

[中文说明](README.zh-CN.md)

## Features

- **`MiniMax H3 FL2VA`** — text-to-video, first-frame, last-frame, or both.
- **`MiniMax H3 Ref2VA`** — ordered reference images, optional 2–15 s reference
  audio, and the `match`/`max` reference sizing policy.
- Generates a 24 fps H.264 MP4 with a 32 kHz stereo AAC track.
- Saves directly to `ComfyUI/output`, shows a video preview, and exposes a
  standard `VIDEO` output plus a `saved_path` string.
- Full H3 parameter surface: resolution, frames/duration, steps, layers, reuse,
  token reduction, SSD streaming, int8 FC2, internal render size, seed, and
  profile.
- Progress parsing, cancellation, timeout, and partial-output cleanup.
- A cross-process lock so two ComfyUI instances do not start two H3 models at
  once.
- Environment/config-file based paths, with preflight checks and a doctor script.

## Requirements

| Requirement | Notes |
|---|---|
| Apple Silicon Mac | Metal only; Intel Macs, Windows, and Linux are not supported. |
| macOS | Tested on macOS 26.x with an M5 Max. |
| Unified memory | 128 GB is the validated configuration. Lower-memory machines may work with `ssd_streaming` but are not validated. |
| Disk | The current checkpoint tree is roughly 464 GB; plan for 500 GB+ free. |
| ComfyUI | `>= 0.41.2` (tested with 0.41.2). The V3 node API and `VIDEO` type are required. |
| Python | 3.10+. |
| h3.c | Built from the pinned upstream commit; see below. |
| FFmpeg / FFprobe | Required by h3.c for media input and MP4 output. `brew install ffmpeg`. |
| Python packages | `torch`, `numpy`, and `Pillow` are provided by ComfyUI. This package has **no extra runtime pip dependencies**. |

## Installation

### 1. Install the ComfyUI node

```sh
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/chenzhe1204/ComfyUI-MiniMax-H3.git comfyui-minimax-h3
```

Or, for a development checkout:

```sh
cd /path/to/ComfyUI-MiniMax-H3
./install.sh /path/to/ComfyUI
```

The repository includes ComfyUI Registry metadata in `pyproject.toml`
(`PublisherId = chenzhe1204`).

### 2. Build h3.c

The adapter invokes `h3` as a subprocess and does not vendor it. Build the pinned
commit into `third_party/h3.c`:

```sh
./scripts/bootstrap_h3.sh
```

This requires the Xcode command line tools (`clang`, the macOS SDK) and `make`.
If you already have an `h3.c` checkout, point `H3_BIN` at its `h3` executable
instead. The binary must remain next to `h3_shaders.metal`; do not copy the
binary alone.

Pinned upstream commit: `8974cc055ea9c02fcd14cc27dfda3e1027c05153`
(`h3-metal 0.1.0-dev`). The CLI contract is checked by `scripts/doctor.py`.

### 3. Download the model weights

Follow the official model instructions and accept the license first:

```sh
hf download MiniMaxAI/MiniMax-H3 \
  --include "model_index.json" "FL2VA/*" "Ref2VA/*" \
  --local-dir /path/to/MiniMax-H3
```

The FL2VA node needs `FL2VA/transformer`; the Ref2VA node additionally needs
`Ref2VA/transformer`. The adapter does not mirror or redistribute weights.

### 4. Configure paths

Configuration files are resolved in this order. **The first existing file wins;
files are not merged.**

| Priority | Source | Notes |
|---:|---|---|
| 1 | `H3_CONFIG` | Explicit JSON path; no fallback if it does not exist. |
| 2 | `<node>/config.json` | Portable/development override. Ignored by Git and the Registry package, but a node update may replace it. |
| 3 | `<ComfyUI>/user/default/comfyui-minimax-h3.json` | Recommended for normal installs. Follows `--user-directory`. |
| 4 | `~/.config/comfyui-minimax-h3/config.json` | Only when ComfyUI's `folder_paths` is unavailable (for example `scripts/doctor.py` outside ComfyUI). |

`<node>` is the installed node directory
(`ComfyUI/custom_nodes/comfyui-minimax-h3`).

Individual environment variables override values from the selected file:

| Variable | Purpose |
|---|---|
| `H3_DIR` | A directory containing `h3` and `model/`; derives both paths. |
| `H3_MODEL_DIR` | Explicit model directory. |
| `H3_BIN` | Explicit `h3` executable. |
| `H3_FFMPEG` / `H3_FFPROBE` | Explicit FFmpeg tools (h3.c also reads these). |
| `H3_CONFIG` | Explicit JSON config path (highest file priority). |
| `H3_SERIALIZE` | `1` (default) serializes generations; `0` disables the lock. |
| `H3_KEEP_TEMP` | `1` keeps the temporary images/audio for debugging. |
| `H3_AUTO_DETECT` | `0` disables development auto-detection of `third_party/h3.c`. |

Recommended normal install — create
`ComfyUI/user/default/comfyui-minimax-h3.json`:

```json
{
  "h3_dir": "/absolute/path/to/h3.c",
  "model_dir": "/absolute/path/to/MiniMax-H3"
}
```

Portable/development install — create `<node>/config.json` with the same
contents. This keeps the configuration with the checkout but may be overwritten
by a node update; delete it to fall back to the ComfyUI user config.

`h3_dir` alone assumes the weights live at `<h3_dir>/model`; set `model_dir`
when they were downloaded elsewhere.

A full config file can also set `model_dir`, `h3_binary`, `ffmpeg`, `ffprobe`,
`serialize`, `keep_temp`, and `auto_detect`; see
[config.example.json](config.example.json).

`~/.config/comfyui-minimax-h3/config.json` is **not** used by a normal ComfyUI
process; it is only the standalone-tool fallback when ComfyUI's `folder_paths`
module cannot be imported.

### 5. Restart ComfyUI and run the doctor

```sh
python scripts/doctor.py --mode ref2va
```

Then restart ComfyUI and search for the `MiniMax H3` category.

> **Upgrading from the pre-0.1 development version:** the node IDs are
> unchanged, but `model_dir` and `h3_binary` are no longer node widgets. Delete
> and re-add the node in older workflows, then configure paths through the
> environment or the JSON config file.

## Nodes

### FL2VA — text-to-video and first/last frame

| Input | Required | Description |
|---|---|---|
| `prompt` | yes | Context-IR style prompt: scene, action, camera, look, sound. |
| `first_frame` | no | First-frame conditioning; stretched to the canvas. |
| `last_frame` | no | Last-frame conditioning; aspect-cover scaled and center-cropped. |

No image means text-to-video (T2VA), still using the FL2VA checkpoint.

### Ref2VA — reference image and audio

| Input | Required | Description |
|---|---|---|
| `prompt` | yes | Use `<Picture 1>`, `<Picture 2>`, … to refer to references. |
| `ref_images` | yes | Ordered batch; item 1 becomes `<Picture 1>`, up to 9 images. |
| `ref_audio` | no | 2–15 s reference audio. Must be used with reference images. |
| `ref_image_size` | yes | `match` (aspect-preserving) or `max` (largest reference canvas). |

FL2VA and Ref2VA are mutually exclusive; H3 does not support mixing first/last
frames with ordered references.

### Common generation parameters

| Parameter | Default | Notes |
|---|---:|---|
| `width` / `height` | 512 / 512 | Multiples of 32; `width*height <= 768*1344`. |
| `frames` | 56 | H3 rounds up to `5+17n`. 22≈0.92 s, 56≈2.33 s, 107≈4.46 s, 243≈10.1 s, 362≈15.08 s. |
| `seconds` | 0 | If >0, overrides `frames` and converts at 24 fps. |
| `steps` | 20 | 4–7 for drafts; 50 for reference quality. |
| `layers` | 45 | DiT blocks: 50 exact, 45 fast, 40 aggressive. |
| `reuse` | 2 | 1 exact, 2 fast, 3 aggressive. |
| `core_reuse` | 1 | 1 exact, 4 fast, 6 aggressive; cannot be combined with `reuse>1`. |
| `token_reduction` | off | Faster, may change composition. |
| `ssd_streaming` | off | Lower memory, slower; cannot be combined with `int8_row_fc2`. |
| `int8_row_fc2` | off | M5-only faster int8 FC2. |
| `use_reference_rope` | off | Restore the released spatial RoPE. |
| `render_width` / `render_height` | 0 / 0 | Internal render canvas; 0 = output size. |
| `seed` | 42 | Native H3 seed. |
| `filename_prefix` | `minimax_h3/H3` | Prefix under `ComfyUI/output`. |

`timeout_seconds` and `profile` are advanced inputs. All generated MP4s include
audio; use `GetVideoComponents` if you need the audio separately.

### Outputs

- `video` — ComfyUI `VIDEO`, usable with `SaveVideo`, `GetVideoComponents`, etc.
- `saved_path` — absolute path to the self-saved MP4.
- The node itself is an output node, so queuing it is enough to save the video.

## Prompt and media notes

- H3 responds well to a structured prompt:
  `Scene: ... Action: ... Camera: ... Look: ... Audio: ...`
- Multiple reference images are passed in **batch order**. Combine images with
  `ImageBatch` (or a similar node) before `ref_images`.
- Reference audio must be **2–15 seconds**. Trim it with `TrimAudioDuration` if
  necessary. H3 does not support standalone audio without an image/video
  reference, so `ref_audio` requires `ref_images`.
- H3 outputs 24 fps and aligns frame requests upward. Requesting 23 frames
  produces 39 frames.

## Performance

Validated on an M5 Max with 128 GB unified memory and ComfyUI 0.41.2:

| Test | Configuration | Result |
|---|---|---|
| Native standard | 512×512, 22 frames, 20 steps, layers 45, reuse 2 | ~52 s |
| ComfyUI FL2VA | 256×256, 22 frames, 4 steps, layers 50, reuse 1 | ~35–45 s |
| ComfyUI Ref2VA | 256×256, 22 frames, 4 steps, reference image + 3 s audio | ~55–60 s |

Every execution starts a fresh h3 process, so the cold-start cost is paid on
each run. The process exits and releases its unified memory when generation
finishes. `H3_SERIALIZE=1` prevents two runs from starting at once.

## Troubleshooting

Run the doctor first:

```sh
python scripts/doctor.py --mode ref2va
```

Common issues:

- **`h3_shaders.metal is missing`** — run `h3` from the directory containing the
  shader; `H3_BIN` must point at that build.
- **`ffmpeg not found`** — install FFmpeg or set `H3_FFMPEG` / `H3_FFPROBE`.
- **Missing `FL2VA/transformer` or `Ref2VA/transformer`** — the model download
  is incomplete or `H3_MODEL_DIR` points at the wrong directory.
- **ComfyUI version too old** — update ComfyUI; the V3 node API and `VIDEO` type
  are required.
- **Out of memory** — close other models, lower the canvas/frames, or use
  `ssd_streaming`.
- **h3 exits with a code** — the error includes the last h3 output. Check the
  canvas, frame count, audio duration, and available memory.

## Security

- `h3` executes as a local process with your privileges; there is no sandbox.
- `h3_binary` is intentionally **not** a node widget. Binary/model paths are
  administrator configuration, so an untrusted workflow cannot point the node at
  an arbitrary executable.
- Prompts and media are passed as argv entries without a shell. Temporary files
  are private and removed after the run by default.
- Do not run untrusted workflows or load untrusted model files. See
  [SECURITY.md](SECURITY.md).

## Compatibility

| Component | Version |
|---|---|
| Node | 0.1.0 |
| ComfyUI | >= 0.41.2, tested 0.41.2 |
| h3.c | `8974cc055ea9c02fcd14cc27dfda3e1027c05153` |
| Model | MiniMax-H3 (FL2VA / Ref2VA) |
| macOS | 26.x tested |
| Hardware | M5 Max, 128 GB tested |

The h3.c CLI is under active development. Update the pinned commit deliberately
and run `python scripts/doctor.py` after every upgrade.

## Development and testing

Unit tests use a fake h3 binary and do not load the model. Use ComfyUI's Python
(or install `torch`, `numpy`, and `Pillow`) so the IMAGE/AUDIO tests can import
their dependencies:

```sh
python -m unittest discover -s tests -t . -v
```

ComfyUI node integration tests (fake h3, real ComfyUI imports):

```sh
COMFYUI_DIR=/path/to/ComfyUI \
  python -m unittest tests.check_nodes_integration -v
```

Optional real-model smoke test:

```sh
python tests/smoke_generate.py --frames 22 --steps 4
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup details. Please do not include
model weights, generated media, or private paths in issues or pull requests.

## License and third-party notices

The code in this repository is licensed under
[GPL-3.0-or-later](LICENSE), matching ComfyUI's GPL-3.0 license.

- MiniMax H3 model weights: MiniMax H3 Community License Agreement; not included.
- h3.c: MIT, Copyright (c) 2026 Salvatore Sanfilippo; not included.
- ccv Metal FlashAttention portions: BSD-3-Clause; see h3.c's notices.
- Qwen3-VL-32B encoder: Apache-2.0; part of the model, not included.
- ComfyUI: GPL-3.0; runtime host, not included.
- FFmpeg/FFprobe: external commands, not bundled.

See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the
full attribution and license summary. This is not legal advice; verify the model
license and your distribution obligations before publishing or commercial use.
