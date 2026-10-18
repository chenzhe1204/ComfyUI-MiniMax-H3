# SPDX-License-Identifier: GPL-3.0-or-later
"""ComfyUI custom node package for MiniMax H3 on Apple Silicon.

The node classes live in :mod:`nodes`, the native CLI wrapper in
:mod:`h3_runner`, configuration in :mod:`config`, and environment checks in
:mod:`preflight`.
"""

from __future__ import annotations

import logging

from .nodes import MiniMaxH3Extension
from .preflight import MODEL_LICENSE_NOTICE
from .version import __version__

logger = logging.getLogger(__name__)
logger.info("ComfyUI MiniMax H3 %s loaded", __version__)
logger.warning(MODEL_LICENSE_NOTICE)

__all__ = ["MiniMaxH3Extension", "comfy_entrypoint", "__version__"]


async def comfy_entrypoint() -> MiniMaxH3Extension:
    return MiniMaxH3Extension()
