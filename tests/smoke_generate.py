#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real end-to-end smoke test for the native h3 CLI.

This intentionally bypasses ComfyUI so it can be used to verify the model,
Metal build, and command construction independently of the web UI.

Examples:
    python tests/smoke_generate.py
    python tests/smoke_generate.py --frames 22 --steps 20
    python tests/smoke_generate.py --mode ref2va --ref-image ref.png --ref-audio music.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import resolve_config  # noqa: E402
from h3_runner import H3Request, run_h3  # noqa: E402
from preflight import MODEL_LICENSE_NOTICE, PreflightError, ensure_ready  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fl2va", "ref2va"], default="fl2va")
    parser.add_argument(
        "--prompt",
        default=(
            "Scene: a single red fox walking through fresh snow in a pine forest at dawn. "
            "Action: the fox walks steadily left to right and glances toward the camera once. "
            "Camera: medium-height lateral tracking shot, 50 mm lens, stable framing. "
            "Look: photorealistic fur, cold blue ambient light, warm sunrise rim light. "
            "Audio: soft footsteps in snow and light wind through pine branches, no music."
        ),
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--h3-binary", default="")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--frames", type=int, default=22)
    parser.add_argument("--seconds", type=float, default=0.0)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--layers", type=int, default=45)
    parser.add_argument("--reuse", type=int, default=2)
    parser.add_argument("--core-reuse", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--first-frame", default="")
    parser.add_argument("--last-frame", default="")
    parser.add_argument("--ref-image", action="append", default=[])
    parser.add_argument("--ref-audio", default="")
    parser.add_argument("--ref-image-size", choices=["match", "max"], default="match")
    parser.add_argument("--render-width", type=int, default=0)
    parser.add_argument("--render-height", type=int, default=0)
    parser.add_argument("--token-reduction", action="store_true")
    parser.add_argument("--ssd-streaming", action="store_true")
    parser.add_argument("--int8-row-fc2", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    if args.output:
        output = Path(args.output).expanduser().resolve()
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output = PROJECT_ROOT / "tests" / "output" / f"smoke-{stamp}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    config = resolve_config()
    model_dir = Path(args.model_dir).expanduser().resolve() if args.model_dir else config.model_dir
    h3_binary = Path(args.h3_binary).expanduser().resolve() if args.h3_binary else config.h3_binary
    if model_dir is None or h3_binary is None:
        raise SystemExit(
            "Set H3_MODEL_DIR and H3_BIN (or run scripts/bootstrap_h3.sh) before this smoke test."
        )
    config = replace(config, model_dir=model_dir, h3_binary=h3_binary)
    try:
        ensure_ready(config, args.mode)
    except PreflightError as exc:
        raise SystemExit(str(exc)) from None

    print(MODEL_LICENSE_NOTICE)
    request = H3Request(
        mode=args.mode,
        prompt=args.prompt,
        output_path=str(output),
        model_dir=str(model_dir),
        h3_binary=str(h3_binary),
        width=args.width,
        height=args.height,
        frames=args.frames,
        seconds=args.seconds,
        steps=args.steps,
        layers=args.layers,
        reuse=args.reuse,
        core_reuse=args.core_reuse,
        seed=args.seed,
        first_frame=args.first_frame or None,
        last_frame=args.last_frame or None,
        ref_images=list(args.ref_image),
        ref_audio=args.ref_audio or None,
        ref_image_size=args.ref_image_size,
        render_width=args.render_width,
        render_height=args.render_height,
        token_reduction=args.token_reduction,
        ssd_streaming=args.ssd_streaming,
        int8_row_fc2=args.int8_row_fc2,
        profile=args.profile,
        timeout_seconds=args.timeout,
        ffmpeg=config.ffmpeg,
        ffprobe=config.ffprobe,
        serialize=config.serialize,
    )

    last_phase = ""

    def on_progress(percent: float, phase: str, done: int, total: int) -> None:
        nonlocal last_phase
        if phase != last_phase:
            print(f"\n[{percent:5.1f}%] {phase} {done}/{total}", end="", flush=True)
            last_phase = phase
        else:
            print(f"\r[{percent:5.1f}%] {phase} {done}/{total}", end="", flush=True)

    request.on_progress = on_progress
    print(f"Model: {request.model_dir}")
    print(f"Binary: {request.h3_binary}")
    print(f"Output: {output}")
    elapsed = run_h3(request)
    print(f"\nDone in {elapsed:.1f}s -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
