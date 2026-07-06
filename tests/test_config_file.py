import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config_file
import media_shrinker


def _write_config(directory: Path, payload) -> Path:
    path = directory / config_file.CONFIG_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@contextlib.contextmanager
def _chdir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class LoadConfigTests(unittest.TestCase):
    def test_absent_file_returns_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with _chdir(root):
                self.assertEqual(config_file.load_config(root), {})

    def test_valid_config_is_loaded_and_converted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(
                root,
                {
                    "target_bytes": 123,
                    "max_duration_seconds": 60,
                    "output_dir": "converted",
                    "flac_all": True,
                    "exclude_dir_prefix": ["split_", "tmp_"],
                },
            )
            config = config_file.load_config(root)

        self.assertEqual(config["target_bytes"], 123)
        self.assertEqual(config["max_duration_seconds"], 60.0)
        self.assertIsInstance(config["max_duration_seconds"], float)
        self.assertEqual(config["output_dir"], Path("converted"))
        self.assertIs(config["flac_all"], True)
        self.assertEqual(config["exclude_dir_prefix"], ["split_", "tmp_"])

    def test_root_config_wins_over_cwd_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            cwd = base / "cwd"
            root.mkdir()
            cwd.mkdir()
            _write_config(root, {"workers": 3})
            _write_config(cwd, {"workers": 7})
            with _chdir(cwd):
                config = config_file.load_config(root)

        self.assertEqual(config["workers"], 3)

    def test_cwd_config_used_when_root_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            cwd = base / "cwd"
            root.mkdir()
            cwd.mkdir()
            _write_config(cwd, {"workers": 7})
            with _chdir(cwd):
                config = config_file.load_config(root)

        self.assertEqual(config["workers"], 7)

    def test_unknown_key_error_lists_valid_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, {"bogus_key": 1, "target_bytes": 5})
            with self.assertRaises(config_file.ConfigFileError) as ctx:
                config_file.load_config(root)

        message = str(ctx.exception)
        self.assertIn("bogus_key", message)
        self.assertIn("Valid keys:", message)
        for valid_key in sorted(config_file.CONFIG_SCHEMA):
            self.assertIn(valid_key, message)

    def test_execute_is_not_a_valid_config_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, {"execute": True})
            with self.assertRaises(config_file.ConfigFileError) as ctx:
                config_file.load_config(root)

        self.assertIn("execute", str(ctx.exception))

    def test_malformed_json_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / config_file.CONFIG_FILENAME).write_text(
                "{not json", encoding="utf-8"
            )
            with self.assertRaises(config_file.ConfigFileError) as ctx:
                config_file.load_config(root)

        self.assertIn("Malformed JSON", str(ctx.exception))

    def test_non_object_top_level_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / config_file.CONFIG_FILENAME).write_text(
                "[1, 2]", encoding="utf-8"
            )
            with self.assertRaises(config_file.ConfigFileError) as ctx:
                config_file.load_config(root)

        self.assertIn("JSON object", str(ctx.exception))

    def test_unreadable_file_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, {"workers": 1})
            with patch.object(Path, "read_text", side_effect=OSError("boom")):
                with self.assertRaises(config_file.ConfigFileError) as ctx:
                    config_file.load_config(root)

        self.assertIn("Could not read config file", str(ctx.exception))


