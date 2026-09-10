"""Deterministic gzipped-tar writing — SDK-4.1 (#4495).

:mod:`app.tar_bundle` exists for one promise: the same content packages to the same bytes. That
promise is what lets a dry run report the digest a publish will upload, so it is asserted here
against each of the things that would otherwise break it — the tar mtime, the build user's
uid/gid, the gzip header's own timestamp, and the order the caller happened to build its file list
in.
"""

from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from app.tar_bundle import TAR_EPOCH, build_tar_gz


def _members(content: bytes):
    """Return the archive's members."""
    return tarfile.open(fileobj=io.BytesIO(content)).getmembers()


def test_entries_round_trip():
    content = build_tar_gz([("pkg/a.txt", "alpha\n"), ("pkg/b.txt", "beta\n")])
    archive = tarfile.open(fileobj=io.BytesIO(content))
    assert archive.getnames() == ["pkg/a.txt", "pkg/b.txt"]
    assert archive.extractfile("pkg/a.txt").read().decode() == "alpha\n"


def test_the_same_content_produces_the_same_bytes():
    entries = [("pkg/a.txt", "alpha\n"), ("pkg/b.txt", "beta\n")]
    assert build_tar_gz(entries) == build_tar_gz(list(entries))


def test_input_order_does_not_change_the_bytes():
    """A caller that assembles its files in a different order still gets one archive."""
    forwards = build_tar_gz([("pkg/a.txt", "alpha\n"), ("pkg/b.txt", "beta\n")])
    backwards = build_tar_gz([("pkg/b.txt", "beta\n"), ("pkg/a.txt", "alpha\n")])
    assert forwards == backwards


def test_timestamps_and_ownership_are_pinned():
    """The four header fields that would otherwise carry the build machine into the archive."""
    for member in _members(build_tar_gz([("pkg/a.txt", "alpha\n")])):
        assert member.mtime == TAR_EPOCH
        assert (member.uid, member.gid) == (0, 0)
        assert (member.uname, member.gname) == ("", "")
        assert member.mode == 0o644


def test_the_gzip_header_carries_no_timestamp():
    """The pin that a tar-level fix cannot reach: gzip stores its own mtime outside the stream."""
    content = build_tar_gz([("pkg/a.txt", "alpha\n")])
    # Bytes 4..8 of a gzip member are its MTIME, little-endian.
    assert content[4:8] == b"\x00\x00\x00\x00"
    # And it still decompresses.
    assert gzip.decompress(content)


def test_unicode_content_and_paths_survive():
    content = build_tar_gz([("pkg/ünïcode.txt", "héllo — wörld\n")])
    archive = tarfile.open(fileobj=io.BytesIO(content))
    assert archive.extractfile("pkg/ünïcode.txt").read().decode("utf-8") == "héllo — wörld\n"


def test_a_duplicate_path_is_refused():
    """A tar keeps both and an extractor keeps the last: a file silently replaced by another."""
    with pytest.raises(ValueError, match="duplicate archive entry"):
        build_tar_gz([("pkg/a.txt", "one"), ("pkg/a.txt", "two")])


def test_an_empty_archive_is_legal():
    assert _members(build_tar_gz([])) == []
