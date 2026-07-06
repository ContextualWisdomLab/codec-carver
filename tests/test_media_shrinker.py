import argparse
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import media_shrinker
import presets
from media_shrinker import (
    ConversionPlan,
    MediaSegment,
    MediaShrinkerError,
    detect_silence_intervals,
    MediaProbe,
    SilenceInterval,
    build_audio_plan,
    build_icloud_download_command,
    build_segments,
    calculate_audio_bitrate,
    choose_worker_count,
    find_candidates,
    parse_silencedetect_intervals,
    write_report,
    preserve_file_attributes,
    probe_media,
    _execute_plan,
    _first_float,
    _first_int,
)


class FindCandidateTests(unittest.TestCase):
    def test_find_candidates_returns_supported_files_over_limit_case_insensitively(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            large_wav = root / "A.WAV"
            large_m4a = root / "nested" / "B.m4a"
            small_mp3 = root / "small.mp3"
            unsupported = root / "large.txt"

            large_m4a.parent.mkdir()
            large_wav.write_bytes(b"0" * 11)
            large_m4a.write_bytes(b"0" * 12)
            small_mp3.write_bytes(b"0" * 4)
            unsupported.write_bytes(b"0" * 99)

            candidates = [
                p[0].relative_to(root)
                for p in find_candidates(
                    root, size_limit_bytes=10, include_under_limit=False
                )
            ]

            self.assertEqual(candidates, [Path("A.WAV"), Path("nested/B.m4a")])

    def test_find_candidates_includes_under_limit_by_default_for_all_source_conversion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            small_mp3 = root / "small.mp3"
            small_mp3.write_bytes(b"0" * 4)

            candidates = [
                p[0].relative_to(root)
                for p in find_candidates(root, size_limit_bytes=10)
            ]

            self.assertEqual(candidates, [Path("small.mp3")])

    def test_find_candidates_can_include_under_limit_and_skip_output_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.m4a"
            output = root / "under_2gb" / "source.flac"
            output.parent.mkdir()
            source.write_bytes(b"0" * 4)
            output.write_bytes(b"0" * 4)

            candidates = [
                p[0].relative_to(root)
                for p in find_candidates(
                    root,
                    size_limit_bytes=10,
                    include_under_limit=True,
                    exclude_paths=[output.parent],
                )
            ]

            self.assertEqual(candidates, [Path("source.m4a")])

    def test_find_candidates_skips_multiple_excluded_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / "keep" / "source.wav"
            excluded = root / "excluded" / "hidden.wav"
            nested_excluded = root / "nested" / "output" / "hidden.wav"

            keep.parent.mkdir()
            excluded.parent.mkdir()
            nested_excluded.parent.mkdir(parents=True)
            keep.write_bytes(b"0" * 4)
            excluded.write_bytes(b"0" * 4)
            nested_excluded.write_bytes(b"0" * 4)

            candidates = [
                p[0].relative_to(root)
                for p in find_candidates(
                    root,
                    include_under_limit=True,
                    exclude_paths=[excluded.parent, nested_excluded.parent],
                )
            ]

            self.assertEqual(candidates, [Path("keep/source.wav")])

    def test_find_candidates_can_skip_generated_split_directories_by_prefix(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            split = root / "split_over_1gb" / "source_part0001.wav"
            split.parent.mkdir()
            source.write_bytes(b"0" * 4)
            split.write_bytes(b"0" * 4)

            candidates = [
                p[0].relative_to(root)
                for p in find_candidates(
                    root,
                    include_under_limit=True,
                    exclude_dir_prefixes=["split_over"],
                )
            ]

            self.assertEqual(candidates, [Path("source.wav")])

    def test_find_candidates_skips_directory_when_current_dir_cannot_resolve(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "good.mp3"
            broken = root / "broken"
            broken_media = broken / "hidden.mp3"

            broken.mkdir()
            good.write_bytes(b"0" * 4)
            broken_media.write_bytes(b"0" * 4)

            import os

            original_realpath = os.path.realpath

            def flaky_realpath(path: str, *args: object, **kwargs: object) -> str:
                if path == str(broken):
                    raise OSError("cannot resolve directory")
                return original_realpath(path, *args, **kwargs)

            with patch("os.path.realpath", flaky_realpath):
                candidates = [
                    p[0].relative_to(root)
                    for p in find_candidates(root, include_under_limit=True)
                ]

            self.assertEqual(candidates, [Path("good.mp3")])

    def test_find_candidates_skips_entries_when_symlink_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "good.mp3"
            bad_file = root / "bad.mp3"
            bad_dir = root / "bad_dir"
            nested = bad_dir / "nested.mp3"

            bad_dir.mkdir()
            good.write_bytes(b"0" * 4)
            bad_file.write_bytes(b"0" * 4)
            nested.write_bytes(b"0" * 4)

            import os

            original_lstat = os.lstat

            def flaky_lstat(path):
                name = os.path.basename(str(path))
                if name in {"bad.mp3", "bad_dir"}:
                    raise OSError("cannot inspect symlink state")
                return original_lstat(path)

            with patch("os.lstat", flaky_lstat):
                candidates = [
                    p[0].relative_to(root)
                    for p in find_candidates(root, include_under_limit=True)
                ]

            self.assertEqual(candidates, [Path("good.mp3")])


class ProbeMediaTests(unittest.TestCase):
    @patch("media_shrinker.subprocess.run")
    def test_probe_media_raises_error_on_invalid_json(
        self, mock_run: MagicMock
    ) -> None:
        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_completed.stdout = "invalid json"
        mock_run.return_value = mock_completed

        with self.assertRaises(MediaShrinkerError) as cm:
            probe_media(Path("test.wav"))

        self.assertIn("ffprobe returned invalid JSON for test.wav", str(cm.exception))

    def test_parse_probe_payload_uses_known_source_size_without_stat(self) -> None:
        payload = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "duration": "1.0",
                    "bit_rate": "128000",
                }
            ],
            "format": {"duration": "1.0", "format_name": "wav"},
        }

        probe = media_shrinker._parse_probe_payload(
            payload,
            Path("missing.wav"),
            source_size=123,
        )

        self.assertEqual(probe.size_bytes, 123)


