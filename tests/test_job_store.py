"""Tests for the SQLite-backed durable job store (job_store.py)."""

import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from job_store import (
    DuplicateJobError,
    JobStore,
    _LEGACY_JOBS_COLUMNS,
    _list_table_columns,
    _list_user_tables,
    _migrate_legacy_jobs_table,
)

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)


class JobStoreTestCase(unittest.TestCase):
    """Base fixture: a fresh JobStore on a temp SQLite file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "conversion_jobs.db")
        self.store = JobStore(self.db_path)


class TestCreateAndGet(JobStoreTestCase):
    def test_create_get_roundtrip(self):
        self.store.create("job-1", temp_dir="/tmp/job-1", now=T0)
        job = self.store.get("job-1")
        self.assertEqual(
            job,
            {
                "job_id": "job-1",
                "job_status": "queued",
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
                "output_path": None,
                "output_name": None,
                "error_message": None,
                "temp_dir": "/tmp/job-1",
            },
        )

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.store.get("nope"))

    def test_create_duplicate_raises(self):
        self.store.create("job-1", temp_dir="/tmp/a", now=T0)
        with self.assertRaises(DuplicateJobError):
            self.store.create("job-1", temp_dir="/tmp/b", now=T1)
        # DuplicateJobError is a ValueError, so generic handlers work too.
        self.assertTrue(issubclass(DuplicateJobError, ValueError))
        # Original record is untouched.
        self.assertEqual(self.store.get("job-1")["temp_dir"], "/tmp/a")

    def test_memory_path_rejected(self):
        with self.assertRaises(ValueError):
            JobStore(":memory:")


class TestSetStatus(JobStoreTestCase):
    def test_transitions_update_status_and_timestamp(self):
        self.store.create("job-1", temp_dir="/tmp/j", now=T0)

        self.store.set_status("job-1", "processing", now=T1)
        job = self.store.get("job-1")
        self.assertEqual(job["job_status"], "processing")
        self.assertEqual(job["created_at"], T0.isoformat())
        self.assertEqual(job["updated_at"], T1.isoformat())

        self.store.set_status(
            "job-1", "done", now=T2,
            output_path="/tmp/out.mp4", output_name="video.mp4",
        )
        job = self.store.get("job-1")
        self.assertEqual(job["job_status"], "done")
        self.assertEqual(job["updated_at"], T2.isoformat())
        self.assertEqual(job["output_path"], "/tmp/out.mp4")
        self.assertEqual(job["output_name"], "video.mp4")
        self.assertIsNone(job["error_message"])

    def test_failed_records_error(self):
        self.store.create("job-1", temp_dir="/tmp/j", now=T0)
        self.store.set_status("job-1", "failed", now=T1, error_message="boom")
        job = self.store.get("job-1")
        self.assertEqual(job["job_status"], "failed")
        self.assertEqual(job["error_message"], "boom")

    def test_omitted_fields_are_preserved(self):
        self.store.create("job-1", temp_dir="/tmp/j", now=T0)
        self.store.set_status(
            "job-1", "done", now=T1,
            output_path="/tmp/out.mp4", output_name="video.mp4",
        )
        # A later update without output fields must not erase them.
        self.store.set_status("job-1", "done", now=T2)
        job = self.store.get("job-1")
        self.assertEqual(job["output_path"], "/tmp/out.mp4")
        self.assertEqual(job["output_name"], "video.mp4")

    def test_invalid_status_raises_value_error(self):
        self.store.create("job-1", temp_dir="/tmp/j", now=T0)
        with self.assertRaises(ValueError):
            self.store.set_status("job-1", "exploded", now=T1)
        # Job unchanged after the rejected update.
        self.assertEqual(self.store.get("job-1")["job_status"], "queued")

    def test_unknown_job_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.store.set_status("ghost", "done", now=T0)


class TestListAndDelete(JobStoreTestCase):
    def test_list_all_and_filter_by_status(self):
        self.store.create("a", temp_dir="/tmp/a", now=T0)
        self.store.create("b", temp_dir="/tmp/b", now=T1)
        self.store.create("c", temp_dir="/tmp/c", now=T2)
        self.store.set_status("b", "processing", now=T2)

        all_ids = [job["job_id"] for job in self.store.list_jobs()]
        self.assertEqual(all_ids, ["a", "b", "c"])

        queued = [job["job_id"] for job in self.store.list_jobs(status="queued")]
        self.assertEqual(queued, ["a", "c"])

        processing = self.store.list_jobs(status="processing")
        self.assertEqual([job["job_id"] for job in processing], ["b"])

        self.assertEqual(self.store.list_jobs(status="failed"), [])

    def test_list_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            self.store.list_jobs(status="bogus")

    def test_delete_removes_job(self):
        self.store.create("a", temp_dir="/tmp/a", now=T0)
        self.store.delete("a")
        self.assertIsNone(self.store.get("a"))
        self.assertEqual(self.store.list_jobs(), [])

    def test_delete_unknown_is_noop(self):
        self.store.delete("ghost")  # must not raise


class TestDurability(JobStoreTestCase):
    def test_job_survives_store_reopen(self):
        self.store.create("job-1", temp_dir="/tmp/j", now=T0)
        self.store.set_status(
            "job-1", "done", now=T1,
            output_path="/tmp/out.mp4", output_name="video.mp4",
        )
        del self.store  # simulate process exit

        reopened = JobStore(self.db_path)
        job = reopened.get("job-1")
        self.assertIsNotNone(job)
        self.assertEqual(job["job_status"], "done")
        self.assertEqual(job["output_path"], "/tmp/out.mp4")
        self.assertEqual(job["output_name"], "video.mp4")
        self.assertEqual(job["created_at"], T0.isoformat())
        self.assertEqual(job["updated_at"], T1.isoformat())


class TestRealisticConversionLifecycle(JobStoreTestCase):
    def test_two_hour_meeting_result_survives_reopen(self):
        """A finished meeting carve remains downloadable after restart."""
        job_id = "meeting-2026-08-16-board-review"
        workspace = "/tmp/meeting-2026-08-16-board-review"
        output_path = f"{workspace}/board-review.wav.flac"
        self.store.create(job_id, temp_dir=workspace, now=T0)
        self.store.set_status(job_id, "processing", now=T1)
        self.store.set_status(
            job_id,
            "done",
            now=T2,
            output_path=output_path,
            output_name="board-review.wav.flac",
        )
        del self.store

        reopened = JobStore(self.db_path)
        job = reopened.get(job_id)
        self.assertEqual(job["job_id"], job_id)
        self.assertEqual(job["job_status"], "done")
        self.assertEqual(job["output_path"], output_path)
        self.assertEqual(job["output_name"], "board-review.wav.flac")
        self.assertTrue(job["output_name"].endswith(".flac"))
        self.assertEqual(job["created_at"], T0.isoformat())
        self.assertEqual(job["updated_at"], T2.isoformat())
        self.assertIsNone(job["error_message"])


class TestLegacyMigration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "legacy_jobs.db")

    def _write_legacy_jobs(self, rows):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "CREATE TABLE jobs ("
                " id TEXT PRIMARY KEY,"
                " status TEXT NOT NULL,"
                " created_at TEXT NOT NULL,"
                " updated_at TEXT NOT NULL,"
                " output_path TEXT,"
                " output_name TEXT,"
                " error TEXT,"
                " temp_dir TEXT)"
            )
            conn.executemany(
                "INSERT INTO jobs (id, status, created_at, updated_at,"
                " output_path, output_name, error, temp_dir)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def test_legacy_jobs_table_is_copied_and_dropped(self):
        self._write_legacy_jobs(
            [
                (
                    "meeting-1",
                    "done",
                    T0.isoformat(),
                    T1.isoformat(),
                    "/tmp/meeting-1/clip.wav.flac",
                    "clip.wav.flac",
                    None,
                    "/tmp/meeting-1",
                )
            ]
        )
        store = JobStore(self.db_path)
        job = store.get("meeting-1")
        self.assertEqual(job["job_id"], "meeting-1")
        self.assertEqual(job["job_status"], "done")
        self.assertEqual(job["output_name"], "clip.wav.flac")
        self.assertEqual(job["error_message"], None)
        conn = sqlite3.connect(self.db_path)
        try:
            tables = _list_user_tables(conn)
            self.assertIn("conversion_jobs", tables)
            self.assertNotIn("jobs", tables)
            self.assertEqual(
                _list_table_columns(conn, "conversion_jobs"),
                (
                    "job_id",
                    "job_status",
                    "created_at",
                    "updated_at",
                    "output_path",
                    "output_name",
                    "error_message",
                    "temp_dir",
                ),
            )
        finally:
            conn.close()

    def test_legacy_and_current_rows_do_not_overwrite(self):
        self._write_legacy_jobs(
            [
                (
                    "shared",
                    "failed",
                    T0.isoformat(),
                    T0.isoformat(),
                    None,
                    None,
                    "old",
                    "/tmp/old",
                )
            ]
        )
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "CREATE TABLE conversion_jobs ("
                " job_id TEXT PRIMARY KEY,"
                " job_status TEXT NOT NULL,"
                " created_at TEXT NOT NULL,"
                " updated_at TEXT NOT NULL,"
                " output_path TEXT,"
                " output_name TEXT,"
                " error_message TEXT,"
                " temp_dir TEXT)"
            )
            conn.execute(
                "INSERT INTO conversion_jobs (job_id, job_status,"
                " created_at, updated_at, temp_dir)"
                " VALUES (?, 'queued', ?, ?, ?)",
                ("shared", T1.isoformat(), T1.isoformat(), "/tmp/new"),
            )
            conn.commit()
        finally:
            conn.close()

        store = JobStore(self.db_path)
        job = store.get("shared")
        self.assertEqual(job["job_status"], "queued")
        self.assertEqual(job["temp_dir"], "/tmp/new")
        self.assertIsNone(job["error_message"])

    def test_unexpected_legacy_columns_fail_closed(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, note TEXT)")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(ValueError) as caught:
            JobStore(self.db_path)
        self.assertIn("unexpected columns", str(caught.exception))

    def test_inspect_helpers_reject_unknown_table(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("CREATE TABLE conversion_jobs (job_id TEXT)")
            with self.assertRaises(ValueError):
                _list_table_columns(conn, "sqlite_master")
            self.assertEqual(_LEGACY_JOBS_COLUMNS[0], "id")
            _migrate_legacy_jobs_table(conn)
        finally:
            conn.close()


class TestConcurrency(JobStoreTestCase):
    def test_concurrent_set_status_is_consistent(self):
        num_jobs = 8
        num_threads = 8
        for i in range(num_jobs):
            self.store.create(f"job-{i}", temp_dir=f"/tmp/{i}", now=T0)

        errors = []
        barrier = threading.Barrier(num_threads)

        def worker(thread_idx):
            try:
                barrier.wait(timeout=10)
                for i in range(num_jobs):
                    status = "done" if (i + thread_idx) % 2 else "processing"
                    self.store.set_status(f"job-{i}", status, now=T1)
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(t,))
            for t in range(num_threads)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        for i in range(num_jobs):
            job = self.store.get(f"job-{i}")
            # Every job ends in exactly one of the two written states,
            # with the updated timestamp applied — no torn writes.
            self.assertIn(job["job_status"], {"processing", "done"})
            self.assertEqual(job["updated_at"], T1.isoformat())
            self.assertEqual(job["created_at"], T0.isoformat())


if __name__ == "__main__":
    unittest.main()
