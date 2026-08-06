"""Regression tests for result-persistence and retention failure isolation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import saas_web
    from job_store import JobStore
    from media_shrinker import ConversionResult
except ImportError:
    raise


class ResultRetentionFailureTests(unittest.TestCase):
    """Protect completed results from secondary cleanup failures and leaks."""

    def setUp(self) -> None:
        """Install isolated durable metadata and an owned result root."""

        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.test_root = Path(self._temporary_directory.name)
        self.store = JobStore(str(self.test_root / "jobs.sqlite3"))

        self.previous_store = saas_web.JOB_STORE
        self.previous_results_root = saas_web._RESULTS_ROOT
        saas_web.JOB_STORE = self.store
        saas_web._RESULTS_ROOT = self.test_root / "owned_results"
        saas_web._RESULTS_ROOT.mkdir()
        self.addCleanup(setattr, saas_web, "JOB_STORE", self.previous_store)
        self.addCleanup(setattr, saas_web, "_RESULTS_ROOT", self.previous_results_root)

    def _make_processing_workspace(self, job_id: str) -> tuple[Path, Path, Path, Path]:
        """Create one queued job and its request workspace for direct worker tests."""

        temp_dir = Path(tempfile.mkdtemp(prefix="codec_carver_test_", dir=self.test_root))
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        source_path = input_dir / "input.wav"
        source_path.write_bytes(b"audio")
        self.store.create(job_id, temp_dir=str(temp_dir), now=saas_web._now())
        return temp_dir, input_dir, output_dir, source_path

    @patch("saas_web._cleanup_expired_results", side_effect=OSError("janitor unavailable"))
    @patch("saas_web.media_shrinker.convert_file")
    def test_cleanup_failure_does_not_downgrade_completed_job(
        self,
        mock_convert_file,
        _mock_cleanup,
    ) -> None:
        """A post-completion janitor failure must not turn a valid result into failed state."""

        temp_dir, input_dir, output_dir, source_path = self._make_processing_workspace(
            "completed-job"
        )
        output = output_dir / "out.flac"
        output.write_bytes(b"converted")
        result = MagicMock(spec=ConversionResult)
        result.output_path = output
        mock_convert_file.return_value = [result]

        with self.assertLogs("saas_web", level="ERROR"):
            saas_web._run_job(
                "completed-job",
                source_path,
                input_dir,
                output_dir,
                10000,
                temp_dir,
            )

        job = self.store.get("completed-job")
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "done")
        persisted = Path(job["output_path"])
        self.assertTrue(persisted.is_file())
        self.assertTrue(persisted.resolve().is_relative_to(saas_web._get_results_root()))
        self.assertFalse(temp_dir.exists())

    @patch("saas_web.media_shrinker.convert_file")
    def test_missing_job_during_done_transition_does_not_leak_moved_result(
        self,
        mock_convert_file,
    ) -> None:
        """If durable metadata disappears, a moved result is removed from the owned root."""

        class VanishingStore:
            """Accept processing state once, then emulate concurrent job deletion."""

            def set_status(self, _job_id, status, **_kwargs):
                """Raise when the worker attempts to commit the completed result."""

                if status == "processing":
                    return None
                raise KeyError("gone")

        temp_dir = Path(tempfile.mkdtemp(prefix="codec_carver_test_", dir=self.test_root))
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        source_path = input_dir / "input.wav"
        source_path.write_bytes(b"audio")
        output = output_dir / "out.flac"
        output.write_bytes(b"converted")
        result = MagicMock(spec=ConversionResult)
        result.output_path = output
        mock_convert_file.return_value = [result]

        with patch("saas_web._get_job_store", return_value=VanishingStore()):
            saas_web._run_job(
                "vanished-job",
                source_path,
                input_dir,
                output_dir,
                10000,
                temp_dir,
            )

        self.assertFalse(temp_dir.exists())
        self.assertEqual(list(saas_web._get_results_root().iterdir()), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
