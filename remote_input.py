"""Safely download a remote media file over HTTPS to a local temp path.

This module lets codec-carver ingest recordings that live at an https URL
(cloud recording links, podcast episodes) by downloading them to a local
file that the existing shrinking engine can process.  It is written to be
SSRF-hardened and uses only the Python standard library.

Threat model
============
The URL is attacker-influenced input.  A hostile URL could try to make this
process issue requests to internal infrastructure (SSRF), exhaust disk with
an unbounded body, or plant a malicious filename.  Defenses:

* **Scheme allowlist** -- only ``https`` is accepted.  ``http``, ``file``,
  ``ftp``, ``data`` and everything else are rejected before any I/O.
* **Address validation before connecting** -- the hostname is resolved with
  :func:`socket.getaddrinfo` and *every* resolved address must be a global
  unicast address.  Private (RFC 1918 / ULA), loopback, link-local,
  multicast, reserved and unspecified addresses are rejected, as are
  numeric-IP URLs pointing at those ranges, IPv4-mapped IPv6 forms of them,
  and the hostname ``localhost`` (including ``*.localhost``).
* **Redirects disabled** -- a custom opener installs a redirect handler
  that raises instead of following.  Without this, an approved public URL
  could 302-bounce the client to ``https://169.254.169.254/`` or another
  internal address *after* validation passed.
* **Size cap** -- ``Content-Length`` is pre-checked when present, and the
  body is streamed in 1 MiB chunks with a running byte count; exceeding
  ``max_bytes`` aborts the download and deletes the partial file.
* **Filename hygiene** -- the local filename derives only from the URL path
  basename, sanitized (no separators, no ``.``/``..``, bounded length),
  falling back to ``download.bin``.  The server-controlled
  ``Content-Disposition`` header is deliberately ignored.
* **Timeouts** -- a socket timeout applies to the connection and each read,
  so a stalling server cannot hang the caller forever.

Known residual risks (documented honestly):

* **DNS rebinding (TOCTOU)** -- validation resolves the hostname, then
  urllib resolves it again to connect.  A DNS server alternating answers
  could pass validation with a public IP and serve a private IP on the
  second lookup.  Pinning the validated IP while keeping TLS/SNI intact is
  not cleanly possible with the stdlib opener; deploy egress filtering if
  this matters in your environment.
* **Slow-loris style trickle** -- the timeout bounds each read, not total
  wall-clock time; a server drip-feeding bytes can stretch a download.
* The downloaded bytes are untrusted media and must still be handled by a
  robust decoder; this module only guarantees *where* they came from
  (a public https endpoint) and *how big* they are.

Usage
=====
>>> from remote_input import fetch_media
>>> path = fetch_media("https://example.com/talk.mp4", "/tmp/incoming")

An optional tiny CLI is provided::

    python -m remote_input <url> <dest_dir>
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

__all__ = ["RemoteInputError", "fetch_media"]

#: The only URL scheme this module will fetch.
_ALLOWED_SCHEME = "https"

#: Streaming chunk size (1 MiB).
_CHUNK_SIZE = 1024 * 1024

#: Local filename used when the URL path yields no safe basename.
_FALLBACK_FILENAME = "download.bin"

#: Longest local filename we will create.
_MAX_FILENAME_LENGTH = 255


class RemoteInputError(Exception):
    """Raised for every rejected or failed remote fetch.

    The message always explains *why* the fetch was refused and, where
    possible, what the caller can do about it.
    """


class _RedirectRefusalHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow any redirect.

    Following a redirect would re-introduce SSRF: the validated public URL
    could answer with ``Location: https://10.0.0.5/`` and urllib would
    happily connect to the internal address.  Instead of following, this
    handler raises :class:`RemoteInputError` for every 3xx response.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Raise instead of building a follow-up request.

        ``urllib`` calls this for 301/302/303/307/308 responses; raising
        here guarantees no second request is ever issued.
        """
        raise RemoteInputError(
            f"Refusing to follow HTTP {code} redirect to {newurl!r}: "
            "redirects are disabled because they can bounce the request to "
            "an internal address. Use the final URL directly."
        )


