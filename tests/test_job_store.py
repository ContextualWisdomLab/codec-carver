"""Unit tests for the SQLite-backed durable job store."""

import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import job_store
from job_store import JobStore


class JobStoreTests(unittest.TestCase):
    """CRUD, durability, recovery, and concurrency behaviour of JobStore."""

    def setUp(self) -> None:
        self.db_dir = Path(tempfile.mkdtemp(prefix="codec_carver_jobdb_"))
        self.store = JobStore(self.db_dir / "jobs.db")

    def tearDown(self) -> None:
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def test_create_and_get_roundtrip(self):
        self.store.create("a", temp_dir="/tmp/ws-a")
        job = self.store.get("a")
        self.assertEqual(job["job_id"], "a")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["temp_dir"], "/tmp/ws-a")
        self.assertIsNone(job["output_path"])
        self.assertGreater(job["created_at"], 0)
        self.assertEqual(job["created_at"], job["updated_at"])

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.store.get("nope"))

    def test_create_duplicate_id_raises(self):
        self.store.create("dup")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create("dup")

    def test_update_changes_fields_and_timestamp(self):
        self.store.create("b")
        created = self.store.get("b")["created_at"]
        with patch("job_store.time.time", return_value=created + 5):
            updated = self.store.update(
                "b", status="done", output_path="/tmp/out.flac", output_name="out.flac"
            )
        self.assertTrue(updated)
        job = self.store.get("b")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["output_path"], "/tmp/out.flac")
        self.assertEqual(job["output_name"], "out.flac")
        self.assertGreater(job["updated_at"], job["created_at"])

    def test_update_unknown_id_returns_false(self):
        self.assertFalse(self.store.update("ghost", status="failed"))

    def test_update_without_fields_reports_existence(self):
        self.store.create("exists")
        self.assertTrue(self.store.update("exists"))
        self.assertFalse(self.store.update("missing"))

    def test_unknown_field_rejected(self):
        self.store.create("c")
        with self.assertRaises(ValueError):
            self.store.update("c", is_admin=True)
        with self.assertRaises(ValueError):
            self.store.create("d", **{"status; DROP TABLE jobs": "x"})

    def test_delete_returns_row_exactly_once(self):
        self.store.create("e", temp_dir="/tmp/ws-e")
        first = self.store.delete("e")
        second = self.store.delete("e")
        self.assertEqual(first["temp_dir"], "/tmp/ws-e")
        self.assertIsNone(second)
        self.assertIsNone(self.store.get("e"))

    def test_state_survives_reopen(self):
        # The core durability property: a brand-new store handle on the same
        # path (fresh process, different worker) sees identical state.
        self.store.create("persist", temp_dir="/tmp/ws-p")
        self.store.update("persist", status="done", output_name="out.flac")

        reopened = JobStore(self.store.db_path)
        job = reopened.get("persist")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["output_name"], "out.flac")

    def test_all_jobs_ordered_by_creation(self):
        with patch("job_store.time.time", side_effect=[100.0, 200.0]):
            self.store.create("first")
            self.store.create("second")
        self.assertEqual([j["job_id"] for j in self.store.all_jobs()], ["first", "second"])

    def test_recover_interrupted_fails_active_jobs_only(self):
        self.store.create("q", status="queued")
        self.store.create("p", status="processing")
        self.store.create("d", status="done")
        self.store.create("f", status="failed", error="original error")

        recovered = self.store.recover_interrupted()

        self.assertEqual(sorted(j["job_id"] for j in recovered), ["p", "q"])
        for job_id in ("q", "p"):
            job = self.store.get(job_id)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Interrupted by service restart")
        self.assertEqual(self.store.get("d")["status"], "done")
        self.assertEqual(self.store.get("f")["error"], "original error")

    def test_purge_stale_removes_only_old_terminal_jobs(self):
        with patch("job_store.time.time", return_value=1000.0):
            self.store.create("old-done", status="done")
            self.store.create("old-failed", status="failed")
            self.store.create("old-active", status="processing")
        with patch("job_store.time.time", return_value=2000.0):
            self.store.create("new-done", status="done")
            purged = self.store.purge_stale(max_age_seconds=500)

        self.assertEqual(
            sorted(j["job_id"] for j in purged), ["old-done", "old-failed"]
        )
        self.assertIsNone(self.store.get("old-done"))
        self.assertIsNone(self.store.get("old-failed"))
        # In-flight jobs are never purged regardless of age; fresh terminal
        # jobs stay within the retention window.
        self.assertIsNotNone(self.store.get("old-active"))
        self.assertIsNotNone(self.store.get("new-done"))

    def test_concurrent_writers_do_not_corrupt_the_store(self):
        errors: list[Exception] = []

        def worker(index: int) -> None:
            try:
                store = JobStore(self.store.db_path)
                for step in range(10):
                    job_id = f"job-{index}-{step}"
                    store.create(job_id, temp_dir=f"/tmp/{job_id}")
                    store.update(job_id, status="done")
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        jobs = self.store.all_jobs()
        self.assertEqual(len(jobs), 80)
        self.assertTrue(all(job["status"] == "done" for job in jobs))

    def test_default_db_path_honours_env_override(self):
        with patch.dict(
            "os.environ", {job_store.DB_PATH_ENV: "/data/jobs/custom.db"}
        ):
            self.assertEqual(
                job_store.default_db_path(), Path("/data/jobs/custom.db")
            )

    def test_default_db_path_falls_back_to_tempdir(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop(job_store.DB_PATH_ENV, None)
            path = job_store.default_db_path()
        self.assertEqual(path.name, "jobs.db")
        self.assertEqual(path.parent.name, "codec-carver")


if __name__ == "__main__":
    unittest.main()
