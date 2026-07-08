"""Tests for the optional transcription sidecar and its conversion-pipeline seam.

No real speech model is ever loaded here: the faster-whisper backend is either
injected as a fake or forced unavailable by patching ``sys.modules``.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import media_shrinker
import transcribe
from media_shrinker import (
    ConversionResult,
    _build_transcription_hook,
    _run_post_process,
)
from transcribe import (
    TranscriptResult,
    TranscriptSegment,
    TranscriptionUnavailableError,
    transcribe_file,
    transcribe_output,
    write_sidecars,
)


def _fake_result() -> TranscriptResult:
    return TranscriptResult(
        text="hello world",
        segments=[TranscriptSegment(start=0.0, end=1.5, text="hello world")],
        language="en",
    )


class TranscribeModuleTests(unittest.TestCase):
    def test_write_sidecars_creates_txt_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "recording.wav.flac"
            audio.write_bytes(b"x")
            txt, js = write_sidecars(_fake_result(), audio)
            self.assertEqual(txt.name, "recording.wav.flac.txt")
            self.assertEqual(js.name, "recording.wav.flac.json")
            self.assertEqual(txt.read_text(encoding="utf-8").strip(), "hello world")
            data = json.loads(js.read_text(encoding="utf-8"))
            self.assertEqual(data["language"], "en")
            self.assertEqual(data["segments"][0]["text"], "hello world")

    def test_transcribe_file_backend_is_injectable(self) -> None:
        result = transcribe_file("a.flac", backend=lambda path, model: _fake_result())
        self.assertEqual(result.text, "hello world")

    def test_transcribe_output_uses_injected_fn_and_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clip.flac"
            audio.write_bytes(b"x")
            calls: dict = {}

            def fake(path, *, model="base"):
                calls["path"] = Path(path)
                calls["model"] = model
                return _fake_result()

            txt, js = transcribe_output(audio, model="small", transcribe_fn=fake)
            self.assertEqual(calls["model"], "small")
            self.assertEqual(calls["path"], audio)
            self.assertTrue(txt.exists() and js.exists())

    def test_default_backend_raises_unavailable_when_missing(self) -> None:
        # Force `import faster_whisper` to fail regardless of the environment.
        with patch.dict(sys.modules, {"faster_whisper": None}):
            with self.assertRaises(TranscriptionUnavailableError):
                transcribe_file("a.flac")


class PostProcessSeamTests(unittest.TestCase):
    def _result(self, status: str, output_path) -> ConversionResult:
        return ConversionResult(
            source_path=Path("source.wav"),
            output_path=output_path,
            status=status,
            original_size_bytes=1,
        )

    def test_run_post_process_only_for_converted_with_output(self) -> None:
        seen: list = []
        results = [
            self._result("converted", Path("a.flac")),
            self._result("failed", None),
            self._result("converted", None),  # converted but no path -> skipped
            self._result("skipped_existing", Path("b.flac")),  # not "converted"
        ]
        _run_post_process(results, lambda r: seen.append(r.output_path))
        self.assertEqual(seen, [Path("a.flac")])

    def test_run_post_process_none_is_noop(self) -> None:
        _run_post_process([self._result("converted", Path("a.flac"))], None)

    def test_build_hook_absent_without_flag(self) -> None:
        args = media_shrinker.parse_args([tempfile.gettempdir()])
        self.assertFalse(args.transcribe)
        self.assertIsNone(_build_transcription_hook(args))

    def test_build_hook_present_and_survives_missing_backend(self) -> None:
        args = media_shrinker.parse_args([tempfile.gettempdir(), "--transcribe"])
        hook = _build_transcription_hook(args)
        self.assertIsNotNone(hook)
        # With faster-whisper unavailable the hook must NOT raise; it must emit a
        # single TRANSCRIBE_SKIP notice carrying the unavailability reason.
        out = io.StringIO()
        with patch.dict(sys.modules, {"faster_whisper": None}):
            with contextlib.redirect_stdout(out):
                hook(self._result("converted", Path("out.flac")))
        printed = out.getvalue()
        self.assertIn("TRANSCRIBE_SKIP\t", printed)
        self.assertNotIn("TRANSCRIBED\t", printed)
        self.assertNotIn("TRANSCRIBE_FAIL\t", printed)

    def test_hook_success_reports_transcribed(self) -> None:
        args = media_shrinker.parse_args([tempfile.gettempdir(), "--transcribe"])
        hook = _build_transcription_hook(args)
        out = io.StringIO()
        with patch(
            "transcribe.transcribe_output",
            return_value=(Path("out.flac.txt"), Path("out.flac.json")),
        ):
            with contextlib.redirect_stdout(out):
                hook(self._result("converted", Path("out.flac")))
        # The success branch must announce the generated .txt sidecar path and
        # must NOT fall through to the skip/fail branches.
        self.assertEqual(out.getvalue().strip(), "TRANSCRIBED\tout.flac.txt")

    def test_hook_success_forwards_configured_model(self) -> None:
        # A meaningful guard on the seam wiring: the model chosen on the CLI must
        # reach transcribe_output, otherwise --transcribe-model would be inert.
        args = media_shrinker.parse_args(
            [tempfile.gettempdir(), "--transcribe", "--transcribe-model", "medium"]
        )
        hook = _build_transcription_hook(args)
        with patch(
            "transcribe.transcribe_output",
            return_value=(Path("out.flac.txt"), Path("out.flac.json")),
        ) as fake_transcribe:
            with contextlib.redirect_stdout(io.StringIO()):
                hook(self._result("converted", Path("out.flac")))
        fake_transcribe.assert_called_once_with(Path("out.flac"), model="medium")

    def test_hook_generic_failure_is_isolated(self) -> None:
        args = media_shrinker.parse_args([tempfile.gettempdir(), "--transcribe"])
        hook = _build_transcription_hook(args)
        out = io.StringIO()
        with patch("transcribe.transcribe_output", side_effect=ValueError("boom")):
            with contextlib.redirect_stdout(out):
                hook(self._result("converted", Path("out.flac")))  # must not raise
        # A broken transcript is swallowed and surfaced as TRANSCRIBE_FAIL with the
        # offending output path and error text, never re-raised into conversion.
        printed = out.getvalue().strip()
        self.assertTrue(printed.startswith("TRANSCRIBE_FAIL\tout.flac\t"))
        self.assertIn("boom", printed)

    def test_transcribe_model_flag_parsed(self) -> None:
        args = media_shrinker.parse_args(
            [tempfile.gettempdir(), "--transcribe", "--transcribe-model", "tiny"]
        )
        self.assertEqual(args.transcribe_model, "tiny")


if __name__ == "__main__":
    unittest.main()