class TypeValidationTests(unittest.TestCase):
    def _assert_type_error(self, payload, expected_fragment: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, payload)
            with self.assertRaises(config_file.ConfigFileError) as ctx:
                config_file.load_config(root)
        self.assertIn(expected_fragment, str(ctx.exception))

    def test_int_key_rejects_string(self) -> None:
        self._assert_type_error({"target_bytes": "big"}, "expects an integer")

    def test_int_key_rejects_bool(self) -> None:
        self._assert_type_error({"workers": True}, "expects an integer")

    def test_float_key_rejects_string(self) -> None:
        self._assert_type_error({"max_duration_seconds": "60"}, "expects a number")

    def test_float_key_rejects_bool(self) -> None:
        self._assert_type_error(
            {"silence_min_duration_seconds": True}, "expects a number"
        )

    def test_bool_key_rejects_int(self) -> None:
        self._assert_type_error({"flac_all": 1}, "expects a boolean")

    def test_str_key_rejects_number(self) -> None:
        self._assert_type_error({"silence_noise": -35}, "expects a string")

    def test_path_key_rejects_number(self) -> None:
        self._assert_type_error({"output_dir": 5}, "expects a string")

    def test_str_list_key_rejects_scalar(self) -> None:
        self._assert_type_error(
            {"exclude_dir_prefix": "split_"}, "expects an array of strings"
        )

    def test_str_list_key_rejects_mixed_items(self) -> None:
        self._assert_type_error(
            {"exclude_dir_prefix": ["split_", 3]}, "expects an array of strings"
        )


class ParseArgsConfigIntegrationTests(unittest.TestCase):
    def test_config_in_root_supplies_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(
                root,
                {
                    "target_bytes": 123,
                    "flac_all": True,
                    "workers": 2,
                    "output_dir": "converted",
                    "include_under_limit": False,
                },
            )
            args = media_shrinker.parse_args([str(root)])

        self.assertEqual(args.target_bytes, 123)
        self.assertTrue(args.flac_all)
        self.assertEqual(args.workers, 2)
        self.assertEqual(args.output_dir, Path("converted"))
        self.assertFalse(args.include_under_limit)

    def test_cli_flag_overrides_config_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, {"target_bytes": 123, "workers": 2})
            args = media_shrinker.parse_args(
                [str(root), "--target-bytes", "9"]
            )

        self.assertEqual(args.target_bytes, 9)
        self.assertEqual(args.workers, 2)

    def test_cli_flag_overrides_config_even_when_equal_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(
                root, {"target_bytes": 123, "include_under_limit": False}
            )
            args = media_shrinker.parse_args(
                [
                    str(root),
                    "--target-bytes",
                    str(media_shrinker.DEFAULT_TARGET_BYTES),
                    "--include-under-limit",
                ]
            )

        self.assertEqual(args.target_bytes, media_shrinker.DEFAULT_TARGET_BYTES)
        self.assertTrue(args.include_under_limit)

    def test_absent_config_keeps_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with _chdir(root):
                args = media_shrinker.parse_args([str(root)])

        self.assertEqual(args.target_bytes, media_shrinker.DEFAULT_TARGET_BYTES)
        self.assertEqual(
            args.size_limit_bytes, media_shrinker.DEFAULT_SIZE_LIMIT_BYTES
        )
        self.assertEqual(args.output_dir, Path("under_2gb"))
        self.assertFalse(args.flac_all)
        self.assertEqual(args.workers, 0)

    def test_unknown_config_key_exits_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, {"bogus_key": 1})
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    media_shrinker.parse_args([str(root)])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("bogus_key", stderr.getvalue())
        self.assertIn("Valid keys:", stderr.getvalue())

    def test_malformed_config_exits_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / config_file.CONFIG_FILENAME).write_text(
                "{oops", encoding="utf-8"
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    media_shrinker.parse_args([str(root)])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("Malformed JSON", stderr.getvalue())

    def test_type_mismatch_exits_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_config(root, {"target_bytes": "big"})
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    media_shrinker.parse_args([str(root)])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("expects an integer", stderr.getvalue())

    def test_main_dry_run_uses_config_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            source.write_bytes(b"1234")
            _write_config(
                root, {"size_limit_bytes": 1, "include_under_limit": False}
            )

            with patch("builtins.print") as mock_print:
                rc = media_shrinker.main([str(root)])

        self.assertEqual(rc, 0)
        printed = ["\t".join(map(str, call.args)) for call in mock_print.call_args_list]
        self.assertIn(f"DRY-RUN\t4\t{source.name}", printed)
        self.assertIn("TOTAL_SELECTED=1", printed)


if __name__ == "__main__":
    unittest.main()
