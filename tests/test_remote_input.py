"""Tests for remote_input.fetch_media -- fully offline, no network.

DNS resolution is faked by patching ``remote_input.socket.getaddrinfo`` and
HTTP responses are faked by patching ``remote_input._build_opener``, so every
SSRF guard is exercised without a single real socket.
"""

import socket
import sys
import tempfile
import http.client
import io
import urllib.error
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import remote_input
from remote_input import RemoteInputError, fetch_media

PUBLIC_ADDRINFO = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
]


def _addrinfo(ip):
    """Build a fake getaddrinfo result resolving to a single address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


class FakeResponse:
    """Minimal stand-in for the object returned by opener.open()."""

    def __init__(self, chunks, headers=None):
        """Store the chunk sequence and optional header dict."""
        self._chunks = list(chunks)
        self.headers = headers or {}
        self.closed = False

    def read(self, size=-1):
        """Return the next chunk, or b'' when exhausted."""
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def close(self):
        """Record that the response was closed."""
        self.closed = True

    def __enter__(self):
        """Support use as a context manager, like urllib responses."""
        return self

    def __exit__(self, *exc_info):
        """Close on context-manager exit."""
        self.close()
        return False


class FakeOpener:
    """Opener double whose open() returns a canned response or raises."""

    def __init__(self, response=None, error=None):
        """Store the canned response or the exception to raise."""
        self._response = response
        self._error = error
        self.calls = []

    def open(self, url, timeout=None):
        """Record the call, then raise or return the canned response."""
        self.calls.append((url, timeout))
        if self._error is not None:
            raise self._error
        return self._response


class SchemeRejectionTests(unittest.TestCase):
    """Only https may pass the scheme allowlist."""

    def _assert_rejected(self, url):
        """Assert fetch_media rejects *url* mentioning the scheme policy."""
        with self.assertRaises(RemoteInputError) as ctx:
            fetch_media(url, tempfile.gettempdir())
        self.assertIn("https", str(ctx.exception))

    def test_http_rejected(self):
        """Plain http is refused."""
        self._assert_rejected("http://example.com/file.mp4")

    def test_file_rejected(self):
        """file:// URLs (local file read) are refused."""
        self._assert_rejected("file:///etc/passwd")

    def test_ftp_rejected(self):
        """ftp:// URLs are refused."""
        self._assert_rejected("ftp://example.com/file.mp4")

    def test_data_rejected(self):
        """data: URLs are refused."""
        self._assert_rejected("data:text/plain;base64,aGk=")

    def test_schemeless_rejected(self):
        """A URL with no scheme at all is refused."""
        self._assert_rejected("example.com/file.mp4")

    def test_credentials_rejected(self):
        """https URLs with embedded user:pass are refused."""
        with self.assertRaises(RemoteInputError) as ctx:
            fetch_media("https://user:pw@example.com/a.mp4", tempfile.gettempdir())
        self.assertIn("credential", str(ctx.exception))

    def test_malformed_url_rejected(self):
        """Unparseable URLs produce RemoteInputError, not ValueError."""
        with self.assertRaises(RemoteInputError) as ctx:
            fetch_media("https://[::1", tempfile.gettempdir())
        self.assertIn("could not be parsed", str(ctx.exception))

    def test_invalid_hostname_property_rejected(self):
        """Late hostname parser errors are wrapped as RemoteInputError."""
        class Parsed:
            scheme = "https"
            username = None
            password = None

            @property
            def hostname(self):
                raise ValueError("bad host")

        with mock.patch.object(
            remote_input.urllib.parse,
            "urlsplit",
            return_value=Parsed(),
        ):
            with self.assertRaises(RemoteInputError) as ctx:
                fetch_media("https://bad.example/a.mp4", tempfile.gettempdir())
        self.assertIn("invalid host", str(ctx.exception))

    def test_missing_hostname_rejected(self):
        """A URL with an empty authority is rejected before DNS lookup."""
        with self.assertRaises(RemoteInputError) as ctx:
            fetch_media("https:///missing-host.mp4", tempfile.gettempdir())
        self.assertIn("no hostname", str(ctx.exception))


