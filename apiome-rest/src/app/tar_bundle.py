"""Deterministic gzipped-tar writing — SDK-4.1 (#4495).

The sibling of :mod:`app.zip_bundle`, for the two archive formats a package registry accepts: an
npm tarball (``.tgz``) and a PyPI source distribution (``.tar.gz``). Both are gzipped tar, and both
must be **byte-deterministic** for the same reason the client kit is — a publish is recorded with
the digest of what was uploaded, a dry-run has to predict that digest exactly, and a consumer must
be able to rebuild an artifact and compare.

Determinism is not free. A tar header carries an mtime, a uid/gid, a uname/gname and a mode, and
gzip stores its own mtime in the stream header; leave any of them to the ambient environment and
two builds of identical content differ. Every one of them is pinned here rather than at each call
site, because two copies of that list agree right up until one of them is changed.

The pins:

* **mtime** — :data:`TAR_EPOCH`, 1980-01-01T00:00:00Z. The same instant :data:`app.zip_bundle.ZIP_EPOCH`
  encodes, chosen so the two bundle formats date their entries alike. (Zero would work too, but
  some extractors render a 1970 date as "unknown".)
* **owner** — uid/gid 0 with empty uname/gname. A tarball built in a container must not record the
  build user.
* **mode** — 0o644 for every file. Nothing in either distribution is executable.
* **gzip mtime** — 0, written through :class:`gzip.GzipFile` explicitly, because the default is
  "now" and it is *outside* the tar stream where a tar-level pin cannot reach it.
* **order** — entries are sorted by path, so a caller that builds its file list in a different
  order still produces the same bytes.
"""

from __future__ import annotations

import gzip
import io
import tarfile
from typing import Iterable, List, Sequence, Tuple

__all__ = ["TAR_EPOCH", "build_tar_gz"]

#: The fixed mtime stamped on every tar entry: 1980-01-01T00:00:00Z as a POSIX timestamp.
TAR_EPOCH = 315_532_800

#: Mode bits for every entry (rw-r--r--). Nothing published here is executable.
_ENTRY_MODE = 0o644

#: Gzip compression level. 9 is deterministic for a given zlib and keeps published tarballs small;
#: the level is pinned because a different level is a different byte stream.
_GZIP_LEVEL = 9


def build_tar_gz(entries: Iterable[Tuple[str, str]]) -> bytes:
    """Package UTF-8 text entries into a deterministic gzipped tar.

    Args:
        entries: ``(path, text)`` pairs. Paths are archive-relative and must already carry whatever
            root directory the format requires (``package/`` for npm, ``<name>-<version>/`` for a
            PyPI sdist). Order does not matter — entries are sorted by path.

    Returns:
        The ``.tar.gz`` bytes. Building twice from equal entries yields identical bytes.

    Raises:
        ValueError: If two entries claim the same path, which would silently publish only one of
            them.
    """
    ordered: List[Tuple[str, str]] = sorted(entries, key=lambda item: item[0])
    _reject_duplicate_paths(ordered)

    tar_buffer = io.BytesIO()
    # ``format=PAX_FORMAT`` is tarfile's default from 3.8 and encodes long paths and non-ASCII
    # names portably; naming it keeps the output stable if that default ever moves again.
    with tarfile.open(
        fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT
    ) as archive:
        for path, text in ordered:
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(payload)
            info.mtime = TAR_EPOCH
            info.mode = _ENTRY_MODE
            info.type = tarfile.REGTYPE
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(payload))

    gz_buffer = io.BytesIO()
    # ``mtime=0`` is the point of writing the GzipFile by hand: the gzip header's timestamp lives
    # outside the tar stream, and its default of "now" would make every build differ.
    with gzip.GzipFile(
        fileobj=gz_buffer, mode="wb", compresslevel=_GZIP_LEVEL, mtime=0
    ) as gz:
        gz.write(tar_buffer.getvalue())
    return gz_buffer.getvalue()


def _reject_duplicate_paths(ordered: Sequence[Tuple[str, str]]) -> None:
    """Raise when two entries share a path.

    A tar happily stores both and an extractor keeps the last, so a duplicate is a file silently
    replaced by another — worth failing the build over rather than publishing.

    Args:
        ordered: Path-sorted entries.

    Raises:
        ValueError: On the first duplicate path found.
    """
    for index in range(1, len(ordered)):
        if ordered[index][0] == ordered[index - 1][0]:
            raise ValueError(f"duplicate archive entry: {ordered[index][0]!r}")