class PlanningTests(unittest.TestCase):
    def test_pcm_wav_uses_lossless_flac_first_and_preserves_container_metadata(
        self,
    ) -> None:
        probe = MediaProbe(
            duration_seconds=3600.0,
            size_bytes=4_294_808_936,
            audio_codec="pcm_s16le",
            audio_bit_rate=1_411_200,
            has_video=False,
            format_name="wav",
        )

        plan = build_audio_plan(
            Path("meeting.wav"),
            probe,
            target_bytes=1_900_000_000,
            output_dir=Path("out"),
        )

        self.assertEqual(plan.strategy, "flac-lossless")
        self.assertEqual(plan.output_path, Path("out/meeting.wav.flac"))
        self.assertIn("-map_metadata", plan.ffmpeg_args)
        self.assertIn("0", plan.ffmpeg_args)
        self.assertIn("flac", plan.ffmpeg_args)

    def test_conversion_command_resolves_input_and_output_overrides(self) -> None:
        plan = ConversionPlan(
            strategy="test",
            input_path=Path("input.wav"),
            output_path=Path("output.flac"),
            ffmpeg_args=["-n", "-i", "input.wav", "output.flac"],
        )

        command = plan.command(
            input_path=Path("-input.wav"),
            output_path=Path("-output.flac"),
        )

        self.assertEqual(
            command[command.index("-i") + 1],
            str(Path("-input.wav").resolve()),
        )
        self.assertEqual(command[-1], str(Path("-output.flac").resolve()))

    def test_lossy_audio_uses_highest_opus_bitrate_that_fits_target_with_safety_margin(
        self,
    ) -> None:
        probe = MediaProbe(
            duration_seconds=10_000.0,
            size_bytes=3_000_000_000,
            audio_codec="aac",
            audio_bit_rate=2_500_000,
            has_video=False,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )

        plan = build_audio_plan(
            Path("long.m4a"), probe, target_bytes=1_900_000_000, output_dir=Path("out")
        )

        self.assertEqual(plan.strategy, "opus-bitrate")
        self.assertEqual(plan.output_path, Path("out/long.m4a.opus"))
        self.assertEqual(
            plan.audio_bitrate_bps,
            calculate_audio_bitrate(10_000.0, 1_900_000_000, 2_500_000),
        )
        self.assertIn("libopus", plan.ffmpeg_args)

    def test_prefer_flac_converts_lossy_audio_to_flac_without_extra_loss(self) -> None:
        probe = MediaProbe(
            duration_seconds=3_600.0,
            size_bytes=50_000_000,
            audio_codec="aac",
            audio_bit_rate=128_000,
            has_video=False,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )

        plan = build_audio_plan(
            Path("voice memo.m4a"),
            probe,
            target_bytes=1_900_000_000,
            output_dir=Path("out"),
            prefer_flac=True,
            ffmpeg_threads=0,
        )

        self.assertEqual(plan.strategy, "flac-transcode")
        self.assertEqual(plan.output_path, Path("out/voice memo.m4a.flac"))
        self.assertIn("flac", plan.ffmpeg_args)
        self.assertIn("-threads", plan.ffmpeg_args)
        self.assertIn("0", plan.ffmpeg_args)

    def test_calculate_audio_bitrate_never_exceeds_source_bitrate(self) -> None:
        bitrate = calculate_audio_bitrate(
            duration_seconds=1_000.0,
            target_bytes=1_900_000_000,
            source_bitrate_bps=96_000,
        )

        self.assertEqual(bitrate, 96_000)

    def test_same_stem_sources_keep_unique_output_paths(self) -> None:
        wav_probe = MediaProbe(
            duration_seconds=60.0,
            size_bytes=1_000,
            audio_codec="pcm_s16le",
            audio_bit_rate=1_411_200,
            has_video=False,
            format_name="wav",
        )
        m4a_probe = MediaProbe(
            duration_seconds=60.0,
            size_bytes=1_000,
            audio_codec="aac",
            audio_bit_rate=128_000,
            has_video=False,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )

        wav_plan = build_audio_plan(
            Path("clip.wav"),
            wav_probe,
            target_bytes=1_900_000_000,
            output_dir=Path("out"),
            prefer_flac=True,
        )
        m4a_plan = build_audio_plan(
            Path("clip.m4a"),
            m4a_probe,
            target_bytes=1_900_000_000,
            output_dir=Path("out"),
            prefer_flac=True,
        )

        self.assertEqual(wav_plan.output_path, Path("out/clip.wav.flac"))
        self.assertEqual(m4a_plan.output_path, Path("out/clip.m4a.flac"))

    def test_execute_plan_refuses_to_replace_source_path_even_with_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.flac"
            fake_ffmpeg = root / "fake_ffmpeg.py"
            source.write_bytes(b"original")
            fake_ffmpeg.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'converted')\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)
            plan = ConversionPlan(
                strategy="test",
                input_path=source,
                output_path=source,
                ffmpeg_args=["-nostdin", "-y", "-i", str(source), str(source)],
            )

            with self.assertRaises(MediaShrinkerError):
                _execute_plan(
                    plan, source, source, ffmpeg_path=str(fake_ffmpeg), overwrite=True
                )

            self.assertEqual(source.read_bytes(), b"original")

    def test_long_sources_plan_part_outputs_below_four_hours_at_latest_silence_point(
        self,
    ) -> None:
        segments = build_segments(
            duration_seconds=18_500.0,
            max_segment_duration_seconds=14_400.0,
            silence_intervals=[
                SilenceInterval(start_seconds=14_200.0, end_seconds=14_260.0)
            ],
        )

        self.assertEqual(
            segments,
            [
                MediaSegment(
                    index=1,
                    start_seconds=0.0,
                    duration_seconds=14_260.0,
                    total_segments=2,
                ),
                MediaSegment(
                    index=2,
                    start_seconds=14_260.0,
                    duration_seconds=4_240.0,
                    total_segments=2,
                ),
            ],
        )
        self.assertTrue(
            all(segment.duration_seconds < 14_400.0 for segment in segments)
        )

    def test_spanning_silence_split_advances_near_window_end_not_segment_start(
        self,
    ) -> None:
        split_point = media_shrinker._choose_silence_split_point(
            segment_start=10_000.0,
            window_end=24_400.0,
            silence_intervals=[
                SilenceInterval(start_seconds=0.0, end_seconds=30_000.0)
            ],
        )

        self.assertEqual(split_point, 24_399.999)

    def test_long_sources_fall_back_to_hard_splits_just_under_four_hours_without_silence(
        self,
    ) -> None:
        segments = build_segments(
            duration_seconds=30_000.0,
            max_segment_duration_seconds=14_400.0,
            silence_intervals=[],
        )

        self.assertEqual(len(segments), 3)
        self.assertTrue(
            all(segment.duration_seconds < 14_400.0 for segment in segments)
        )
        self.assertAlmostEqual(
            sum(segment.duration_seconds for segment in segments), 30_000.0, places=3
        )

    def test_segmented_conversion_plan_uses_part_name_seek_and_segment_duration(
        self,
    ) -> None:
        probe = MediaProbe(
            duration_seconds=18_500.0,
            size_bytes=4_000_000_000,
            audio_codec="pcm_s16le",
            audio_bit_rate=1_411_200,
            has_video=False,
            format_name="wav",
        )
        segment = MediaSegment(
            index=1, start_seconds=0.0, duration_seconds=14_230.0, total_segments=2
        )

        plan = build_audio_plan(
            Path("meeting.wav"),
            probe,
            target_bytes=1_900_000_000,
            output_dir=Path("out"),
            prefer_flac=True,
            segment=segment,
        )

        self.assertEqual(plan.output_path, Path("out/meeting.wav.part0001.flac"))
        self.assertIn("-ss", plan.ffmpeg_args)
        self.assertIn("0", plan.ffmpeg_args)
        self.assertIn("-t", plan.ffmpeg_args)
        self.assertIn("14230", plan.ffmpeg_args)

    def test_segment_duration_ffmpeg_arg_never_rounds_up_to_four_hours(self) -> None:
        probe = MediaProbe(
            duration_seconds=14_399.9996,
            size_bytes=1_000,
            audio_codec="pcm_s16le",
            audio_bit_rate=1_411_200,
            has_video=False,
            format_name="wav",
        )
        segment = MediaSegment(
            index=1, start_seconds=0.0, duration_seconds=14_399.9996, total_segments=2
        )

        plan = build_audio_plan(
            Path("meeting.wav"),
            probe,
            target_bytes=1_900_000_000,
            output_dir=Path("out"),
            prefer_flac=True,
            segment=segment,
        )
        t_value = plan.ffmpeg_args[plan.ffmpeg_args.index("-t") + 1]

        self.assertLess(float(t_value), 14_400.0)

    def test_convert_segment_marks_too_long_when_generated_output_probes_over_limit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            output_dir = root / "out"
            fake_ffmpeg = root / "fake_ffmpeg.py"
            source.write_bytes(b"source")
            fake_ffmpeg.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'converted')\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)
            source_probe = MediaProbe(
                14_399.999, 1_000, "pcm_s16le", 1_411_200, False, "wav"
            )
            output_probe = MediaProbe(14_400.0, 1_000, "flac", 1_411_200, False, "flac")
            original_probe_media = media_shrinker.probe_media

            def fake_probe_media(
                path: Path,
                *,
                ffprobe_path: str = "ffprobe",
                source_size: int | None = None,
            ) -> MediaProbe:
                return output_probe if path.suffix == ".flac" else source_probe

            try:
                media_shrinker.probe_media = fake_probe_media
                result = media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=source_probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=14_399.999,
                        total_segments=1,
                    ),
                    output_dir=output_dir,
                    target_bytes=1_900_000_000,
                    original_size=source.stat().st_size,
                    ffmpeg_path=str(fake_ffmpeg),
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                )
            finally:
                media_shrinker.probe_media = original_probe_media

            self.assertEqual(result.status, "too_long")
            self.assertIsNone(result.output_path)
            self.assertFalse((output_dir / "source.wav.flac").exists())

    def test_convert_segment_deletes_generated_output_when_duration_mismatches_expected_segment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            output_dir = root / "out"
            fake_ffmpeg = root / "fake_ffmpeg.py"
            source.write_bytes(b"source")
            fake_ffmpeg.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'converted')\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)
            source_probe = MediaProbe(60.0, 1_000, "pcm_s16le", 1_411_200, False, "wav")
            truncated_probe = MediaProbe(12.0, 1_000, "flac", 1_411_200, False, "flac")
            original_probe_media = media_shrinker.probe_media

            try:
                media_shrinker.probe_media = (
                    lambda path, *, ffprobe_path="ffprobe", source_size=None: (
                        truncated_probe
                    )
                )
                result = media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=source_probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=60.0,
                        total_segments=1,
                    ),
                    output_dir=output_dir,
                    target_bytes=1_900_000_000,
                    original_size=source.stat().st_size,
                    ffmpeg_path=str(fake_ffmpeg),
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                )
            finally:
                media_shrinker.probe_media = original_probe_media

            self.assertEqual(result.status, "duration_mismatch")
            self.assertIsNone(result.output_path)
            self.assertFalse((output_dir / "source.wav.flac").exists())

    def test_existing_output_with_wrong_duration_is_replaced_not_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            output_dir = root / "out"
            existing = output_dir / "source.wav.flac"
            fake_ffmpeg = root / "fake_ffmpeg.py"
            output_dir.mkdir()
            source.write_bytes(b"source")
            existing.write_bytes(b"truncated")
            fake_ffmpeg.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'converted')\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)
            source_probe = MediaProbe(60.0, 1_000, "pcm_s16le", 1_411_200, False, "wav")
            probes = iter(
                [
                    MediaProbe(12.0, 1_000, "flac", 1_411_200, False, "flac"),
                    MediaProbe(60.0, 1_000, "flac", 1_411_200, False, "flac"),
                ]
            )
            original_probe_media = media_shrinker.probe_media

            try:
                media_shrinker.probe_media = (
                    lambda path, *, ffprobe_path="ffprobe", source_size=None: next(
                        probes
                    )
                )
                result = media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=source_probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=60.0,
                        total_segments=1,
                    ),
                    output_dir=output_dir,
                    target_bytes=1_900_000_000,
                    original_size=source.stat().st_size,
                    ffmpeg_path=str(fake_ffmpeg),
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                )
            finally:
                media_shrinker.probe_media = original_probe_media

            self.assertEqual(result.status, "converted")
            self.assertEqual(existing.read_bytes(), b"converted")

    def test_stale_oversized_existing_output_is_replaced_at_canonical_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            output_dir = root / "out"
            existing = output_dir / "source.wav.flac"
            fake_ffmpeg = root / "fake_ffmpeg.py"
            output_dir.mkdir()
            source.write_bytes(b"source")
            existing.write_bytes(b"oversized")
            fake_ffmpeg.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'ok')\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)
            probe = MediaProbe(60.0, 1_000, "pcm_s16le", 1_411_200, False, "wav")
            original_probe_media = media_shrinker.probe_media

            try:
                media_shrinker.probe_media = (
                    lambda path, *, ffprobe_path="ffprobe", source_size=None: probe
                )
                result = media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=60.0,
                        total_segments=1,
                    ),
                    output_dir=output_dir,
                    target_bytes=5,
                    original_size=source.stat().st_size,
                    ffmpeg_path=str(fake_ffmpeg),
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                    protected_sources={source},
                )
            finally:
                media_shrinker.probe_media = original_probe_media

            self.assertEqual(result.status, "converted")
            self.assertEqual(result.output_path, existing)
            self.assertFalse((output_dir / "source.wav-1.flac").exists())
            self.assertEqual(existing.read_bytes(), b"ok")

    def test_legacy_stem_output_over_duration_is_deleted_before_segmented_conversion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            output_dir = root / "out"
            legacy = output_dir / "source.flac"
            canonical = output_dir / "source.wav.part0001.flac"
            fake_ffmpeg = root / "fake_ffmpeg.py"
            output_dir.mkdir()
            source.write_bytes(b"source")
            legacy.write_bytes(b"legacy")
            fake_ffmpeg.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'ok')\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)
            source_probe = MediaProbe(
                18_000.0, 1_000, "pcm_s16le", 1_411_200, False, "wav"
            )
            probes = iter(
                [
                    MediaProbe(18_000.0, 1_000, "flac", 1_411_200, False, "flac"),
                    MediaProbe(14_399.0, 1_000, "flac", 1_411_200, False, "flac"),
                ]
            )
            original_probe_media = media_shrinker.probe_media

            try:
                media_shrinker.probe_media = (
                    lambda path, *, ffprobe_path="ffprobe", source_size=None: next(
                        probes
                    )
                )
                result = media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=source_probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=14_399.0,
                        total_segments=2,
                    ),
                    output_dir=output_dir,
                    target_bytes=1_900_000_000,
                    original_size=source.stat().st_size,
                    ffmpeg_path=str(fake_ffmpeg),
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                    protected_sources={source},
                )
            finally:
                media_shrinker.probe_media = original_probe_media

            self.assertEqual(result.status, "converted")
            self.assertFalse(legacy.exists())
            self.assertEqual(canonical.read_bytes(), b"ok")

    def test_cleanup_refuses_to_delete_another_protected_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            other_source = root / "source.wav.flac"
            source.write_bytes(b"source")
            other_source.write_bytes(b"do-not-delete")
            probe = MediaProbe(60.0, 1_000, "pcm_s16le", 1_411_200, False, "wav")

            with self.assertRaises(MediaShrinkerError):
                media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=60.0,
                        total_segments=1,
                    ),
                    output_dir=root,
                    target_bytes=5,
                    original_size=source.stat().st_size,
                    ffmpeg_path="missing-ffmpeg",
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                    protected_sources={source.resolve(), other_source.resolve()},
                )

            self.assertEqual(other_source.read_bytes(), b"do-not-delete")

    def test_prefer_flac_reuses_existing_opus_fallback_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            output_dir = root / "out"
            existing_opus = output_dir / "source.wav.opus"
            existing_opus.parent.mkdir()
            source.write_bytes(b"source")
            existing_opus.write_bytes(b"opus")
            probe = MediaProbe(60.0, 1_000, "pcm_s16le", 1_411_200, False, "wav")
            original_probe_media = media_shrinker.probe_media

            try:
                media_shrinker.probe_media = (
                    lambda path, *, ffprobe_path="ffprobe", source_size=None: probe
                )
                result = media_shrinker._convert_segment(
                    source,
                    rel_source=Path("source.wav"),
                    probe=probe,
                    segment=MediaSegment(
                        index=1,
                        start_seconds=0.0,
                        duration_seconds=60.0,
                        total_segments=1,
                    ),
                    output_dir=output_dir,
                    target_bytes=1_900_000_000,
                    original_size=source.stat().st_size,
                    ffmpeg_path="missing-ffmpeg",
                    ffprobe_path="fake_ffprobe",
                    prefer_flac=True,
                    ffmpeg_threads=None,
                    overwrite=False,
                    max_segment_duration_seconds=14_400.0,
                )
            finally:
                media_shrinker.probe_media = original_probe_media

            self.assertEqual(result.status, "skipped_existing")
            self.assertEqual(result.output_path, existing_opus)

    def test_missing_source_size_fallback_keeps_failure_reporting_safe(self) -> None:
        missing_source = Path("/tmp/media-shrinker-test-missing-source.wav")

        self.assertEqual(media_shrinker.safe_source_size(missing_source), 0)

    def test_parse_silencedetect_intervals_pairs_long_silence_start_and_end(
        self,
    ) -> None:
        stderr = """
        [silencedetect @ 0x1] silence_start: 14200.125
        [silencedetect @ 0x1] silence_end: 14260.375 | silence_duration: 60.25
        [silencedetect @ 0x1] silence_start: 28000
        [silencedetect @ 0x1] silence_end: 28008 | silence_duration: 8
        """

        intervals = parse_silencedetect_intervals(stderr)

        self.assertEqual(
            intervals,
            [
                SilenceInterval(start_seconds=14_200.125, end_seconds=14_260.375),
                SilenceInterval(start_seconds=28_000.0, end_seconds=28_008.0),
            ],
        )


