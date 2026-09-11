"""Executable contracts for FFmpeg/FFprobe input protocol admission."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audio_library


class FfmpegProtocolWhitelistContractTests(unittest.TestCase):
    """Keep untrusted media parsing on the reviewed local-protocol boundary."""

    _ALLOWED_PROTOCOLS = {"file", "crypto", "data"}
    _NETWORK_PROTOCOLS = {
        "ftp",
        "gopher",
        "http",
        "https",
        "rtmp",
        "rtsp",
        "sftp",
        "smb",
        "srt",
        "tcp",
        "udp",
    }

    def assert_local_input_protocols(self, command: list[str]) -> int:
        """Return the whitelist index after checking its exact network boundary."""

        whitelist_index = command.index("-protocol_whitelist")
        protocols = set(command[whitelist_index + 1].split(","))
        self.assertEqual(protocols, self._ALLOWED_PROTOCOLS)
        self.assertTrue(protocols.isdisjoint(self._NETWORK_PROTOCOLS))
        return whitelist_index

    def test_ffprobe_duration_applies_whitelist_immediately_before_input(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="12.5\n", stderr=""
        )
        with tempfile.TemporaryDirectory() as root:
            media_path = Path(root) / "recording.m4a"
            media_path.write_bytes(b"fixture")
            with (
                patch(
                    "audio_library.trusted_ffprobe_binary",
                    return_value=Path("/usr/bin/ffprobe"),
                ),
                patch("audio_library.subprocess.run", return_value=completed) as run,
            ):
                self.assertEqual(audio_library.audio_duration_seconds(media_path), 12.5)

        command = run.call_args.args[0]
        whitelist_index = self.assert_local_input_protocols(command)
        self.assertEqual(command[whitelist_index + 2], str(media_path))
        self.assertEqual(run.call_args.kwargs["pass_fds"], ())

    def test_silence_detection_applies_whitelist_before_input_flag(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        with (
            patch(
                "audio_library.trusted_ffmpeg_binary",
                return_value=Path("/usr/bin/ffmpeg"),
            ),
            patch("audio_library.subprocess.run", return_value=completed) as run,
        ):
            self.assertEqual(
                audio_library.detect_silence_intervals(Path("recording.m4a")), []
            )

        command = run.call_args.args[0]
        whitelist_index = self.assert_local_input_protocols(command)
        self.assertEqual(
            command[whitelist_index + 2 : whitelist_index + 4],
            ["-i", "recording.m4a"],
        )
        self.assertEqual(run.call_args.kwargs["pass_fds"], ())



    def test_decode_mlx_audio_applies_whitelist_before_input_flag(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"dummy", stderr=b""
        )
        with tempfile.TemporaryDirectory() as root:
            media_path = Path(root) / "recording.m4a"
            media_path.write_bytes(b"fixture")
            with (
                patch(
                    "audio_library.trusted_ffmpeg_binary",
                    return_value=Path("/usr/bin/ffmpeg"),
                ),
                patch("audio_library.subprocess.run", return_value=completed) as run,
            ):
                with patch.dict("sys.modules", {"mlx": unittest.mock.MagicMock(), "mlx.core": unittest.mock.MagicMock(), "numpy": unittest.mock.MagicMock()}):
                    try:
                        audio_library.decode_audio_for_mlx(media_path)
                    except Exception:
                        pass

        command = run.call_args.args[0]
        whitelist_index = self.assert_local_input_protocols(command)
        self.assertEqual(
            command[whitelist_index + 2 : whitelist_index + 4],
            ["-i", str(media_path)],
        )
        self.assertEqual(run.call_args.kwargs["pass_fds"], ())

if __name__ == '__main__':
    unittest.main()
