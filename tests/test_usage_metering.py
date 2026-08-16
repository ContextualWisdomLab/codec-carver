"""Tests for usage_metering: durable per-credential monthly quotas.

All tests use a temporary SQLite file and inject `now` explicitly, so they are
deterministic and touch no network. Identifiers are registry primary keys,
never plaintext API keys.
"""

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from usage_metering import (
    MAX_CREDENTIAL_ID_BYTES,
    QuotaExceededError,
    UsageStore,
    seconds_until_next_period,
)

JAN = datetime(2026, 1, 15, 12, 0, 0)
JAN_LATER = datetime(2026, 1, 28, 23, 59, 59)
FEB = datetime(2026, 2, 1, 0, 0, 0)
DEC = datetime(2026, 12, 31, 23, 0, 0, tzinfo=timezone.utc)

CRED_A = "cred-acme-stt"
CRED_B = "cred-partner-ingest"


class UsageStoreTestCase(unittest.TestCase):
    """Base fixture: a fresh UsageStore on a tmp sqlite file per test."""

    def setUp(self):
        """Create an isolated on-disk store for one test."""

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = Path(self._tmpdir.name) / "usage.db"
        self.store = UsageStore(self.db_path)


class TestRecordAndUsage(UsageStoreTestCase):
    """record() accumulates within a period; periods are independent."""

    def test_record_accumulates_within_period(self):
        """Two January meeting uploads add on the same invoice row."""

        self.store.record(CRED_A, input_bytes=100, output_bytes=40, now=JAN)
        self.store.record(CRED_A, input_bytes=200, output_bytes=60, now=JAN_LATER)
        got = self.store.usage(CRED_A, JAN)
        self.assertEqual(
            got,
            {
                "billing_period": "2026-01",
                "conversions": 2,
                "input_bytes": 300,
                "output_bytes": 100,
            },
        )

    def test_new_period_starts_fresh(self):
        """February billing does not inherit January conversion count."""

        self.store.record(CRED_A, input_bytes=100, output_bytes=40, now=JAN)
        got = self.store.usage(CRED_A, FEB)
        self.assertEqual(
            got,
            {
                "billing_period": "2026-02",
                "conversions": 0,
                "input_bytes": 0,
                "output_bytes": 0,
            },
        )
        self.assertEqual(self.store.usage(CRED_A, JAN)["conversions"], 1)

    def test_unknown_credential_reports_zero_usage(self):
        """A never-seen contractor credential shows an empty January invoice."""

        got = self.store.usage("cred-never-seen", JAN)
        self.assertEqual(
            got,
            {
                "billing_period": "2026-01",
                "conversions": 0,
                "input_bytes": 0,
                "output_bytes": 0,
            },
        )

    def test_credentials_are_isolated(self):
        """Acme and a partner do not share byte totals."""

        self.store.record(CRED_A, input_bytes=10, output_bytes=5, now=JAN)
        self.store.record(CRED_B, input_bytes=99, output_bytes=1, now=JAN)
        self.assertEqual(self.store.usage(CRED_A, JAN)["input_bytes"], 10)
        self.assertEqual(self.store.usage(CRED_B, JAN)["input_bytes"], 99)

    def test_negative_bytes_rejected(self):
        """Negative sizes are operator errors, not silent undercounts."""

        with self.assertRaises(ValueError):
            self.store.record(CRED_A, input_bytes=-1, output_bytes=0, now=JAN)
        with self.assertRaises(ValueError):
            self.store.record(CRED_A, input_bytes=0, output_bytes=-1, now=JAN)

    def test_usage_survives_reopen(self):
        """A worker restart still sees the recorded conversion."""

        self.store.record(CRED_A, input_bytes=7, output_bytes=3, now=JAN)
        reopened = UsageStore(self.db_path)
        self.assertEqual(reopened.usage(CRED_A, JAN)["conversions"], 1)

    def test_ninety_minute_meeting_is_one_conversion(self):
        """A 90-minute 32 kB/s meeting upload is one billed conversion."""

        meeting_bytes = 90 * 60 * 32_000
        flac_bytes = 40 * 1024 * 1024
        self.store.record(
            CRED_A, input_bytes=meeting_bytes, output_bytes=flac_bytes, now=JAN
        )
        got = self.store.usage(CRED_A, JAN)
        self.assertEqual(got["conversions"], 1)
        self.assertEqual(got["input_bytes"], meeting_bytes)
        self.assertEqual(got["output_bytes"], flac_bytes)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota(CRED_A, JAN, max_conversions=1)
        self.assertEqual(ctx.exception.credential_id, CRED_A)
        self.assertTrue(self.store.check_quota(CRED_A, FEB, max_conversions=1))


