import unittest
from pathlib import Path
from media_shrinker import build_silencedetect_command, MediaShrinkerError

class SecurityTests(unittest.TestCase):
    def test_silence_noise_validation(self):
        valid_noises = ["-35dB", "35", "+35.5", "-35.5dB"]
        for noise in valid_noises:
            build_silencedetect_command(Path("test.wav"), silence_noise=noise)

        invalid_noises = ["-35dB; rm -rf /", "-35dB,ametadata=mode=print:file=hacked.txt", "abc"]
        for noise in invalid_noises:
            with self.assertRaises(MediaShrinkerError):
                build_silencedetect_command(Path("test.wav"), silence_noise=noise)

if __name__ == "__main__":
    unittest.main()
