"""Regression contracts for semantic durable-job naming and migration."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from job_store import JobStore

NOW = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)


class TestJobStoreNamingContract(unittest.TestCase):
    """Pin organization-owned SQLite and Python job vocabulary."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "jobs.sqlite3")

    def test_new_store_uses_semantic_table_columns_and_record_keys(self) -> None:
        """Require qualified names in both persisted and Python-owned records."""

        store = JobStore(self.db_path)
        store.create("job-1", temp_dir="/tmp/job-1", now=NOW)

        with sqlite3.connect(self.db_path) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            column_names = {
                row[1]
                for row in connection.execute("PRAGMA table_info(job_record)")
            }

        self.assertIn("job_record", table_names)
        self.assertNotIn("jobs", table_names)
        self.assertIn("job_id", column_names)
        self.assertIn("job_status", column_names)
        self.assertIn("error_message", column_names)
        self.assertNotIn("id", column_names)
        self.assertNotIn("status", column_names)
        self.assertNotIn("error", column_names)

        job_record = store.get("job-1")
        self.assertEqual(job_record["job_id"], "job-1")
        self.assertEqual(job_record["job_status"], "queued")
        self.assertIsNone(job_record["error_message"])
        self.assertNotIn("id", job_record)
        self.assertNotIn("status", job_record)
        self.assertNotIn("error", job_record)

    def test_legacy_jobs_schema_migrates_in_place_without_data_loss(self) -> None:
        """Upgrade the historical table/columns while preserving durable rows."""

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    output_path TEXT,
                    output_name TEXT,
                    error TEXT,
                    temp_dir TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, created_at, updated_at,
                    output_path, output_name, error, temp_dir
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-job",
                    "failed",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    None,
                    None,
                    "legacy failure",
                    "/tmp/legacy-job",
                ),
            )

        store = JobStore(self.db_path)
        migrated_record = store.get("legacy-job")

        self.assertEqual(migrated_record["job_id"], "legacy-job")
        self.assertEqual(migrated_record["job_status"], "failed")
        self.assertEqual(migrated_record["error_message"], "legacy failure")

        with sqlite3.connect(self.db_path) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            row_count = connection.execute(
                "SELECT COUNT(*) FROM job_record"
            ).fetchone()[0]

        self.assertIn("job_record", table_names)
        self.assertNotIn("jobs", table_names)
        self.assertEqual(row_count, 1)

    def test_job_status_and_error_message_are_canonical_update_keywords(self) -> None:
        """Keep the organization-owned update API semantically qualified."""

        store = JobStore(self.db_path)
        store.create("job-1", temp_dir="/tmp/job-1", now=NOW)
        store.set_status(
            "job-1",
            job_status="failed",
            now=NOW,
            error_message="processing failed",
        )

        job_record = store.get("job-1")
        self.assertEqual(job_record["job_status"], "failed")
        self.assertEqual(job_record["error_message"], "processing failed")


if __name__ == "__main__":
    unittest.main()
