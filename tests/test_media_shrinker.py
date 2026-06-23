import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import media_shrinker
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



            # When using os.scandir, entry attributes (is_symlink, stat) don't call os.lstat
            # in a way that can be mocked by patch("os.lstat"). We patch os.scandir to yield
            # a mock entry that raises OSError when is_symlink or stat is called, or we just
            # patch os.lstat and add a call to os.lstat in the code.
            # A cleaner way is to patch the code to simulate the failure, but since we just
            # want to verify that an OSError on checking a file causes it to be skipped,
            # we can create a directory/file without read permissions, but Python tests running
            # as root might bypass it. Let's patch os.scandir instead.

            original_scandir = os.scandir
            class FlakyDirEntry:
                def __init__(self, entry):
                    self._entry = entry
                def __getattr__(self, name):
                    if name in ('is_symlink', 'is_dir', 'is_file', 'stat'):
                        if self._entry.name in {"bad.mp3", "bad_dir"}:
                            def raise_os_error(*args, **kwargs):
                                raise OSError("cannot inspect state")
                            return raise_os_error
                    return getattr(self._entry, name)

            def flaky_scandir(path):
                for entry in original_scandir(path):
                    yield FlakyDirEntry(entry)

            class FlakyScandirContext:
                def __init__(self, path):
                    self.path = path
                    self.it = flaky_scandir(path)
                def __enter__(self):
                    return self.it
                def __exit__(self, *args):
                    pass

            with patch("os.scandir", FlakyScandirContext):
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
            else:
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


if __name__ == "__main__":
    unittest.main()
