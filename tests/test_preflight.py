# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for preflight checks using a fake h3 install."""

from __future__ import annotations

import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import H3Config  # noqa: E402
from preflight import (  # noqa: E402
    check_ffmpeg,
    check_h3_cli_contract,
    check_h3_install,
    doctor_report,
)


def _executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.h3_dir = self.root / "h3.c"
        (self.h3_dir / "model" / "FL2VA" / "transformer").mkdir(parents=True)
        (self.h3_dir / "model" / "FL2VA" / "transformer" / "weights.safetensors").write_text("x")
        (self.h3_dir / "model" / "Ref2VA" / "transformer").mkdir(parents=True)
        (self.h3_dir / "model" / "Ref2VA" / "transformer" / "weights.safetensors").write_text("x")
        _executable(self.h3_dir / "h3", 'echo "fake h3"\n')
        (self.h3_dir / "h3_shaders.metal").write_text("// fake\n")
        self.ffmpeg = _executable(self.root / "ffmpeg", "exit 0\n")
        self.ffprobe = _executable(self.root / "ffprobe", "exit 0\n")
        self.config = H3Config(
            config_path=self.root / "config.json",
            h3_dir=self.h3_dir,
            model_dir=self.h3_dir / "model",
            h3_binary=self.h3_dir / "h3",
            ffmpeg=str(self.ffmpeg),
            ffprobe=str(self.ffprobe),
            serialize=True,
            keep_temp=False,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_ffmpeg_check(self):
        self.assertEqual(check_ffmpeg(self.config), [])
        missing = H3Config(
            config_path=self.config.config_path,
            h3_dir=None,
            model_dir=None,
            h3_binary=None,
            ffmpeg="/nonexistent/ffmpeg",
            ffprobe="/nonexistent/ffprobe",
            serialize=True,
            keep_temp=False,
        )
        self.assertEqual(len(check_ffmpeg(missing)), 2)

    def test_h3_install(self):
        self.assertEqual(check_h3_install(self.config, "fl2va"), [])
        self.assertEqual(check_h3_install(self.config, "ref2va"), [])
        (self.h3_dir / "h3_shaders.metal").unlink()
        self.assertTrue(check_h3_install(self.config, "fl2va"))

    def test_cli_contract(self):
        _executable(
            self.h3_dir / "h3",
            'echo "--core-reuse --frames --seconds --ref-image --ref-image-size '
            '--ref-audio --ssd-streaming --use-int8-row-fc2 --use-reference-rope"\n',
        )
        self.assertEqual(check_h3_cli_contract(self.config), [])

        _executable(self.h3_dir / "h3", 'echo "--frames"\n')
        errors = check_h3_cli_contract(self.config)
        self.assertTrue(errors)
        self.assertIn("--core-reuse", errors[0])

    @unittest.skipUnless(sys.platform == "darwin", "doctor checks target macOS")
    def test_doctor_report(self):
        _executable(
            self.h3_dir / "h3",
            'echo "--core-reuse --frames --seconds --ref-image --ref-image-size '
            '--ref-audio --ssd-streaming --use-int8-row-fc2 --use-reference-rope"\n',
        )
        lines, errors, warnings = doctor_report(self.config, "fl2va")
        self.assertTrue(lines)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
