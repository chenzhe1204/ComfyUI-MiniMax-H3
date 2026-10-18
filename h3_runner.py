# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the native MiniMax-H3 ``h3`` CLI as a child process.

This module deliberately has no ComfyUI imports so it can be tested (and
reused) outside of a ComfyUI process.  It is responsible for:

* validating the H3 generation parameters,
* translating them into an ``h3`` command line,
* streaming the CLI's progress lines back to a callback,
* cancelling/timing out the child process cleanly.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import logging
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

H3_FPS = 24
H3_CANVAS_MULTIPLE = 32
H3_MAX_PIXELS = 768 * 1344
H3_MIN_FRAMES = 5
H3_MAX_FRAMES = 362
H3_MAX_TEXT_SECONDS = H3_MAX_FRAMES / H3_FPS
H3_MAX_STEPS = 1000
H3_MIN_LAYERS = 35
H3_MAX_LAYERS = 50
H3_MAX_IMAGE_REFERENCES = 9
H3_MIN_AUDIO_SECONDS = 2.0
H3_MAX_AUDIO_SECONDS = 15.0

# Approximate overall progress ranges for the phases printed by h3.  The
# denoising phase dominates wall-clock time, hence its wide range.
_PHASE_RANGES: tuple[tuple[str, float, float], ...] = (
    ("tokenizer", 0.0, 1.0),
    ("text encoder", 1.0, 18.0),
    ("qwen vision", 18.0, 30.0),
    ("audio vae encoder", 30.0, 34.0),
    ("video vae encoder", 34.0, 42.0),
    ("load transformer core", 42.0, 50.0),
    ("refine text", 50.0, 54.0),
    ("denoise enqueue", 54.0, 90.0),
    ("audio vae", 90.0, 93.0),
    ("video vae load", 93.0, 95.0),
    ("video vae decode", 95.0, 99.0),
    ("ffmpeg", 99.0, 100.0),
)

