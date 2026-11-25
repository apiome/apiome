"""Unit tests for content-type detection — the ``contentType`` matcher (PFX-3.4, #6934).

:mod:`app.pact_content_type` names what a body is from its bytes. Covered here: every magic
signature, the RIFF and ISO-media containers, text (JSON, XML, plain), binary that decodes as
UTF-8, aliases and structured-syntax suffixes.
"""

from __future__ import annotations

import pytest

from app.pact_content_type import MAGIC_SIGNATURES, OCTET_STREAM, content_type_matches, detect_content_type


@pytest.mark.parametrize(("offset", "signature", "media_type"), MAGIC_SIGNATURES)
def test_every_magic_signature_is_detected(offset: int, signature: bytes, media_type: str) -> None:
    assert detect_content_type(b"\x00" * offset + signature + b"\x00\x01payload") == media_type


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio/x-wav"),
        (b"RIFF\x24\x00\x00\x00AVI LIST", "video/x-msvideo"),
        (b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00", "video/mp4"),
        (b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00", "image/avif"),
        (b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00", "video/quicktime"),
        (b"\xff\xfb\x90\x00", "audio/mpeg"),
    ],
)
def test_containers_and_frames_are_detected(data: bytes, media_type: str) -> None:
    assert detect_content_type(data) == media_type


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b'{"a": [1, 2]}', "application/json"),
        (b"  [1]\n", "application/json"),
        (b"\xef\xbb\xbf{}", "application/json"),
        (b'<?xml version="1.0"?><a/>', "application/xml"),
        (b"<root><child/></root>", "application/xml"),
        (b"a,b\n1,2", "text/plain"),
        (b"< not xml", "text/plain"),
        (b"", "text/plain"),
    ],
)
def test_text_is_json_xml_or_plain(data: bytes, media_type: str) -> None:
    assert detect_content_type(data) == media_type


def test_binary_that_is_not_text_is_an_octet_stream() -> None:
    assert detect_content_type(b"\xfe\xfe\x00\x01") == OCTET_STREAM
    # Valid UTF-8 full of control characters is binary, not text.
    assert detect_content_type(b"\x01\x02\x03\x04") == OCTET_STREAM


@pytest.mark.parametrize(
    ("data", "expected", "matched"),
    [
        (b"\xff\xd8\xff\xe0", "image/jpeg", True),
        (b"\xff\xd8\xff\xe0", "image/jpg", True),
        (b"\xff\xd8\xff\xe0", "IMAGE/JPEG; q=1", True),
        (b"\xff\xd8\xff\xe0", "image/png", False),
        (b"<a/>", "text/xml", True),
        (b'{"_links": {}}', "application/hal+json", True),
        (b"<svg/>", "image/svg+xml", True),
        (b"plain", "application/hal+json", False),
        (b"a,b", "text/csv", True),
        (b'{"a": 1}', "text/plain", True),
        (b"\x89PNG\r\n\x1a\n", "text/plain", False),
        (b"\x00\x00\x01\x00", "image/x-icon", True),
    ],
)
def test_a_rule_matches_its_type_its_aliases_and_its_family(data: bytes, expected: str, matched: bool) -> None:
    assert content_type_matches(data, expected)[0] is matched


def test_a_mismatch_says_what_was_detected() -> None:
    assert content_type_matches(b"\x89PNG\r\n\x1a\n", "image/jpeg") == (False, "image/png")