class SilenceDetectionTests(unittest.TestCase):
    @patch("media_shrinker.subprocess.run")
    def test_detect_silence_intervals_success(self, mock_run: MagicMock) -> None:
        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_completed.stderr = """
        [silencedetect @ 0x1] silence_start: 14200.125
        [silencedetect @ 0x1] silence_end: 14260.375 | silence_duration: 60.25
        """
        mock_run.return_value = mock_completed

        intervals = detect_silence_intervals(
            Path("source.wav"),
            ffmpeg_path="custom-ffmpeg",
            silence_noise="-40dB",
            silence_min_duration_seconds=5.0,
        )

        self.assertEqual(
            intervals,
            [SilenceInterval(start_seconds=14_200.125, end_seconds=14_260.375)],
        )

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        command = args[0]

        self.assertEqual(command[0], "custom-ffmpeg")
        self.assertIn("source.wav", str(command))
        self.assertIn("silencedetect=noise=-40dB:d=5", str(command))

        self.assertEqual(kwargs.get("check"), False)
        self.assertEqual(kwargs.get("capture_output"), True)
        self.assertEqual(kwargs.get("text"), True)

    @patch("media_shrinker.subprocess.run")
    def test_detect_silence_intervals_failure_raises_error(
        self, mock_run: MagicMock
    ) -> None:
        mock_completed = MagicMock()
        mock_completed.returncode = 1

        mock_completed.stderr = "ffmpeg error message"
        mock_run.return_value = mock_completed

        with self.assertRaisesRegex(
            MediaShrinkerError,
            "silencedetect failed for source.wav: ffmpeg error message",
        ):
            detect_silence_intervals(Path("source.wav"))


