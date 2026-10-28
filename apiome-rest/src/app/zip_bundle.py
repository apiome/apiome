"""Deterministic zip entry writing, shared by every bundle Apiome serves.

Two surfaces package files into a zip a caller downloads: the MFX-4.2 multi-file export bundle
(:mod:`app.export_job_engine`) and the SDK-3.3 public client kit (:mod:`app.sdk_kit`). Both make
the same promise — *the same inputs produce byte-identical bytes*, which is what lets a response
carry a content-addressed ``ETag`` and what lets a consumer verify one download against another.

That promise is not free: a zip stores an mtime per entry, so an archive built twice from
identical content differs unless the timestamp is pinned. The pin (and the mode bits that go with
it) lives here rather than in each builder, because two copies of it would agree right up until
one of them was changed.
"""

from __future__ import annotations

import re
import zipfile

__all__ = ["ZIP_EPOCH", "safe_bundle_path", "write_zip_entry"]

#: A fixed DOS epoch for every zip entry's timestamp, so the same content always packages to
#: byte-identical bundle bytes. 1980-01-01 is the earliest a DOS timestamp can encode.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


#: A Windows drive prefix (``C:``) at the start of a path.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
#: Control characters, which no file name should carry.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_bundle_path(path: str, fallback: str = "file") -> str:
    """Reduce ``path`` to a relative path that stays inside the bundle root (X6, #6226 follow-up).

    Emitters name their files from the source — a type's namespace, a package, an API title — and
    the source is imported, user-controlled content. A member name like ``/etc/x``, ``C:\\x`` or
    ``a/../../x`` would let a naive extractor write outside the folder it unpacks into
    ("zip slip"). So: backslashes become ``/``, a drive prefix and control characters are dropped,
    empty and ``.`` segments are removed, and a ``..`` segment becomes ``_``.

    Args:
        path: The emitter's bundle-relative path.
        fallback: The name to use when nothing usable remains.

    Returns:
        A non-empty, relative, ``/``-separated path with no ``..`` segment.
    """
    cleaned = _CONTROL_CHARS.sub("", _DRIVE_PREFIX.sub("", (path or "").replace("\\", "/")))
    segments = [
        "_" if segment == ".." else segment
        for segment in cleaned.split("/")
        if segment not in ("", ".")
    ]
    return "/".join(segments) or fallback


def write_zip_entry(archive: zipfile.ZipFile, name: str, text: str) -> None:
    """Write one UTF-8 text entry to ``archive`` with a pinned timestamp.

    Args:
        archive: The open archive to write into.
        name: The entry's bundle-relative path; it must already be safe (:func:`safe_bundle_path`).
        text: The entry's content, encoded as UTF-8.

    Raises:
        ValueError: When ``name`` is absolute, climbs out of the bundle or carries a backslash,
            drive prefix or control character — the last line of defence against zip slip.
    """
    if safe_bundle_path(name) != name:
        raise ValueError(f"Refusing an unsafe zip entry name: {name!r}")
    info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    # 0o644 (rw-r--r--) in the high 16 bits, the conventional Unix mode for a zip entry.
    info.external_attr = 0o644 << 16
    archive.writestr(info, text.encode("utf-8"))
