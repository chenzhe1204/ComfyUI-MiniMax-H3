# SPDX-License-Identifier: GPL-3.0-or-later
"""Package version and compatibility constants."""

from __future__ import annotations

__version__ = "0.1.0"

# The V3 node API and the VIDEO type used by this package.  Tested with
# ComfyUI 0.41.2; keep this as the minimum supported version for now.
MIN_COMFYUI_VERSION = "0.41.2"

# Flags the node relies on.  ``scripts/doctor.py`` checks these against the
# installed h3 --help output so a changed upstream CLI fails early.
REQUIRED_H3_FLAGS: tuple[str, ...] = (
    "--core-reuse",
    "--frames",
    "--seconds",
    "--ref-image",
    "--ref-image-size",
    "--ref-audio",
    "--ssd-streaming",
    "--use-int8-row-fc2",
    "--use-reference-rope",
)
