# SPDX-License-Identifier: GPL-3.0-or-later
"""Environment checks shared by the nodes and ``scripts/doctor.py``."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

try:  # Package import (ComfyUI custom node)
    from .config import H3Config, describe_config
    from .version import MIN_COMFYUI_VERSION, REQUIRED_H3_FLAGS
except ImportError:  # pragma: no cover - scripts/doctor.py runs outside the package
    from config import H3Config, describe_config  # type: ignore
    from version import MIN_COMFYUI_VERSION, REQUIRED_H3_FLAGS  # type: ignore

logger = logging.getLogger(__name__)

MODEL_LICENSE_NOTICE = (
    "MiniMax H3 model weights are NOT included in this project. Their use is "
    "governed by the MiniMax H3 Community License Agreement, which excludes the "
    "European Union, the United Kingdom, the Republic of Korea, and the United "
    "States of America. Review the license before downloading the weights."
)


class PreflightError(RuntimeError):
    """Raised when the local environment cannot run the H3 backend."""

    def __init__(self, issues: Iterable[str]):
        self.issues = list(issues)
        message = "MiniMax H3 is not ready:\n" + "\n".join(f"  - {item}" for item in self.issues)
        super().__init__(message)


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.replace("-", ".").split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def _executable(value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or os.sep in value:
        return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None
    found = shutil.which(value)
    return Path(found) if found else None


def _component(directory: Path, label: str) -> list[str]:
    if not directory.is_dir():
        return [f"Missing model component {label}: {directory}"]
    try:
        next(directory.iterdir())
    except StopIteration:
        return [f"Model component {label} is empty: {directory}"]
    return []


def check_platform() -> list[str]:
    issues: list[str] = []
    if sys.platform != "darwin":
        issues.append("MiniMax H3 requires macOS on Apple Silicon (Metal).")
    if platform.machine().lower() not in ("arm64", "aarch64"):
        issues.append(
            f"MiniMax H3 requires an Apple Silicon (arm64) machine, found {platform.machine()}."
        )
    return issues


def check_comfyui_version() -> list[str]:
    try:
        from comfyui_version import __version__ as comfyui_version  # type: ignore
    except Exception:
        return []
    if _version_tuple(comfyui_version) < _version_tuple(MIN_COMFYUI_VERSION):
        return [
            f"ComfyUI {comfyui_version} is too old; this node requires >= {MIN_COMFYUI_VERSION} "
            "(the V3 node API and VIDEO type)."
        ]
    return []


def check_ffmpeg(config: H3Config) -> list[str]:
    issues: list[str] = []
    if _executable(config.ffmpeg) is None:
        issues.append(
            f"ffmpeg not found ({config.ffmpeg}). Install it with 'brew install ffmpeg' "
            "or set H3_FFMPEG to an absolute path."
        )
    if _executable(config.ffprobe) is None:
        issues.append(
            f"ffprobe not found ({config.ffprobe}). Install it with 'brew install ffmpeg' "
            "or set H3_FFPROBE to an absolute path."
        )
    return issues


def check_h3_install(config: H3Config, mode: str) -> list[str]:
    issues: list[str] = []
    if config.h3_binary is None:
        issues.append(
            "h3 binary is not configured. Set H3_DIR, H3_BIN, or run 'scripts/bootstrap_h3.sh'."
        )
        return issues
    binary = config.h3_binary
    if not binary.is_file():
        issues.append(f"h3 binary not found: {binary}")
        return issues
    if not os.access(binary, os.X_OK):
        issues.append(f"h3 binary is not executable: {binary}")
    shader = binary.resolve().parent / "h3_shaders.metal"
    if not shader.is_file():
        issues.append(
            f"h3_shaders.metal is missing next to the binary: {shader}. "
            "Run h3 from its build directory; do not copy the binary alone."
        )

    if config.model_dir is None:
        issues.append(
            "H3 model directory is not configured. Set H3_MODEL_DIR or put the "
            "weights under '<h3.c>/model'."
        )
        return issues
    model = config.model_dir
    if not model.is_dir():
        issues.append(f"H3 model directory not found: {model}")
        return issues
    issues.extend(_component(model / "FL2VA" / "transformer", "FL2VA/transformer"))
    if mode == "ref2va":
        issues.extend(_component(model / "Ref2VA" / "transformer", "Ref2VA/transformer"))
    return issues


def check_h3_cli_contract(config: H3Config) -> list[str]:
    """Verify that the installed h3 exposes the CLI flags this package uses."""

    if config.h3_binary is None or not config.h3_binary.is_file():
        return ["Cannot check the h3 CLI contract: the binary is missing."]
    try:
        completed = subprocess.run(
            [str(config.h3_binary), "--help"],
            cwd=str(config.h3_binary.resolve().parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"Cannot run 'h3 --help': {exc}"]
    output = completed.stdout or ""
    missing = [flag for flag in REQUIRED_H3_FLAGS if flag not in output]
    if missing:
        return [
            "Installed h3 is missing required CLI flags: "
            + ", ".join(missing)
            + ". Update h3.c to the pinned commit documented in README.md."
        ]
    return []


def resource_warnings(config: H3Config) -> list[str]:
    warnings: list[str] = []
    if config.model_dir is not None and config.model_dir.is_dir():
        try:
            free = shutil.disk_usage(config.model_dir).free
            if free < 100 * 1024**3:
                warnings.append(
                    f"Only {free / 1024**3:.1f} GiB free next to the model; "
                    "H3 model/output usage can exceed 100 GiB."
                )
        except OSError:
            pass
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            memory = int(completed.stdout.strip())
            if memory < 96 * 1024**3:
                warnings.append(
                    f"Detected {memory / 1024**3:.1f} GiB unified memory. "
                    "128 GiB is the validated configuration; lower-memory machines "
                    "may need --ssd-streaming and are not validated."
                )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return warnings


def ensure_ready(config: H3Config, mode: str) -> None:
    """Raise :class:`PreflightError` unless the backend can be started."""

    issues = []
    issues.extend(check_platform())
    issues.extend(check_comfyui_version())
    issues.extend(check_ffmpeg(config))
    issues.extend(check_h3_install(config, mode))
    for warning in resource_warnings(config):
        logger.warning(warning)
    if issues:
        raise PreflightError(issues)


def doctor_report(config: H3Config, mode: str) -> tuple[list[str], list[str], list[str]]:
    """Return ``(lines, errors, warnings)`` for the doctor script."""

    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(check_platform())
    errors.extend(check_comfyui_version())
    errors.extend(check_ffmpeg(config))
    errors.extend(check_h3_install(config, mode))
    errors.extend(check_h3_cli_contract(config))
    warnings.extend(resource_warnings(config))

    lines = ["Resolved configuration:"]
    lines.extend(f"  {line}" for line in describe_config(config))
    lines.append("")
    lines.append("Node version: " + _node_version())
    lines.append("")
    lines.append(MODEL_LICENSE_NOTICE)
    return lines, errors, warnings


def _node_version() -> str:
    try:
        try:
            from .version import __version__
        except ImportError:
            from version import __version__  # type: ignore

        return __version__
    except Exception:
        return "unknown"
