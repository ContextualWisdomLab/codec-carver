import unittest

try:
    from fastapi.testclient import TestClient

    from saas_web import app

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
class UploadMimeUxContractTests(unittest.TestCase):
    """Rendered-page contract for browser MIME uncertainty."""

    def test_unknown_browser_mime_is_not_silently_treated_as_verified_media(self) -> None:
        """An empty File.type must receive explicit, non-blocking server-validation copy."""
        html = TestClient(app).get("/").text

        self.assertIn("if (!file.type)", html)
        self.assertIn(
            "File type could not be identified; it will be validated after upload.",
            html,
        )


if __name__ == "__main__":
    unittest.main()
