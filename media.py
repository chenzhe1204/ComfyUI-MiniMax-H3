# SPDX-License-Identifier: GPL-3.0-or-later
"""Convert ComfyUI IMAGE/AUDIO values into files the H3 CLI can read."""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image as PILImage


class MediaError(ValueError):
    """Raised when an IMAGE or AUDIO input cannot be converted."""


def _as_image_batch(images: torch.Tensor) -> torch.Tensor:
    if not torch.is_tensor(images):
        raise MediaError("IMAGE input is not a torch.Tensor.")
    if images.ndim == 3:
        images = images.unsqueeze(0)
    if images.ndim != 4:
        raise MediaError(f"IMAGE input must have shape [B,H,W,C], got {tuple(images.shape)}.")
    if images.shape[0] < 1:
        raise MediaError("IMAGE input is an empty batch.")
    return images


def image_to_pil(image: torch.Tensor) -> PILImage.Image:
    """Convert one ComfyUI image tensor in [0,1] to an RGB PIL image."""

    if image.ndim == 4:
        if image.shape[0] != 1:
            raise MediaError("A single-image conversion requires batch size 1.")
        image = image[0]
    if image.ndim == 2:
        array = image.detach().to("cpu", torch.float32).numpy()
        array = np.repeat(array[..., None], 3, axis=-1)
    elif image.ndim == 3:
        array = image.detach().to("cpu", torch.float32).numpy()
        if array.shape[-1] == 1:
            array = np.repeat(array, 3, axis=-1)
        elif array.shape[-1] == 4:
            # Composite transparent pixels over black, matching typical video
            # conditioning assumptions.
            alpha = np.clip(array[..., 3:4], 0.0, 1.0)
            array = np.clip(array[..., :3], 0.0, 1.0) * alpha
        elif array.shape[-1] != 3:
            raise MediaError(f"IMAGE must have 1, 3, or 4 channels, got {array.shape[-1]}.")
    else:
        raise MediaError(f"Invalid IMAGE shape: {tuple(image.shape)}.")

    array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
    # ComfyUI's convention is 0..1.  Be tolerant of nodes that emit 0..255.
    if array.size and float(array.max()) > 1.5:
        array = array / 255.0
    array = np.rint(np.clip(array * 255.0, 0.0, 255.0)).astype(np.uint8)
    return PILImage.fromarray(array, mode="RGB")


def save_image(image: torch.Tensor, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image_to_pil(image).save(path, format="PNG", compress_level=1)
    return path


def save_image_batch(
    images: torch.Tensor,
    directory: Path,
    prefix: str,
    *,
    limit: int | None = None,
) -> list[Path]:
    """Save every image in a ComfyUI batch, preserving batch order."""

    batch = _as_image_batch(images)
    count = int(batch.shape[0])
    if limit is not None and count > limit:
        raise MediaError(f"At most {limit} images are supported, got {count}.")
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(count):
        path = directory / f"{prefix}_{index + 1:03d}.png"
        save_image(batch[index], path)
        paths.append(path)
    return paths


def _audio_waveform(audio: Any) -> tuple[torch.Tensor, int]:
    if not isinstance(audio, dict):
        raise MediaError("AUDIO input must be a dict with waveform and sample_rate.")
    waveform = audio.get("waveform")
    sample_rate = audio.get("sample_rate")
    if sample_rate is None:
        # Older ComfyUI builds used a typo in the TypedDict; accept both.
        sample_rate = audio.get("sampler_rate")
    if waveform is None:
        raise MediaError("AUDIO input is missing waveform.")
    try:
        sample_rate = int(sample_rate)
    except (TypeError, ValueError) as exc:
        raise MediaError("AUDIO input is missing a valid sample_rate.") from exc
    if sample_rate <= 0:
        raise MediaError(f"Invalid AUDIO sample_rate: {sample_rate}")

    if not torch.is_tensor(waveform):
        waveform = torch.as_tensor(waveform)
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    elif waveform.ndim == 3:
        if waveform.shape[0] < 1:
            raise MediaError("AUDIO batch is empty.")
        waveform = waveform[0]
    elif waveform.ndim != 2:
        raise MediaError(
            f"AUDIO waveform must have shape [C,T] or [B,C,T], got {tuple(waveform.shape)}."
        )

    if waveform.shape[1] == 0:
        raise MediaError("AUDIO waveform has zero length.")
    if waveform.shape[0] > 2:
        waveform = waveform[:2]
    return waveform, sample_rate


def audio_duration(audio: Any) -> float:
    waveform, sample_rate = _audio_waveform(audio)
    return float(waveform.shape[1]) / float(sample_rate)


def save_audio(
    audio: Any,
    path: Path,
    *,
    min_seconds: float = 2.0,
    max_seconds: float = 15.0,
) -> tuple[Path, float]:
    """Write AUDIO to a 16-bit PCM WAV and validate H3's duration window."""

    waveform, sample_rate = _audio_waveform(audio)
    duration = float(waveform.shape[1]) / float(sample_rate)
    if not math.isfinite(duration):
        raise MediaError("Invalid AUDIO duration.")
    if duration < min_seconds or duration > max_seconds:
        raise MediaError(
            f"Reference audio must be {min_seconds:g}-{max_seconds:g} seconds;"
            f"got {duration:.3f} seconds. Trim it with a node such as TrimAudioDuration."
        )

    samples = waveform.detach().to("cpu", torch.float32)
    samples = torch.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
    samples = samples.clamp(-1.0, 1.0)
    pcm = (samples * 32767.0).round().to(torch.int16).transpose(0, 1).contiguous()
    channels = int(pcm.shape[1])

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.numpy().tobytes())
    return path, duration
