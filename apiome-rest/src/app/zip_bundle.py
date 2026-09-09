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

import zipfile

__all__ = ["ZIP_EPOCH", "write_zip_entry"]

#: A fixed DOS epoch for every zip entry's timestamp, so the same content always packages to
#: byte-identical bundle bytes. 1980-01-01 is the earliest a DOS timestamp can encode.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def write_zip_entry(archive: zipfile.ZipFile, name: str, text: str) -> None:
    """Write one UTF-8 text entry to ``archive`` with a pinned timestamp.

    Args:
        archive: The open archive to write into.
        name: The entry's bundle-relative path.
        text: The entry's content, encoded as UTF-8.
    """
    info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    # 0o644 (rw-r--r--) in the high 16 bits, the conventional Unix mode for a zip entry.
    info.external_attr = 0o644 << 16
    archive.writestr(info, text.encode("utf-8"))
