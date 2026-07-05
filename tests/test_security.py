import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_shrinker import build_silencedetect_command, MediaShrinkerError, probe_media

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

if __name__ == "__main__":
    unittest.main()
    @patch("media_shrinker.subprocess.run")
    def test_probe_media_handles_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffprobe", timeout=60)
        with self.assertRaisesRegex(MediaShrinkerError, "ffprobe timed out"):
            probe_media(Path("source.wav"))

    @patch("media_shrinker.subprocess.run")
    def test_detect_silence_handles_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=3600)
        with self.assertRaisesRegex(MediaShrinkerError, "silencedetect timed out"):
            detect_silence_intervals(Path("source.wav"))

    @patch("media_shrinker.subprocess.run")
    def test_download_icloud_handles_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="brctl", timeout=3600)
        with patch("shutil.which", return_value="brctl"):
            with self.assertRaisesRegex(MediaShrinkerError, "iCloud download timed out"):
                download_from_icloud(Path("source.wav"))

    @patch("media_shrinker.subprocess.run")
    def test_execute_plan_handles_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=3600)
        plan = ConversionPlan(
            strategy="test",
            input_path=Path("source.wav"),
            output_path=Path("out.opus"),
            ffmpeg_args=["-i", "source.wav", "out.opus"]
        )
        with self.assertRaisesRegex(MediaShrinkerError, "ffmpeg timed out"):
            _execute_plan(plan, Path("source.wav"), Path("final.opus"), ffmpeg_path="ffmpeg", overwrite=True)

    @patch("media_shrinker.subprocess.run")
    def test_copy_macos_creation_time_handles_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="SetFile", timeout=60)
        mock_stat = MagicMock()
        mock_stat.st_birthtime = 1234567890.0
        # Should not raise exception
        _copy_macos_creation_time(mock_stat, Path("dest.txt"), "SetFile")

    @patch("media_shrinker.subprocess.run")
    def test_probe_media_invalid_json(self, mock_run: MagicMock) -> None:
        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_completed.stdout = "invalid json"
        mock_run.return_value = mock_completed
        with self.assertRaisesRegex(MediaShrinkerError, "ffprobe returned invalid JSON"):
            probe_media(Path("source.wav"))