def _reject_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> None:
    """Raise :class:`RemoteInputError` unless *ip* is a global unicast address.

    IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) are unwrapped and judged
    by their embedded IPv4 address, so ``::ffff:127.0.0.1`` is treated as
    loopback.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        raise RemoteInputError(
            f"Refusing to fetch from {host!r}: it resolves to {ip} which is a "
            "private, loopback, link-local, multicast or otherwise "
            "non-public address. Only publicly routable hosts are allowed."
        )


def _validate_host(host: str) -> None:
    """Validate that *host* refers only to publicly routable addresses.

    Rejects ``localhost`` (and ``*.localhost``) by name, numeric-IP hosts in
    forbidden ranges, and hostnames whose DNS resolution includes *any*
    forbidden address.  Raises :class:`RemoteInputError` on rejection or if
    the name cannot be resolved at all.
    """
    normalized = host.rstrip(".").lower()
    if not normalized:
        raise RemoteInputError("URL has an empty hostname; nothing to fetch.")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        raise RemoteInputError(
            "Refusing to fetch from 'localhost': local addresses are not "
            "allowed. Provide a publicly reachable https URL."
        )

    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        literal = None
    if literal is not None:
        _reject_ip(literal, host)
        return

    try:
        infos = socket.getaddrinfo(normalized, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RemoteInputError(
            f"Could not resolve hostname {host!r}: {exc}. Check the URL for "
            "typos and confirm the host exists."
        ) from exc
    if not infos:
        raise RemoteInputError(
            f"Hostname {host!r} resolved to no addresses; cannot fetch."
        )
    for info in infos:
        _reject_ip(ipaddress.ip_address(info[4][0]), host)


def _validate_url(url: str) -> urllib.parse.SplitResult:
    """Parse *url* and enforce the scheme allowlist and URL shape rules.

    Returns the parsed :class:`urllib.parse.SplitResult`.  Raises
    :class:`RemoteInputError` for non-https schemes, embedded credentials,
    or unparseable URLs.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise RemoteInputError(f"URL {url!r} could not be parsed: {exc}") from exc
    if parsed.scheme.lower() != _ALLOWED_SCHEME:
        raise RemoteInputError(
            f"URL scheme {parsed.scheme or '(none)'!r} is not allowed: only "
            "https URLs are accepted. http, file, ftp and data URLs are "
            "rejected because they are common SSRF and local-read vectors."
        )
    if parsed.username is not None or parsed.password is not None:
        raise RemoteInputError(
            "URLs with embedded credentials (user:pass@host) are not "
            "accepted. Remove the credentials from the URL."
        )
    try:
        host = parsed.hostname
    except ValueError as exc:
        raise RemoteInputError(f"URL {url!r} has an invalid host: {exc}") from exc
    if not host:
        raise RemoteInputError(f"URL {url!r} has no hostname; nothing to fetch.")
    return parsed


def _derive_filename(url: str) -> str:
    """Derive a safe local filename from the URL path basename.

    Only the URL path is consulted -- never the server's
    ``Content-Disposition`` header, which is attacker-controlled.  The path
    is percent-decoded, the final ``/``-separated component is taken (so a
    directory-style URL ending in ``/`` yields nothing), and the result is
    rejected in favor of ``download.bin`` if it is empty, ``.``, ``..``,
    contains a path separator or NUL byte, or is unreasonably long.
    """
    path = urllib.parse.urlsplit(url).path
    candidate = urllib.parse.unquote(path).rsplit("/", 1)[-1]
    if (
        not candidate
        or candidate in {".", ".."}
        or "/" in candidate
        or "\\" in candidate
        or "\x00" in candidate
        or len(candidate) > _MAX_FILENAME_LENGTH
    ):
        return _FALLBACK_FILENAME
    return candidate


def _build_opener() -> urllib.request.OpenerDirector:
    """Build the hardened opener used for the actual fetch.

    The opener carries :class:`_RedirectRefusalHandler` so any 3xx response
    raises instead of being followed, and it deliberately includes no proxy,
    cookie, or auth handlers beyond urllib's defaults.
    """
    return urllib.request.build_opener(_RedirectRefusalHandler())


