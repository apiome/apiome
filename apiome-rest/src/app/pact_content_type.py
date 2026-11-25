"""Detect the content type of a body from its bytes — the ``contentType`` matcher (PFX-3.4, #6934).

A pact for an endpoint that returns an image cannot record "this exact image": any JPEG will do.
Pact's ``contentType`` matcher (``{"match": "contentType", "value": "image/jpeg"}``) says so, and
a verifier judges it the way the Pact reference implementation does: by **looking at the bytes**
(their magic number), never by trusting the ``Content-Type`` header the provider sent.

How a type is detected
----------------------
1. **Magic numbers.** The leading bytes of common binary formats (:data:`MAGIC_SIGNATURES`):
   PNG, JPEG, GIF, WebP, BMP, TIFF, ICO, PDF, ZIP, gzip, bzip2, 7-Zip, WebAssembly, WOFF/WOFF2,
   MP3, WAV, Ogg, FLAC and the ISO media family (MP4, QuickTime, HEIC, AVIF).
2. **Text.** Bytes with no signature that decode as UTF-8 are JSON when they parse as JSON, XML
   when they start with an XML declaration or element, and plain text otherwise.
3. **Anything else** is ``application/octet-stream``.

A media type with a structured-syntax suffix (``application/hal+json``, ``image/svg+xml``) is
satisfied by its base family — content cannot say which JSON vocabulary it is — and
``text/xml`` / ``application/xml`` are equivalent, as are the aliases in :data:`_ALIASES`.

Pure: bytes in, a media type out. No I/O, no third-party detector.
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

__all__ = [
    "MAGIC_SIGNATURES",
    "OCTET_STREAM",
    "content_type_matches",
    "detect_content_type",
]

#: What content is when nothing more specific can be said about it.
OCTET_STREAM = "application/octet-stream"

#: ``(offset, signature, media type)`` — the leading bytes of the binary formats detected, in the
#: order they are tried.
MAGIC_SIGNATURES: Tuple[Tuple[int, bytes, str], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"GIF87a", "image/gif"),
    (0, b"GIF89a", "image/gif"),
    (0, b"BM", "image/bmp"),
    (0, b"II*\x00", "image/tiff"),
    (0, b"MM\x00*", "image/tiff"),
    (0, b"\x00\x00\x01\x00", "image/vnd.microsoft.icon"),
    (0, b"%PDF-", "application/pdf"),
    (0, b"PK\x03\x04", "application/zip"),
    (0, b"\x1f\x8b", "application/gzip"),
    (0, b"BZh", "application/x-bzip2"),
    (0, b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (0, b"\x00asm", "application/wasm"),
    (0, b"wOFF", "font/woff"),
    (0, b"wOF2", "font/woff2"),
    (0, b"ID3", "audio/mpeg"),
    (0, b"OggS", "audio/ogg"),
    (0, b"fLaC", "audio/x-flac"),
)

#: The four-character ISO base media "brands" (``ftyp`` box at offset 4) and what they mean.
_ISO_BRANDS = {
    b"avif": "image/avif",
    b"heic": "image/heic",
    b"heix": "image/heic",
    b"mif1": "image/heif",
    b"qt  ": "video/quicktime",
    b"M4A ": "audio/mp4",
    b"M4V ": "video/x-m4v",
}

#: Media types that name the same thing, mapped to the name :func:`detect_content_type` uses.
_ALIASES = {
    "text/xml": "application/xml",
    "image/jpg": "image/jpeg",
    "image/x-icon": "image/vnd.microsoft.icon",
    "image/x-ms-bmp": "image/bmp",
    "application/x-gzip": "application/gzip",
    "application/x-zip-compressed": "application/zip",
    "audio/mp3": "audio/mpeg",
    "audio/wav": "audio/x-wav",
    "audio/wave": "audio/x-wav",
    "audio/flac": "audio/x-flac",
    "application/x-pdf": "application/pdf",
}

#: How many leading bytes of a text body are inspected to tell XML from plain text.
_TEXT_SNIFF_LIMIT = 512


def _riff_type(data: bytes) -> Optional[str]:
    """The type of a RIFF container (WebP, WAV, AVI), or ``None`` when ``data`` is not one."""
    if len(data) < 12 or data[:4] != b"RIFF":
        return None
    return {b"WEBP": "image/webp", b"WAVE": "audio/x-wav", b"AVI ": "video/x-msvideo"}.get(data[8:12])


def _iso_media_type(data: bytes) -> Optional[str]:
    """The type of an ISO base media file (MP4, QuickTime, HEIC, AVIF), or ``None``."""
    if len(data) < 12 or data[4:8] != b"ftyp":
        return None
    return _ISO_BRANDS.get(data[8:12], "video/mp4")


def _text_type(data: bytes) -> Optional[str]:
    """The type of a text body — JSON, XML or plain text — or ``None`` when it is not UTF-8 text."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 0x20 and char not in "\t\n\r\f" for char in text[:_TEXT_SNIFF_LIMIT]):
        return None  # control characters: binary content that happens to decode
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped:
        try:
            json.loads(stripped)
            return "application/json"
        except ValueError:
            pass
        if stripped.startswith("<?xml") or (
            stripped.startswith("<") and len(stripped) > 1 and (stripped[1].isalpha() or stripped[1] in "_!")
        ):
            return "application/xml"
    return "text/plain"


def detect_content_type(data: bytes) -> str:
    """Detect what a body is from its bytes.

    Args:
        data: The body, undecoded.

    Returns:
        A media type without parameters, such as ``image/png``, ``application/json`` or
        ``text/plain``; :data:`OCTET_STREAM` when nothing more specific can be said (an empty
        body is ``text/plain``, as an empty text).
    """
    for offset, signature, media_type in MAGIC_SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            return media_type
    for detector in (_riff_type, _iso_media_type):
        found = detector(data)
        if found:
            return found
    if data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3" or data[:2] == b"\xff\xf2":
        return "audio/mpeg"  # an MP3 frame with no ID3 tag
    return _text_type(data) or OCTET_STREAM


def _normal(media_type: str) -> str:
    """A media type lowercased, without parameters, and with its alias resolved."""
    base = media_type.split(";", 1)[0].strip().lower()
    return _ALIASES.get(base, base)


def content_type_matches(data: bytes, expected: str) -> Tuple[bool, str]:
    """Whether a body's detected type is the type a ``contentType`` rule names.

    Args:
        data: The body, undecoded.
        expected: The rule's ``value`` (``image/jpeg``; parameters such as ``charset`` are ignored).

    Returns:
        ``(matched, detected)`` — ``detected`` is the type found in the bytes, for the message.
        A suffixed type (``+json``, ``+xml``) is satisfied by JSON or XML content; any ``text/*``
        type is satisfied by plain text, since bytes cannot say which text format they are.
    """
    detected = detect_content_type(data)
    wanted = _normal(expected)
    if wanted == detected:
        return True, detected
    if wanted.endswith("+json") or wanted == "text/json":
        return detected == "application/json", detected
    if wanted.endswith("+xml"):
        return detected == "application/xml", detected
    if wanted.startswith("text/") and detected in ("text/plain", "application/json", "application/xml"):
        # CSV, HTML, Markdown … are text the bytes cannot tell apart; JSON and XML are text too.
        return True, detected
    return False, detected