class AddressRejectionTests(unittest.TestCase):
    """Private, loopback, link-local and localhost targets are refused."""

    def test_localhost_rejected(self):
        """The literal hostname localhost never resolves."""
        with self.assertRaises(RemoteInputError) as ctx:
            fetch_media("https://localhost/a.mp4", tempfile.gettempdir())
        self.assertIn("localhost", str(ctx.exception))

    def test_localhost_subdomain_rejected(self):
        """*.localhost is refused just like localhost."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://foo.localhost/a.mp4", tempfile.gettempdir())

    def test_numeric_loopback_rejected(self):
        """A numeric 127.0.0.1 URL is refused without any DNS lookup."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://127.0.0.1/a.mp4", tempfile.gettempdir())

    def test_numeric_private_rejected(self):
        """A numeric RFC 1918 address is refused."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://192.168.1.5/a.mp4", tempfile.gettempdir())

    def test_numeric_link_local_rejected(self):
        """The cloud metadata address 169.254.169.254 is refused."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://169.254.169.254/latest/meta", tempfile.gettempdir())

    def test_ipv6_loopback_rejected(self):
        """The IPv6 loopback literal [::1] is refused."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://[::1]/a.mp4", tempfile.gettempdir())

    def test_ipv4_mapped_ipv6_loopback_rejected(self):
        """An IPv4-mapped IPv6 loopback literal is unwrapped and refused."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://[::ffff:127.0.0.1]/a.mp4", tempfile.gettempdir())

    def test_hostname_resolving_to_private_rejected(self):
        """A hostname whose DNS answer is private is refused (rebind guard)."""
        for ip in ("10.0.0.8", "172.16.4.4", "192.168.0.2", "127.0.0.1"):
            with mock.patch.object(
                remote_input.socket, "getaddrinfo", return_value=_addrinfo(ip)
            ):
                with self.assertRaises(RemoteInputError) as ctx:
                    fetch_media("https://evil.example/a.mp4", tempfile.gettempdir())
                self.assertIn(ip, str(ctx.exception))

    def test_hostname_with_one_private_answer_rejected(self):
        """If ANY resolved address is private, the whole host is refused."""
        infos = _addrinfo("93.184.216.34") + _addrinfo("10.0.0.8")
        with mock.patch.object(
            remote_input.socket, "getaddrinfo", return_value=infos
        ):
            with self.assertRaises(RemoteInputError):
                fetch_media("https://mixed.example/a.mp4", tempfile.gettempdir())

    def test_unresolvable_hostname_rejected(self):
        """A DNS failure surfaces as a clear RemoteInputError."""
        with mock.patch.object(
            remote_input.socket,
            "getaddrinfo",
            side_effect=socket.gaierror("no such host"),
        ):
            with self.assertRaises(RemoteInputError) as ctx:
                fetch_media("https://nope.example/a.mp4", tempfile.gettempdir())
            self.assertIn("resolve", str(ctx.exception))

    def test_empty_host_helper_rejected(self):
        """The lower-level host validator rejects empty hostnames clearly."""
        with self.assertRaises(RemoteInputError) as ctx:
            remote_input._validate_host("")
        self.assertIn("empty hostname", str(ctx.exception))

    def test_public_numeric_ip_needs_no_dns_lookup(self):
        """A global numeric IP literal passes without DNS resolution."""
        with mock.patch.object(remote_input.socket, "getaddrinfo") as getaddrinfo:
            remote_input._validate_host("93.184.216.34")
        getaddrinfo.assert_not_called()

    def test_hostname_with_no_dns_answers_rejected(self):
        """An empty DNS answer is rejected before fetching."""
        with mock.patch.object(
            remote_input.socket,
            "getaddrinfo",
            return_value=[],
        ):
            with self.assertRaises(RemoteInputError) as ctx:
                remote_input._validate_host("empty.example")
        self.assertIn("no addresses", str(ctx.exception))


