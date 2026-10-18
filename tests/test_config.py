# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for configuration discovery (no ComfyUI, no torch)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as config_module  # noqa: E402
from config import ConfigError, resolve_config  # noqa: E402

_KEYS = (
    "H3_CONFIG",
    "H3_DIR",
    "H3_MODEL_DIR",
    "H3_BIN",
    "H3_FFMPEG",
    "H3_FFPROBE",
    "H3_SERIALIZE",
    "H3_KEEP_TEMP",
    "H3_AUTO_DETECT",
)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.backup = {key: os.environ.get(key) for key in _KEYS}
        for key in _KEYS:
            os.environ.pop(key, None)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "config.json"
        os.environ["H3_CONFIG"] = str(self.config_path)
        os.environ["H3_AUTO_DETECT"] = "0"

    def tearDown(self):
        for key, value in self.backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def _write_config(self, data: dict) -> None:
        self.config_path.write_text(json.dumps(data), encoding="utf-8")

    def test_h3_dir_derives_paths(self):
        h3_dir = self.root / "h3.c"
        self._write_config({"h3_dir": str(h3_dir)})
        config = resolve_config()
        self.assertEqual(config.model_dir, (h3_dir / "model").resolve())
        self.assertEqual(config.h3_binary, (h3_dir / "h3").resolve())
        self.assertEqual(config.sources["model_dir"], "derived from h3_dir")

    def test_env_overrides_config(self):
        h3_dir = self.root / "h3.c"
        env_model = self.root / "env-model"
        env_binary = self.root / "env-bin"
        self._write_config({"h3_dir": str(h3_dir), "serialize": False})
        os.environ["H3_MODEL_DIR"] = str(env_model)
        os.environ["H3_BIN"] = str(env_binary)
        os.environ["H3_SERIALIZE"] = "1"
        config = resolve_config()
        self.assertEqual(config.model_dir, env_model.resolve())
        self.assertEqual(config.h3_binary, env_binary.resolve())
        self.assertTrue(config.serialize)
        self.assertEqual(config.sources["model_dir"], "env H3_MODEL_DIR")

    def test_explicit_model_and_binary(self):
        model = self.root / "model"
        binary = self.root / "h3"
        self._write_config(
            {
                "model_dir": str(model),
                "h3_binary": str(binary),
                "ffmpeg": "/opt/homebrew/bin/ffmpeg",
                "ffprobe": "/opt/homebrew/bin/ffprobe",
            }
        )
        config = resolve_config()
        self.assertEqual(config.model_dir, model.resolve())
        self.assertEqual(config.h3_binary, binary.resolve())
        self.assertEqual(config.ffmpeg, "/opt/homebrew/bin/ffmpeg")
        self.assertEqual(config.ffprobe, "/opt/homebrew/bin/ffprobe")

    def test_relative_paths_are_relative_to_config(self):
        self._write_config({"h3_dir": "third_party/h3.c"})
        config = resolve_config()
        self.assertEqual(config.model_dir, (self.root / "third_party/h3.c/model").resolve())

    def test_boolean_environment(self):
        self._write_config({})
        os.environ["H3_KEEP_TEMP"] = "1"
        os.environ["H3_SERIALIZE"] = "0"
        config = resolve_config()
        self.assertTrue(config.keep_temp)
        self.assertFalse(config.serialize)

    def test_invalid_json_raises(self):
        self.config_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            resolve_config()

    def test_non_object_json_raises(self):
        self.config_path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ConfigError):
            resolve_config()

    def test_missing_config_file_is_allowed(self):
        config = resolve_config()
        self.assertEqual(config.config_path, self.config_path)
        self.assertIsNone(config.model_dir)
        self.assertIsNone(config.h3_binary)

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_package_config_wins_over_comfyui_user_config(self):
        os.environ.pop("H3_CONFIG", None)
        package_dir = self.root / "package"
        package_config = package_dir / "config.json"
        user_config = self.root / "comfyui-user-default.json"
        self._write_json(package_config, {"h3_dir": str(self.root / "pkg-h3")})
        self._write_json(user_config, {"h3_dir": str(self.root / "user-h3")})

        with (
            patch.object(config_module, "package_config_path", return_value=package_config),
            patch.object(config_module, "_comfyui_config_path", return_value=user_config),
        ):
            config = resolve_config()

        self.assertEqual(config.config_path, package_config)
        self.assertEqual(config.model_dir, (self.root / "pkg-h3" / "model").resolve())
        self.assertEqual(config.config_candidates, (package_config, user_config))

    def test_user_config_used_when_package_config_is_missing(self):
        os.environ.pop("H3_CONFIG", None)
        package_config = self.root / "package" / "config.json"
        user_config = self.root / "comfyui-user-default.json"
        self._write_json(user_config, {"h3_dir": str(self.root / "user-h3")})

        with (
            patch.object(config_module, "package_config_path", return_value=package_config),
            patch.object(config_module, "_comfyui_config_path", return_value=user_config),
        ):
            config = resolve_config()

        self.assertEqual(config.config_path, user_config)
        self.assertEqual(config.model_dir, (self.root / "user-h3" / "model").resolve())

    def test_h3_config_overrides_package_and_user_configs(self):
        explicit = self.root / "explicit.json"
        package_config = self.root / "package" / "config.json"
        user_config = self.root / "comfyui-user-default.json"
        self._write_json(explicit, {"h3_dir": str(self.root / "explicit-h3")})
        self._write_json(package_config, {"h3_dir": str(self.root / "pkg-h3")})
        self._write_json(user_config, {"h3_dir": str(self.root / "user-h3")})
        os.environ["H3_CONFIG"] = str(explicit)

        with (
            patch.object(config_module, "package_config_path", return_value=package_config),
            patch.object(config_module, "_comfyui_config_path", return_value=user_config),
        ):
            config = resolve_config()

        self.assertEqual(config.config_path, explicit)
        self.assertEqual(config.config_candidates, (explicit,))
        self.assertEqual(config.model_dir, (self.root / "explicit-h3" / "model").resolve())

    def test_environment_overrides_package_config_value(self):
        os.environ.pop("H3_CONFIG", None)
        package_config = self.root / "package" / "config.json"
        self._write_json(package_config, {"h3_dir": str(self.root / "pkg-h3")})
        os.environ["H3_MODEL_DIR"] = str(self.root / "env-model")

        with (
            patch.object(config_module, "package_config_path", return_value=package_config),
            patch.object(config_module, "_comfyui_config_path", return_value=None),
        ):
            config = resolve_config()

        self.assertEqual(config.model_dir, (self.root / "env-model").resolve())
        self.assertEqual(config.sources["model_dir"], "env H3_MODEL_DIR")


if __name__ == "__main__":
    unittest.main()