class TestQuota(UsageStoreTestCase):
    """check_quota() allows under the limit and denies at the boundary."""

    def test_allowed_under_limit(self):
        """One of two allowed conversions still proceeds."""

        self.store.record(CRED_A, input_bytes=10, output_bytes=10, now=JAN)
        self.assertTrue(
            self.store.check_quota(CRED_A, JAN, max_conversions=2, max_bytes=100)
        )

    def test_unlimited_when_no_limits_given(self):
        """Unset limits mean a busy ingest day is not blocked."""

        for _ in range(50):
            self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        self.assertTrue(self.store.check_quota(CRED_A, JAN))

    def test_denied_at_conversion_boundary(self):
        """The second of two allowed conversions is the last; a third is 429."""

        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota(CRED_A, JAN, max_conversions=2)
        self.assertEqual(ctx.exception.limit_name, "max_conversions")
        self.assertEqual(ctx.exception.limit, 2)
        self.assertEqual(ctx.exception.used, 2)
        self.assertEqual(ctx.exception.credential_id, CRED_A)

    def test_allowed_one_below_conversion_boundary(self):
        """Exactly one conversion remains on a two-conversion plan."""

        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        self.assertTrue(self.store.check_quota(CRED_A, JAN, max_conversions=2))

    def test_denied_at_byte_boundary(self):
        """60 + 40 = 100 total bytes, exactly at the limit, is denied."""

        self.store.record(CRED_A, input_bytes=60, output_bytes=40, now=JAN)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota(CRED_A, JAN, max_bytes=100)
        self.assertEqual(ctx.exception.limit_name, "max_bytes")
        self.assertEqual(ctx.exception.used, 100)

    def test_allowed_just_below_byte_boundary(self):
        """99 of 100 billed bytes still allows another conversion."""

        self.store.record(CRED_A, input_bytes=60, output_bytes=39, now=JAN)
        self.assertTrue(self.store.check_quota(CRED_A, JAN, max_bytes=100))

    def test_error_message_names_the_limit_not_a_secret(self):
        """Quota errors name the credential id and must not look like keys."""

        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        with self.assertRaises(QuotaExceededError) as ctx:
            self.store.check_quota(CRED_A, JAN, max_conversions=1)
        self.assertIn("max_conversions", str(ctx.exception))
        self.assertIn(CRED_A, str(ctx.exception))
        self.assertNotIn("api_key", str(ctx.exception))

    def test_quota_resets_in_new_period(self):
        """A January cap does not block the February invoice period."""

        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        with self.assertRaises(QuotaExceededError):
            self.store.check_quota(CRED_A, JAN, max_conversions=1)
        self.assertTrue(self.store.check_quota(CRED_A, FEB, max_conversions=1))

    def test_unknown_credential_always_allowed(self):
        """A new credential has not consumed any of a 1-conversion plan."""

        self.assertTrue(
            self.store.check_quota(
                "cred-never-seen", JAN, max_conversions=1, max_bytes=1
            )
        )