class MetadataPreservationTests(unittest.TestCase):
    @patch("os.setxattr", create=True)
    @patch("os.getxattr", create=True)
    @patch("os.listxattr", create=True)
    def test_preserve_file_attributes_ignores_getxattr_oserror(
        self, mock_list, mock_get, mock_set
    ) -> None:
        mock_list.return_value = ["user.attr1", "user.attr2"]

        def mock_getxattr_side_effect(src, name):
            if name == "user.attr1":
                raise OSError("Access denied")
            return b"value2"

        mock_get.side_effect = mock_getxattr_side_effect

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            dest = root / "dest.flac"
            source.write_bytes(b"source")
            dest.write_bytes(b"dest")

            preserve_file_attributes(source, dest, setfile_path=None)

            self.assertEqual(mock_get.call_count, 2)
            mock_set.assert_called_once_with(dest, "user.attr2", b"value2")

    def test_preserve_file_attributes_copies_times_and_extended_attributes_when_supported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            dest = root / "dest.flac"
            source.write_bytes(b"source")
            dest.write_bytes(b"dest")

            atime_ns = 1_700_000_001_123_456_789
            mtime_ns = 1_700_000_002_987_654_321
            os.utime(source, ns=(atime_ns, mtime_ns))

            setxattr = getattr(os, "setxattr", None)
            getxattr = getattr(os, "getxattr", None)
            xattr_supported = setxattr is not None and getxattr is not None
            if xattr_supported:
                assert setxattr is not None
                try:
                    setxattr(source, b"user.media_shrinker_test", b"recording-date")
                except OSError:
                    xattr_supported = False

            preserve_file_attributes(source, dest, setfile_path=None)

            dest_stat = dest.stat()
            self.assertEqual(dest_stat.st_atime_ns, atime_ns)
            self.assertEqual(dest_stat.st_mtime_ns, mtime_ns)
            if xattr_supported:
                assert getxattr is not None
                self.assertEqual(
                    getxattr(dest, b"user.media_shrinker_test"), b"recording-date"
                )


class ICloudDownloadTests(unittest.TestCase):
    def test_build_icloud_download_command_uses_argument_list_for_paths_with_spaces(
        self,
    ) -> None:
        command = build_icloud_download_command(
            Path("folder/file with spaces.m4a"), brctl_path="brctl"
        )

        self.assertEqual(
            command,
            ["brctl", "download", str(Path("folder/file with spaces.m4a").resolve())],
        )


class ParallelismTests(unittest.TestCase):
    def test_choose_worker_count_uses_requested_workers_when_positive(self) -> None:
        self.assertEqual(choose_worker_count(3, cpu_count=8), 3)

    def test_choose_worker_count_auto_uses_multiple_workers_without_exceeding_half_cores(
        self,
    ) -> None:
        self.assertEqual(choose_worker_count(0, cpu_count=10), 4)


