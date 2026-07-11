"""Tests for the SQLite-backed durable job store (job_store.py)."""

import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from job_store import DuplicateJobError, JobStore

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)


class JobStoreTestCase(unittest.TestCase):
    """Base fixture: a fresh JobStore on a temp SQLite file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "jobs.db")
        self.store = JobStore(self.db_path)


class TestCreateAndGet(JobStoreTestCase):
    def test_create_get_roundtrip(self):
        self.store.create("job-1", temp_dir="/tmp/job-1", now=T0)
        job = self.store.get("job-1")
        self.assertEqual(
            job,
            {
                "id": "job-1",
                "status": "queued",
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
                "output_path": None,
                "output_name": None,
                "error": None,
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
        self.assertEqual(job["status"], "processing")
        self.assertEqual(job["created_at"], T0.isoformat())
        self.assertEqual(job["updated_at"], T1.isoformat())

        self.store.set_status(
            "job-1", "done", now=T2,
            output_path="/tmp/out.mp4", output_name="video.mp4",
        )
        job = self.store.get("job-1")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["updated_at"], T2.isoformat())
        self.assertEqual(job["output_path"], "/tmp/out.mp4")
        self.assertEqual(job["output_name"], "video.mp4")
        self.assertIsNone(job["error"])

    def test_failed_records_error(self):
        self.store.create("job-1", temp_dir="/tmp/j", now=T0)
        self.store.set_status("job-1", "failed", now=T1, error="boom")
        job = self.store.get("job-1")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "boom")

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
        self.assertEqual(self.store.get("job-1")["status"], "queued")

    def test_unknown_job_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.store.set_status("ghost", "done", now=T0)


class TestListAndDelete(JobStoreTestCase):
    def test_list_all_and_filter_by_status(self):
        self.store.create("a", temp_dir="/tmp/a", now=T0)
        self.store.create("b", temp_dir="/tmp/b", now=T1)
        self.store.create("c", temp_dir="/tmp/c", now=T2)
        self.store.set_status("b", "processing", now=T2)

        all_ids = [job["id"] for job in self.store.list_jobs()]
        self.assertEqual(all_ids, ["a", "b", "c"])

        queued = [job["id"] for job in self.store.list_jobs(status="queued")]
        self.assertEqual(queued, ["a", "c"])

        processing = self.store.list_jobs(status="processing")
        self.assertEqual([job["id"] for job in processing], ["b"])

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
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["output_path"], "/tmp/out.mp4")
        self.assertEqual(job["output_name"], "video.mp4")
        self.assertEqual(job["created_at"], T0.isoformat())
        self.assertEqual(job["updated_at"], T1.isoformat())


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
            self.assertIn(job["status"], {"processing", "done"})
            self.assertEqual(job["updated_at"], T1.isoformat())
            self.assertEqual(job["created_at"], T0.isoformat())


if __name__ == "__main__":
    unittest.main()