def _precheck_content_length(headers, max_bytes: int, url: str) -> None:
    """Reject the response early if Content-Length already exceeds the cap.

    A missing or malformed Content-Length is tolerated (the streaming byte
    counter still enforces the cap); an honest oversized declaration lets us
    abort before downloading a single chunk.
    """
    declared = headers.get("Content-Length") if headers is not None else None
    if declared is None:
        return
    try:
        length = int(declared)
    except (TypeError, ValueError):
        return
    if length > max_bytes:
        raise RemoteInputError(
            f"Remote file at {url!r} declares Content-Length {length} bytes, "
            f"which exceeds the limit of {max_bytes} bytes. Raise max_bytes "
            "if this size is expected."
        )


def fetch_media(
    url: str,
    dest_dir,
    *,
    max_bytes: int = 5 * 1024**3,
    timeout: float = 60,
) -> Path:
    """Download the media file at *url* into *dest_dir* and return its path.

    The URL must be ``https`` and its host must resolve exclusively to
    publicly routable addresses (see the module docstring for the full
    threat model).  Redirects are never followed.  The body is streamed in
    1 MiB chunks and the download is aborted -- with the partial file
    deleted -- if it exceeds *max_bytes*.

    :param url: The ``https`` URL of the remote media file.
    :param dest_dir: Directory to download into; created if missing.
    :param max_bytes: Hard cap on the downloaded size in bytes
        (default 5 GiB).  Must be positive.
    :param timeout: Socket timeout in seconds for the connection and each
        read (default 60).  Must be positive.
    :returns: :class:`pathlib.Path` of the downloaded file.
    :raises RemoteInputError: on any validation failure, refused redirect,
        network error, oversized body, or destination conflict.
    """
    if max_bytes <= 0:
        raise RemoteInputError("max_bytes must be a positive number of bytes.")
    if timeout <= 0:
        raise RemoteInputError("timeout must be a positive number of seconds.")

    parsed = _validate_url(url)
    _validate_host(parsed.hostname)

    dest_dir = Path(dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RemoteInputError(
            f"Could not create destination directory {dest_dir}: {exc}"
        ) from exc

    dest = dest_dir / _derive_filename(url)
    opener = _build_opener()
    try:
        response = opener.open(url, timeout=timeout)
    except RemoteInputError:
        raise
    except urllib.error.HTTPError as exc:
        raise RemoteInputError(
            f"Server returned HTTP {exc.code} for {url!r}: {exc.reason}. "
            "Confirm the link is valid and publicly accessible."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RemoteInputError(
            f"Could not fetch {url!r}: {exc}. Check network connectivity "
            "and that the host accepts https connections."
        ) from exc

    written = 0
    try:
        with response:
            _precheck_content_length(
                getattr(response, "headers", None), max_bytes, url
            )
            try:
                out = open(dest, "xb")
            except FileExistsError as exc:
                raise RemoteInputError(
                    f"Destination file {dest} already exists; refusing to "
                    "overwrite. Remove it or choose another directory."
                ) from exc
            except OSError as exc:
                raise RemoteInputError(
                    f"Could not create destination file {dest}: {exc}"
                ) from exc
            try:
                with out:
                    while True:
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            raise RemoteInputError(
                                f"Download from {url!r} exceeded the limit "
                                f"of {max_bytes} bytes; aborted and partial "
                                "file deleted. Raise max_bytes if this size "
                                "is expected."
                            )
                        out.write(chunk)
            except BaseException:
                dest.unlink(missing_ok=True)
                raise
    except RemoteInputError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise RemoteInputError(
            f"Download from {url!r} failed mid-transfer: {exc}. The partial "
            "file was deleted; retry the fetch."
        ) from exc
    return dest


def _main(argv: list[str]) -> int:
    """Tiny CLI entry point: ``python -m remote_input <url> <dest_dir>``.

    Prints the downloaded path on success and the rejection reason on
    failure; returns a process exit code.
    """
    if len(argv) != 2:
        print("usage: python -m remote_input <https-url> <dest_dir>", file=sys.stderr)
        return 2
    try:
        path = fetch_media(argv[0], argv[1])
    except RemoteInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
