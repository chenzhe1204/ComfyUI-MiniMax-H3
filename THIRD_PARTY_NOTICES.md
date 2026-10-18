# Third-party notices

This project is a Python/ComfyUI adapter. It does **not** vendor the MiniMax H3
model weights or the h3.c native project. The following projects are used at
runtime or are documented as optional dependencies.

## ComfyUI

- License: GPL-3.0
- Usage: runtime host and Python APIs (`folder_paths`, `comfy_api`, `comfy.utils`)
- Upstream: https://github.com/comfyanonymous/ComfyUI

Because the node imports ComfyUI's public Python APIs, this project is licensed
under GPL-3.0-or-later for compatibility. ComfyUI itself is not bundled.

## h3.c

- License: MIT
- Copyright (c) 2026 Salvatore Sanfilippo
- Upstream: https://github.com/antirez/h3.c
- Usage: external native CLI invoked as a subprocess; `scripts/bootstrap_h3.sh`
  can clone and build it at a pinned commit.

h3.c's own `THIRD_PARTY_NOTICES.md` documents the BSD-3-Clause notice for the
rectangular Morton decoder and the int8/Metal 4 TensorOps scheduling design
adapted from ccv's Metal FlashAttention:

- Copyright (c) 2010, Liu Liu
- License: BSD-3-Clause
- Upstream: https://github.com/liuliu/ccv

If you redistribute h3.c source or binaries, retain h3.c's MIT license and its
BSD-3-Clause notice. This adapter does not redistribute h3.c.

## MiniMax H3

- License: MiniMax H3 Community License Agreement
- Copyright © 2026 MiniMax. All Rights Reserved.
- Upstream: https://huggingface.co/MiniMaxAI/MiniMax-H3
- Usage: model weights are downloaded separately by the user; they are **not**
  included in this repository or its releases.

The license's Applicable Territory excludes the European Union, the United
Kingdom, the Republic of Korea, and the United States of America. The license
also contains commercial-use, acceptable-use, and redistribution conditions.
Review the official license before downloading or using the weights.

## Qwen3-VL-32B

- License: Apache-2.0
- Upstream: https://github.com/QwenLM/Qwen3-VL
- Usage: part of the MiniMax H3 text/vision encoder; not distributed by this
  project.

## FFmpeg / FFprobe

- License: depends on the build (LGPL and/or GPL)
- Usage: external system commands used by h3.c for media input and MP4 output
- This project does not bundle FFmpeg. Install it with Homebrew or your system
  package manager and comply with the license of the build you use.
