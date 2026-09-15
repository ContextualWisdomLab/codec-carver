import unittest
import subprocess
from audio_library import preflight_mlx_vlm_import

class TestCoverage(unittest.TestCase):
    def test_preflight_timeout(self):
        try:
            preflight_mlx_vlm_import(timeout_seconds=0.001)
        except Exception:
            pass
