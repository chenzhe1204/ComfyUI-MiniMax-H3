# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration discovery for the MiniMax H3 ComfyUI nodes.

Configuration file precedence, highest first:

1. ``H3_CONFIG``: explicit JSON file (no fallback).
2. ``<this package>/config.json``: portable/development override.  This file
   can be replaced by a node update, so it is meant for self-contained
   checkouts rather than normal installs.
3. ``<ComfyUI>/user/default/comfyui-minimax-h3.json``: the recommended location
   for normal ComfyUI installs.  It follows ``folder_paths.get_user_directory()``
   and therefore respects a custom ``--user-directory``.
4. ``~/.config/comfyui-minimax-h3/config.json``: only used when ComfyUI's
   ``folder_paths`` module is unavailable (for example when running
   ``scripts/doctor.py`` outside ComfyUI).

The first **existing** file wins; files are not merged.  Individual environment
variables (``H3_DIR``, ``H3_MODEL_DIR``, ``H3_BIN``, ``H3_FFMPEG``,
``H3_FFPROBE``, ``H3_SERIALIZE``, ``H3_KEEP_TEMP``) override values from the
selected file.  Development auto-detection of ``third_party/h3.c`` or a sibling
``../h3.c`` is the last resort.

The module deliberately avoids hard dependencies on ComfyUI so it can be
tested and used by ``scripts/doctor.py`` outside a ComfyUI process.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised when the configuration file is malformed."""


@dataclass(frozen=True)
class H3Config:
    """Resolved paths and process settings for the H3 backend."""

    config_path: Path
    h3_dir: Path | None
    model_dir: Path | None
    h3_binary: Path | None
    ffmpeg: str
    ffprobe: str
    serialize: bool
    keep_temp: bool
    sources: dict[str, str] = field(default_factory=dict, compare=False)
    config_candidates: tuple[Path, ...] = field(default_factory=tuple, compare=False)


def _comfyui_config_path() -> Path | None:
    try:
        import folder_paths  # type: ignore

        return Path(folder_paths.get_user_directory()) / "default" / "comfyui-minimax-h3.json"
    except Exception:
        return None


def package_config_path() -> Path:
    """Return the optional config file stored next to the node package."""

    return Path(__file__).resolve().parent / "config.json"


def home_config_path() -> Path:
    """Return the standalone-tool fallback config path."""

    return Path.home() / ".config" / "comfyui-minimax-h3" / "config.json"


def candidate_config_paths() -> list[Path]:
    """Return config candidates in priority order.

    The first existing file wins; callers must not merge them.
    """

    override = _env("H3_CONFIG")
    if override:
        return [Path(override).expanduser()]

    candidates = [package_config_path()]
    comfy_path = _comfyui_config_path()
    if comfy_path is not None:
        candidates.append(comfy_path)
    else:
        candidates.append(home_config_path())

    # Keep the order while dropping duplicates (for example if a symlinked
    # package happens to resolve to the ComfyUI user directory).
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def default_config_path() -> Path:
    """Return the selected config file (first existing candidate)."""

    candidates = candidate_config_paths()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise ConfigError(f"H3 config path is not a file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Cannot read H3 config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"H3 config must be a JSON object: {path}")
    return data


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name).lower()
    if not value:
        return default
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


def _path_value(value: Any, base: Path, label: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a non-empty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _command(value: str) -> str:
    """Resolve a command name to an absolute path when possible."""

    value = value.strip()
    if not value:
        return value
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or os.sep in value:
        return str(candidate)
    found = shutil.which(value)
    return found if found else value


def _auto_detect_pairs() -> list[Path]:
    package_dir = Path(__file__).resolve().parent
    candidates = [
        package_dir / "third_party" / "h3.c",
        package_dir.parent / "h3.c",
    ]
    return [candidate for candidate in candidates if candidate.is_dir()]


def resolve_config(config_path: Path | None = None) -> H3Config:
    """Resolve configuration from env vars, JSON, and development defaults."""

    if config_path is not None:
        candidates = [Path(config_path).expanduser()]
        path = candidates[0]
    else:
        candidates = candidate_config_paths()
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    file_data = _read_config(path)
    file_base = path.parent
    env_base = Path.cwd()

    for key in ("serialize", "keep_temp", "auto_detect"):
        if key in file_data and not isinstance(file_data[key], bool):
            raise ConfigError(f"{key} must be a boolean in {path}")
    for key in ("ffmpeg", "ffprobe"):
        if key in file_data and not isinstance(file_data[key], str):
            raise ConfigError(f"{key} must be a string in {path}")

    sources: dict[str, str] = {}

    h3_dir_value = _env("H3_DIR")
    if h3_dir_value:
        h3_dir = _path_value(h3_dir_value, env_base, "H3_DIR")
        sources["h3_dir"] = "env H3_DIR"
    elif file_data.get("h3_dir"):
        h3_dir = _path_value(file_data["h3_dir"], file_base, "h3_dir")
        sources["h3_dir"] = f"config {path}"
    else:
        h3_dir = None

    model_value = _env("H3_MODEL_DIR")
    if model_value:
        model_dir = _path_value(model_value, env_base, "H3_MODEL_DIR")
        sources["model_dir"] = "env H3_MODEL_DIR"
    elif file_data.get("model_dir"):
        model_dir = _path_value(file_data["model_dir"], file_base, "model_dir")
        sources["model_dir"] = f"config {path}"
    elif h3_dir is not None:
        model_dir = h3_dir / "model"
        sources["model_dir"] = "derived from h3_dir"
    else:
        model_dir = None

    binary_value = _env("H3_BIN")
    if binary_value:
        h3_binary = _path_value(binary_value, env_base, "H3_BIN")
        sources["h3_binary"] = "env H3_BIN"
    elif file_data.get("h3_binary"):
        h3_binary = _path_value(file_data["h3_binary"], file_base, "h3_binary")
        sources["h3_binary"] = f"config {path}"
    elif h3_dir is not None:
        h3_binary = h3_dir / "h3"
        sources["h3_binary"] = "derived from h3_dir"
    else:
        h3_binary = None

    auto_detect = True
    if "H3_AUTO_DETECT" in os.environ:
        auto_detect = _env_bool("H3_AUTO_DETECT", True)
    elif "auto_detect" in file_data:
        auto_detect = bool(file_data["auto_detect"])

    # Development auto-detection: a checked-out h3.c next to this package.
    if auto_detect and h3_dir is None and (model_dir is None or h3_binary is None):
        for candidate in _auto_detect_pairs():
            if h3_dir is None:
                h3_dir = candidate
                sources["h3_dir"] = "auto-detected"
            if model_dir is None:
                model_dir = candidate / "model"
                sources["model_dir"] = "auto-detected"
            if h3_binary is None:
                h3_binary = candidate / "h3"
                sources["h3_binary"] = "auto-detected"
            break

    # If only one of model/binary was configured, infer the other from it.
    if model_dir is None and h3_binary is not None:
        model_dir = h3_binary.parent / "model"
        sources["model_dir"] = "derived from h3_binary"
    if h3_binary is None and model_dir is not None:
        h3_binary = model_dir.parent / "h3"
        sources["h3_binary"] = "derived from model_dir"

    ffmpeg_value = _env("H3_FFMPEG") or str(file_data.get("ffmpeg") or "").strip()
    if ffmpeg_value:
        ffmpeg = _command(ffmpeg_value)
        sources["ffmpeg"] = "env or config"
    else:
        ffmpeg = _command("ffmpeg")
        sources["ffmpeg"] = "PATH" if shutil.which("ffmpeg") else "default (not found)"

    ffprobe_value = _env("H3_FFPROBE") or str(file_data.get("ffprobe") or "").strip()
    if ffprobe_value:
        ffprobe = _command(ffprobe_value)
        sources["ffprobe"] = "env or config"
    else:
        ffprobe = _command("ffprobe")
        sources["ffprobe"] = "PATH" if shutil.which("ffprobe") else "default (not found)"

    if "H3_SERIALIZE" in os.environ:
        serialize = _env_bool("H3_SERIALIZE", True)
        sources["serialize"] = "env H3_SERIALIZE"
    elif "serialize" in file_data:
        serialize = bool(file_data["serialize"])
        sources["serialize"] = f"config {path}"
    else:
        serialize = True

    if "H3_KEEP_TEMP" in os.environ:
        keep_temp = _env_bool("H3_KEEP_TEMP", False)
        sources["keep_temp"] = "env H3_KEEP_TEMP"
    elif "keep_temp" in file_data:
        keep_temp = bool(file_data["keep_temp"])
        sources["keep_temp"] = f"config {path}"
    else:
        keep_temp = False

    return H3Config(
        config_path=path,
        h3_dir=h3_dir,
        model_dir=model_dir,
        h3_binary=h3_binary,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        serialize=serialize,
        keep_temp=keep_temp,
        sources=sources,
        config_candidates=tuple(candidates),
    )


def describe_config(config: H3Config) -> list[str]:
    """Human-readable configuration lines for logs and the doctor script."""

    found = config.config_path.is_file()
    lines = [f"config file: {config.config_path}" + ("" if found else " (not found)")]
    candidates = config.config_candidates or (config.config_path,)
    if len(candidates) > 1:
        lines.append("config candidates (first existing wins):")
        for candidate in candidates:
            mark = "  <- selected" if candidate == config.config_path else ""
            lines.append(f"  - {candidate}{mark}")
    for key in ("h3_dir", "model_dir", "h3_binary", "ffmpeg", "ffprobe"):
        value = getattr(config, key)
        source = config.sources.get(key, "default")
        lines.append(f"{key}: {value if value is not None else '<not found>'} ({source})")
    lines.append(f"serialize: {config.serialize} ({config.sources.get('serialize', 'default')})")
    lines.append(f"keep_temp: {config.keep_temp} ({config.sources.get('keep_temp', 'default')})")
    return lines
