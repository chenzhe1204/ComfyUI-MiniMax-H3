#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print resolved H3 configuration and run local preflight checks.

Run from the repository root or anywhere else:

    python scripts/doctor.py --mode ref2va
    COMFYUI_DIR=/path/to/ComfyUI python scripts/doctor.py

The doctor never downloads weights and never starts a generation.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "").strip()
if COMFYUI_DIR and COMFYUI_DIR not in sys.path:
    sys.path.insert(0, COMFYUI_DIR)

from config import resolve_config  # noqa: E402
from preflight import doctor_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fl2va", "ref2va"], default="fl2va")
    args = parser.parse_args()

    config = resolve_config()
    lines, errors, warnings = doctor_report(config, args.mode)

    print("\n".join(lines))
    print()
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  ! {warning}")
        print()
    if errors:
        print("Errors:")
        for error in errors:
            print(f"  x {error}")
        return 1
    print("OK: this environment looks ready for the selected mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
