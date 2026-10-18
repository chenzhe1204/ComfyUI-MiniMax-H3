# SPDX-License-Identifier: GPL-3.0-or-later
"""ComfyUI nodes for the native Apple-Silicon MiniMax-H3 CLI."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import folder_paths
from comfy.utils import ProgressBar
from comfy_api.latest import ComfyExtension, InputImpl, io, ui

from .config import resolve_config
from .h3_runner import (
    H3_MAX_AUDIO_SECONDS,
    H3_MIN_AUDIO_SECONDS,
    H3Interrupted,
    H3Request,
    run_h3,
)
from .media import MediaError, save_audio, save_image_batch
from .preflight import ensure_ready
from .version import __version__

try:  # Present in a normal ComfyUI process; absent in standalone unit tests.
    from comfy.model_management import InterruptProcessingException, processing_interrupted
except Exception:  # pragma: no cover - only used outside ComfyUI

    class InterruptProcessingException(RuntimeError):
        pass

    def processing_interrupted() -> bool:
        return False


try:
    from comfy_execution.utils import get_executing_context
except Exception:  # pragma: no cover - only used outside ComfyUI

    def get_executing_context():
        return None


try:
    from server import PromptServer
except Exception:  # pragma: no cover - only used outside ComfyUI
    PromptServer = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = (
    "Scene: a single red fox walking through fresh snow in a pine forest at dawn. "
    "Action: the fox walks steadily left to right and glances toward the camera once. "
    "Camera: medium-height lateral tracking shot, 50 mm lens, stable framing. "
    "Look: photorealistic fur, cold blue ambient light, warm sunrise rim light. "
    "Audio: soft footsteps in snow and light wind through pine branches, no music."
)

_REQUIRED_REF_IMAGES_TOOLTIP = (
    "Ordered reference images: batch item 1 becomes <Picture 1>, item 2 becomes "
    "<Picture 2>, and so on (maximum 9). Ref2VA cannot be combined with first/last "
    "frames; use the FL2VA node for text-to-video."
)


class _StatusSender:
    """Throttled textual progress for the ComfyUI node status line."""

    def __init__(self) -> None:
        self._last_sent = 0.0
        self._last_text = ""

    def send(self, text: str, *, force: bool = False) -> None:
        if text == self._last_text and not force:
            return
        now = time.monotonic()
        if not force and now - self._last_sent < 0.25:
            return
        self._last_text = text
        self._last_sent = now
        if PromptServer is None or getattr(PromptServer, "instance", None) is None:
            return
        context = get_executing_context()
        if context is None:
            return
        try:
            PromptServer.instance.send_progress_text(text, context.node_id)
        except Exception:
            # Status text is cosmetic; never fail a generation over it.
            logger.debug("Could not send H3 progress text", exc_info=True)


def _unique_output_path(
    filename_prefix: str,
    width: int,
    height: int,
) -> tuple[Path, str, str]:
    prefix = (filename_prefix or "").strip()
    if not prefix:
        raise ValueError("filename_prefix must not be empty.")
    if prefix.lower().endswith(".mp4"):
        prefix = prefix[:-4]
    output_root = folder_paths.get_output_directory()
    full_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
        prefix, output_root, width, height
    )
    folder = Path(full_folder)
    folder.mkdir(parents=True, exist_ok=True)
    while True:
        file_name = f"{filename}_{counter:05}_.mp4"
        candidate = folder / file_name
        if not candidate.exists():
            return candidate, file_name, subfolder
        counter += 1


def _execute_generation(
    *,
    mode: str,
    prompt: str,
    width: int,
    height: int,
    frames: int,
    seconds: float,
    steps: int,
    layers: int,
    reuse: int,
    core_reuse: int,
    token_reduction: bool,
    ssd_streaming: bool,
    int8_row_fc2: bool,
    use_reference_rope: bool,
    render_width: int,
    render_height: int,
    seed: int,
    filename_prefix: str,
    timeout_seconds: int,
    profile: bool,
    first_frame: Any | None = None,
    last_frame: Any | None = None,
    ref_images: Any | None = None,
    ref_audio: Any | None = None,
    ref_image_size: str = "match",
):
    config = resolve_config()
    ensure_ready(config, mode)
    assert config.model_dir is not None and config.h3_binary is not None

    output_path, file_name, subfolder = _unique_output_path(filename_prefix, width, height)

    temp_dir = Path(tempfile.mkdtemp(prefix="comfy_h3_"))
    keep_temp = config.keep_temp

    try:
        source_first: str | None = None
        source_last: str | None = None
        source_refs: list[str] = []
        source_audio: str | None = None

        if mode == "fl2va":
            if first_frame is not None:
                source_first = str(
                    save_image_batch(first_frame, temp_dir, "first_frame", limit=1)[0]
                )
            if last_frame is not None:
                source_last = str(save_image_batch(last_frame, temp_dir, "last_frame", limit=1)[0])
        else:
            if ref_images is None:
                raise MediaError("Ref2VA requires an IMAGE reference input.")
            source_refs = [
                str(path) for path in save_image_batch(ref_images, temp_dir, "ref", limit=9)
            ]
            if ref_audio is not None:
                source_audio = str(
                    save_audio(
                        ref_audio,
                        temp_dir / "ref_audio.wav",
                        min_seconds=H3_MIN_AUDIO_SECONDS,
                        max_seconds=H3_MAX_AUDIO_SECONDS,
                    )[0]
                )

        request = H3Request(
            mode=mode,
            prompt=prompt,
            output_path=str(output_path),
            model_dir=str(config.model_dir),
            h3_binary=str(config.h3_binary),
            width=int(width),
            height=int(height),
            frames=int(frames),
            seconds=float(seconds),
            steps=int(steps),
            layers=int(layers),
            reuse=int(reuse),
            core_reuse=int(core_reuse),
            token_reduction=bool(token_reduction),
            ssd_streaming=bool(ssd_streaming),
            int8_row_fc2=bool(int8_row_fc2),
            use_reference_rope=bool(use_reference_rope),
            render_width=int(render_width),
            render_height=int(render_height),
            seed=int(seed),
            first_frame=source_first,
            last_frame=source_last,
            ref_images=source_refs,
            ref_audio=source_audio,
            ref_image_size=ref_image_size,
            profile=bool(profile),
            timeout_seconds=int(timeout_seconds),
            ffmpeg=config.ffmpeg,
            ffprobe=config.ffprobe,
            serialize=config.serialize,
            interrupt_check=processing_interrupted,
        )

        progress_bar = ProgressBar(100)
        status = _StatusSender()

        def on_progress(percentage: float, phase: str, completed: int, total: int) -> None:
            progress_bar.update_absolute(max(0, min(100, int(round(percentage)))))
            if phase == "done":
                status.send("H3: done", force=True)
            else:
                status.send(f"H3: {phase} {completed}/{total}", force=completed >= total)

        request.on_progress = on_progress
        logger.info(
            "MiniMax H3 %s (%s): %sx%s, %d aligned frames, steps=%d layers=%d reuse=%d",
            __version__,
            mode,
            width,
            height,
            request.aligned_frames,
            steps,
            layers,
            reuse,
        )
        run_h3(request)
    except H3Interrupted as exc:
        raise InterruptProcessingException(str(exc)) from exc
    finally:
        if keep_temp:
            logger.info("H3 temp files kept at %s", temp_dir)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)

    video = InputImpl.VideoFromFile(str(output_path))
    preview = ui.PreviewVideo([ui.SavedResult(file_name, subfolder, io.FolderType.output)])
    return io.NodeOutput(video, str(output_path), ui=preview)


def _prompt_input() -> io.String.Input:
    return io.String.Input(
        "prompt",
        display_name="prompt",
        multiline=True,
        default=_DEFAULT_PROMPT,
        tooltip=(
            "H3 works best with a Context-IR style prompt: scene, action, camera, "
            "look/lighting, and sound. The generated MP4 includes a 32 kHz stereo AAC track."
        ),
    )


def _shared_inputs() -> list:
    return [
        io.Int.Input(
            "width",
            display_name="width",
            default=512,
            min=32,
            max=1344,
            step=32,
            tooltip="Output width; must be a multiple of 32 and width*height <= 768*1344.",
        ),
        io.Int.Input(
            "height",
            display_name="height",
            default=512,
            min=32,
            max=1344,
            step=32,
            tooltip="Output height; must be a multiple of 32 and width*height <= 768*1344.",
        ),
        io.Int.Input(
            "frames",
            display_name="frames",
            default=56,
            min=5,
            max=362,
            step=1,
            tooltip=(
                "Requested frames; H3 rounds up to 5+17n. 22~0.92s, 56~2.33s, "
                "107~4.46s, 243~10.1s, 362~15.08s."
            ),
        ),
        io.Float.Input(
            "seconds",
            display_name="seconds (overrides frames)",
            default=0.0,
            min=0.0,
            max=15.0,
            step=0.0416667,
            tooltip=(
                "If greater than 0, use a duration at 24 fps instead of frames. "
                "H3 rounds up to a legal temporal shape."
            ),
        ),
        io.Int.Input(
            "steps",
            display_name="steps",
            default=20,
            min=2,
            max=1000,
            step=1,
            tooltip="Denoising passes. 20 is the default; 4-7 for drafts; 50 for reference quality.",
        ),
        io.Int.Input(
            "layers",
            display_name="layers",
            default=45,
            min=35,
            max=50,
            step=1,
            tooltip="Active DiT blocks: 50 exact, 45 fast, 40 aggressive.",
        ),
        io.Int.Input(
            "reuse",
            display_name="reuse",
            default=2,
            min=1,
            max=3,
            step=1,
            tooltip=(
                "Whole-velocity reuse: 1 exact, 2 fast, 3 aggressive. "
                "Cannot be combined with core_reuse > 1."
            ),
        ),
        io.Int.Input(
            "core_reuse",
            display_name="core_reuse",
            default=1,
            min=1,
            max=6,
            step=1,
            tooltip=(
                "Core residual reuse: 1 exact, 4 fast, 6 aggressive. "
                "Cannot be combined with reuse > 1."
            ),
        ),
        io.Boolean.Input(
            "token_reduction",
            display_name="token_reduction",
            default=False,
            tooltip="Pair video tokens in middle DiT blocks; faster but may change composition.",
        ),
        io.Boolean.Input(
            "ssd_streaming",
            display_name="ssd_streaming",
            default=False,
            tooltip=(
                "Stream original BF16 DiT layers from SSD. Much lower memory, slower; "
                "cannot be combined with int8_row_fc2."
            ),
        ),
        io.Boolean.Input(
            "int8_row_fc2",
            display_name="int8_row_fc2",
            default=False,
            tooltip="M5-only faster one-scale int8 FC2; less numerically conservative.",
        ),
        io.Boolean.Input(
            "use_reference_rope",
            display_name="use_reference_rope",
            default=False,
            tooltip="Restore the released spatial RoPE (disable the 256px adaptation).",
        ),
        io.Int.Input(
            "render_width",
            display_name="render_width (0 = native)",
            default=0,
            min=0,
            max=1344,
            step=32,
            tooltip=(
                "Internal model/VAE render width; 0 uses the output size. Set together "
                "with render_height and preserve the output aspect ratio."
            ),
        ),
        io.Int.Input(
            "render_height",
            display_name="render_height (0 = native)",
            default=0,
            min=0,
            max=1344,
            step=32,
            tooltip=(
                "Internal model/VAE render height; 0 uses the output size. Set together "
                "with render_width and preserve the output aspect ratio."
            ),
        ),
        io.Int.Input(
            "seed",
            display_name="seed",
            default=42,
            min=0,
            max=0xFFFFFFFFFFFFFFFF,
            step=1,
            control_after_generate=True,
            tooltip="Native H3 random seed. Use a fixed value to reproduce a result.",
        ),
        io.String.Input(
            "filename_prefix",
            display_name="filename_prefix",
            default="minimax_h3/H3",
            tooltip=(
                "Prefix under ComfyUI/output. May include subdirectories and "
                "format variables such as %date%."
            ),
        ),
        io.Int.Input(
            "timeout_seconds",
            display_name="timeout_seconds",
            default=3600,
            min=0,
            max=86400,
            step=1,
            advanced=True,
            tooltip="Child process timeout in seconds; 0 disables the timeout.",
        ),
        io.Boolean.Input(
            "profile",
            display_name="profile",
            default=False,
            advanced=True,
            tooltip="Ask h3 to print per-phase Metal timing and memory data to the console.",
        ),
    ]


class MiniMaxH3FL2VA(io.ComfyNode):
    """Text-to-video and first/last-frame conditioning (FL2VA)."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3_FL2VA",
            display_name="MiniMax H3 FL2VA (First/Last Frame)",
            category="MiniMax H3",
            description=(
                "Unofficial ComfyUI node for MiniMax H3 on Apple Silicon. Generates an "
                "MP4 with audio using the native Metal h3 CLI. Supports text-to-video "
                "and optional first/last-frame conditioning. Each run starts a fresh "
                "h3 process, so expect a model cold-start cost."
            ),
            search_aliases=["minimax", "h3", "fl2va", "t2v", "i2v", "video"],
            is_output_node=True,
            inputs=[
                _prompt_input(),
                io.Image.Input(
                    "first_frame",
                    display_name="first_frame",
                    optional=True,
                    tooltip=(
                        "First-frame conditioning image (FL2VA). It is stretched to the "
                        "target canvas. Cannot be combined with Ref2VA references."
                    ),
                ),
                io.Image.Input(
                    "last_frame",
                    display_name="last_frame",
                    optional=True,
                    tooltip=(
                        "Last-frame conditioning image (FL2VA). It is aspect-cover scaled "
                        "and center-cropped to the target canvas."
                    ),
                ),
                *_shared_inputs(),
            ],
            outputs=[
                io.Video.Output(display_name="video", tooltip="Generated MP4 with audio."),
                io.String.Output(
                    display_name="saved_path",
                    tooltip="Absolute path under ComfyUI/output.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        width,
        height,
        frames,
        seconds,
        steps,
        layers,
        reuse,
        core_reuse,
        token_reduction,
        ssd_streaming,
        int8_row_fc2,
        use_reference_rope,
        render_width,
        render_height,
        seed,
        filename_prefix,
        timeout_seconds,
        profile,
        first_frame=None,
        last_frame=None,
    ):
        return _execute_generation(
            mode="fl2va",
            prompt=prompt,
            width=width,
            height=height,
            frames=frames,
            seconds=seconds,
            steps=steps,
            layers=layers,
            reuse=reuse,
            core_reuse=core_reuse,
            token_reduction=token_reduction,
            ssd_streaming=ssd_streaming,
            int8_row_fc2=int8_row_fc2,
            use_reference_rope=use_reference_rope,
            render_width=render_width,
            render_height=render_height,
            seed=seed,
            filename_prefix=filename_prefix,
            timeout_seconds=timeout_seconds,
            profile=profile,
            first_frame=first_frame,
            last_frame=last_frame,
        )


class MiniMaxH3Ref2VA(io.ComfyNode):
    """Ordered image/audio reference conditioning (Ref2VA)."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3_Ref2VA",
            display_name="MiniMax H3 Ref2VA (Reference Image/Audio)",
            category="MiniMax H3",
            description=(
                "Unofficial ComfyUI node for MiniMax H3 on Apple Silicon. Uses the "
                "Ref2VA checkpoint with ordered reference images (and optional 2-15s "
                "reference audio). Each run starts a fresh h3 process, so expect a "
                "model cold-start cost."
            ),
            search_aliases=["minimax", "h3", "ref2va", "reference", "video"],
            is_output_node=True,
            inputs=[
                _prompt_input(),
                io.Image.Input(
                    "ref_images",
                    display_name="ref_images",
                    tooltip=_REQUIRED_REF_IMAGES_TOOLTIP,
                ),
                io.Audio.Input(
                    "ref_audio",
                    display_name="ref_audio",
                    optional=True,
                    tooltip=(
                        "Reference audio, 2-15 seconds. Must be used with reference "
                        "images; standalone audio is not supported by H3."
                    ),
                ),
                io.Combo.Input(
                    "ref_image_size",
                    display_name="ref_image_size",
                    options=["match", "max"],
                    default="match",
                    tooltip=(
                        "Reference image sizing: 'match' preserves aspect ratio against "
                        "the canvas; 'max' uses the largest reference canvas."
                    ),
                ),
                *_shared_inputs(),
            ],
            outputs=[
                io.Video.Output(display_name="video", tooltip="Generated MP4 with audio."),
                io.String.Output(
                    display_name="saved_path",
                    tooltip="Absolute path under ComfyUI/output.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        ref_images,
        width,
        height,
        frames,
        seconds,
        steps,
        layers,
        reuse,
        core_reuse,
        token_reduction,
        ssd_streaming,
        int8_row_fc2,
        use_reference_rope,
        render_width,
        render_height,
        seed,
        filename_prefix,
        timeout_seconds,
        profile,
        ref_audio=None,
        ref_image_size="match",
    ):
        return _execute_generation(
            mode="ref2va",
            prompt=prompt,
            width=width,
            height=height,
            frames=frames,
            seconds=seconds,
            steps=steps,
            layers=layers,
            reuse=reuse,
            core_reuse=core_reuse,
            token_reduction=token_reduction,
            ssd_streaming=ssd_streaming,
            int8_row_fc2=int8_row_fc2,
            use_reference_rope=use_reference_rope,
            render_width=render_width,
            render_height=render_height,
            seed=seed,
            filename_prefix=filename_prefix,
            timeout_seconds=timeout_seconds,
            profile=profile,
            ref_images=ref_images,
            ref_audio=ref_audio,
            ref_image_size=ref_image_size,
        )


class MiniMaxH3Extension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [MiniMaxH3FL2VA, MiniMaxH3Ref2VA]


async def comfy_entrypoint() -> MiniMaxH3Extension:
    return MiniMaxH3Extension()
