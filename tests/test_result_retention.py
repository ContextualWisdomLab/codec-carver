"""Regression tests for owned result storage and download-independent cleanup."""

from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from fastapi.testclient import TestClient
except ImportError:
    _HAS_FASTAPI = False
else:
    _HAS_FASTAPI = True
    import saas_web
    from job_store import JobStore
    from media_shrinker import ConversionResult


@unittest.skipUnless(_HAS_FASTAPI, "fastapi not installed (optional integration dependency)")
class ResultRetentionTests(unittest.TestCase):
    """Pin owned-root creation and bounded retention for completed job outputs."""

    def setUp(self) -> None:
        """Create isolated job metadata, credentials, and result roots for every test."""

        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.test_root = Path(self._temporary_directory.name)
        self.store = JobStore(str(self.test_root / "jobs.sqlite3"))
        self.previous_results_root = saas_web._RESULTS_ROOT
        self.addCleanup(setattr, saas_web, "_RESULTS_ROOT", self.previous_results_root)
        saas_web._RESULTS_ROOT = self.test_root / "owned_results"
        saas_web._RESULTS_ROOT.mkdir()

        credential_name = saas_web.CODEC_CARVER_API_KEYS_NAME
        previous_credential = saas_web.CREDENTIAL_REGISTRY.get_credential(credential_name)
        saas_web.CREDENTIAL_REGISTRY.delete_credential(credential_name)

        def restore_credential() -> None:
            """Restore deployment credential state after a retention test."""

            if previous_credential is None:
                saas_web.CREDENTIAL_REGISTRY.delete_credential(credential_name)
            else:
                saas_web.CREDENTIAL_REGISTRY.set_credential(
                    credential_name,
                    previous_credential,
                )

        self.addCleanup(restore_credential)

    def _create_done_job(
        self,
        job_id: str,
        *,
        updated_at: datetime,
        output_path: Path | None,
    ) -> None:
        """Insert one completed job with deterministic timestamps and output metadata."""

        created_at = updated_at - timedelta(minutes=1)
        self.store.create(job_id, temp_dir="", now=created_at)
        self.store.set_status(
            job_id,
            "done",
            now=updated_at,
            output_path=str(output_path) if output_path is not None else None,
            output_name=output_path.name if output_path is not None else None,
        )

    def test_results_root_uses_mkdtemp_once_and_reuses_owned_root(self) -> None:
        """The service creates one unpredictable owned root instead of a fixed /tmp name."""

        saas_web._RESULTS_ROOT = None
        generated_root = self.test_root / "generated_owner_root"
        generated_root.mkdir()
        with patch("saas_web.tempfile.mkdtemp", return_value=str(generated_root)) as mock_mkdtemp:
            first = saas_web._get_results_root()
            second = saas_web._get_results_root()

        self.assertEqual(first, generated_root.resolve())
        self.assertIs(first, second)
        mock_mkdtemp.assert_called_once_with(prefix="codec_carver_results_")

    def test_expired_cleanup_removes_old_file_and_job_but_preserves_fresh_result(self) -> None:
        """Retention cleanup removes expired bytes and metadata independently of download."""

        now = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
        expired_output = saas_web._get_results_root() / "expired.flac"
        fresh_output = saas_web._get_results_root() / "fresh.flac"
        expired_output.write_bytes(b"expired")
        fresh_output.write_bytes(b"fresh")
        self._create_done_job(
            "expired-job",
            updated_at=now - timedelta(seconds=saas_web.RESULT_RETENTION_SECONDS + 1),
            output_path=expired_output,
        )
        self._create_done_job(
            "fresh-job",
            updated_at=now - timedelta(seconds=saas_web.RESULT_RETENTION_SECONDS - 1),
            output_path=fresh_output,
        )

        removed = saas_web._cleanup_expired_results(self.store, now=now)

        self.assertEqual(removed, 1)
        self.assertFalse(expired_output.exists())
        self.assertIsNone(self.store.get("expired-job"))
        self.assertTrue(fresh_output.exists())
        self.assertIsNotNone(self.store.get("fresh-job"))

    def test_expired_cleanup_never_deletes_file_outside_owned_root(self) -> None:
        """A compromised metadata path cannot make retention unlink an external file."""

        now = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
        outside_output = self.test_root / "outside-secret.flac"
        outside_output.write_bytes(b"must-survive")
        self._create_done_job(
            "outside-job",
            updated_at=now - timedelta(seconds=saas_web.RESULT_RETENTION_SECONDS + 1),
            output_path=outside_output,
        )

        removed = saas_web._cleanup_expired_results(self.store, now=now)

        self.assertEqual(removed, 1)
        self.assertTrue(outside_output.exists())
        self.assertIsNone(self.store.get("outside-job"))

    def test_expired_cleanup_removes_metadata_without_output_path(self) -> None:
        """Expired done records without result bytes are still retired from metadata."""

        now = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
        self._create_done_job(
            "metadata-only",
            updated_at=now - timedelta(seconds=saas_web.RESULT_RETENTION_SECONDS + 1),
            output_path=None,
        )

        removed = saas_web._cleanup_expired_results(self.store, now=now)

        self.assertEqual(removed, 1)
        self.assertIsNone(self.store.get("metadata-only"))

    def test_malformed_timestamp_is_preserved_for_operator_diagnosis(self) -> None:
        """Malformed durable metadata is logged and retained instead of guessed expired."""

        now = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
        self.store.create("malformed-job", temp_dir="", now=now)
        self.store.set_status("malformed-job", "done", now=now)
        with self.store._lock, self.store._connect() as connection:
            connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE id = ?",
                ("not-a-timestamp", "malformed-job"),
            )

        with self.assertLogs("saas_web", level="WARNING"):
            removed = saas_web._cleanup_expired_results(self.store, now=now)

        self.assertEqual(removed, 0)
        self.assertIsNotNone(self.store.get("malformed-job"))

    def test_naive_timestamp_is_preserved_for_operator_diagnosis(self) -> None:
        """Timezone-incompatible metadata is logged rather than guessed expired."""

        now = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 8, 5, 0, 0)
        self._create_done_job("naive-job", updated_at=naive, output_path=None)

        with self.assertLogs("saas_web", level="WARNING"):
            removed = saas_web._cleanup_expired_results(self.store, now=now)

        self.assertEqual(removed, 0)
        self.assertIsNotNone(self.store.get("naive-job"))

    @patch("saas_web.media_shrinker.convert_file")
    @patch("saas_web._get_results_root", side_effect=OSError("no safe result root"))
    def test_batch_result_persistence_failure_cleans_workspace(
        self,
        _mock_results_root,
        mock_convert_file,
    ) -> None:
        """Batch persistence failure returns 500 and removes the request workspace."""

        created_workspaces: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def tracked_mkdtemp(*args, **kwargs):
            """Create a test-owned workspace while recording its path for cleanup proof."""

            path = Path(real_mkdtemp(*args, dir=self.test_root, **kwargs))
            created_workspaces.append(path)
            return str(path)

        def fake_convert(*, source, root, output_dir, target_bytes):
            """Write one valid conversion result into the request output directory."""

            output = Path(output_dir) / "out.flac"
            output.write_bytes(b"converted")
            result = MagicMock(spec=ConversionResult)
            result.output_path = output
            return [result]

        mock_convert_file.side_effect = fake_convert
        with patch("saas_web.tempfile.mkdtemp", side_effect=tracked_mkdtemp):
            client = TestClient(saas_web.app)
            response = client.post(
                "/shrink-batch",
                files=[("files", ("a.wav", io.BytesIO(b"audio"), "audio/wav"))],
                data={"target_bytes": 10000},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "Upload processing failed"})
        self.assertTrue(created_workspaces)
        self.assertTrue(all(not path.exists() for path in created_workspaces))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
