# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure-Python H3 runner (no ComfyUI, no torch)."""

from __future__ import annotations

import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from h3_runner import (  # noqa: E402
    H3Error,
    H3Interrupted,
    H3Request,
    align_frame_count,
    aligned_frames_from_seconds,
    phase_progress,
    run_h3,
)


def _make_fake_install(root: Path, script: str) -> tuple[Path, Path]:
    h3_dir = root / "h3.c"
    h3_dir.mkdir(parents=True)
    binary = h3_dir / "h3"
    binary.write_text("#!/bin/sh\n" + textwrap.dedent(script))
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (h3_dir / "h3_shaders.metal").write_text("// fake\n")

    model = h3_dir / "model"
    (model / "FL2VA" / "transformer").mkdir(parents=True)
    (model / "FL2VA" / "transformer" / "dummy.safetensors").write_text("x")
    (model / "Ref2VA" / "transformer").mkdir(parents=True)
    (model / "Ref2VA" / "transformer" / "dummy.safetensors").write_text("x")
    return binary, model


def _request(
    root: Path, output: Path, *, mode: str = "fl2va", script: str = "exit 0\n"
) -> H3Request:
    binary, model = _make_fake_install(root, script)
    return H3Request(
        mode=mode,
        prompt="A red fox in fresh snow.",
        output_path=str(output),
        model_dir=str(model),
        h3_binary=str(binary),
        width=512,
        height=512,
        frames=22,
        steps=20,
        layers=45,
        reuse=2,
        core_reuse=1,
        seed=7,
        serialize=False,
    )


class AlignmentTests(unittest.TestCase):
    def test_align_frame_count(self):
        self.assertEqual(align_frame_count(5), 5)
        self.assertEqual(align_frame_count(6), 22)
        self.assertEqual(align_frame_count(22), 22)
        self.assertEqual(align_frame_count(23), 39)
        self.assertEqual(align_frame_count(56), 56)
        self.assertEqual(align_frame_count(362), 362)

    def test_seconds_alignment(self):
        self.assertEqual(aligned_frames_from_seconds(0.92), 22)
        self.assertEqual(aligned_frames_from_seconds(2.33), 56)
        self.assertEqual(aligned_frames_from_seconds(10.0), 243)

    def test_phase_progress(self):
        self.assertEqual(phase_progress("tokenizer", 0, 1), 0.0)
        self.assertEqual(phase_progress("tokenizer", 1, 1), 1.0)
        self.assertEqual(phase_progress("denoise enqueue", 10, 20), 72.0)
        self.assertEqual(phase_progress("unknown phase", 1, 2), None)


class ValidationTests(unittest.TestCase):
    def test_valid_fl2va(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4")
            request.validate()
            self.assertEqual(request.aligned_frames, 22)

    def test_rejects_empty_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4")
            request.prompt = "   "
            with self.assertRaises(H3Error):
                request.validate()

    def test_rejects_bad_canvas(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4")
            request.width = 500
            with self.assertRaises(H3Error):
                request.validate()
            request.width = 1344
            request.height = 1344
            with self.assertRaises(H3Error):
                request.validate()

    def test_rejects_reuse_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4")
            request.core_reuse = 4
            with self.assertRaises(H3Error):
                request.validate()

    def test_rejects_ref2va_without_images(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4", mode="ref2va")
            with self.assertRaises(H3Error):
                request.validate()

    def test_command_flags_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4", mode="ref2va")
            image1 = root / "p1.png"
            image2 = root / "p2.png"
            audio = root / "a.wav"
            for media in (image1, image2, audio):
                media.write_bytes(b"test")
            request.ref_images = [str(image1), str(image2)]
            request.ref_audio = str(audio)
            request.token_reduction = True
            request.ssd_streaming = True
            request.render_width = 256
            request.render_height = 256
            request.validate()
            command = request.build_command()
            self.assertEqual(command[0], str(root / "h3.c" / "h3"))
            self.assertEqual(command[command.index("--frames") + 1], "22")
            self.assertEqual(
                [command[i + 1] for i, item in enumerate(command) if item == "--ref-image"],
                [str(image1), str(image2)],
            )
            self.assertIn("--ref-audio", command)
            self.assertIn("--token-reduction", command)
            self.assertIn("--ssd-streaming", command)
            self.assertEqual(command[command.index("--render-width") + 1], "256")

    def test_seconds_override_frames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = _request(root, root / "out.mp4")
            request.seconds = 2.33
            request.validate()
            command = request.build_command()
            self.assertIn("--seconds", command)
            self.assertNotIn("--frames", command)
            self.assertEqual(request.aligned_frames, 56)


class RunTests(unittest.TestCase):
    def test_success_and_progress(self):
        script = """
        out=""
        while [ $# -gt 0 ]; do
          case "$1" in
            -o) out="$2"; shift 2;;
            *) shift;;
          esac
        done
        printf 'tokenizer 0/1\\r' >&2
        printf 'text encoder 5/50\\n' >&2
        printf 'denoise enqueue 5/20\\r' >&2
        printf 'denoise enqueue 20/20\\n' >&2
        printf 'ffmpeg 22/22\\n' >&2
        printf 'fake-mp4' > "$out"
        exit 0
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "result.mp4"
            request = _request(root, output, script=script)
            events: list[float] = []

            def on_progress(percent, phase, done, total):
                events.append(percent)

            request.on_progress = on_progress
            elapsed = run_h3(request)
            self.assertGreaterEqual(elapsed, 0.0)
            self.assertTrue(output.is_file())
            self.assertEqual(events, sorted(events))
            self.assertEqual(events[-1], 100.0)

    def test_failure_removes_partial_output(self):
        script = """
        out=""
        while [ $# -gt 0 ]; do
          case "$1" in
            -o) out="$2"; shift 2;;
            *) shift;;
          esac
        done
        printf 'partial' > "$out"
        printf 'h3: something exploded\\n' >&2
        exit 3
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "result.mp4"
            request = _request(root, output, script=script)
            with self.assertRaises(H3Error) as caught:
                run_h3(request)
            self.assertIn("exited with code 3", str(caught.exception))
            self.assertFalse(output.exists())

    def test_timeout(self):
        script = """
        sleep 5
        exit 0
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "result.mp4"
            request = _request(root, output, script=script)
            request.timeout_seconds = 1
            started = time.monotonic()
            with self.assertRaises(H3Error):
                run_h3(request)
            self.assertLess(time.monotonic() - started, 4.0)

    def test_interrupt(self):
        script = """
        sleep 10
        exit 0
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "result.mp4"
            request = _request(root, output, script=script)
            start = time.monotonic()

            def interrupted():
                return time.monotonic() - start > 0.4

            request.interrupt_check = interrupted
            with self.assertRaises(H3Interrupted):
                run_h3(request)
            self.assertLess(time.monotonic() - start, 4.0)


if __name__ == "__main__":
    unittest.main()