class TestAdminOperations(UsageStoreTestCase):
    """reset() and all_usage() admin helpers."""

    def test_reset_clears_all_periods_for_credential(self):
        """A billing dispute wipe removes only that credential."""

        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=JAN)
        self.store.record(CRED_A, input_bytes=1, output_bytes=1, now=FEB)
        self.store.record(CRED_B, input_bytes=5, output_bytes=5, now=JAN)
        self.store.reset(CRED_A)
        self.assertEqual(self.store.usage(CRED_A, JAN)["conversions"], 0)
        self.assertEqual(self.store.usage(CRED_A, FEB)["conversions"], 0)
        self.assertEqual(self.store.usage(CRED_B, JAN)["conversions"], 1)

    def test_all_usage_lists_only_that_period(self):
        """January export omits February rows and uses credential ids."""

        self.store.record(CRED_A, input_bytes=10, output_bytes=2, now=JAN)
        self.store.record(CRED_B, input_bytes=20, output_bytes=4, now=JAN)
        self.store.record("cred-other", input_bytes=30, output_bytes=6, now=FEB)
        got = self.store.all_usage("2026-01")
        self.assertEqual(
            got,
            {
                CRED_A: {"conversions": 1, "input_bytes": 10, "output_bytes": 2},
                CRED_B: {"conversions": 1, "input_bytes": 20, "output_bytes": 4},
            },
        )

    def test_all_usage_empty_period(self):
        """An unused month exports an empty billing map."""

        self.assertEqual(self.store.all_usage("1999-12"), {})


class TestConcurrency(UsageStoreTestCase):
    """Concurrent record() calls from many threads must sum correctly."""

    def test_concurrent_records_sum_correctly(self):
        """Eight workers each recording 25 meetings total 200 conversions."""

        threads_n, per_thread = 8, 25

        def worker():
            """Record one worker's share of meeting uploads."""

            for _ in range(per_thread):
                self.store.record(CRED_A, input_bytes=3, output_bytes=2, now=JAN)

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        got = self.store.usage(CRED_A, JAN)
        total = threads_n * per_thread
        self.assertEqual(got["conversions"], total)
        self.assertEqual(got["input_bytes"], 3 * total)
        self.assertEqual(got["output_bytes"], 2 * total)


class TestMalformedDbPath(unittest.TestCase):
    """Constructor errors are clear for bad paths."""

    def test_missing_parent_directory(self):
        """A missing parent directory fails before sqlite's opaque error."""

        with self.assertRaises(ValueError) as ctx:
            UsageStore("/nonexistent-dir-xyz/deeper/usage.db")
        self.assertIn("parent directory does not exist", str(ctx.exception))

    def test_path_is_a_directory(self):
        """Passing a directory is a configuration error."""

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as ctx:
                UsageStore(tmpdir)
            self.assertIn("directory", str(ctx.exception))

    def test_memory_path_rejected(self):
        """In-memory sqlite would drop every short-lived connection."""

        with self.assertRaises(ValueError) as ctx:
            UsageStore(":memory:")
        self.assertIn(":memory:", str(ctx.exception))


class TestIdentifierAndSchema(UsageStoreTestCase):
    """Identifiers stay non-secret; schema uses two-word names."""

    def test_empty_and_control_ids_rejected(self):
        """Hostile or empty handles never become billing keys."""

        for bad in ("", None, "cred\x00hidden", "x" * (MAX_CREDENTIAL_ID_BYTES + 1)):
            with self.assertRaises(ValueError):
                self.store.record(bad, input_bytes=1, output_bytes=1, now=JAN)

    def test_schema_uses_two_word_table(self):
        """Org naming: usage_periods, not a single-word usage table."""

        with sqlite3.connect(self.db_path) as conn:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("usage_periods", names)
        self.assertNotIn("usage", names)

    def test_repr_is_redacted(self):
        """Repr names the file, not a credential or API key."""

        text = repr(self.store)
        self.assertIn("UsageStore", text)
        self.assertIn(str(self.db_path), text)
        self.assertNotIn(CRED_A, text)

    def test_seconds_until_next_period_crosses_year(self):
        """A 31 December customer is told to retry after 1 January."""

        seconds = seconds_until_next_period(DEC)
        self.assertEqual(seconds, 3600)
        mid_month = seconds_until_next_period(JAN)
        self.assertGreater(mid_month, 1)


if __name__ == "__main__":
    unittest.main()
