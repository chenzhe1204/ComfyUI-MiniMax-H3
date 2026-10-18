# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration tests for the ComfyUI node classes using a fake h3 binary."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

COMFY_ROOT = pathlib.Path(os.environ.get("COMFYUI_DIR", ""))
if not (COMFY_ROOT / "comfy").is_dir():
    raise RuntimeError(
        "Set COMFYUI_DIR to a ComfyUI checkout before running this integration test."
    )
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(COMFY_ROOT) not in sys.path:
    sys.path.insert(0, str(COMFY_ROOT))

import folder_paths  # noqa: E402
import torch  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "comfyui_minimax_h3",
    PACKAGE_ROOT / "__init__.py",
    submodule_search_locations=[str(PACKAGE_ROOT)],
)
_package = importlib.util.module_from_spec(_spec)
sys.modules["comfyui_minimax_h3"] = _package
_spec.loader.exec_module(_package)

from comfyui_minimax_h3 import nodes  # noqa: E402


def _make_fake_h3(root: Path) -> tuple[Path, Path]:
    h3_dir = root / "h3.c"
    h3_dir.mkdir(parents=True)
    binary = h3_dir / "h3"
    binary.write_text(
        "#!/bin/sh\n"
        + textwrap.dedent(
            """
            printf '%s\\n' "$@" > "${FAKE_H3_LOG:-/dev/null}"
            out=""
            while [ $# -gt 0 ]; do
              case "$1" in
                -o) out="$2"; shift 2;;
                *) shift;;
              esac
            done
            printf 'tokenizer 1/1\\n' >&2
            printf 'text encoder 50/50\\n' >&2
            printf 'denoise enqueue 20/20\\n' >&2
            printf 'ffmpeg 22/22\\n' >&2
            printf 'fake-mp4' > "$out"
            exit "${FAKE_H3_EXIT:-0}"
            """
        )
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (h3_dir / "h3_shaders.metal").write_text("// fake\n")
    model = h3_dir / "model"
    for component in ("FL2VA", "Ref2VA"):
        target = model / component / "transformer"
        target.mkdir(parents=True)
        (target / "dummy.safetensors").write_text("x")
    return binary, model


def _base_kwargs() -> dict:
    return dict(
        prompt="A red fox in fresh snow.",
        width=512,
        height=512,
        frames=22,
        seconds=0.0,
        steps=20,
        layers=45,
        reuse=2,
        core_reuse=1,
        token_reduction=False,
        ssd_streaming=False,
        int8_row_fc2=False,
        use_reference_rope=False,
        render_width=0,
        render_height=0,
        seed=7,
        filename_prefix="test/H3",
        timeout_seconds=60,
        profile=False,
    )


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary, self.model = _make_fake_h3(self.root)
        self.output_dir = self.root / "output"
        self.output_dir.mkdir()
        self.original_get_output = folder_paths.get_output_directory
        folder_paths.get_output_directory = lambda: str(self.output_dir)
        self.log = self.root / "args.log"
        os.environ["FAKE_H3_LOG"] = str(self.log)
        os.environ.pop("FAKE_H3_EXIT", None)
        for name in ("ffmpeg", "ffprobe"):
            executable = self.root / name
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
        self._env_backup = {
            key: os.environ.get(key)
            for key in (
                "H3_BIN",
                "H3_MODEL_DIR",
                "H3_CONFIG",
                "H3_FFMPEG",
                "H3_FFPROBE",
                "H3_SERIALIZE",
            )
        }
        os.environ["H3_BIN"] = str(self.binary)
        os.environ["H3_MODEL_DIR"] = str(self.model)
        os.environ["H3_CONFIG"] = str(self.root / "config.json")
        os.environ["H3_FFMPEG"] = str(self.root / "ffmpeg")
        os.environ["H3_FFPROBE"] = str(self.root / "ffprobe")
        os.environ["H3_SERIALIZE"] = "0"
        os.environ["COMFYUI_DIR"] = str(COMFY_ROOT)

    def tearDown(self):
        folder_paths.get_output_directory = self.original_get_output
        os.environ.pop("FAKE_H3_LOG", None)
        os.environ.pop("FAKE_H3_EXIT", None)
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def test_extension_registers_two_nodes(self):
        extension = asyncio.run(_package.comfy_entrypoint())
        nodes_list = asyncio.run(extension.get_node_list())
        self.assertEqual(
            [node.GET_SCHEMA().node_id for node in nodes_list],
            ["MiniMaxH3_FL2VA", "MiniMaxH3_Ref2VA"],
        )

    def test_fl2va_text_to_video(self):
        result = nodes.MiniMaxH3FL2VA.execute(
            **_base_kwargs(),
        )
        video, saved_path = result.args
        self.assertTrue(Path(saved_path).is_file())
        self.assertEqual(Path(saved_path).parent, self.output_dir / "test")
        self.assertEqual(Path(saved_path).suffix, ".mp4")
        self.assertEqual(result.ui.values[0]["filename"], Path(saved_path).name)
        self.assertIsNotNone(video)
        argv = self.log.read_text().splitlines()
        self.assertIn("--frames", argv)
        self.assertNotIn("--ref-image", argv)

    def test_fl2va_first_and_last_frame(self):
        kwargs = _base_kwargs()
        kwargs["first_frame"] = torch.zeros((1, 8, 8, 3))
        kwargs["last_frame"] = torch.ones((1, 8, 8, 3))
        result = nodes.MiniMaxH3FL2VA.execute(**kwargs)
        argv = self.log.read_text().splitlines()
        self.assertIn("--first-frame", argv)
        self.assertIn("--last-frame", argv)
        self.assertTrue(Path(result.args[1]).is_file())

    def test_ref2va_image_and_audio(self):
        audio = {
            "waveform": torch.zeros((1, 1, 3 * 32000)),
            "sample_rate": 32000,
        }
        kwargs = _base_kwargs()
        kwargs.update(
            ref_images=torch.zeros((2, 8, 8, 3)),
            ref_audio=audio,
            ref_image_size="max",
        )
        result = nodes.MiniMaxH3Ref2VA.execute(**kwargs)
        argv = self.log.read_text().splitlines()
        self.assertEqual(argv.count("--ref-image"), 2)
        self.assertIn("--ref-audio", argv)
        self.assertEqual(argv[argv.index("--ref-image-size") + 1], "max")
        self.assertTrue(Path(result.args[1]).is_file())

    def test_validation_error_does_not_spawn(self):
        kwargs = _base_kwargs()
        kwargs["core_reuse"] = 4  # conflicts with reuse=2
        with self.assertRaises(RuntimeError):
            nodes.MiniMaxH3FL2VA.execute(**kwargs)
        self.assertFalse(self.log.exists())

    def test_h3_failure_propagates(self):
        os.environ["FAKE_H3_EXIT"] = "5"
        with self.assertRaises(RuntimeError):
            nodes.MiniMaxH3FL2VA.execute(**_base_kwargs())


if __name__ == "__main__":
    unittest.main()
