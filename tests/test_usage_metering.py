"""Tests for usage_metering: durable per-key usage counters and monthly quotas.

All tests use a temporary SQLite file and inject `now` explicitly, so they are
deterministic and touch no network.
"""

import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from usage_metering import QuotaExceededError, UsageStore

JAN = datetime(2026, 1, 15, 12, 0, 0)
JAN_LATER = datetime(2026, 1, 28, 23, 59, 59)
FEB = datetime(2026, 2, 1, 0, 0, 0)


class UsageStoreTestCase(unittest.TestCase):
    """Base fixture: a fresh UsageStore on a tmp sqlite file per test."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = Path(self._tmpdir.name) / "usage.db"
        self.store = UsageStore(self.db_path)


class TestRecordAndUsage(UsageStoreTestCase):
    """record() accumulates within a period; periods are independent."""

    def test_record_accumulates_within_period(self):
        self.store.record("key-a", input_bytes=100, output_bytes=40, now=JAN)
        self.store.record("key-a", input_bytes=200, output_bytes=60, now=JAN_LATER)
        got = self.store.usage("key-a", JAN)
        self.assertEqual(
            got,
            {
                "period": "2026-01",
                "conversions": 2,
                "input_bytes": 300,
                "output_bytes": 100,
            },
        )

    def test_new_period_starts_fresh(self):
        self.store.record("key-a", input_bytes=100, output_bytes=40, now=JAN)
        got = self.store.usage("key-a", FEB)
        self.assertEqual(
            got,
            {
                "period": "2026-02",
                "conversions": 0,
                "input_bytes": 0,
                "output_bytes": 0,
            },
        )
        # January's totals are untouched.
        self.assertEqual(self.store.usage("key-a", JAN)["conversions"], 1)

    def test_unknown_key_reports_zero_usage(self):
        got = self.store.usage("never-seen", JAN)
        self.assertEqual(
            got,
            {
                "period": "2026-01",
                "conversions": 0,
                "input_bytes": 0,
                "output_bytes": 0,
            },
        )

    def test_keys_are_isolated(self):
        self.store.record("key-a", input_bytes=10, output_bytes=5, now=JAN)
        self.store.record("key-b", input_bytes=99, output_bytes=1, now=JAN)
        self.assertEqual(self.store.usage("key-a", JAN)["input_bytes"], 10)
        self.assertEqual(self.store.usage("key-b", JAN)["input_bytes"], 99)

    def test_negative_bytes_rejected(self):
        with self.assertRaises(ValueError):
            self.store.record("key-a", input_bytes=-1, output_bytes=0, now=JAN)
        with self.assertRaises(ValueError):
            self.store.record("key-a", input_bytes=0, output_bytes=-1, now=JAN)

    def test_usage_survives_reopen(self):
        self.store.record("key-a", input_bytes=7, output_bytes=3, now=JAN)
        reopened = UsageStore(self.db_path)
        self.assertEqual(reopened.usage("key-a", JAN)["conversions"], 1)


class TestQuota(UsageStoreTestCase):
    """check_quota() allows under the limit and denies at the boundary."""

    def test_allowed_under_limit(self):
        self.store.record("key-a", input_bytes=10, output_bytes=10, now=JAN)
        self.assertTrue(
            self.store.check_quota(
                "key-a", JAN, max_conversions=2, max_bytes=100
            )
        )

    def test_unlimited_when_no_limits_given(self):
        for _ in range(50):
            self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        self.assertTrue(self.store.check_quota("key-a", JAN))

    def test_denied_at_conversion_boundary(self):
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota("key-a", JAN, max_conversions=2)
        self.assertEqual(ctx.exception.limit_name, "max_conversions")
        self.assertEqual(ctx.exception.limit, 2)
        self.assertEqual(ctx.exception.used, 2)
        self.assertEqual(ctx.exception.api_key, "key-a")

    def test_allowed_one_below_conversion_boundary(self):
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        self.assertTrue(self.store.check_quota("key-a", JAN, max_conversions=2))

    def test_denied_at_byte_boundary(self):
        # 60 + 40 = 100 total bytes, exactly at the limit -> denied.
        self.store.record("key-a", input_bytes=60, output_bytes=40, now=JAN)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota("key-a", JAN, max_bytes=100)
        self.assertEqual(ctx.exception.limit_name, "max_bytes")
        self.assertEqual(ctx.exception.used, 100)

    def test_allowed_just_below_byte_boundary(self):
        self.store.record("key-a", input_bytes=60, output_bytes=39, now=JAN)
        self.assertTrue(self.store.check_quota("key-a", JAN, max_bytes=100))

    def test_error_message_names_the_limit(self):
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota("key-a", JAN, max_conversions=1)
        self.assertIn("max_conversions", str(ctx.exception))
        self.assertIn("key-a", str(ctx.exception))

    def test_quota_resets_in_new_period(self):
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        with self.assertRaises(QuotaExceededError):
            self.store.check_quota("key-a", JAN, max_conversions=1)
        self.assertTrue(self.store.check_quota("key-a", FEB, max_conversions=1))

    def test_unknown_key_always_allowed(self):
        self.assertTrue(
            self.store.check_quota("never-seen", JAN, max_conversions=1, max_bytes=1)
        )


class TestAdminOperations(UsageStoreTestCase):
    """reset() and all_usage() admin helpers."""

    def test_reset_clears_all_periods_for_key(self):
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=JAN)
        self.store.record("key-a", input_bytes=1, output_bytes=1, now=FEB)
        self.store.record("key-b", input_bytes=5, output_bytes=5, now=JAN)
        self.store.reset("key-a")
        self.assertEqual(self.store.usage("key-a", JAN)["conversions"], 0)
        self.assertEqual(self.store.usage("key-a", FEB)["conversions"], 0)
        # Other keys are unaffected.
        self.assertEqual(self.store.usage("key-b", JAN)["conversions"], 1)

    def test_all_usage_lists_only_that_period(self):
        self.store.record("key-a", input_bytes=10, output_bytes=2, now=JAN)
        self.store.record("key-b", input_bytes=20, output_bytes=4, now=JAN)
        self.store.record("key-c", input_bytes=30, output_bytes=6, now=FEB)
        got = self.store.all_usage("2026-01")
        self.assertEqual(
            got,
            {
                "key-a": {"conversions": 1, "input_bytes": 10, "output_bytes": 2},
                "key-b": {"conversions": 1, "input_bytes": 20, "output_bytes": 4},
            },
        )

    def test_all_usage_empty_period(self):
        self.assertEqual(self.store.all_usage("1999-12"), {})


class TestConcurrency(UsageStoreTestCase):
    """Concurrent record() calls from many threads must sum correctly."""

    def test_concurrent_records_sum_correctly(self):
        threads_n, per_thread = 8, 25

        def worker():
            for _ in range(per_thread):
                self.store.record("key-a", input_bytes=3, output_bytes=2, now=JAN)

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        got = self.store.usage("key-a", JAN)
        total = threads_n * per_thread
        self.assertEqual(got["conversions"], total)
        self.assertEqual(got["input_bytes"], 3 * total)
        self.assertEqual(got["output_bytes"], 2 * total)


class TestMalformedDbPath(unittest.TestCase):
    """Constructor errors are clear for bad paths."""

    def test_missing_parent_directory(self):
        with self.assertRaises(ValueError) as ctx:
            UsageStore("/nonexistent-dir-xyz/deeper/usage.db")
        self.assertIn("parent directory does not exist", str(ctx.exception))

    def test_path_is_a_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as ctx:
                UsageStore(tmpdir)
            self.assertIn("directory", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
