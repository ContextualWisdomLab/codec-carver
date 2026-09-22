import re
import unittest

try:
    from fastapi.testclient import TestClient

    from saas_web import app

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "fastapi not installed")
class TestSaasWebUiValidationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TestClient(app).get("/").text

    def _listener_body(self, input_id: str, next_marker: str) -> str:
        pattern = re.compile(
            rf"document\.getElementById\('{re.escape(input_id)}'\)\.addEventListener\('input'.*?(?={re.escape(next_marker)})",
            re.DOTALL,
        )
        match = pattern.search(self.html)
        self.assertIsNotNone(match, f"missing input listener for {input_id}")
        return match.group(0)

    def test_bad_input_is_fail_closed_for_single_and_batch_target_bytes(self):
        single = self._listener_body(
            "target_bytes", "document.getElementById('batch_target_bytes')"
        )
        batch = self._listener_body(
            "batch_target_bytes", "document.getElementById('shrink-form')"
        )

        for input_id, body in (("target_bytes", single), ("batch_target_bytes", batch)):
            with self.subTest(input_id=input_id):
                self.assertIn("this.validity && this.validity.badInput", body)
                self.assertIn("Must be a valid number.", body)
                self.assertIn("this.setAttribute('aria-invalid', 'true')", body)

    def test_file_type_feedback_exists_for_single_and_batch_uploads(self):
        self.assertGreaterEqual(
            self.html.count(
                "!file.type.startsWith('audio/') && !file.type.startsWith('video/')"
            ),
            2,
        )
        self.assertIn("Selected file is not an audio or video file.", self.html)
        self.assertIn("One or more selected files are not audio or video files.", self.html)


if __name__ == "__main__":
    unittest.main()
