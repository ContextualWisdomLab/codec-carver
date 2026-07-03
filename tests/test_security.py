import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_shrinker import build_silencedetect_command, MediaShrinkerError, probe_media, build_audio_plan, build_opus_plan, MediaProbe

class SecurityTests(unittest.TestCase):
    def test_silence_noise_validation(self):
        valid_noises = ["-35dB", "35", "+35.5", "-35.5dB"]
        for noise in valid_noises:
            build_silencedetect_command(Path("test.wav"), silence_noise=noise)

        invalid_noises = ["-35dB; rm -rf /", "-35dB,ametadata=mode=print:file=hacked.txt", "abc"]
        for noise in invalid_noises:
            with self.assertRaises(MediaShrinkerError):
                build_silencedetect_command(Path("test.wav"), silence_noise=noise)

    @patch("media_shrinker.subprocess.run")
    def test_probe_media_uses_explicit_input_flag_for_dash_prefixed_path(
        self, mock_run: MagicMock
    ):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format":{"duration":"1","size":"10","format_name":"wav"},"streams":[{"codec_type":"audio","codec_name":"pcm_s16le","bit_rate":"128000"}]}',
        )

        source_path = Path("-version.wav")
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=10)
            probe_media(source_path)

        command = mock_run.call_args.args[0]
        input_index = command.index("-i")
        self.assertEqual(command[input_index + 1], str(source_path.resolve()))

    def test_build_audio_plan_uses_absolute_path_for_input(self):
        source_path = Path("-test.wav")
        probe = MediaProbe(has_video=False, audio_codec="flac", duration_seconds=10, size_bytes=100, audio_bit_rate=None, format_name="wav")
        plan = build_audio_plan(source_path, probe, target_bytes=1000, output_dir=Path("/tmp"))

        args = plan.ffmpeg_args
        self.assertIn("-i", args)
        input_index = args.index("-i")
        self.assertEqual(args[input_index + 1], str(source_path.resolve()))

    def test_build_opus_plan_uses_absolute_path_for_input(self):
        source_path = Path("-test.wav")
        probe = MediaProbe(has_video=False, audio_codec="flac", duration_seconds=10, size_bytes=100, audio_bit_rate=None, format_name="wav")
        plan = build_opus_plan(source_path, probe, target_bytes=1000000000, output_dir=Path("/tmp"))

        args = plan.ffmpeg_args
        self.assertIn("-i", args)
        input_index = args.index("-i")
        self.assertEqual(args[input_index + 1], str(source_path.resolve()))

if __name__ == "__main__":
    unittest.main()
