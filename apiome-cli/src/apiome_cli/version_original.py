"""``apiome versions original`` (COA-5.7, #7083): download the file a version was imported from.

``GET /v1/versions/{tenant}/{project}/{version}/original`` streams the original document (for a
set of files, its JSON manifest; ``…/original/{part_path}`` one of the files). These helpers hold
the rules the command applies to the response, so they can be tested without a server:

* :func:`download_name` reads the file name the server offered in ``Content-Disposition``;
* :func:`target_path` decides where ``-o`` writes (a file, or that name inside a directory);
* :func:`digest_problem` checks the bytes against ``X-Apiome-Content-Sha256``;
* :func:`error_message` turns ``original-not-stored`` / ``original-withheld`` into a sentence.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

__all__ = [
    "digest_problem",
    "download_name",
    "error_message",
    "json_result",
    "original_suffix",
    "target_path",
]

_FILENAME_STAR = re.compile(r"filename\*\s*=\s*UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME = re.compile(r'filename\s*=\s*"([^"]*)"', re.IGNORECASE)


def original_suffix(part: str | None) -> str:
    """The path after ``…/{version_record_id}``: ``/original`` or ``/original/<part>`` (URL-quoted).

    Args:
        part: A file of a stored set, by its path inside the set; ``None`` for the original itself.

    Returns:
        The suffix to append to the version record path.
    """
    if not part or not part.strip("/"):
        return "/original"
    return "/original/" + quote(part.strip("/"), safe="/")


def download_name(disposition: str | None, fallback: str = "original") -> str:
    """The file name a ``Content-Disposition`` header offers (``filename*`` wins), never a path.

    Args:
        disposition: The header's value, or ``None``.
        fallback: Used when the header names no file.

    Returns:
        A bare file name: any directory part (``../``, ``a/b``) is dropped.
    """
    name = None
    if disposition:
        star = _FILENAME_STAR.search(disposition)
        plain = _FILENAME.search(disposition)
        if star:
            name = unquote(star.group(1).strip())
        elif plain:
            name = plain.group(1)
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name not in ("", ".", "..") else fallback


def target_path(output: Path, offered_name: str) -> Path:
    """Where ``-o`` writes: the path itself, or the offered name inside it when it is a directory.

    Args:
        output: The ``-o`` value.
        offered_name: The name from :func:`download_name`.

    Returns:
        The file to write.
    """
    return output / offered_name if output.is_dir() else output


def digest_problem(body: bytes, expected: str | None) -> str | None:
    """Check downloaded bytes against the digest the server sent.

    Args:
        body: The bytes received.
        expected: ``X-Apiome-Content-Sha256``; ``None`` skips the check (an older server).

    Returns:
        ``None`` when they match (or nothing to check); otherwise a sentence naming both digests.
    """
    if not expected:
        return None
    actual = hashlib.sha256(body).hexdigest()
    if actual == expected.strip().lower():
        return None
    return f"The download is corrupt: SHA-256 {actual} does not match the stored {expected}."


def error_message(status: int, detail: Any, version_ref: str) -> str | None:
    """A sentence for the two errors this command expects; ``None`` for any other.

    Args:
        status: The HTTP status.
        detail: The response's ``detail`` (a dict with ``code`` for these two).
        version_ref: The version the user named, for the sentence.

    Returns:
        The message, or ``None`` so the caller falls back to the generic API error.
    """
    code = detail.get("code") if isinstance(detail, dict) else None
    if status == 404 and code == "original-not-stored":
        extra = detail.get("message") if isinstance(detail.get("message"), str) else ""
        return f"No original is stored for {version_ref}. {extra}".strip()
    if status == 410 and code == "original-withheld":
        reason = detail.get("reason") or "the intake policy"
        return f"The original of {version_ref} was withheld at import ({reason}); it cannot be downloaded."
    return None


def json_result(*, path: Path | None, name: str, body: bytes, media_type: str | None) -> dict:
    """The ``--json`` record of a download written to a file.

    Args:
        path: The file written (``None`` when written to stdout).
        name: The file name the server offered.
        body: The bytes.
        media_type: The response's ``Content-Type``.

    Returns:
        ``{file, filename, sha256, sizeBytes, mediaType}``.
    """
    return {
        "file": str(path) if path is not None else None,
        "filename": name,
        "sha256": hashlib.sha256(body).hexdigest(),
        "sizeBytes": len(body),
        "mediaType": (media_type or "").split(";", 1)[0].strip() or None,
    }