_PROGRESS_RE = re.compile(r"^(?P<phase>.+?)\s+(?P<done>\d+)/(?P<total>\d+)\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

ProgressCallback = Callable[[float, str, int, int], None]
InterruptCheck = Callable[[], bool]


class H3Error(RuntimeError):
    """Raised when h3 cannot be started or exits unsuccessfully."""


class H3Interrupted(H3Error):
    """Raised when the owning application asks to cancel generation."""


def align_frame_count(frames: int) -> int:
    """Round a frame request up to H3's legal ``5 + 17 * n`` temporal shape."""

    if frames <= H3_MIN_FRAMES:
        return H3_MIN_FRAMES
    return H3_MIN_FRAMES + ((frames - H3_MIN_FRAMES + 16) // 17) * 17


def aligned_frames_from_seconds(seconds: float) -> int:
    """Convert a duration to the frame count h3 will actually generate."""

    # h3 uses llround(seconds * 24); mirror that for positive values.
    requested = int(seconds * H3_FPS + 0.5)
    return align_frame_count(requested)


def phase_progress(phase: str, completed: int, total: int) -> float | None:
    """Map an h3 phase/counter pair onto an overall 0..100 percentage."""

    if total <= 0:
        return None
    lowered = phase.strip().lower()
    for key, start, end in _PHASE_RANGES:
        if lowered == key or lowered.startswith(key):
            fraction = min(max(completed / total, 0.0), 1.0)
            return start + (end - start) * fraction
    return None


def _is_within_frame_limit(frames: int) -> bool:
    return H3_MIN_FRAMES <= frames <= H3_MAX_FRAMES and align_frame_count(frames) <= H3_MAX_FRAMES


def _check_component(directory: Path, label: str) -> None:
    if not directory.is_dir():
        raise H3Error(
            f"H3 model directory is missing {label} ({directory}). Point H3_MODEL_DIR at a complete MiniMax-H3 directory."
        )
    try:
        next(directory.iterdir())
    except StopIteration as exc:
        raise H3Error(f"H3 model component {label} is an empty directory: {directory}") from exc


@dataclass
class H3Request:
    """One validated H3 generation request."""

    mode: str
    prompt: str
    output_path: str
    model_dir: str
    h3_binary: str

    width: int = 512
    height: int = 512
    frames: int = 56
    seconds: float = 0.0

    steps: int = 20
    layers: int = 45
    reuse: int = 2
    core_reuse: int = 1
    token_reduction: bool = False
    ssd_streaming: bool = False
    int8_row_fc2: bool = False
    use_reference_rope: bool = False

    render_width: int = 0
    render_height: int = 0
    seed: int = 42

    first_frame: str | None = None
    last_frame: str | None = None
    ref_images: list[str] = field(default_factory=list)
    ref_audio: str | None = None
    ref_image_size: str = "match"

    profile: bool = False
    timeout_seconds: int = 3600
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    serialize: bool = True

    # Runtime-only callbacks (not part of the command line).
    on_progress: ProgressCallback | None = field(default=None, repr=False)
    interrupt_check: InterruptCheck | None = field(default=None, repr=False)

    def validate(self) -> None:
        """Validate everything h3 validates plus the ComfyUI-specific limits."""

        if self.mode not in ("fl2va", "ref2va"):
            raise H3Error(f"Unknown H3 mode: {self.mode}")
        if not self.prompt or not self.prompt.strip():
            raise H3Error("Prompt is empty.")
        if "\x00" in self.prompt:
            raise H3Error("Prompt must not contain NUL characters.")

        if self.width < H3_CANVAS_MULTIPLE or self.height < H3_CANVAS_MULTIPLE:
            raise H3Error("Width and height must be at least 32.")
        if self.width % H3_CANVAS_MULTIPLE or self.height % H3_CANVAS_MULTIPLE:
            raise H3Error("Width and height must be multiples of 32.")
        if self.width * self.height > H3_MAX_PIXELS:
            raise H3Error("Canvas exceeds H3's 768*1344 pixel limit.")

        if self.seconds > 0:
            if self.seconds > H3_MAX_TEXT_SECONDS:
                raise H3Error(
                    f"Duration is too long: H3 supports at most {H3_MAX_FRAMES} frames (~{H3_MAX_TEXT_SECONDS:.3f}s)."
                )
            if aligned_frames_from_seconds(self.seconds) > H3_MAX_FRAMES:
                raise H3Error(
                    f"Duration {self.seconds:g}s exceeds H3's {H3_MAX_FRAMES}-frame limit."
                )
        elif not _is_within_frame_limit(self.frames):
            raise H3Error(f"Frames must be in 5..{H3_MAX_FRAMES} (H3 rounds up to 5+17*n).")

        if self.steps < 2 or self.steps > H3_MAX_STEPS:
            raise H3Error(f"steps must be in 2..{H3_MAX_STEPS}.")
        if self.layers < H3_MIN_LAYERS or self.layers > H3_MAX_LAYERS:
            raise H3Error(f"layers must be in {H3_MIN_LAYERS}..{H3_MAX_LAYERS}.")
        if self.reuse < 1 or self.reuse > 3:
            raise H3Error("reuse must be in 1..3 (1=exact, 2=fast, 3=aggressive).")
        if self.core_reuse < 1 or self.core_reuse > 6:
            raise H3Error("core_reuse must be in 1..6.")
        if self.reuse > 1 and self.core_reuse > 1:
            raise H3Error(
                "reuse and core_reuse cannot both be greater than 1; choose one acceleration mode."
            )
        if self.ssd_streaming and self.int8_row_fc2:
            raise H3Error("ssd_streaming and int8_row_fc2 cannot be enabled together.")

        if (self.render_width == 0) != (self.render_height == 0):
            raise H3Error("render_width and render_height must both be 0 or both be set.")
        if self.render_width:
            if (
                self.render_width < H3_CANVAS_MULTIPLE
                or self.render_height < H3_CANVAS_MULTIPLE
                or self.render_width % H3_CANVAS_MULTIPLE
                or self.render_height % H3_CANVAS_MULTIPLE
            ):
                raise H3Error("Internal render size must be multiples of 32 and at least 32.")
            if self.render_width > self.width or self.render_height > self.height:
                raise H3Error("Internal render size cannot exceed the output size.")
            if self.render_width * self.height != self.render_height * self.width:
                raise H3Error("Internal render size must preserve the output aspect ratio.")

        if self.seed < 0:
            raise H3Error("seed must not be negative.")
        if self.timeout_seconds is not None and self.timeout_seconds < 0:
            raise H3Error("timeout_seconds must not be negative.")

        if self.mode == "fl2va":
            if self.ref_images:
                raise H3Error("The FL2VA node cannot use reference images; use the Ref2VA node.")
            if self.ref_audio:
                raise H3Error(
                    "The FL2VA node cannot use standalone reference audio; use the Ref2VA node."
                )
        else:
            if self.first_frame or self.last_frame:
                raise H3Error("The Ref2VA node cannot use first/last frames; use the FL2VA node.")
            if not self.ref_images:
                raise H3Error(
                    "Ref2VA requires at least one reference image. Use the FL2VA node for text-to-video."
                )
            if len(self.ref_images) > H3_MAX_IMAGE_REFERENCES:
                raise H3Error(f"At most {H3_MAX_IMAGE_REFERENCES} reference images are supported.")
            if self.ref_image_size not in ("match", "max"):
                raise H3Error("ref_image_size must be 'match' or 'max'.")

        if len(self.prompt) > 100_000:
            raise H3Error("Prompt is too long (over 100,000 characters).")

        media_paths = [
            path
            for path in (self.first_frame, self.last_frame, self.ref_audio, *self.ref_images)
            if path
        ]
        for path in media_paths:
            if not Path(path).expanduser().is_file():
                raise H3Error(f"Input media file does not exist: {path}")

        binary = Path(self.h3_binary).expanduser()
        if not binary.is_file():
            raise H3Error(f"h3 executable not found: {binary}")
        if not os.access(binary, os.X_OK):
            raise H3Error(f"h3 is not executable: {binary}")
        shader_dir = binary.resolve().parent
        if not (shader_dir / "h3_shaders.metal").is_file():
            raise H3Error(
                f"h3_shaders.metal is missing from the h3 directory: {shader_dir}."
                "h3 must run with that directory as its working directory."
            )

        model = Path(self.model_dir).expanduser()
        if not model.is_dir():
            raise H3Error(f"H3 model directory not found: {model}")
        _check_component(model / "FL2VA" / "transformer", "FL2VA/transformer")
        if self.mode == "ref2va":
            _check_component(model / "Ref2VA" / "transformer", "Ref2VA/transformer")

        output = Path(self.output_path).expanduser()
        if output.suffix.lower() != ".mp4":
            raise H3Error("H3 output must be an .mp4 file.")
        if output.exists():
            raise H3Error(f"Output file already exists; refusing to overwrite: {output}")

    @property
    def aligned_frames(self) -> int:
        if self.seconds > 0:
            return aligned_frames_from_seconds(self.seconds)
        return align_frame_count(self.frames)

    def build_command(self) -> list[str]:
        """Build the h3 argv.  ``validate`` should be called first."""

        command = [
            self.h3_binary,
            "-d",
            self.model_dir,
            "-p",
            self.prompt,
            "-o",
            self.output_path,
            "--width",
            str(self.width),
            "--height",
            str(self.height),
            "--steps",
            str(self.steps),
            "--layers",
            str(self.layers),
            "--reuse",
            str(self.reuse),
            "--core-reuse",
            str(self.core_reuse),
            "--seed",
            str(self.seed),
        ]

        if self.seconds > 0:
            command += ["--seconds", f"{self.seconds:.6f}"]
        else:
            command += ["--frames", str(self.frames)]

        if self.render_width:
            command += [
                "--render-width",
                str(self.render_width),
                "--render-height",
                str(self.render_height),
            ]
        if self.first_frame:
            command += ["--first-frame", self.first_frame]
        if self.last_frame:
            command += ["--last-frame", self.last_frame]
        for image in self.ref_images:
            command += ["--ref-image", image]
        if self.mode == "ref2va":
            command += ["--ref-image-size", self.ref_image_size]
        if self.ref_audio:
            command += ["--ref-audio", self.ref_audio]

        if self.token_reduction:
            command.append("--token-reduction")
        if self.ssd_streaming:
            command.append("--ssd-streaming")
        if self.int8_row_fc2:
            command.append("--use-int8-row-fc2")
        if self.use_reference_rope:
            command.append("--use-reference-rope")
        if self.profile:
            command.append("--profile")
        return command


def _reader_thread(stream, messages: queue.Queue[str | None]) -> None:
    """Split h3's stdout/stderr stream on both ``\\n`` and ``\\r``."""

    buffer = b""
    fd = stream.fileno()
    try:
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while True:
                positions = [p for p in (buffer.find(b"\r"), buffer.find(b"\n")) if p >= 0]
                if not positions:
                    break
                index = min(positions)
                raw = buffer[:index]
                buffer = buffer[index + 1 :]
                text = _ANSI_RE.sub("", raw.decode("utf-8", errors="replace")).strip()
                if text:
                    messages.put(text)
    finally:
        trailing = _ANSI_RE.sub("", buffer.decode("utf-8", errors="replace")).strip()
        if trailing:
            messages.put(trailing)
        messages.put(None)


def _terminate_process(process: subprocess.Popen, grace: float = 5.0) -> None:
    """Terminate the whole process group, escalating to SIGKILL if needed."""

    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            process.terminate()
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        logger.warning("h3 process %s did not exit after SIGKILL", process.pid)


def _subprocess_environment(ffmpeg: str, ffprobe: str) -> dict[str, str]:
    env = os.environ.copy()
    # ComfyUI may be started from a GUI launcher with a minimal PATH; h3 needs
    # ffmpeg/ffprobe from Homebrew or /usr/local/bin.
    extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    current = env.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    for directory in reversed(extra):
        if directory not in parts:
            parts.insert(0, directory)
    env["PATH"] = os.pathsep.join(parts)
    if ffmpeg:
        env["H3_FFMPEG"] = ffmpeg
    if ffprobe:
        env["H3_FFPROBE"] = ffprobe
    return env


def _redacted_command(command: list[str]) -> list[str]:
    """Return argv for debug logs without the prompt or media paths."""

    hidden_flags = {
        "-p",
        "--prompt",
        "--first-frame",
        "--last-frame",
        "--ref-image",
        "--ref-audio",
        "--ref-video",
        "--ref-silent-video",
        "--ref-video-audio",
    }
    redacted: list[str] = []
    hide_next = False
    for item in command:
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            continue
        redacted.append(item)
        if item in hidden_flags:
            hide_next = True
    return redacted


def _format_failure(command: list[str], returncode: int, tail: deque[str]) -> str:
    interesting = [
        line
        for line in tail
        if line and not _PROGRESS_RE.match(line) and not line.startswith("h3: preview")
    ]
    message = [f"h3 exited with code {returncode}; generation failed."]
    if interesting:
        message.append("Last h3 output:")
        message.extend(f"  {line}" for line in interesting[-40:])
    message.append("Command: " + " ".join(_redacted_command(command)[:4] + ["..."]))
    return "\n".join(message)


def _lock_path() -> Path:
    return Path(tempfile.gettempdir()) / f"comfyui-minimax-h3-{os.getuid()}.lock"


def _acquire_generation_lock(request: H3Request) -> int:
    """Serialize H3 processes so two ComfyUI instances cannot exhaust memory."""

    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    waited = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if waited:
                    logger.info("Acquired the H3 generation lock.")
                return fd
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if not waited:
                    logger.info("Another H3 generation is running; waiting for the lock...")
                    waited = True
                if request.interrupt_check is not None and request.interrupt_check():
                    raise H3Interrupted(
                        "H3 generation was cancelled while waiting for the lock."
                    ) from None
                time.sleep(0.5)
    except BaseException:
        os.close(fd)
        raise


def _release_generation_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def run_h3(request: H3Request) -> float:
    """Run one h3 generation and return the elapsed wall time in seconds.

    Raises:
        H3Interrupted: the caller requested cancellation.
        H3Error: validation failed, the process failed, or the output is missing.
    """

    request.validate()
    output = Path(request.output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    command = request.build_command()
    logger.info(
        "MiniMax H3: mode=%s %dx%d frames=%d steps=%d layers=%d reuse=%d core_reuse=%d seed=%d",
        request.mode,
        request.width,
        request.height,
        request.aligned_frames,
        request.steps,
        request.layers,
        request.reuse,
        request.core_reuse,
        request.seed,
    )
    logger.debug("MiniMax H3 argv: %s", _redacted_command(command))

    if request.serialize:
        lock_fd = _acquire_generation_lock(request)
        try:
            return _run_process(request, output, command)
        finally:
            _release_generation_lock(lock_fd)
    return _run_process(request, output, command)


def _run_process(request: H3Request, output: Path, command: list[str]) -> float:
    started = time.monotonic()
    deadline = None
    if request.timeout_seconds:
        deadline = started + float(request.timeout_seconds)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(Path(request.h3_binary).resolve().parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            start_new_session=True,
            env=_subprocess_environment(request.ffmpeg, request.ffprobe),
        )
    except OSError as exc:
        raise H3Error(f"Cannot start h3: {exc}") from exc

    assert process.stdout is not None
    messages: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(
        target=_reader_thread,
        args=(process.stdout, messages),
        name="h3-output-reader",
        daemon=True,
    )
    reader.start()

    tail: deque[str] = deque(maxlen=200)
    last_reported = -1.0
    last_phase = ""
    last_status_time = 0.0
    saw_eof = False
    failure: BaseException | None = None

    try:
        while True:
            if request.interrupt_check is not None and request.interrupt_check():
                raise H3Interrupted("H3 generation was cancelled.")
            if deadline is not None and time.monotonic() > deadline:
                raise H3Error(f"H3 generation timed out after {request.timeout_seconds}s.")

            try:
                item = messages.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue

            if item is None:
                saw_eof = True
                break

            line = str(item)
            tail.append(line)
            if line.startswith("h3:"):
                logger.info(line)

            match = _PROGRESS_RE.match(line)
            if not match or line.startswith("h3:"):
                continue

            phase = match.group("phase").strip()
            completed = int(match.group("done"))
            total = int(match.group("total"))
            percentage = phase_progress(phase, completed, total)
            if percentage is None:
                continue

            # Keep the bar monotonic; H3 phases can overlap slightly.
            percentage = max(percentage, last_reported)
            if percentage > last_reported:
                last_reported = percentage
            now = time.monotonic()
            if request.on_progress is not None and (
                phase != last_phase or now - last_status_time >= 0.2 or completed >= total
            ):
                request.on_progress(percentage, phase, completed, total)
                last_phase = phase
                last_status_time = now

        if not saw_eof:
            # The loop can only break here when the reader is done; join it so
            # the queue is fully drained before we inspect the exit code.
            reader.join(timeout=5.0)

        try:
            returncode = process.wait(timeout=30.0)
        except subprocess.TimeoutExpired as exc:
            raise H3Error("h3 closed its output but did not exit.") from exc

        if returncode != 0:
            raise H3Error(_format_failure(command, returncode, tail))
    except BaseException as exc:
        failure = exc
        raise
    finally:
        _terminate_process(process)
        with contextlib.suppress(OSError):
            process.stdout.close()
        reader.join(timeout=2.0)
        if failure is not None:
            try:
                if output.exists():
                    output.unlink()
            except OSError:
                logger.warning("Could not clean up failed H3 output: %s", output)

    if not output.is_file() or output.stat().st_size == 0:
        try:
            if output.exists():
                output.unlink()
        except OSError:
            pass
        raise H3Error(f"h3 returned success but did not write a valid video: {output}")

    elapsed = time.monotonic() - started
    if request.on_progress is not None:
        request.on_progress(100.0, "done", 1, 1)
    logger.info(
        "MiniMax H3: wrote %s (%.1f MiB) in %.1f s",
        output,
        output.stat().st_size / 1048576.0,
        elapsed,
    )
    return elapsed
