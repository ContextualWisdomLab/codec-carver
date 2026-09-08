"""Browser/server media-type admission contract for the upload UI."""

import unittest

import saas_web


class TestClientMediaTypeAdmission(unittest.TestCase):
    """Keep advisory browser MIME evidence aligned with server admission."""

    def test_unknown_browser_mime_is_not_rejected_before_server_decode(self):
        """An empty File.type is unknown evidence, not a non-media verdict."""
        html = saas_web.HTML_TEMPLATE

        self.assertIn(
            "if (file.type && !file.type.startsWith('audio/') && "
            "!file.type.startsWith('video/'))",
            html,
        )
        self.assertIn(
            "if (files[i].type && !files[i].type.startsWith('audio/') && "
            "!files[i].type.startsWith('video/'))",
            html,
        )

    def test_server_also_treats_missing_declared_mime_as_unknown(self):
        """The backend may continue to bounded decoder validation when MIME is absent."""

        class Upload:
            filename = "recording.bin"
            content_type = ""

        self.assertIsNone(saas_web._validate_request(Upload(), 1024))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
