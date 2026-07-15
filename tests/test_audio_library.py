"""Tests for the Python GPU orchestration and Rust backend boundary."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import audio_library
from audio_library import (
    AudioLibrary,
    GpuTranscriber,
    GpuTranscriptionUnavailableError,
    RustBackend,
    TranscriptionConfig,
    audio_duration_seconds,
    atomic_json_write,
    ensure_staging_capacity,
    is_icloud_dataless,
    mutation,
    normalize_segment,
    quarantine_path,
    rebuild_manifest_summary,
    remove_staged_file,
    sanitize_component,
    standard_filename,
    trusted_transcript_text,
    transcript_description,
    unique_audio_records,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
TMK_HASH = "c" * 64


def _record(path: str, sha256: str, **updates):
    record = {
        "path": path,
        "kind": "audio",
        "extension": "wav",
        "size_bytes": 10,
        "sha256": sha256,
        "recorded_at": "2024-01-02T03:04:00+09:00",
        "time_source": "compact_filename",
        "location": "양평동4가 24-1",
        "tmk_path": None,
        "tmk_marker_count": None,
        "tmk_last_marker_seconds": None,
        "error": None,
    }
    record.update(updates)
    return record


def _manifest(root: Path):
    return {
        "schema_version": 1,
        "root": str(root),
        "files": [
            _record("canonical.wav", HASH_A, tmk_path="canonical.tmk"),
            _record("copies/duplicate.wav", HASH_A, tmk_path="copies/duplicate.tmk"),
            _record(
                "second.wav",
                HASH_B,
                location=None,
                recorded_at="2024-02-03T04:05:00+09:00",
            ),
            {
                "path": "canonical.tmk",
                "kind": "tmk",
                "extension": "tmk",
                "size_bytes": 20,
                "sha256": TMK_HASH,
            },
            {
                "path": "copies/duplicate.tmk",
                "kind": "tmk",
                "extension": "tmk",
                "size_bytes": 20,
                "sha256": TMK_HASH,
            },
        ],
        "duplicate_groups": [
            {
                "sha256": HASH_A,
                "size_bytes": 10,
                "canonical_path": "canonical.wav",
                "duplicate_paths": ["copies/duplicate.wav"],
                "earliest_recorded_at": "2023-12-31T23:59:00+09:00",
            }
        ],
    }


class NamingTests(unittest.TestCase):
    def test_audio_duration_fast_and_fallback_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(audio_duration_seconds(root / "missing.wav"))
            wav_path = root / "short.wav"
            with wave.open(str(wav_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(b"\0\0" * 1_600)
            self.assertAlmostEqual(audio_duration_seconds(wav_path), 0.1)

            invalid_wav = root / "invalid.wav"
            invalid_wav.write_bytes(b"invalid")
            with patch("audio_library.shutil.which", return_value=None):
                self.assertIsNone(audio_duration_seconds(invalid_wav))

            media_path = root / "clip.m4a"
            media_path.write_bytes(b"media")
            completed = subprocess.CompletedProcess([], 0, stdout="1.25\n", stderr="")
            with (
                patch("audio_library.shutil.which", return_value="/usr/bin/ffprobe"),
                patch("audio_library.subprocess.run", return_value=completed),
            ):
                self.assertEqual(audio_duration_seconds(media_path), 1.25)
            with (
                patch("audio_library.shutil.which", return_value="/usr/bin/ffprobe"),
                patch(
                    "audio_library.subprocess.run", side_effect=OSError("probe failed")
                ),
            ):
                self.assertIsNone(audio_duration_seconds(media_path))

    def test_segment_and_description_normalization(self) -> None:
        self.assertEqual(
            normalize_segment({"start": "1", "end": 2, "text": " hello "}),
            {"start": 1.0, "end": 2.0, "text": "hello"},
        )
        transcript = {
            "segments": [
                {"text": "어 그러니까 프로젝트 예산 검토를 시작하겠습니다."},
                {"text": "짧음"},
            ]
        }
        self.assertIn("프로젝트-예산-검토", transcript_description(transcript))
        self.assertEqual(transcript_description({"text": ""}), "무음-또는-전사불명")
        low = normalize_segment(
            {
                "start": 0,
                "end": 0.08,
                "text": "감사합니다.",
                "words": [{"probability": 0.177}],
            }
        )
        self.assertTrue(low["low_confidence"])
        self.assertEqual(trusted_transcript_text([low]), "")
        self.assertEqual(
            transcript_description({"text": "", "segments": [low]}),
            "무음-또는-전사불명",
        )

    def test_sanitize_and_standard_filename(self) -> None:
        self.assertEqual(sanitize_component(" a / b ::: ", limit=20), "a-b")
        self.assertEqual(sanitize_component("///", limit=20), "미상")
        name = standard_filename(
            _record("a.WAV", HASH_A),
            {"segments": [{"text": "프로젝트 일정 검토 회의"}]},
            "2024-01-02T03:04:05+09:00",
        )
        self.assertEqual(
            name,
            "2024-01-02_03-04-05__양평동4가-24-1__프로젝트-일정-검토-회의__sha256-aaaaaaaaaaaa.wav",
        )
        with patch(
            "audio_library.STANDARD_NAME_RE", Mock(match=Mock(return_value=None))
        ):
            with self.assertRaisesRegex(ValueError, "does not satisfy standard"):
                standard_filename(
                    _record("a.wav", HASH_A),
                    {"text": "회의", "segments": []},
                    "2024-01-02T03:04:05+09:00",
                )

    def test_helpers_are_deterministic(self) -> None:
        self.assertEqual(
            quarantine_path(HASH_A, "copies/a.wav"),
            f".codec-carver/quarantine/exact-duplicates/{HASH_A}/copies/a.wav",
        )
        self.assertEqual(
            mutation("rename", "a", "b", HASH_A),
            {"action": "rename", "source": "a", "destination": "b", "sha256": HASH_A},
        )


class RustBackendTests(unittest.TestCase):
    def test_inventory_and_apply_commands_decode_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "core"
            binary.write_bytes(b"")
            backend = RustBackend(binary)
            completed = subprocess.CompletedProcess(
                [], 0, stdout='{"ok": true}', stderr=""
            )
            with patch("audio_library.subprocess.run", return_value=completed) as run:
                self.assertEqual(
                    backend.inventory(
                        Path(tmp), Path(tmp) / "inventory.json", threads=3
                    ),
                    {"ok": True},
                )
                command = run.call_args.args[0]
                self.assertIn("--threads", command)
                self.assertFalse(run.call_args.kwargs["shell"])
                backend.apply(
                    Path(tmp) / "plan.json", Path(tmp) / "journal.json", execute=True
                )
                self.assertIn("--execute", run.call_args.args[0])
                backend.inspect(Path(tmp), "a.wav", timeout_seconds=12)
                self.assertEqual(run.call_args.kwargs["timeout"], 12)
                backend.stage(
                    Path(tmp), "a.wav", Path(tmp) / "stage", timeout_seconds=34
                )
                self.assertIn("--staging-dir", run.call_args.args[0])
                self.assertEqual(run.call_args.kwargs["timeout"], 34)

    def test_default_backend_and_optional_command_flags(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout='{"ok": true}', stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / "codec-carver-core"
            installed.write_bytes(b"")
            with (
                patch("audio_library.shutil.which", return_value=str(installed)),
                patch("audio_library.subprocess.run", return_value=completed) as run,
            ):
                backend = RustBackend()
                backend.inventory(Path("."), Path("inventory.json"))
                self.assertNotIn("--threads", run.call_args.args[0])
                backend.apply(Path("plan.json"), Path("journal.json"), execute=False)
                self.assertNotIn("--execute", run.call_args.args[0])

    def test_missing_backend_has_build_instruction(self) -> None:
        with (
            patch("audio_library.Path.is_file", return_value=False),
            patch("audio_library.shutil.which", return_value=None),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "cargo build"):
                RustBackend("missing")


class GpuTranscriberTests(unittest.TestCase):
    @staticmethod
    def _mlx_modules(result=None):
        core = types.ModuleType("mlx.core")
        core.gpu = object()
        core.set_default_device = Mock()
        package = types.ModuleType("mlx")
        package.core = core
        whisper = types.ModuleType("mlx_whisper")
        whisper.transcribe = Mock(
            return_value=result
            or {
                "text": " 안녕하세요 ",
                "language": "ko",
                "segments": [{"start": 0, "end": 1, "text": " 안녕하세요 "}],
            }
        )
        return package, core, whisper

    def test_mlx_auto_selects_gpu_and_transcribes(self) -> None:
        package, core, whisper = self._mlx_modules()
        with (
            patch.dict(
                sys.modules, {"mlx": package, "mlx.core": core, "mlx_whisper": whisper}
            ),
            patch("audio_library.platform.system", return_value="Darwin"),
            patch("audio_library.platform.machine", return_value="arm64"),
            patch("audio_library.audio_duration_seconds", return_value=1.0),
        ):
            transcriber = GpuTranscriber()
            result = transcriber.transcribe(Path("clip.wav"))
        core.set_default_device.assert_called_once_with(core.gpu)
        self.assertEqual(result["accelerator"], "mlx")
        self.assertEqual(result["text"], "안녕하세요")
        self.assertEqual(result["segments"][0]["text"], "안녕하세요")
        self.assertFalse(
            whisper.transcribe.call_args.kwargs["condition_on_previous_text"]
        )
        self.assertEqual(whisper.transcribe.call_args.kwargs["temperature"], 0.0)

    def test_too_short_audio_skips_model_inference(self) -> None:
        package, _, whisper = self._mlx_modules()
        with (
            patch.dict(
                sys.modules,
                {"mlx": package, "mlx.core": package.core, "mlx_whisper": whisper},
            ),
            patch("audio_library.audio_duration_seconds", return_value=0.1),
        ):
            result = GpuTranscriber(TranscriptionConfig(accelerator="mlx")).transcribe(
                Path("short.wav")
            )
        self.assertEqual(result["text"], "")
        self.assertEqual(result["quality_flags"], ["too_short_for_reliable_speech"])
        whisper.transcribe.assert_not_called()

    def test_cuda_model_is_persistent_and_transcribes(self) -> None:
        calls = {}

        class Model:
            def __init__(self, model, **kwargs):
                calls["init"] = (model, kwargs)

            def transcribe(self, path, **kwargs):
                calls["transcribe"] = (path, kwargs)
                segment = types.SimpleNamespace(
                    start=0,
                    end=1,
                    text=" hello ",
                    words=[types.SimpleNamespace(probability=0.9)],
                )
                empty_segment = types.SimpleNamespace(
                    start=1, end=2, text="", words=None
                )
                return [segment, empty_segment], types.SimpleNamespace(language="en")

        module = types.ModuleType("faster_whisper")
        module.WhisperModel = Model
        with patch.dict(sys.modules, {"faster_whisper": module}):
            transcriber = GpuTranscriber(
                TranscriptionConfig(accelerator="cuda", language=None)
            )
            result = transcriber.transcribe(Path("clip.wav"))
        self.assertEqual(
            calls["init"][1], {"device": "cuda", "compute_type": "float16"}
        )
        self.assertTrue(calls["transcribe"][1]["vad_filter"])
        self.assertFalse(calls["transcribe"][1]["condition_on_previous_text"])
        self.assertEqual(calls["transcribe"][1]["beam_size"], 1)
        self.assertEqual(calls["transcribe"][1]["best_of"], 1)
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["segments"][0]["word_probability"], 0.9)

    def test_invalid_and_missing_gpu_runtimes_are_explicit(self) -> None:
        with self.assertRaises(ValueError):
            GpuTranscriber(TranscriptionConfig(accelerator="cpu"))
        with patch.dict(
            sys.modules, {"mlx": None, "mlx.core": None, "mlx_whisper": None}
        ):
            with self.assertRaises(GpuTranscriptionUnavailableError):
                GpuTranscriber(TranscriptionConfig(accelerator="mlx"))
        with patch.dict(sys.modules, {"faster_whisper": None}):
            with self.assertRaises(GpuTranscriptionUnavailableError):
                GpuTranscriber(TranscriptionConfig(accelerator="cuda"))

    def test_cuda_initialization_failure_is_gpu_error(self) -> None:
        module = types.ModuleType("faster_whisper")
        module.WhisperModel = Mock(side_effect=RuntimeError("no CUDA"))
        with patch.dict(sys.modules, {"faster_whisper": module}):
            with self.assertRaises(GpuTranscriptionUnavailableError):
                GpuTranscriber(TranscriptionConfig(accelerator="cuda"))


class AudioLibraryTests(unittest.TestCase):
    def test_inventory_apply_and_missing_inventory(self) -> None:
        backend = Mock()
        backend.inventory.return_value = {"ok": True}
        backend.apply.return_value = {"executed": False}
        with tempfile.TemporaryDirectory() as tmp:
            library = AudioLibrary(tmp, backend)
            self.assertEqual(library.inventory(threads=2), {"ok": True})
            backend.inventory.assert_called_once()
            with self.assertRaises(FileNotFoundError):
                library.plan()
            self.assertEqual(library.apply(), {"executed": False})

    def test_unique_records_choose_duplicate_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = unique_audio_records(_manifest(Path(tmp)))
        self.assertEqual(
            [record["path"] for record in records], ["canonical.wav", "second.wav"]
        )

    def test_plan_quarantines_duplicates_and_renames_tmk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            manifest = _manifest(root)
            manifest["files"].append(_record("second-copy.wav", HASH_B))
            manifest["duplicate_groups"].append(
                {
                    "sha256": HASH_B,
                    "size_bytes": 10,
                    "canonical_path": "second.wav",
                    "duplicate_paths": ["second-copy.wav"],
                    "earliest_recorded_at": "2024-02-03T04:05:00+09:00",
                }
            )
            atomic_json_write(state / "inventory.json", manifest)
            for sha, text in ((HASH_A, "예산 검토 회의"), (HASH_B, "개발 일정 공유")):
                atomic_json_write(
                    state / "transcripts" / f"{sha}.json",
                    {"text": text, "segments": [{"text": text}]},
                )
            plan = AudioLibrary(root, Mock()).plan()
            actions = [(item["action"], item["source"]) for item in plan["operations"]]
            self.assertIn(("quarantine", "copies/duplicate.wav"), actions)
            self.assertIn(("quarantine", "copies/duplicate.tmk"), actions)
            self.assertIn(("rename", "canonical.wav"), actions)
            self.assertIn(("rename", "canonical.tmk"), actions)
            self.assertTrue((state / "mutation-plan.json").is_file())

    def test_plan_requires_transcripts_unless_override_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic_json_write(
                root / ".codec-carver" / "inventory.json", _manifest(root)
            )
            library = AudioLibrary(root, Mock())
            with self.assertRaisesRegex(ValueError, "transcripts are missing"):
                library.plan()
            plan = library.plan(allow_missing_transcripts=True)
            self.assertTrue(plan["operations"])

    def test_plan_rejects_unknown_time_and_skips_standard_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            unknown = _record("unknown.wav", HASH_A, recorded_at=None)
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": [unknown],
                    "duplicate_groups": [],
                },
            )
            with self.assertRaisesRegex(ValueError, "recording time is unknown"):
                AudioLibrary(root, Mock()).plan(allow_missing_transcripts=True)

            transcript = {"text": "전사대기", "segments": []}
            standard = standard_filename(
                _record("source.wav", HASH_A),
                transcript,
                "2024-01-02T03:04:00+09:00",
            )
            tmk = str(Path(standard).with_suffix(".tmk"))
            record = _record(standard, HASH_A, tmk_path=tmk)
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": [
                        record,
                        {
                            "path": tmk,
                            "kind": "tmk",
                            "extension": "tmk",
                            "sha256": TMK_HASH,
                        },
                    ],
                    "duplicate_groups": [],
                },
            )
            plan = AudioLibrary(root, Mock()).plan(allow_missing_transcripts=True)
            self.assertEqual(plan["operations"], [])

    def test_transcribe_writes_sidecars_and_isolates_bad_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            manifest = _manifest(root)
            atomic_json_write(state / "inventory.json", manifest)
            (root / "canonical.wav").write_bytes(b"one")
            (root / "second.wav").write_bytes(b"two")
            fake = Mock()
            fake.accelerator = "mlx"
            fake.model = "model"
            fake.transcribe.side_effect = [
                {"text": "성공", "segments": [], "language": "ko"},
                RuntimeError("corrupt"),
            ]
            progress = Mock()
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, Mock()).transcribe(progress=progress)
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(summary["failed"], 1)
            self.assertTrue((state / "transcripts" / f"{HASH_A}.json").is_file())
            self.assertEqual(progress.call_count, 2)

    def test_transcribe_honors_cache_and_max_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            atomic_json_write(state / "inventory.json", _manifest(root))
            atomic_json_write(
                state / "transcripts" / f"{HASH_A}.json", {"text": "cached"}
            )
            fake = Mock(accelerator="mlx", model="model")
            progress = Mock()
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, Mock()).transcribe(
                    max_files=1, progress=progress
                )
            self.assertEqual(summary["cached"], 1)
            progress.assert_called_once()
            fake.transcribe.assert_not_called()

            (state / "transcripts" / f"{HASH_A}.json").unlink()
            fake.transcribe.return_value = {
                "text": "성공",
                "segments": [],
                "language": "ko",
            }
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, Mock()).transcribe(max_files=1)
            self.assertEqual(summary["completed"], 1)

            fake.reset_mock()
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, Mock()).transcribe(max_files=1)
            self.assertEqual(summary["cached"], 1)
            fake.transcribe.assert_not_called()

    def test_stream_transcribe_inspects_tmk_and_audio_then_evicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            manifest = _manifest(root)
            manifest["files"] = manifest["files"][:1] + manifest["files"][3:4]
            manifest["files"][0].update(
                {"sha256": None, "materialized": False, "error": "dataless"}
            )
            manifest["files"][1].update(
                {"sha256": None, "materialized": False, "error": "dataless"}
            )
            manifest["duplicate_groups"] = []
            atomic_json_write(state / "inventory.json", manifest)
            backend = Mock()
            library = AudioLibrary(root, backend)
            backend.stage.side_effect = [
                {
                    "record": {
                        **manifest["files"][1],
                        "sha256": TMK_HASH,
                        "materialized": False,
                        "tmk_marker_count": 2,
                        "tmk_last_marker_seconds": 600.0,
                        "error": None,
                    },
                    "staged_path": str(library.staging_dir / f"{TMK_HASH}.tmk"),
                },
                {
                    "record": {
                        **manifest["files"][0],
                        "sha256": HASH_A,
                        "materialized": False,
                        "error": None,
                    },
                    "staged_path": str(library.staging_dir / f"{HASH_A}.wav"),
                },
            ]
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "회의",
                "segments": [],
                "language": "ko",
            }
            progress = Mock()
            with (
                patch("audio_library.GpuTranscriber", return_value=fake),
                patch("audio_library.is_icloud_dataless", return_value=True),
                patch("audio_library.evict_icloud_file") as evict,
            ):
                summary = library.stream_transcribe(progress=progress)
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(backend.stage.call_count, 2)
            backend.inspect.assert_not_called()
            evict.assert_not_called()
            progress.assert_called_once()
            checkpoint = json.loads(
                (state / "inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["files"][0]["sha256"], HASH_A)
            self.assertFalse(checkpoint["files"][0]["materialized"])

    def test_stream_transcribe_uses_cached_hash_and_isolates_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            manifest = _manifest(root)
            manifest["files"] = [manifest["files"][2]]
            manifest["files"][0]["materialized"] = True
            manifest["duplicate_groups"] = []
            atomic_json_write(state / "inventory.json", manifest)
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.side_effect = RuntimeError("bad audio")
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, Mock()).stream_transcribe(
                    max_files=1, evict_after=False
                )
            self.assertEqual(summary["failed"], 1)
            self.assertIn("bad audio", summary["failures"][0]["error"])

            atomic_json_write(
                state / "transcripts" / f"{HASH_B}.json", {"text": "cached"}
            )
            fake.reset_mock()
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, Mock()).stream_transcribe(
                    max_files=1, evict_after=False
                )
            self.assertEqual(summary["cached"], 1)
            fake.transcribe.assert_not_called()

    def test_stream_transcribe_selects_explicit_paths_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            manifest = _manifest(root)
            manifest["files"] = [manifest["files"][2]]
            manifest["files"][0]["materialized"] = True
            manifest["duplicate_groups"] = []
            atomic_json_write(state / "inventory.json", manifest)
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "선택 회의",
                "segments": [],
                "language": "ko",
            }
            library = AudioLibrary(root, Mock())
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = library.stream_transcribe(
                    relative_paths=["second.wav"], evict_after=False
                )
            self.assertEqual(summary["recordings_selected"], 1)
            with self.assertRaisesRegex(ValueError, "absent from inventory"):
                library.stream_transcribe(relative_paths=["missing.wav"])

    def test_stream_transcribe_inspects_local_unhashed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            audio = _record(
                "local.wav",
                "",
                materialized=True,
                tmk_path="local.tmk",
            )
            tmk = {
                "path": "local.tmk",
                "kind": "tmk",
                "extension": "tmk",
                "size_bytes": 5,
                "sha256": None,
                "materialized": True,
            }
            (root / "local.wav").write_bytes(b"audio")
            (root / "local.tmk").write_bytes(b"marks")
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": [audio, tmk],
                    "duplicate_groups": [],
                },
            )
            backend = Mock()
            backend.inspect.side_effect = [
                {**tmk, "sha256": TMK_HASH, "tmk_marker_count": 1},
                {**audio, "sha256": HASH_A},
            ]
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "로컬 회의",
                "segments": [],
                "language": "ko",
            }
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, backend).stream_transcribe()
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(backend.inspect.call_count, 2)
            backend.stage.assert_not_called()

    def test_stream_transcribe_rejects_hash_drift_and_evicts_materialized_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            record = _record("remote.wav", HASH_A, materialized=False)
            manifest = {
                "schema_version": 1,
                "root": str(root),
                "files": [record],
                "duplicate_groups": [],
            }
            library = AudioLibrary(root, Mock())
            staged = library.staging_dir / f"{HASH_B}.wav"
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(b"drift")
            library.backend.stage.return_value = {
                "record": {**record, "sha256": HASH_B},
                "staged_path": str(staged),
            }
            atomic_json_write(state / "inventory.json", manifest)
            with (
                patch(
                    "audio_library.GpuTranscriber",
                    return_value=Mock(accelerator="mlx", model="model"),
                ),
                patch("audio_library.is_icloud_dataless", return_value=True),
            ):
                summary = library.stream_transcribe()
            self.assertEqual(summary["failed"], 1)
            self.assertIn("SHA-256 changed", summary["failures"][0]["error"])
            self.assertFalse(staged.exists())

            staged = library.staging_dir / f"{HASH_A}.wav"
            staged.write_bytes(b"audio")
            library.backend.stage.return_value = {
                "record": {**record, "sha256": HASH_A},
                "staged_path": str(staged),
            }
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "원격 회의",
                "segments": [],
                "language": "ko",
            }
            atomic_json_write(state / "inventory.json", manifest)
            with (
                patch("audio_library.GpuTranscriber", return_value=fake),
                patch("audio_library.is_icloud_dataless", return_value=False),
                patch("audio_library.evict_icloud_file") as evict,
            ):
                summary = library.stream_transcribe()
            self.assertEqual(summary["completed"], 1)
            evict.assert_called_once_with(root.resolve() / "remote.wav")
            self.assertFalse(staged.exists())

    def test_rebuild_manifest_summary_finds_exact_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            manifest["files"].append(_record("pending.wav", "", materialized=True))
            for record in manifest["files"]:
                record.setdefault("materialized", True)
                record.setdefault("error", None)
            rebuild_manifest_summary(manifest)
        self.assertEqual(len(manifest["duplicate_groups"]), 1)
        self.assertEqual(
            manifest["duplicate_groups"][0]["canonical_path"], "canonical.wav"
        )
        self.assertEqual(manifest["dataless_file_count"], 0)


class CliTests(unittest.TestCase):
    def test_progress_and_main_inventory(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            audio_library.progress_line(1, 2, "a.wav", "completed")
        self.assertIn("1/2", output.getvalue())
        backend = Mock()
        library = Mock()
        library.inventory.return_value = {"ok": True}
        with (
            patch("audio_library.RustBackend", return_value=backend),
            patch("audio_library.AudioLibrary", return_value=library),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                audio_library.main([".", "inventory", "--threads", "2"]), 0
            )
        library.inventory.assert_called_once_with(threads=2)

    def test_main_routes_transcribe_stream_plan_and_apply(self) -> None:
        library = Mock()
        library.transcribe.return_value = {"mode": "transcribe"}
        library.stream_transcribe.return_value = {"mode": "stream"}
        library.plan.return_value = {"mode": "plan"}
        library.apply.return_value = {"mode": "apply"}
        commands = [
            [".", "transcribe", "--max-files", "1", "--word-timestamps"],
            [
                ".",
                "stream-transcribe",
                "--max-files",
                "1",
                "--path",
                "a.wav",
                "--keep-local",
            ],
            [".", "plan", "--allow-missing-transcripts"],
            [".", "apply", "--execute"],
        ]
        with (
            patch("audio_library.RustBackend"),
            patch("audio_library.AudioLibrary", return_value=library),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for command in commands:
                self.assertEqual(audio_library.main(command), 0)
        library.transcribe.assert_called_once()
        self.assertTrue(library.transcribe.call_args.args[0].word_timestamps)
        library.stream_transcribe.assert_called_once()
        self.assertFalse(library.stream_transcribe.call_args.kwargs["evict_after"])
        self.assertEqual(
            library.stream_transcribe.call_args.kwargs["relative_paths"], ["a.wav"]
        )
        library.plan.assert_called_once_with(allow_missing_transcripts=True)
        library.apply.assert_called_once_with(execute=True)

    def test_evict_icloud_file_platform_and_tool_checks(self) -> None:
        with (
            patch("audio_library.platform.system", return_value="Linux"),
            patch("audio_library.subprocess.run") as run,
        ):
            audio_library.evict_icloud_file(Path("a.wav"))
            run.assert_not_called()
        with (
            patch("audio_library.platform.system", return_value="Darwin"),
            patch("audio_library.shutil.which", return_value=None),
        ):
            with self.assertRaises(FileNotFoundError):
                audio_library.evict_icloud_file(Path("a.wav"))
        with (
            patch("audio_library.platform.system", return_value="Darwin"),
            patch("audio_library.shutil.which", return_value="/usr/bin/brctl"),
            patch("audio_library.subprocess.run") as run,
        ):
            audio_library.evict_icloud_file(Path("a.wav"))
            self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/brctl", "evict"])

    def test_icloud_dataless_detection(self) -> None:
        path = Mock()
        with patch("audio_library.platform.system", return_value="Linux"):
            self.assertFalse(is_icloud_dataless(path))
            path.stat.assert_not_called()
        with patch("audio_library.platform.system", return_value="Darwin"):
            path.stat.return_value = Mock(st_flags=audio_library.MACOS_SF_DATALESS)
            self.assertTrue(is_icloud_dataless(path))
            path.stat.return_value = Mock(st_flags=0)
            self.assertFalse(is_icloud_dataless(path))
            path.stat.side_effect = FileNotFoundError
            self.assertFalse(is_icloud_dataless(path))

    def test_staging_capacity_and_safe_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "stage"
            with patch(
                "audio_library.shutil.disk_usage",
                return_value=types.SimpleNamespace(free=1024 * 1024 * 1024),
            ):
                ensure_staging_capacity(staging, 1)
            with patch(
                "audio_library.shutil.disk_usage",
                return_value=types.SimpleNamespace(free=1),
            ):
                with self.assertRaisesRegex(OSError, "insufficient staging space"):
                    ensure_staging_capacity(staging, 1)
            staged = staging / "recording.wav"
            staged.write_bytes(b"audio")
            remove_staged_file(staging, staged)
            self.assertFalse(staged.exists())
            with self.assertRaisesRegex(ValueError, "escaped scratch root"):
                remove_staged_file(staging, Path(tmp) / "outside.wav")


if __name__ == "__main__":
    unittest.main()
