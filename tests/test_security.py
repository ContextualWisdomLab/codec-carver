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

    @patch("media_shrinker.subprocess.run")
    def test_probe_media_passes_shell_metacharacters_as_single_argv_item(
        self, mock_run: MagicMock
    ):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format":{"duration":"1","size":"10","format_name":"wav"},"streams":[{"codec_type":"audio","codec_name":"pcm_s16le","bit_rate":"128000"}]}',
        )

        source_path = Path("test; echo POC_SUCCESS > /tmp/poc_success; #.mp3")
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=10)
            probe_media(source_path)

        command = mock_run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertFalse(mock_run.call_args.kwargs["shell"])
        input_index = command.index("-i")
        self.assertEqual(command[input_index + 1], str(source_path.resolve()))
        self.assertNotIn("echo", command)
        self.assertNotIn(">", command)


if __name__ == "__main__":
    unittest.main()