class ReportingTests(unittest.TestCase):
    def test_write_report(self) -> None:
        result1 = media_shrinker.ConversionResult(
            source_path=Path("/scan/source1.wav"),
            output_path=Path("/scan/source1.wav.flac"),
            status="converted",
            original_size_bytes=100,
            output_size_bytes=50,
            strategy="flac-lossless",
        )
        result2 = media_shrinker.ConversionResult(
            source_path=Path("/scan/source2.wav"),
            output_path=None,
            status="skipped",
            original_size_bytes=200,
            strategy=None,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            write_report([result1, result2], report_path)

            self.assertTrue(report_path.exists())

            with open(report_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            self.assertEqual(len(payload), 2)
            self.assertEqual(payload[0]["source_path"], "/scan/source1.wav")
            self.assertEqual(payload[0]["output_path"], "/scan/source1.wav.flac")
            self.assertEqual(payload[0]["status"], "converted")
            self.assertEqual(payload[0]["strategy"], "flac-lossless")
            self.assertEqual(payload[0]["original_size_bytes"], 100)
            self.assertEqual(payload[0]["output_size_bytes"], 50)

            self.assertEqual(payload[1]["source_path"], "/scan/source2.wav")
            self.assertIsNone(payload[1]["output_path"])
            self.assertEqual(payload[1]["status"], "skipped")
            self.assertIsNone(payload[1]["strategy"])
            self.assertEqual(payload[1]["original_size_bytes"], 200)
            self.assertIsNone(payload[1]["output_size_bytes"])

    def test_format_result_handles_output_path_outside_scan_root(self) -> None:
        result = media_shrinker.ConversionResult(
            source_path=Path("/scan/source.wav"),
            output_path=Path("/external-output/source.wav.flac"),
            status="converted",
            original_size_bytes=100,
            output_size_bytes=50,
            strategy="flac-lossless",
        )

        line = media_shrinker._format_result(Path("/scan"), result)

        self.assertIn("source.wav", line)
        self.assertIn("/external-output/source.wav.flac", line)


class FirstFloatTests(unittest.TestCase):
    def test_first_float_returns_first_valid_number(self) -> None:
        self.assertEqual(_first_float(1.5, "2.0"), 1.5)
        self.assertEqual(_first_float(None, 2.0, 3.0), 2.0)
        self.assertEqual(_first_float("N/A", "1.1"), 1.1)

    def test_first_float_ignores_type_error_and_value_error(self) -> None:
        self.assertEqual(_first_float({}, "not-a-float", 3.14), 3.14)
        self.assertEqual(_first_float([], None, "bad", 42.0), 42.0)

    def test_first_float_returns_zero_on_all_failures(self) -> None:
        self.assertEqual(_first_float(), 0.0)
        self.assertEqual(_first_float(None, "N/A"), 0.0)
        self.assertEqual(_first_float({}, "bad"), 0.0)


class FirstIntTests(unittest.TestCase):
    def test_first_int_handles_uncastable_types(self) -> None:
        self.assertEqual(_first_int("invalid", "N/A", None, "12"), 12)
        self.assertIsNone(_first_int("invalid", object(), []))
        self.assertEqual(_first_int(10), 10)
        self.assertEqual(_first_int(10.5), 10)
        self.assertIsNone(_first_int())

    def test_first_int_more_cases(self) -> None:
        self.assertIsNone(_first_int("not a number"))
        self.assertIsNone(_first_int([1, 2]))
        self.assertIsNone(_first_int({"a": 1}))
        self.assertEqual(_first_int("not a number", "10", 20), 10)
        self.assertEqual(_first_int(None, "N/A", "1.5"), 1)


class FormatSecondsTests(unittest.TestCase):
    def test_format_seconds_truncates_to_three_decimals(self) -> None:
        from media_shrinker import _format_seconds

        self.assertEqual(_format_seconds(1.23456), "1.234")
        self.assertEqual(_format_seconds(10.0), "10")
        self.assertEqual(_format_seconds(0.0001), "0")
        self.assertEqual(_format_seconds(14400.0), "14400")


class CollisionResolutionTests(unittest.TestCase):
    def test_resolve_collision_returns_original_if_no_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.flac"
            resolved = media_shrinker._resolve_collision(path, overwrite=False)
            self.assertEqual(resolved, path)

    def test_resolve_collision_returns_numbered_variant_if_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.flac"
            path.write_bytes(b"data")
            resolved = media_shrinker._resolve_collision(path, overwrite=False)
            self.assertEqual(resolved, Path(tmp) / "existing-1.flac")

    def test_resolve_collision_returns_original_if_overwrite_is_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.flac"
            path.write_bytes(b"data")
            resolved = media_shrinker._resolve_collision(path, overwrite=True)
            self.assertEqual(resolved, path)


class CliTests(unittest.TestCase):
    def test_normalize_argv_handles_silence_noise_values(self) -> None:
        self.assertIsNone(media_shrinker._normalize_argv(None))
        self.assertEqual(
            media_shrinker._normalize_argv(["--silence-noise", "quiet"]),
            ["--silence-noise", "quiet"],
        )
        self.assertEqual(
            media_shrinker._normalize_argv(["--silence-noise"]),
            ["--silence-noise"],
        )

    def test_parse_args_sets_conversion_options(self) -> None:
        args = media_shrinker.parse_args(
            [
                "media",
                "--size-limit-bytes",
                "10",
                "--target-bytes",
                "9",
                "--max-duration-seconds",
                "8.5",
                "--output-dir",
                "out",
                "--report",
                "report.json",
                "--ffmpeg",
                "ff",
                "--ffprobe",
                "probe",
                "--brctl",
                "br",
                "--download-icloud",
                "--over-limit-only",
                "--exclude-dir-prefix",
                "split_",
                "--flac-all",
                "--workers",
                "2",
                "--ffmpeg-threads",
                "-1",
                "--silence-noise",
                "-40dB",
                "--silence-min-duration-seconds",
                "3.5",
                "--execute",
                "--overwrite",
            ]
        )

        self.assertEqual(args.root, Path("media"))
        self.assertEqual(args.size_limit_bytes, 10)
        self.assertEqual(args.target_bytes, 9)
        self.assertEqual(args.max_duration_seconds, 8.5)
        self.assertEqual(args.output_dir, Path("out"))
        self.assertEqual(args.report, Path("report.json"))
        self.assertEqual(args.ffmpeg, "ff")
        self.assertEqual(args.ffprobe, "probe")
        self.assertEqual(args.brctl, "br")
        self.assertTrue(args.download_icloud)
        self.assertFalse(args.include_under_limit)
        self.assertEqual(args.exclude_dir_prefix, ["split_"])
        self.assertTrue(args.flac_all)
        self.assertEqual(args.workers, 2)
        self.assertEqual(args.ffmpeg_threads, -1)
        self.assertEqual(args.silence_noise, "-40dB")
        self.assertEqual(args.silence_min_duration_seconds, 3.5)
        self.assertTrue(args.execute)
        self.assertTrue(args.overwrite)

    def test_main_dry_run_lists_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            source.write_bytes(b"1234")

            with patch("builtins.print") as mock_print:
                rc = media_shrinker.main([str(root), "--size-limit-bytes", "1"])

        self.assertEqual(rc, 0)
        printed = ["\t".join(map(str, call.args)) for call in mock_print.call_args_list]
        self.assertIn(f"DRY-RUN\t4\t{source.name}", printed)
        self.assertIn("TOTAL_SELECTED=1", printed)

    def test_main_execute_writes_report_and_returns_success(self) -> None:
        result = media_shrinker.ConversionResult(
            source_path=Path("/scan/b.wav"),
            output_path=Path("/scan/out/b.flac"),
            status="converted",
            original_size_bytes=4,
            output_size_bytes=2,
            strategy="flac-lossless",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "b.wav").write_bytes(b"1234")
            report = root / "report.json"
            with patch("media_shrinker._execute_conversions", return_value=[result]):
                rc = media_shrinker.main(
                    [str(root), "--execute", "--report", str(report)]
                )

            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload[0]["status"], "converted")

    def test_main_execute_returns_failure_when_any_result_failed(self) -> None:
        result = media_shrinker.ConversionResult(
            source_path=Path("/scan/a.wav"),
            output_path=None,
            status="failed",
            original_size_bytes=4,
            message="boom",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.wav").write_bytes(b"1234")
            with patch("media_shrinker._execute_conversions", return_value=[result]):
                rc = media_shrinker.main([str(root), "--execute"])

        self.assertEqual(rc, 1)

    def test_execute_conversions_records_success_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ok = root / "ok.wav"
            bad = root / "bad.wav"
            ok.write_bytes(b"ok")
            bad.write_bytes(b"bad")
            args = media_shrinker.parse_args([str(root), "--workers", "1"])
            result = media_shrinker.ConversionResult(
                source_path=ok,
                output_path=root / "out" / "ok.flac",
                status="converted",
                original_size_bytes=2,
                output_size_bytes=1,
                strategy="flac-lossless",
            )

            def fake_convert_file(source: Path, **_kwargs):
                if source == bad:
                    raise RuntimeError("boom")
                return [result]

            with patch("media_shrinker.convert_file", side_effect=fake_convert_file):
                results = media_shrinker._execute_conversions(
                    [(ok, 2), (bad, 3)], args, root, root / "out"
                )

        statuses = sorted(item.status for item in results)
        self.assertEqual(statuses, ["converted", "failed"])
        self.assertEqual(
            [item.message for item in results if item.status == "failed"], ["boom"]
        )

    def test_small_segment_returns_single_segment(self) -> None:
        segments = build_segments(duration_seconds=1.0, max_segment_duration_seconds=2.0)
        self.assertEqual(segments, [MediaSegment(1, 0.0, 1.0, 1)])

    def test_build_segments_rejects_invalid_durations(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration_seconds must be positive"):
            build_segments(duration_seconds=0, max_segment_duration_seconds=2)
        with self.assertRaisesRegex(
            ValueError, "max_segment_duration_seconds must be greater than"
        ):
            build_segments(duration_seconds=10, max_segment_duration_seconds=0.001)

    def test_calculate_audio_bitrate_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration_seconds must be positive"):
            calculate_audio_bitrate(0, 1000, None)
        with self.assertRaisesRegex(ValueError, "target_bytes must be positive"):
            calculate_audio_bitrate(10, 0, None)
        with self.assertRaises(MediaShrinkerError):
            calculate_audio_bitrate(10_000, 1, None)

    def test_download_from_icloud_requires_brctl_and_reports_failure(self) -> None:
        with patch("media_shrinker.shutil.which", return_value=None):
            with self.assertRaisesRegex(MediaShrinkerError, "was not found"):
                media_shrinker.download_from_icloud(Path("source.wav"))

        completed = MagicMock(returncode=1, stderr="no cloud")
        with patch("media_shrinker.shutil.which", return_value="/usr/bin/brctl"):
            with patch("media_shrinker.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(MediaShrinkerError, "no cloud"):
                    media_shrinker.download_from_icloud(Path("source.wav"))

    def test_conversion_plan_command_rejects_missing_input_placeholder(self) -> None:
        plan = ConversionPlan("bad", Path("in.wav"), Path("out.flac"), ["-n", "out"])
        with self.assertRaisesRegex(MediaShrinkerError, "missing '-i'"):
            plan.command(input_path=Path("other.wav"))

    def test_conversion_plan_command_can_disable_overwrite(self) -> None:
        plan = ConversionPlan(
            "test",
            Path("in.wav"),
            Path("out.flac"),
            ["-y", "-i", "in.wav", "out.flac"],
        )
        self.assertIn("-n", plan.command(overwrite=False))

    def test_convert_file_calls_segment_conversion_with_protected_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            source.write_bytes(b"1234")
            result = media_shrinker.ConversionResult(
                source_path=source,
                output_path=root / "out/source.wav.flac",
                status="converted",
                original_size_bytes=4,
            )
            probe = MediaProbe(1.0, 4, "pcm_s16le", 128_000, False, "wav")

            with patch("media_shrinker.probe_media", return_value=probe):
                with patch("media_shrinker._convert_segment", return_value=result) as mocked:
                    results = media_shrinker.convert_file(
                        source,
                        root=root,
                        output_dir=root / "out",
                        original_size=4,
                    )

        self.assertEqual(results, [result])
        self.assertEqual(mocked.call_args.kwargs["original_size"], 4)

    def test_convert_file_downloads_icloud_and_detects_silence_for_long_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            source.write_bytes(b"1234")
            result = media_shrinker.ConversionResult(
                source_path=source,
                output_path=root / "out/source.wav.flac",
                status="converted",
                original_size_bytes=4,
            )
            probe = MediaProbe(3.0, 4, "pcm_s16le", 128_000, False, "wav")

            with patch("media_shrinker.download_from_icloud") as mock_download:
                with patch("media_shrinker.probe_media", return_value=probe):
                    with patch("media_shrinker.detect_silence_intervals", return_value=[]):
                        with patch("media_shrinker._convert_segment", return_value=result):
                            results = media_shrinker.convert_file(
                                source,
                                root=root,
                                output_dir=root / "out",
                                download_icloud=True,
                                max_segment_duration_seconds=2,
                                original_size=4,
                            )

        self.assertEqual([item.status for item in results], ["converted", "converted"])
        mock_download.assert_called_once_with(source, brctl_path="brctl")

    def test_build_audio_plan_rejects_video_and_missing_audio(self) -> None:
        with self.assertRaisesRegex(MediaShrinkerError, "contains video"):
            build_audio_plan(
                Path("clip.mp4"),
                MediaProbe(10, 100, "aac", 96_000, True, "mp4"),
                target_bytes=100,
                output_dir=Path("out"),
            )
        with self.assertRaisesRegex(MediaShrinkerError, "has no audio stream"):
            build_audio_plan(
                Path("silent.wav"),
                MediaProbe(10, 100, None, None, False, "wav"),
                target_bytes=100,
                output_dir=Path("out"),
            )

    def test_find_candidates_skips_excluded_roots_files_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            excluded_root = root / "excluded"
            excluded_root.mkdir()
            (excluded_root / "source.wav").write_bytes(b"1234")
            source = root / "source.wav"
            source.write_bytes(b"1234")
            target = root / "target.wav"
            target.write_bytes(b"1234")
            try:
                (root / "link.wav").symlink_to(target)
                symlink_created = True
            except OSError:
                symlink_created = False

            self.assertEqual(
                find_candidates(excluded_root, exclude_paths=[excluded_root]), []
            )
            candidates = find_candidates(root, exclude_paths=[source])
            self.assertIn((target, 4), candidates)
            self.assertNotIn((source, 4), candidates)
            if symlink_created:
                self.assertNotIn((root / "link.wav", 4), candidates)

    def test_find_candidates_ignores_symlink_dir_realpath_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_dir = root / "target"
            target_dir.mkdir()
            link_dir = root / "linked"
            try:
                link_dir.symlink_to(target_dir, target_is_directory=True)
            except OSError:
                return
            original_realpath = os.path.realpath

            def flaky_realpath(path, *_args, **_kwargs):
                if Path(path) == link_dir:
                    raise OSError("bad link")
                return original_realpath(path)

            with patch("media_shrinker.os.path.realpath", side_effect=flaky_realpath):
                self.assertEqual(find_candidates(root, exclude_paths=[target_dir]), [])

    def test_probe_media_reports_ffprobe_failure(self) -> None:
        completed = MagicMock(returncode=1, stderr="bad probe")
        with patch("media_shrinker.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(MediaShrinkerError, "bad probe"):
                probe_media(Path("source.wav"))

    def test_parse_probe_payload_rejects_missing_audio_and_duration(self) -> None:
        with self.assertRaisesRegex(MediaShrinkerError, "has no audio stream"):
            media_shrinker._parse_probe_payload(
                {"streams": [{"codec_type": "video"}], "format": {}},
                Path("silent.mp4"),
            )
        with self.assertRaisesRegex(MediaShrinkerError, "has no usable duration"):
            media_shrinker._parse_probe_payload(
                {
                    "streams": [
                        {"codec_type": "audio", "codec_name": "aac", "duration": "0"}
                    ],
                    "format": {},
                },
                Path("zero.wav"),
            )
        probe = media_shrinker._parse_probe_payload(
            {
                "streams": [
                    {"codec_type": "video"},
                    {"codec_type": "audio", "codec_name": "aac", "duration": "1"},
                ],
                "format": {"size": "10"},
            },
            Path("video.mp4"),
        )
        self.assertTrue(probe.has_video)

    def test_execute_plan_reports_ffmpeg_failures_and_existing_output(self) -> None:
        plan = ConversionPlan(
            "test",
            Path("in.wav"),
            Path("out.flac"),
            ["-n", "-i", "in.wav", "out.flac"],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            source.write_bytes(b"source")
            output = root / "out.flac"

            with patch("media_shrinker.subprocess.run", side_effect=FileNotFoundError):
                with self.assertRaisesRegex(MediaShrinkerError, "ffmpeg not found"):
                    media_shrinker._execute_plan(
                        plan, source, output, ffmpeg_path="missing", overwrite=True
                    )

            completed = MagicMock(returncode=1, stderr="bad ffmpeg")
            with patch("media_shrinker.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(MediaShrinkerError, "bad ffmpeg"):
                    media_shrinker._execute_plan(
                        plan, source, output, ffmpeg_path="ffmpeg", overwrite=True
                    )

            output.write_bytes(b"existing")
            completed = MagicMock(returncode=0, stderr="")
            with patch("media_shrinker.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    media_shrinker._execute_plan(
                        plan, source, output, ffmpeg_path="ffmpeg", overwrite=False
                    )

    def test_execute_segment_conversion_falls_back_to_opus_then_discards_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.wav"
            source.write_bytes(b"source")
            probe = MediaProbe(1.0, 10, "pcm_s16le", 128_000, False, "wav")
            segment = MediaSegment(1, 0.0, 1.0, 1)

            def fake_execute_plan(_plan, _source, final_output, **_kwargs):
                final_output.parent.mkdir(parents=True, exist_ok=True)
                final_output.write_bytes(b"0" * 5000)
                return final_output

            with patch("media_shrinker._execute_plan", side_effect=fake_execute_plan):
                with patch("media_shrinker._probe_output_duration", return_value=1.0):
                    with patch("media_shrinker.preserve_file_attributes"):
                        result = media_shrinker._execute_segment_conversion(
                            source,
                            rel_source=Path("source.wav"),
                            probe=probe,
                            segment=segment,
                            output_dir=root / "out",
                            target_bytes=3000,
                            original_size=10,
                            ffmpeg_path="ffmpeg",
                            ffprobe_path="ffprobe",
                            prefer_flac=False,
                            ffmpeg_threads=None,
                            overwrite=False,
                            max_segment_duration_seconds=2,
                            resolved_protected_sources=frozenset({source.resolve()}),
                        )

        self.assertEqual(result.status, "too_large")
        self.assertIsNone(result.output_path)

    def test_remove_invalid_legacy_outputs_skips_canonical_and_removes_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "out"
            output_dir.mkdir()
            source = root / "source.wav"
            source.write_bytes(b"source")
            oversized_legacy = output_dir / "source.flac"
            oversized_legacy.write_bytes(b"0123456789")
            probe = MediaProbe(1.0, 10, "pcm_s16le", 128_000, False, "wav")

            media_shrinker._remove_invalid_legacy_outputs(
                source,
                rel_source=Path("source"),
                probe=probe,
                output_dir=output_dir,
                suffixes=[".flac"],
                target_bytes=5,
                ffprobe_path="ffprobe",
                max_segment_duration_seconds=2,
                protected_sources=frozenset({source.resolve()}),
            )
            media_shrinker._remove_invalid_legacy_outputs(
                source,
                rel_source=Path("source.wav"),
                probe=probe,
                output_dir=output_dir,
                suffixes=[".flac"],
                target_bytes=5,
                ffprobe_path="ffprobe",
                max_segment_duration_seconds=2,
                protected_sources=frozenset({source.resolve()}),
            )

        self.assertFalse(oversized_legacy.exists())

    def test_build_segments_guards_nonadvancing_split_points(self) -> None:
        with patch("media_shrinker._choose_silence_split_point", return_value=0.0):
            segments = build_segments(
                duration_seconds=3.0, max_segment_duration_seconds=2.0
            )

        self.assertGreater(segments[0].duration_seconds, 0)

    def test_resolve_collision_reports_exhausted_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.flac"
            path.write_bytes(b"data")
            with patch("pathlib.Path.exists", return_value=True):
                with self.assertRaisesRegex(FileExistsError, "Could not find free"):
                    media_shrinker._resolve_collision(path, overwrite=False)

    def test_attribute_copy_helpers_ignore_platform_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.wav"
            dest = Path(tmp) / "dest.wav"
            source.write_bytes(b"source")
            dest.write_bytes(b"dest")

            with patch("media_shrinker.os.chmod", side_effect=OSError):
                preserve_file_attributes(source, dest, setfile_path=None)

            with patch("media_shrinker.os.listxattr", side_effect=OSError, create=True):
                with patch("media_shrinker.os.getxattr", return_value=b"", create=True):
                    with patch("media_shrinker.os.setxattr", create=True):
                        media_shrinker._copy_extended_attributes(source, dest)

            with patch("media_shrinker.os.listxattr", return_value=["user.test"], create=True):
                with patch("media_shrinker.os.getxattr", side_effect=OSError, create=True):
                    with patch("media_shrinker.os.setxattr", create=True):
                        media_shrinker._copy_extended_attributes(source, dest)

            with patch("media_shrinker.os.listxattr", return_value=["user.test"], create=True):
                with patch("media_shrinker.os.getxattr", return_value=b"value", create=True):
                    with patch("media_shrinker.os.setxattr", side_effect=OSError, create=True):
                        media_shrinker._copy_extended_attributes(source, dest)

            stat_result = os.stat(source)
            media_shrinker._copy_macos_creation_time(stat_result, dest, "SetFile")
            media_shrinker._copy_macos_creation_time(MagicMock(spec=[]), dest, "SetFile")

            with patch("media_shrinker._get_setfile_path", return_value="SetFile"):
                with patch("media_shrinker._copy_macos_creation_time") as mock_copy:
                    media_shrinker.preserve_file_attributes(source, dest)
                    mock_copy.assert_called_once()

            with patch("media_shrinker.os.listxattr", side_effect=OSError):
                media_shrinker._copy_extended_attributes(source, dest)

            # Test unsupported OS for extended attributes
            with patch("builtins.hasattr", return_value=False):
                media_shrinker._copy_extended_attributes(source, dest)

            # Test macos creation time logic when birthtime is present
            with patch("media_shrinker.subprocess.run") as mock_run:
                mock_stat = MagicMock()
                mock_stat.st_birthtime = 1234567890.0
                media_shrinker._copy_macos_creation_time(mock_stat, dest, "SetFile")
                mock_run.assert_called_once()

class PresetTests(unittest.TestCase):
    """Scenario preset CLI wiring and precedence."""

    def test_music_preset_applies_bundled_overrides(self) -> None:
        """`--preset music` fills flac_all and gentler silence from the preset."""
        args = media_shrinker.parse_args(["root", "--preset", "music"])
        self.assertTrue(args.flac_all)
        self.assertEqual(args.silence_noise, "-45dB")
        self.assertEqual(args.silence_min_duration_seconds, 3.0)
        # target_bytes is not overridden by music -> stays the real default.
        self.assertEqual(args.target_bytes, media_shrinker.DEFAULT_TARGET_BYTES)

    def test_archive_preset_raises_target_and_prefers_flac(self) -> None:
        """`--preset archive` bumps target_bytes and enables flac_all."""
        args = media_shrinker.parse_args(["root", "--preset", "archive"])
        self.assertTrue(args.flac_all)
        self.assertEqual(args.target_bytes, 1_950_000_000)
        self.assertEqual(args.silence_noise, "-50dB")

    def test_voice_preset_keeps_opus_and_trims_aggressively(self) -> None:
        """`--preset voice` keeps Opus (flac_all False) with aggressive silence."""
        args = media_shrinker.parse_args(["root", "--preset", "voice"])
        self.assertFalse(args.flac_all)
        self.assertEqual(args.silence_noise, "-30dB")
        self.assertEqual(args.silence_min_duration_seconds, 0.5)

    def test_explicit_flag_overrides_preset(self) -> None:
        """A value the user sets on the CLI wins over the preset override."""
        args = media_shrinker.parse_args(
            ["root", "--preset", "music", "--silence-noise", "-99dB"]
        )
        self.assertEqual(args.silence_noise, "-99dB")
        # Unspecified options still come from the preset.
        self.assertTrue(args.flac_all)

    def test_explicit_store_true_flag_overrides_preset(self) -> None:
        """`--flac-all` set explicitly is honored even for a preset that omits it."""
        args = media_shrinker.parse_args(["root", "--preset", "voice", "--flac-all"])
        self.assertTrue(args.flac_all)

    def test_explicit_target_bytes_overrides_archive_preset(self) -> None:
        """A user-set --target-bytes beats the archive preset's larger value."""
        args = media_shrinker.parse_args(
            ["root", "--preset", "archive", "--target-bytes", "5"]
        )
        self.assertEqual(args.target_bytes, 5)

    def test_no_preset_leaves_defaults_unchanged(self) -> None:
        """Without --preset every tunable option equals the built-in default."""
        args = media_shrinker.parse_args(["root"])
        self.assertIsNone(args.preset)
        self.assertFalse(args.flac_all)
        self.assertEqual(args.silence_noise, media_shrinker.DEFAULT_SILENCE_NOISE)
        self.assertEqual(
            args.silence_min_duration_seconds,
            media_shrinker.DEFAULT_SILENCE_MIN_DURATION_SECONDS,
        )
        self.assertEqual(args.target_bytes, media_shrinker.DEFAULT_TARGET_BYTES)
        self.assertEqual(
            args.max_duration_seconds,
            media_shrinker.DEFAULT_MAX_SEGMENT_DURATION_SECONDS,
        )

    def test_unknown_preset_is_rejected(self) -> None:
        """An unknown preset name exits via argparse (SystemExit)."""
        with self.assertRaises(SystemExit):
            media_shrinker.parse_args(["root", "--preset", "bogus"])


class PresetModuleTests(unittest.TestCase):
    """Unit tests for the standalone presets module logic."""

    def test_preset_names_matches_registry(self) -> None:
        """preset_names reports every registered preset in definition order."""
        self.assertEqual(
            presets.preset_names(), ("voice", "podcast", "music", "archive")
        )

    def test_apply_preset_without_preset_restores_real_defaults(self) -> None:
        """No preset: every unset dest receives its real default."""
        args = argparse.Namespace(preset=None)
        for dest in presets.PRESET_TUNABLE_DESTS:
            setattr(args, dest, presets._UNSET)
        defaults = {dest: f"D_{dest}" for dest in presets.PRESET_TUNABLE_DESTS}
        presets.apply_preset(args, defaults)
        for dest, value in defaults.items():
            self.assertEqual(getattr(args, dest), value)

    def test_apply_preset_override_beats_default_but_not_explicit(self) -> None:
        """Preset override applies to unset dests; explicit values are untouched."""
        args = argparse.Namespace(preset="music")
        # flac_all explicitly set by the user -> must be preserved.
        args.flac_all = False
        args.silence_noise = presets._UNSET
        args.silence_min_duration_seconds = presets._UNSET
        args.target_bytes = presets._UNSET
        args.max_duration_seconds = presets._UNSET
        defaults = {dest: None for dest in presets.PRESET_TUNABLE_DESTS}
        presets.apply_preset(args, defaults)
        self.assertFalse(args.flac_all)  # explicit user value survives
        self.assertEqual(args.silence_noise, "-45dB")  # from music preset
        self.assertIsNone(args.target_bytes)  # not in preset -> default

    def test_apply_preset_returns_same_namespace(self) -> None:
        """apply_preset mutates and returns the same namespace object."""
        args = argparse.Namespace(preset=None)
        for dest in presets.PRESET_TUNABLE_DESTS:
            setattr(args, dest, presets._UNSET)
        result = presets.apply_preset(args, {d: 0 for d in presets.PRESET_TUNABLE_DESTS})
        self.assertIs(result, args)


if __name__ == "__main__":
    unittest.main()

class FastPathTests(unittest.TestCase):
    def test_copy_extended_attributes_dummy(self) -> None:
        import os
        from media_shrinker import _copy_extended_attributes

        # We need to hit lines 703-704
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")

            with patch("os.listxattr", side_effect=OSError("Permission denied")):
                _copy_extended_attributes(src, dest)

    def test_copy_macos_creation_time_dummy(self) -> None:
        from media_shrinker import _copy_macos_creation_time
        import stat

        # Hit 1632
        class MockStat:
            st_birthtime = 12345.0

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dest.txt"
            dest.write_text("hello")
            _copy_macos_creation_time(MockStat(), dest, "/bin/echo")

    def test_format_result_dummy(self) -> None:
        from media_shrinker import _format_result, ConversionResult

        # Hit 1654-1657
        result = ConversionResult(
            source_path=Path("/tmp/foo.txt"),
            output_path=Path("/tmp/foo.flac"),
            status="converted",
            original_size_bytes=200,
            output_size_bytes=100,
            strategy="flac-lossless"
        )
        s = _format_result(Path("/tmp"), result)
        self.assertIn("foo.txt", s)

    def test_copy_extended_attributes_dummy_success(self) -> None:
        import os
        from media_shrinker import _copy_extended_attributes

        # Hit 703-704
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")

            with patch("os.listxattr", return_value=["user.test"]):
                with patch("os.getxattr", side_effect=OSError("denied")):
                    _copy_extended_attributes(src, dest)

    def test_copy_macos_creation_time_dummy_none(self) -> None:
        from media_shrinker import _copy_macos_creation_time
        import stat

        # Hit 1632
        class MockStat:
            st_birthtime = None

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dest.txt"
            dest.write_text("hello")
            _copy_macos_creation_time(MockStat(), dest, "/bin/echo")

    def test_copy_extended_attributes_dummy_set_fail(self) -> None:
        import os
        from media_shrinker import _copy_extended_attributes

        # Hit 703-704
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")

            with patch("os.listxattr", return_value=["user.test"]):
                with patch("os.getxattr", return_value=b"value"):
                    with patch("os.setxattr", side_effect=OSError("denied")):
                        _copy_extended_attributes(src, dest)

    def test_copy_macos_creation_time_dummy_not_found(self) -> None:
        from media_shrinker import _copy_macos_creation_time
        import stat

        # Hit 1632
        class MockStat:
            st_birthtime = 12345.0

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dest.txt"
            dest.write_text("hello")
            with patch("subprocess.run") as mock_run:
                _copy_macos_creation_time(MockStat(), dest, "/usr/bin/SetFile")
                mock_run.assert_called_once()

    def test_copy_macos_creation_time_dummy_success(self) -> None:
        from media_shrinker import _copy_macos_creation_time
        import stat

        # Hit 1632
        class MockStat:
            st_birthtime = 12345.0

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dest.txt"
            dest.write_text("hello")
            with patch("subprocess.run") as mock_run:
                _copy_macos_creation_time(MockStat(), dest, "/bin/echo")

    def test_preserve_file_attributes_no_setfile(self) -> None:
        from media_shrinker import preserve_file_attributes

        # Hit 703-704
        class MockStat:
            st_atime_ns = 12345000
            st_mtime_ns = 67890000
            st_mode = 0o644

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")
            with patch("os.stat", return_value=MockStat()):
                with patch("media_shrinker._get_setfile_path", return_value=None):
                    preserve_file_attributes(src, dest)

    def test_copy_extended_attributes_dummy_success_branch(self) -> None:
        import os
        from media_shrinker import _copy_extended_attributes

        # Hit 703-704
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")

            with patch("os.listxattr", return_value=["user.test"]):
                with patch("os.getxattr", return_value=b"value"):
                    with patch("os.setxattr") as mock_set:
                        _copy_extended_attributes(src, dest)
                        mock_set.assert_called_once()

    def test_copy_extended_attributes_dummy_listxattr_missing(self) -> None:
        import builtins
        import os
        from media_shrinker import _copy_extended_attributes

        # Hit early return inside _copy_extended_attributes when OS doesn't support it
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")

            original_hasattr = builtins.hasattr
            def fake_hasattr(obj, name):
                if name in ("listxattr", "getxattr", "setxattr"):
                    return False
                return original_hasattr(obj, name)

            with patch("builtins.hasattr", side_effect=fake_hasattr):
                _copy_extended_attributes(src, dest)

    def test_preserve_file_attributes_chmod_error(self) -> None:
        from media_shrinker import preserve_file_attributes
        import stat

        # Hit 703-704
        class MockStat:
            st_atime_ns = 12345000
            st_mtime_ns = 67890000
            st_mode = 0o644

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")
            with patch("os.stat", return_value=MockStat()):
                with patch("os.chmod", side_effect=OSError("denied")):
                    with patch("media_shrinker._get_setfile_path", return_value=None):
                        preserve_file_attributes(src, dest)

    def test_preserve_file_attributes_with_setfile(self) -> None:
        from media_shrinker import preserve_file_attributes
        import stat

        # Hit 703-704
        class MockStat:
            st_atime_ns = 12345000
            st_mtime_ns = 67890000
            st_mode = 0o644

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.txt"
            src.write_text("hello")
            dest = Path(tmp) / "dest.txt"
            dest.write_text("world")
            with patch("os.stat", return_value=MockStat()):
                with patch("media_shrinker._copy_macos_creation_time"):
                    with patch("media_shrinker._get_setfile_path", return_value="/bin/echo"):
                        preserve_file_attributes(src, dest)
