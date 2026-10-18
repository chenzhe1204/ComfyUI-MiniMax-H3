#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Submit a real MiniMax H3 prompt through the ComfyUI HTTP API.

Start ComfyUI with the node installed first, for example:

    python main.py --port 8199 --disable-all-custom-nodes \
      --whitelist-custom-nodes comfyui-minimax-h3
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8199")
    parser.add_argument("--mode", choices=["fl2va", "ref2va"], default="fl2va")
    parser.add_argument("--ref-image", default="")
    parser.add_argument("--ref-audio", default="")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--frames", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--prefix", default="h3_api_test/H3")
    args = parser.parse_args()

    common = {
        "prompt": (
            "Scene: a red fox walking through fresh snow in a pine forest at dawn. "
            "Camera: stable medium tracking shot. "
            "Audio: soft footsteps and wind."
        ),
        "width": args.width,
        "height": args.height,
        "frames": args.frames,
        "seconds": 0.0,
        "steps": args.steps,
        "layers": 50,
        "reuse": 1,
        "core_reuse": 1,
        "token_reduction": False,
        "ssd_streaming": False,
        "int8_row_fc2": False,
        "use_reference_rope": False,
        "render_width": 0,
        "render_height": 0,
        "seed": 42,
        "filename_prefix": args.prefix,
        "timeout_seconds": args.timeout,
        "profile": False,
    }
    workflow = {}
    if args.mode == "fl2va":
        workflow["1"] = {"class_type": "MiniMaxH3_FL2VA", "inputs": common}
    else:
        if not args.ref_image:
            parser.error("--ref-image is required for ref2va")
        workflow["10"] = {
            "class_type": "LoadImage",
            "inputs": {"image": args.ref_image},
        }
        common["ref_images"] = ["10", 0]
        common["ref_image_size"] = "match"
        if args.ref_audio:
            workflow["11"] = {
                "class_type": "LoadAudio",
                "inputs": {"audio": args.ref_audio},
            }
            common["ref_audio"] = ["11", 0]
        workflow["1"] = {"class_type": "MiniMaxH3_Ref2VA", "inputs": common}

    response = post_json(f"{args.url}/prompt", {"prompt": workflow, "client_id": "h3-smoke"})
    prompt_id = response["prompt_id"]
    print("queued:", prompt_id, flush=True)

    deadline = time.monotonic() + args.timeout + 60
    while time.monotonic() < deadline:
        history = get_json(f"{args.url}/history/{prompt_id}")
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            print("status:", json.dumps(status, ensure_ascii=False), flush=True)
            if status.get("completed") or status.get("status_str") in ("success", "error"):
                print(json.dumps(entry.get("outputs", {}), ensure_ascii=False, indent=2))
                if status.get("status_str") == "error":
                    return 1
                return 0
        time.sleep(2)
    print("timed out waiting for ComfyUI history")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
