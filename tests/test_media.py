# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for IMAGE/AUDIO conversion."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import (  # noqa: E402
    MediaError,
    audio_duration,
    image_to_pil,
    save_audio,
    save_image_batch,
)


class ImageTests(unittest.TestCase):
    def test_rgb_conversion(self):
        image = torch.zeros((2, 2, 3), dtype=torch.float32)
        image[..., 0] = 1.0
        pil = image_to_pil(image)
        self.assertEqual(pil.mode, "RGB")
        self.assertEqual(pil.size, (2, 2))
        self.assertEqual(pil.getpixel((0, 0)), (255, 0, 0))

    def test_alpha_composited_over_black(self):
        image = torch.ones((1, 1, 4), dtype=torch.float32)
        image[..., 3] = 0.0
        pil = image_to_pil(image)
        self.assertEqual(pil.getpixel((0, 0)), (0, 0, 0))

    def test_grayscale_expands(self):
        image = torch.full((2, 2, 1), 0.5)
        pil = image_to_pil(image)
        self.assertEqual(pil.getpixel((0, 0)), (128, 128, 128))

    def test_batch_order_and_limit(self):
        batch = torch.zeros((2, 4, 4, 3))
        batch[0, ..., 0] = 1.0
        batch[1, ..., 1] = 1.0
        with tempfile.TemporaryDirectory() as td:
            paths = save_image_batch(batch, Path(td), "ref")
            self.assertEqual([path.name for path in paths], ["ref_001.png", "ref_002.png"])
            self.assertTrue(paths[0].is_file() and paths[1].is_file())
            with self.assertRaises(MediaError):
                save_image_batch(batch, Path(td), "ref", limit=1)

    def test_accepts_zero_to_255(self):
        image = torch.full((1, 1, 3), 255.0)
        pil = image_to_pil(image[0])
        self.assertEqual(pil.getpixel((0, 0)), (255, 255, 255))


class AudioTests(unittest.TestCase):
    @staticmethod
    def _tone(seconds: float, rate: int = 44100, channels: int = 1) -> dict:
        t = torch.arange(int(seconds * rate), dtype=torch.float32) / rate
        wave_data = torch.sin(2 * math.pi * 440.0 * t) * 0.5
        waveform = wave_data.unsqueeze(0)
        if channels == 2:
            waveform = waveform.repeat(2, 1)
        return {"waveform": waveform.unsqueeze(0), "sample_rate": rate}

    def test_save_three_seconds(self):
        audio = self._tone(3.0)
        with tempfile.TemporaryDirectory() as td:
            path, duration = save_audio(audio, Path(td) / "a.wav")
            self.assertAlmostEqual(duration, 3.0, places=3)
            with wave.open(str(path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertEqual(handle.getframerate(), 44100)
                self.assertEqual(handle.getnframes(), 3 * 44100)

    def test_stereo(self):
        audio = self._tone(2.5, channels=2)
        with tempfile.TemporaryDirectory() as td:
            path, _ = save_audio(audio, Path(td) / "a.wav")
            with wave.open(str(path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 2)

    def test_duration_limits(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(MediaError):
                save_audio(self._tone(1.0), Path(td) / "short.wav")
            with self.assertRaises(MediaError):
                save_audio(self._tone(15.5), Path(td) / "long.wav")

    def test_audio_duration(self):
        self.assertAlmostEqual(audio_duration(self._tone(2.25)), 2.25, places=3)

    def test_missing_sample_rate(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(MediaError):
            save_audio({"waveform": torch.zeros((1, 1, 48000))}, Path(td) / "a.wav")


if __name__ == "__main__":
    unittest.main()