class RedirectRefusalTests(unittest.TestCase):
    """Redirects must raise, never be followed."""

    def test_redirect_request_raises(self):
        """The handler's redirect_request hook raises RemoteInputError."""
        handler = remote_input._RedirectRefusalHandler()
        with self.assertRaises(RemoteInputError) as ctx:
            handler.redirect_request(
                mock.Mock(), mock.Mock(), 302, "Found", {},
                "https://10.0.0.5/internal",
            )
        self.assertIn("redirect", str(ctx.exception).lower())

    def test_redirect_during_fetch_leaves_no_file(self):
        """A refused redirect propagates and no file is created."""
        refusal = RemoteInputError("Refusing to follow HTTP 302 redirect")
        opener = FakeOpener(error=refusal)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                remote_input.socket,
                "getaddrinfo",
                return_value=PUBLIC_ADDRINFO,
            ), mock.patch.object(
                remote_input, "_build_opener", return_value=opener
            ):
                with self.assertRaises(RemoteInputError):
                    fetch_media("https://example.com/a.mp4", tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_opener_contains_refusal_handler(self):
        """The real opener is built with the redirect-refusing handler."""
        opener = remote_input._build_opener()
        self.assertTrue(
            any(
                isinstance(h, remote_input._RedirectRefusalHandler)
                for h in opener.handlers
            )
        )


class SizeLimitTests(unittest.TestCase):
    """max_bytes is enforced both up-front and while streaming."""

    def _patched(self, opener):
        """Return context managers patching DNS and the opener."""
        return (
            mock.patch.object(
                remote_input.socket, "getaddrinfo", return_value=PUBLIC_ADDRINFO
            ),
            mock.patch.object(remote_input, "_build_opener", return_value=opener),
        )

    def test_content_length_precheck(self):
        """An oversized Content-Length aborts before any chunk is read."""
        response = FakeResponse([b"x" * 10], headers={"Content-Length": "999"})
        opener = FakeOpener(response=response)
        dns, op = self._patched(opener)
        with tempfile.TemporaryDirectory() as tmp, dns, op:
            with self.assertRaises(RemoteInputError) as ctx:
                fetch_media("https://example.com/big.mp4", tmp, max_bytes=100)
            self.assertIn("Content-Length", str(ctx.exception))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_missing_and_malformed_content_length_are_tolerated(self):
        """Only a trustworthy oversized Content-Length is rejected early."""
        remote_input._precheck_content_length(None, 10, "https://example.com/a")
        remote_input._precheck_content_length({}, 10, "https://example.com/a")
        remote_input._precheck_content_length(
            {"Content-Length": "not-an-int"},
            10,
            "https://example.com/a",
        )

    def test_streaming_overrun_deletes_partial(self):
        """Exceeding max_bytes mid-stream aborts and deletes the partial."""
        response = FakeResponse([b"a" * 40, b"b" * 40, b"c" * 40])
        opener = FakeOpener(response=response)
        dns, op = self._patched(opener)
        with tempfile.TemporaryDirectory() as tmp, dns, op:
            with self.assertRaises(RemoteInputError) as ctx:
                fetch_media("https://example.com/big.mp4", tmp, max_bytes=100)
            self.assertIn("exceeded", str(ctx.exception))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_exact_limit_allowed(self):
        """A body of exactly max_bytes is accepted."""
        response = FakeResponse([b"a" * 50, b"b" * 50])
        opener = FakeOpener(response=response)
        dns, op = self._patched(opener)
        with tempfile.TemporaryDirectory() as tmp, dns, op:
            dest = fetch_media("https://example.com/ok.mp4", tmp, max_bytes=100)
            self.assertEqual(dest.stat().st_size, 100)

    def test_nonpositive_limits_rejected(self):
        """max_bytes and timeout must be positive."""
        with self.assertRaises(RemoteInputError):
            fetch_media("https://example.com/a.mp4", tempfile.gettempdir(), max_bytes=0)
        with self.assertRaises(RemoteInputError):
            fetch_media("https://example.com/a.mp4", tempfile.gettempdir(), timeout=0)


class FilenameTests(unittest.TestCase):
    """Local filenames come only from the sanitized URL path basename."""

    def test_normal_basename(self):
        """A plain basename is kept as-is."""
        self.assertEqual(
            remote_input._derive_filename("https://h/media/talk.mp4"), "talk.mp4"
        )

    def test_empty_path_falls_back(self):
        """No path at all falls back to download.bin."""
        self.assertEqual(remote_input._derive_filename("https://h"), "download.bin")

    def test_trailing_slash_falls_back(self):
        """A directory-style URL falls back to download.bin."""
        self.assertEqual(
            remote_input._derive_filename("https://h/media/"), "download.bin"
        )

    def test_dotdot_falls_back(self):
        """A '..' basename falls back instead of traversing."""
        self.assertEqual(
            remote_input._derive_filename("https://h/.."), "download.bin"
        )

    def test_encoded_traversal_falls_back(self):
        """Percent-encoded '..' decodes to '..' and falls back."""
        self.assertEqual(
            remote_input._derive_filename("https://h/%2e%2e"), "download.bin"
        )

    def test_encoded_slash_cannot_escape(self):
        """Encoded slashes decode, then only the final component is kept."""
        self.assertEqual(
            remote_input._derive_filename("https://h/a%2Fb%2Fc.mp4"), "c.mp4"
        )

    def test_overlong_name_falls_back(self):
        """A 300-character basename falls back to download.bin."""
        self.assertEqual(
            remote_input._derive_filename("https://h/" + "a" * 300), "download.bin"
        )

    def test_query_ignored(self):
        """Query strings do not leak into the filename."""
        self.assertEqual(
            remote_input._derive_filename("https://h/ep.mp3?token=abc"), "ep.mp3"
        )


class HappyPathTests(unittest.TestCase):
    """A valid public https URL streams to the destination directory."""

    def test_download_succeeds(self):
        """Chunks are streamed to dest_dir under the sanitized basename."""
        chunks = [b"RIFF", b"fakemedia", b"tail"]
        response = FakeResponse(list(chunks), headers={"Content-Length": "17"})
        opener = FakeOpener(response=response)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                remote_input.socket, "getaddrinfo", return_value=PUBLIC_ADDRINFO
            ), mock.patch.object(
                remote_input, "_build_opener", return_value=opener
            ):
                dest = fetch_media(
                    "https://cdn.example.com/media/episode.mp4", tmp, timeout=5
                )
            self.assertEqual(dest, Path(tmp) / "episode.mp4")
            self.assertEqual(dest.read_bytes(), b"".join(chunks))
            self.assertTrue(response.closed)
            self.assertEqual(opener.calls[0][1], 5)

    def test_existing_destination_refused(self):
        """A pre-existing destination file is never overwritten."""
        response = FakeResponse([b"data"])
        opener = FakeOpener(response=response)
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "episode.mp4"
            existing.write_bytes(b"keep me")
            with mock.patch.object(
                remote_input.socket, "getaddrinfo", return_value=PUBLIC_ADDRINFO
            ), mock.patch.object(
                remote_input, "_build_opener", return_value=opener
            ):
                with self.assertRaises(RemoteInputError) as ctx:
                    fetch_media("https://cdn.example.com/media/episode.mp4", tmp)
            self.assertIn("already exists", str(ctx.exception))
            self.assertEqual(existing.read_bytes(), b"keep me")

    def test_destination_directory_creation_failure_is_reported(self):
        """mkdir failures explain that the destination directory is invalid."""
        with mock.patch.object(
            remote_input.socket,
            "getaddrinfo",
            return_value=PUBLIC_ADDRINFO,
        ), mock.patch.object(Path, "mkdir", side_effect=OSError("mkdir failed")):
            with self.assertRaises(RemoteInputError) as ctx:
                fetch_media("https://cdn.example.com/media/episode.mp4", "out")
        self.assertIn("destination directory", str(ctx.exception))

    def test_http_error_is_reported(self):
        """HTTP status failures retain status code and reason."""
        error = urllib.error.HTTPError(
            "https://cdn.example.com/a.mp4",
            403,
            "Forbidden",
            {},
            None,
        )
        opener = FakeOpener(error=error)
        with mock.patch.object(
            remote_input.socket,
            "getaddrinfo",
            return_value=PUBLIC_ADDRINFO,
        ), mock.patch.object(remote_input, "_build_opener", return_value=opener):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RemoteInputError) as ctx:
                    fetch_media("https://cdn.example.com/a.mp4", tmp)
        self.assertIn("HTTP 403", str(ctx.exception))

    def test_url_error_is_reported(self):
        """Network opener failures are wrapped with a fetch hint."""
        opener = FakeOpener(error=urllib.error.URLError("offline"))
        with mock.patch.object(
            remote_input.socket,
            "getaddrinfo",
            return_value=PUBLIC_ADDRINFO,
        ), mock.patch.object(remote_input, "_build_opener", return_value=opener):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RemoteInputError) as ctx:
                    fetch_media("https://cdn.example.com/a.mp4", tmp)
        self.assertIn("Could not fetch", str(ctx.exception))

    def test_destination_file_creation_failure_is_reported(self):
        """open(..., 'xb') failures are surfaced and no file is left behind."""
        response = FakeResponse([b"data"])
        opener = FakeOpener(response=response)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                remote_input.socket,
                "getaddrinfo",
                return_value=PUBLIC_ADDRINFO,
            ), mock.patch.object(
                remote_input, "_build_opener", return_value=opener
            ), mock.patch(
                "builtins.open", side_effect=OSError("create failed")
            ):
                with self.assertRaises(RemoteInputError) as ctx:
                    fetch_media("https://cdn.example.com/a.mp4", tmp)
        self.assertIn("destination file", str(ctx.exception))

    def test_mid_transfer_protocol_failure_deletes_partial_file(self):
        """Read failures are wrapped and partial downloads are deleted."""
        class FailingResponse(FakeResponse):
            def read(self, size=-1):
                if not self._chunks:
                    raise http.client.HTTPException("socket reset")
                return super().read(size)

        response = FailingResponse([b"partial"])
        opener = FakeOpener(response=response)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                remote_input.socket,
                "getaddrinfo",
                return_value=PUBLIC_ADDRINFO,
            ), mock.patch.object(remote_input, "_build_opener", return_value=opener):
                with self.assertRaises(RemoteInputError) as ctx:
                    fetch_media("https://cdn.example.com/a.mp4", tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertIn("mid-transfer", str(ctx.exception))


class CliTests(unittest.TestCase):
    """The tiny CLI reports success and failure reasons."""

    def test_main_usage_error(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = remote_input._main([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", stderr.getvalue())

    def test_main_fetch_error(self):
        stderr = io.StringIO()
        with mock.patch.object(
            remote_input,
            "fetch_media",
            side_effect=RemoteInputError("blocked"),
        ), redirect_stderr(stderr):
            code = remote_input._main(["https://cdn.example/a.mp4", "out"])
        self.assertEqual(code, 1)
        self.assertIn("blocked", stderr.getvalue())

    def test_main_success_prints_path(self):
        stdout = io.StringIO()
        with mock.patch.object(
            remote_input,
            "fetch_media",
            return_value=Path("out/a.mp4"),
        ), redirect_stdout(stdout):
            code = remote_input._main(["https://cdn.example/a.mp4", "out"])
        self.assertEqual(code, 0)
        self.assertIn("out", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
