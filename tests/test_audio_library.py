"""Tests for the Python GPU orchestration and Rust backend boundary."""

from __future__ import annotations

import contextlib
import hashlib
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
    restore_inventory_evidence,
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
        self.assertEqual(
            transcript_description(
                {
                    "text": "다음 영상에서 만나요.",
                    "duration_seconds": 14.2,
                    "segments": [{"text": "다음 영상에서 만나요."}],
                }
            ),
            "무음-또는-전사불명",
        )
        self.assertEqual(
            transcript_description(
                {
                    "text": "감사합니다.",
                    "duration_seconds": 0.8,
                    "segments": [{"text": "감사합니다."}],
                }
            ),
            "무음-또는-전사불명",
        )
        self.assertEqual(
            transcript_description(
                {
                    "text": "반복 문장입니다. 반복 문장입니다. 실제 안건 검토입니다.",
                    "duration_seconds": 60,
                    "segments": [
                        {"text": "반복 문장입니다."},
                        {"text": "반복 문장입니다."},
                        {"text": "실제 안건 검토입니다."},
                    ],
                }
            ),
            "실제-안건-검토입니다",
        )
        self.assertEqual(
            transcript_description(
                {
                    "duration_seconds": 400,
                    "segments": [
                        {"text": "이 시각 세계였습니다."},
                        {"text": "이곳은 이곳에서 전달한 곳입니다."},
                        {"text": "다음 영상에서 만나요."},
                        {"text": "서울시장"},
                    ],
                }
            ),
            "무음-또는-전사불명",
        )

        long_segments = [{"text": f"도입 잡음 문장 {index}"} for index in range(12)] + [
            {"text": "VOC 경영 프로세스를 검토합니다."},
            {"text": "VOC 데이터 수집과 경영 과제를 확인합니다."},
            {"text": "시스템에서 VOC 프로세스를 관리합니다."},
        ]
        long_description = transcript_description(
            {"duration_seconds": 1800, "segments": long_segments}
        )
        self.assertIn("VOC", long_description)
        self.assertIn("프로세스", long_description)
        self.assertNotIn("도입-잡음", long_description)
        self.assertEqual(
            audio_library.description_terms("그래서 VOC를 1234 아아"),
            [("VOC", "voc")],
        )
        repeated_description = audio_library.topical_transcript_description(
            [
                "VOC VOC 프로세스 추가",
                "VOC 프로세스 다른",
                "반복 구절",
                "반복 구절",
                "고유 항목",
            ],
            limit=48,
        )
        self.assertIn("VOC-프로세스", repeated_description)
        unique_segments = [{"text": f"개별항목{index}"} for index in range(13)]
        self.assertIsNone(
            audio_library.topical_transcript_description(
                [segment["text"] for segment in unique_segments], limit=48
            )
        )
        self.assertEqual(
            transcript_description({"segments": unique_segments}), "개별항목0"
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

    def test_existing_standard_filename_validation(self) -> None:
        recorded_at = "2024-01-02T03:04:05+09:00"
        transcript = {"segments": [{"text": "프로젝트 일정 검토 회의"}]}
        record = _record("source.wav", HASH_A)
        name = standard_filename(record, transcript, recorded_at)
        standardized = _record(name, HASH_A)
        self.assertTrue(
            audio_library.is_existing_standard_filename(standardized, recorded_at)
        )
        self.assertFalse(
            audio_library.is_existing_standard_filename(
                _record("not-standard.wav", HASH_A), recorded_at
            )
        )
        self.assertFalse(
            audio_library.is_existing_standard_filename(
                _record(str(Path(name).with_suffix(".mp3")), HASH_A), recorded_at
            )
        )
        self.assertFalse(
            audio_library.is_existing_standard_filename(
                standardized, "2024-01-02T03:04:06+09:00"
            )
        )
        self.assertFalse(
            audio_library.is_existing_standard_filename(
                _record(name, HASH_B), recorded_at
            )
        )
        self.assertFalse(
            audio_library.is_existing_standard_filename(
                _record(name, HASH_A, location="다른 장소"), recorded_at
            )
        )
        no_location = _record("source.wav", HASH_A, location=None)
        no_location_name = standard_filename(no_location, transcript, recorded_at)
        self.assertTrue(
            audio_library.is_existing_standard_filename(
                _record(no_location_name, HASH_A, location=None), recorded_at
            )
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
                backend.evict(Path(tmp), "a.wav", timeout_seconds=8)
                self.assertEqual(run.call_args.args[0][1], "evict")
                self.assertEqual(run.call_args.kwargs["timeout"], 8)
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    backend.evict(Path(tmp), "a.wav", timeout_seconds=0)

    def test_stage_command_decodes_success_and_monitors_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "core"
            binary.write_bytes(b"")
            staging = root / "stage"
            staging.mkdir()
            backend = RustBackend(binary)
            process = Mock(pid=71, returncode=0)
            process.communicate.return_value = ('{"ok": true}', "")
            with patch("audio_library.subprocess.Popen", return_value=process) as popen:
                self.assertEqual(
                    backend.stage(root, "a.wav", staging, timeout_seconds=34),
                    {"ok": True},
                )
            self.assertIn("--staging-dir", popen.call_args.args[0])
            self.assertFalse(popen.call_args.kwargs["shell"])

            partial = staging / ".codec-carver-72-1.wav.partial"
            partial.write_bytes(b"progress")
            process = Mock(pid=72, returncode=0)
            process.communicate.side_effect = [
                subprocess.TimeoutExpired(["core", "stage"], 1),
                ('{"ok": true}', ""),
            ]
            with (
                patch("audio_library.subprocess.Popen", return_value=process),
                patch(
                    "audio_library.time.monotonic",
                    side_effect=[0.0, 0.0, 0.5, 0.5],
                ),
            ):
                result = RustBackend._run_stage_json(
                    ["core", "stage"], staging, stall_timeout_seconds=1
                )
            self.assertEqual(result, {"ok": True})

    def test_stage_retries_incomplete_icloud_reads_only_while_progressing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "core"
            binary.write_bytes(b"")
            staging = root / "stage"
            staging.mkdir()
            backend = RustBackend(binary)
            empty = subprocess.CalledProcessError(
                1,
                ["core", "stage"],
                stderr="STAGE_SOURCE_NOT_READY copied 0 of 5 bytes",
            )
            partial = subprocess.CalledProcessError(
                1,
                ["core", "stage"],
                stderr="STAGE_SOURCE_NOT_READY copied 3 of 5 bytes",
            )
            with (
                patch.object(
                    RustBackend,
                    "_run_stage_json",
                    side_effect=[empty, partial, {"ok": True}],
                ) as run,
                patch("audio_library.time.sleep") as sleep,
            ):
                self.assertEqual(
                    backend.stage(root, "a.wav", staging, timeout_seconds=34),
                    {"ok": True},
                )
            self.assertEqual(run.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

            unrelated = subprocess.CalledProcessError(
                2, ["core", "stage"], stderr="permission denied"
            )
            with (
                patch.object(RustBackend, "_run_stage_json", side_effect=unrelated),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                backend.stage(root, "a.wav", staging, timeout_seconds=1)

            with (
                patch.object(RustBackend, "_run_stage_json", side_effect=empty),
                patch("audio_library.time.monotonic", side_effect=[0.0, 0.0, 2.0]),
                self.assertRaises(subprocess.TimeoutExpired) as raised,
            ):
                backend.stage(root, "a.wav", staging, timeout_seconds=1)
            self.assertIn("STAGE_SOURCE_NOT_READY", raised.exception.stderr)

            with self.assertRaisesRegex(ValueError, "must be positive"):
                backend.stage(root, "a.wav", staging, timeout_seconds=0)

    def test_stage_stall_cleanup_errors_and_invalid_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            partial = staging / ".codec-carver-73-1.wav.partial"
            process = Mock(pid=73, returncode=None)
            process.communicate.side_effect = [
                subprocess.TimeoutExpired(["core", "stage"], 1),
                ("", "stalled"),
            ]
            process.kill.side_effect = lambda: partial.write_bytes(b"")
            with (
                patch("audio_library.subprocess.Popen", return_value=process),
                patch("audio_library.time.monotonic", side_effect=[0.0, 0.0, 2.0]),
                self.assertRaises(subprocess.TimeoutExpired) as raised,
            ):
                RustBackend._run_stage_json(
                    ["core", "stage"], staging, stall_timeout_seconds=1
                )
            process.kill.assert_called_once()
            self.assertEqual(raised.exception.stderr, "stalled")
            self.assertFalse(partial.exists())

            process = Mock(pid=74, returncode=2)
            process.communicate.return_value = ("", "bad stage")
            with (
                patch("audio_library.subprocess.Popen", return_value=process),
                self.assertRaises(subprocess.CalledProcessError) as raised,
            ):
                RustBackend._run_stage_json(
                    ["core", "stage"], staging, stall_timeout_seconds=1
                )
            self.assertEqual(raised.exception.stderr, "bad stage")
            with self.assertRaisesRegex(ValueError, "must be positive"):
                RustBackend._run_stage_json(
                    ["core", "stage"], staging, stall_timeout_seconds=0
                )

    def test_stage_interrupt_kills_child_and_cleans_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            partial = staging / ".codec-carver-75-1.wav.partial"
            partial.write_bytes(b"partial")
            process = Mock(pid=75, returncode=None)
            process.poll.return_value = None
            process.communicate.side_effect = [KeyboardInterrupt, ("", "interrupted")]
            with (
                patch("audio_library.subprocess.Popen", return_value=process),
                self.assertRaises(KeyboardInterrupt),
            ):
                RustBackend._run_stage_json(
                    ["core", "stage"], staging, stall_timeout_seconds=1
                )
            process.kill.assert_called_once()
            self.assertFalse(partial.exists())

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
        backend.inventory.side_effect = [
            {"ok": True},
            {
                "schema_version": 1,
                "root": "unused",
                "files": [],
                "duplicate_groups": [],
            },
            {
                "schema_version": 1,
                "root": "unused",
                "files": [],
                "duplicate_groups": [],
            },
        ]
        backend.apply.return_value = {"executed": False}
        with tempfile.TemporaryDirectory() as tmp:
            library = AudioLibrary(tmp, backend)
            with self.assertRaises(FileNotFoundError):
                library.plan()
            self.assertEqual(library.inventory(), {"ok": True})
            atomic_json_write(
                library.state_dir / "inventory.json",
                {"schema_version": 1, "files": []},
            )
            self.assertEqual(library.inventory(threads=2)["files"], [])
            self.assertEqual(backend.inventory.call_count, 2)
            self.assertTrue((library.state_dir / "inventory.json").is_file())
            self.assertEqual(
                len(list((library.state_dir / "inventory-history").glob("*.json"))),
                1,
            )
            current_bytes = (library.state_dir / "inventory.json").read_bytes()
            history_path = (
                library.state_dir
                / "inventory-history"
                / f"{hashlib.sha256(current_bytes).hexdigest()}.json"
            )
            atomic_json_write(history_path, json.loads(current_bytes))
            self.assertEqual(library.inventory()["files"], [])
            self.assertEqual(backend.inventory.call_count, 3)
            self.assertEqual(library.apply(), {"executed": False})

    def test_unique_records_choose_duplicate_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = unique_audio_records(_manifest(Path(tmp)))
        self.assertEqual(
            [record["path"] for record in records], ["canonical.wav", "second.wav"]
        )

    def test_inventory_restores_sha_and_reconciles_transcript_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            standard = "2024-01-02_03-04-05__회의__sha256-aaaaaaaaaaaa.wav"
            manifest = {
                "schema_version": 1,
                "root": str(root),
                "files": [
                    _record(standard, "", materialized=False, location=None),
                    _record("journaled.wav", "", materialized=False),
                    _record("native.wav", TMK_HASH, materialized=True),
                    _record("previous.wav", "", materialized=False),
                    _record("changed.wav", "", materialized=False),
                ],
                "duplicate_groups": [],
            }
            atomic_json_write(
                state / "transcripts" / f"{HASH_A}.json",
                {"text": "회의", "segments": []},
            )
            atomic_json_write(
                state / "mutation-journal.json",
                {"executed": False, "completed": []},
            )
            self.assertEqual(restore_inventory_evidence(manifest, state), 1)
            self.assertEqual(manifest["files"][0]["sha256"], HASH_A)
            transcript = json.loads(
                (state / "transcripts" / f"{HASH_A}.json").read_text()
            )
            self.assertEqual(transcript["source_path"], standard)

            previous_manifest = {
                "files": [
                    _record("previous.wav", HASH_B, materialized=True),
                    {
                        **_record("changed.wav", TMK_HASH, materialized=True),
                        "size_bytes": 999,
                    },
                ]
            }
            self.assertEqual(
                restore_inventory_evidence(
                    manifest,
                    state,
                    previous_manifest=previous_manifest,
                ),
                1,
            )
            self.assertEqual(
                manifest["files"][3]["sha256_source"], "previous_inventory"
            )
            self.assertFalse(manifest["files"][4].get("sha256"))

            atomic_json_write(
                state / "mutation-journal.json",
                {
                    "executed": True,
                    "completed": [
                        {"destination": "journaled.wav", "sha256": HASH_B},
                        {"destination": "ignored.wav", "sha256": None},
                    ],
                },
            )
            atomic_json_write(
                state / "transcripts" / f"{HASH_B}.json",
                {"text": "다른 회의", "segments": []},
            )
            self.assertEqual(restore_inventory_evidence(manifest, state), 1)
            self.assertEqual(manifest["files"][1]["sha256"], HASH_B)
            self.assertEqual(manifest["files"][1]["sha256_source"], "mutation_journal")

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
            deferred = library.plan(defer_unready=True)
            self.assertEqual(
                deferred["deferred_paths"], ["canonical.wav", "second.wav"]
            )
            self.assertNotIn(
                "전사대기",
                "\n".join(item["destination"] for item in deferred["operations"]),
            )
            with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                library.plan(
                    allow_missing_transcripts=True,
                    defer_unready=True,
                )

    def test_plan_requires_sha_or_defers_unhashed_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = _manifest(root)
            manifest["files"][0]["sha256"] = None
            atomic_json_write(root / ".codec-carver" / "inventory.json", manifest)
            library = AudioLibrary(root, Mock())
            with self.assertRaisesRegex(ValueError, "SHA-256 is unresolved"):
                library.plan(allow_missing_transcripts=True)
            plan = library.plan(defer_unready=True)
            self.assertIn("canonical.wav", plan["deferred_paths"])

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

            transcript = {"text": "원래 제목", "segments": [{"text": "원래 제목"}]}
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
            atomic_json_write(
                state / "transcripts" / f"{HASH_A}.json",
                {
                    "text": "나중에 개선된 완전히 다른 대표 주제",
                    "segments": [{"text": "나중에 개선된 완전히 다른 대표 주제"}],
                },
            )
            plan = AudioLibrary(root, Mock()).plan()
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

    def test_hydrate_tmk_metadata_parallel_checkpoint_and_empty_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            records = [
                {
                    "path": "remote.tmk",
                    "kind": "tmk",
                    "extension": "tmk",
                    "size_bytes": 20,
                    "sha256": None,
                    "materialized": False,
                    "tmk_marker_count": None,
                },
                {
                    "path": "local.tmk",
                    "kind": "tmk",
                    "extension": "tmk",
                    "size_bytes": 20,
                    "sha256": None,
                    "materialized": True,
                    "tmk_marker_count": None,
                },
                {
                    "path": "failed.tmk",
                    "kind": "tmk",
                    "extension": "tmk",
                    "size_bytes": 20,
                    "sha256": None,
                    "materialized": False,
                    "tmk_marker_count": None,
                },
            ]
            audio_records = [
                _record(
                    "remote.wav",
                    HASH_A,
                    materialized=False,
                    tmk_path="remote.tmk",
                ),
                _record(
                    "local.wav",
                    HASH_B,
                    materialized=True,
                    tmk_path="local.tmk",
                ),
            ]
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": records + audio_records,
                    "duplicate_groups": [],
                },
            )
            atomic_json_write(
                state / "transcripts" / f"{HASH_A}.json",
                {"text": "existing transcript"},
            )
            backend = Mock()
            library = AudioLibrary(root, backend)
            staged = library.staging_dir / f"{TMK_HASH}.tmk"
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(b"markers")
            backend.stage.side_effect = [
                {
                    "record": {
                        **records[0],
                        "sha256": TMK_HASH,
                        "tmk_marker_count": 2,
                        "tmk_last_marker_seconds": 600.0,
                    },
                    "staged_path": str(staged),
                },
                RuntimeError("iCloud timeout"),
            ]
            backend.inspect.return_value = {
                **records[1],
                "sha256": HASH_B,
                "tmk_marker_count": 1,
                "tmk_last_marker_seconds": 30.0,
            }
            progress = Mock()
            with patch(
                "audio_library.is_icloud_dataless",
                side_effect=[True, False, False],
            ):
                summary = library.hydrate_tmk_metadata(
                    workers=1,
                    inspect_timeout_seconds=12,
                    progress=progress,
                )
            self.assertEqual(summary["completed"], 2)
            self.assertEqual(summary["failed"], 1)
            self.assertIn("iCloud timeout", summary["failures"][0]["error"])
            self.assertFalse(staged.exists())
            self.assertEqual(progress.call_count, 3)
            checkpoint = json.loads(
                (state / "inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["files"][0]["sha256"], TMK_HASH)
            self.assertEqual(checkpoint["files"][1]["tmk_marker_count"], 1)
            self.assertIn("iCloud timeout", checkpoint["files"][2]["error"])
            self.assertEqual(checkpoint["files"][3]["tmk_marker_count"], 2)
            self.assertEqual(checkpoint["files"][4]["tmk_marker_count"], 1)
            existing_transcript = json.loads(
                (state / "transcripts" / f"{HASH_A}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(existing_transcript["tmk_last_marker_seconds"], 600.0)
            with self.assertRaisesRegex(ValueError, "at least 1"):
                library.hydrate_tmk_metadata(workers=0)

            resumed_staged = library.staging_dir / f"{HASH_A}.tmk"
            resumed_staged.write_bytes(b"")
            backend.stage.side_effect = None
            backend.stage.return_value = {
                "record": {
                    **checkpoint["files"][2],
                    "sha256": HASH_A,
                    "tmk_marker_count": 0,
                    "tmk_last_marker_seconds": None,
                },
                "staged_path": str(resumed_staged),
            }
            with patch("audio_library.is_icloud_dataless", return_value=True):
                resumed = library.hydrate_tmk_metadata(workers=2)
            self.assertEqual(resumed["selected"], 1)
            self.assertEqual(resumed["completed"], 1)
            empty = library.hydrate_tmk_metadata(workers=2)
            self.assertEqual(empty["selected"], 0)

    def test_stream_transcribe_reuses_pre_hydrated_dataless_tmk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            audio = _record("remote.wav", "", materialized=False, tmk_path="remote.tmk")
            tmk = {
                "path": "remote.tmk",
                "kind": "tmk",
                "extension": "tmk",
                "size_bytes": 20,
                "sha256": TMK_HASH,
                "materialized": False,
                "tmk_marker_count": 3,
                "tmk_last_marker_seconds": 90.0,
                "error": None,
            }
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
            library = AudioLibrary(root, backend)
            staged = library.staging_dir / f"{HASH_A}.wav"
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(b"audio")
            backend.stage.return_value = {
                "record": {**audio, "sha256": HASH_A, "error": None},
                "staged_path": str(staged),
            }
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "사전 수집 TMK",
                "segments": [],
                "language": "ko",
            }
            with (
                patch("audio_library.GpuTranscriber", return_value=fake),
                patch("audio_library.is_icloud_dataless", return_value=True),
            ):
                summary = library.stream_transcribe(evict_after=False)
            self.assertEqual(summary["completed"], 1)
            backend.stage.assert_called_once()
            transcript = json.loads(
                (state / "transcripts" / f"{HASH_A}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(transcript["tmk_marker_count"], 3)
            self.assertEqual(transcript["tmk_last_marker_seconds"], 90.0)

    def test_stream_transcribe_prioritizes_runtime_local_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            remote = _record(
                "remote.wav",
                HASH_A,
                materialized=True,
                recorded_at="2024-01-01T00:00:00+09:00",
            )
            local = _record(
                "local.wav",
                HASH_B,
                materialized=False,
                recorded_at="2024-01-02T00:00:00+09:00",
            )
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": [remote, local],
                    "duplicate_groups": [],
                },
            )
            atomic_json_write(
                state / "transcripts" / f"{HASH_B}.json",
                {"text": "cached local"},
            )
            backend = Mock()
            fake = Mock(accelerator="mlx", model="model")
            with (
                patch("audio_library.GpuTranscriber", return_value=fake),
                patch(
                    "audio_library.is_icloud_dataless",
                    side_effect=lambda path: path.name == "remote.wav",
                ),
            ):
                summary = AudioLibrary(root, backend).stream_transcribe(max_files=1)
            self.assertEqual(summary["cached"], 1)
            backend.stage.assert_not_called()
            fake.transcribe.assert_not_called()

    def test_stream_transcribe_skips_unresolved_tmk_and_streams_audio(self) -> None:
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
            backend.stage.return_value = {
                "record": {
                    **manifest["files"][0],
                    "sha256": HASH_A,
                    "materialized": False,
                    "error": None,
                },
                "staged_path": str(library.staging_dir / f"{HASH_A}.wav"),
            }
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
            ):
                summary = library.stream_transcribe(progress=progress)
            self.assertEqual(summary["completed"], 1)
            backend.stage.assert_called_once()
            backend.inspect.assert_not_called()
            backend.evict.assert_not_called()
            progress.assert_called_once()
            checkpoint = json.loads(
                (state / "inventory.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["files"][0]["sha256"], HASH_A)
            self.assertFalse(checkpoint["files"][0]["materialized"])
            self.assertEqual(checkpoint["files"][0]["tmk_error"], "dataless")
            transcript = json.loads(
                (state / "transcripts" / f"{HASH_A}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(transcript["tmk_error"], "dataless")

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
            backend.inspect.return_value = {**audio, "sha256": HASH_A}
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "로컬 회의",
                "segments": [],
                "language": "ko",
            }
            with patch("audio_library.GpuTranscriber", return_value=fake):
                summary = AudioLibrary(root, backend).stream_transcribe()
            self.assertEqual(summary["completed"], 1)
            backend.inspect.assert_called_once()
            transcript = json.loads(
                (state / "transcripts" / f"{HASH_A}.json").read_text(encoding="utf-8")
            )
            self.assertIn("run hydrate-tmk", transcript["tmk_error"])
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
                patch(
                    "audio_library.is_icloud_dataless",
                    side_effect=[True, True, False],
                ),
            ):
                library.backend.evict.return_value = {"evicted": True}
                summary = library.stream_transcribe()
            self.assertEqual(summary["completed"], 1)
            library.backend.evict.assert_called_once_with(root.resolve(), "remote.wav")
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
            audio_library.tmk_progress_line(2, 3, "a.tmk", "completed")
        self.assertIn("1/2", output.getvalue())
        self.assertIn("TMK\t2/3", output.getvalue())
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
        library.hydrate_tmk_metadata.return_value = {"mode": "tmk"}
        library.stream_transcribe.return_value = {"mode": "stream"}
        library.plan.return_value = {"mode": "plan"}
        library.apply.return_value = {"mode": "apply"}
        commands = [
            [".", "hydrate-tmk", "--workers", "2", "--inspect-timeout-seconds", "3"],
            [".", "transcribe", "--max-files", "1", "--word-timestamps"],
            [
                ".",
                "stream-transcribe",
                "--max-files",
                "1",
                "--path",
                "a.wav",
                "--stage-stall-timeout-seconds",
                "7",
                "--keep-local",
            ],
            [".", "plan", "--defer-unready"],
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
        library.hydrate_tmk_metadata.assert_called_once_with(
            workers=2,
            inspect_timeout_seconds=3.0,
            progress=audio_library.tmk_progress_line,
        )
        self.assertTrue(library.transcribe.call_args.args[0].word_timestamps)
        library.stream_transcribe.assert_called_once()
        self.assertFalse(library.stream_transcribe.call_args.kwargs["evict_after"])
        self.assertEqual(
            library.stream_transcribe.call_args.kwargs["relative_paths"], ["a.wav"]
        )
        self.assertEqual(
            library.stream_transcribe.call_args.kwargs["stage_stall_timeout_seconds"],
            7.0,
        )
        library.plan.assert_called_once_with(
            allow_missing_transcripts=False,
            defer_unready=True,
        )
        library.apply.assert_called_once_with(execute=True)

    def test_main_returns_failure_when_batch_contains_failed_files(self) -> None:
        library = Mock()
        library.stream_transcribe.return_value = {
            "completed": 0,
            "failed": 1,
            "failures": [{"path": "remote.wav", "error": "download timed out"}],
        }
        with (
            patch("audio_library.RustBackend"),
            patch("audio_library.AudioLibrary", return_value=library),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(audio_library.main([".", "stream-transcribe"]), 1)

    def test_stream_transcribe_keeps_checkpoint_when_eviction_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".codec-carver"
            record = _record("remote.wav", HASH_A, materialized=False)
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": [record],
                    "duplicate_groups": [],
                },
            )
            library = AudioLibrary(root, Mock())
            staged = library.staging_dir / f"{HASH_A}.wav"
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(b"audio")
            library.backend.stage.return_value = {
                "record": {**record, "sha256": HASH_A, "materialized": False},
                "staged_path": str(staged),
            }
            library.backend.evict.side_effect = subprocess.TimeoutExpired(
                ["codec-carver-core", "evict"], 30
            )
            fake = Mock(accelerator="mlx", model="model")
            fake.transcribe.return_value = {
                "text": "보존된 회의",
                "segments": [],
                "language": "ko",
            }
            with (
                patch("audio_library.GpuTranscriber", return_value=fake),
                patch(
                    "audio_library.is_icloud_dataless",
                    side_effect=[True, True, False, False],
                ),
            ):
                summary = library.stream_transcribe()
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["eviction_failed"], 1)
            self.assertIn("timed out", summary["eviction_failures"][0]["error"])
            self.assertTrue((state / "transcripts" / f"{HASH_A}.json").is_file())
            checkpoint = json.loads((state / "inventory.json").read_text())
            self.assertTrue(checkpoint["files"][0]["materialized"])
            self.assertFalse(staged.exists())

            (state / "transcripts" / f"{HASH_A}.json").unlink()
            (state / "transcripts" / f"{HASH_A}.txt").unlink()
            atomic_json_write(
                state / "inventory.json",
                {
                    "schema_version": 1,
                    "root": str(root),
                    "files": [record],
                    "duplicate_groups": [],
                },
            )
            staged.write_bytes(b"audio")
            library.backend.evict.side_effect = None
            library.backend.evict.return_value = {"evicted": False}
            with (
                patch("audio_library.GpuTranscriber", return_value=fake),
                patch(
                    "audio_library.is_icloud_dataless",
                    side_effect=[True, True, False, False],
                ),
            ):
                unconfirmed = library.stream_transcribe()
            self.assertEqual(unconfirmed["completed"], 1)
            self.assertEqual(unconfirmed["failed"], 0)
            self.assertEqual(unconfirmed["eviction_failed"], 1)
            self.assertIn(
                "without confirmation", unconfirmed["eviction_failures"][0]["error"]
            )
            self.assertFalse(staged.exists())

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
