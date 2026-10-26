"""Apache Thrift multi-file sets — MFI-19.3 (#3981).

A Thrift API is often split across files: the root includes other ``.thrift`` files and
refers to their definitions with the file's name as a prefix::

    include "shared.thrift"          // shared.Money, shared.BaseService
    include "common/errors.thrift"   // errors.NotFound

:func:`parse_thrift_set` parses the root and every file it includes, transitively, and links
them through :attr:`~app.thrift_parser.ThriftDocument.included` so the normalizer can resolve
``prefix.Name`` to the right file's definition.

Include paths resolve the way the Thrift compiler does: relative to the including file, then
relative to the root's folder (the compiler's ``-I`` search path). A path that is absolute, a
URL, or climbs out of the uploaded set with ``..`` is never followed.
"""

from __future__ import annotations

import posixpath
from dataclasses import replace
from typing import Dict, Mapping, Optional, Tuple

from .fileset import resolve_relative_reference
from .import_source import ImportSourceError
from .thrift_parser import ThriftDocument, ThriftParseError, parse_thrift

__all__ = ["include_prefix", "parse_thrift_set"]


def include_prefix(target: str) -> str:
    """The prefix an included file's definitions are referenced with.

    Args:
        target: The ``include`` path as written (``common/shared.thrift``).

    Returns:
        The file name without its ``.thrift`` extension (``shared``).
    """
    name = posixpath.basename(target)
    return name[: -len(".thrift")] if name.lower().endswith(".thrift") else name


class _SetParser:
    """Parses one set, each member at most once."""

    def __init__(self, members: Mapping[str, str], root: str) -> None:
        self.members = members
        self.root = root
        self.parsed: Dict[str, ThriftDocument] = {}

    def locate(self, member: str, target: str) -> str:
        """The member an ``include`` in ``member`` names.

        Raises:
            ImportSourceError: ``INPUT_REFERENCE_UNRESOLVED`` when the path leaves the set or
                names a file that is not in it.
        """
        beside = resolve_relative_reference(member, target)
        if beside is None:
            raise ImportSourceError(
                f'{member}: `include "{target}"` points outside the uploaded files and was not '
                "read. Bundle the file into the upload and include it by a relative path.",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        if beside in self.members:
            return beside
        from_root = resolve_relative_reference(self.root, target)
        if from_root is not None and from_root in self.members:
            return from_root
        raise ImportSourceError(
            f'{member}: `include "{target}"` names a file that is not in the upload. Add '
            f"{beside} to the archive.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )

    def load(self, path: str, chain: Tuple[str, ...]) -> ThriftDocument:
        """Parse ``path`` and, recursively, everything it includes.

        Args:
            path: The member to parse.
            chain: The members whose includes led here (to detect a cycle).

        Raises:
            ImportSourceError: On a parse failure, an unresolved include or an include cycle.
        """
        if path in chain:
            cycle = " → ".join(chain[chain.index(path):] + (path,))
            raise ImportSourceError(
                f"The Thrift files include each other in a cycle: {cycle}.",
                code="INPUT_SEMANTIC_INVALID",
            )
        if path in self.parsed:
            return self.parsed[path]
        try:
            document = parse_thrift(
                self.members[path], source_label=path, require_definitions=path == self.root
            )
        except ThriftParseError as exc:
            raise ImportSourceError(f"{path}: {exc}") from exc
        included: Dict[str, ThriftDocument] = {}
        for target in document.includes:
            included[include_prefix(target)] = self.load(self.locate(path, target), chain + (path,))
        document = replace(document, path=path, included=included)
        self.parsed[path] = document
        return document


def parse_thrift_set(
    members: Mapping[str, str],
    root: str,
    *,
    source_label: Optional[str] = None,
) -> ThriftDocument:
    """Parse a Thrift root document and every file it includes.

    Args:
        members: The set's members, path → text.
        root: The root document's path among ``members``.
        source_label: Label used when the root is missing.

    Returns:
        The root document, with :attr:`~app.thrift_parser.ThriftDocument.included` (and its
        included documents' own) filled in. Files in the set that nothing includes are not
        part of the API.

    Raises:
        ImportSourceError: ``INPUT_ARCHIVE_INVALID`` when the root is missing;
            ``INPUT_REFERENCE_UNRESOLVED`` for an include outside the set or missing from it;
            ``INPUT_SEMANTIC_INVALID`` for an include cycle; the parser's error (prefixed
            with the file) when a file is not valid Thrift.
    """
    if root not in members:
        label = f" ({source_label})" if source_label else ""
        raise ImportSourceError(
            f"Thrift fileset is missing its root document{label}", code="INPUT_ARCHIVE_INVALID"
        )
    return _SetParser(members, root).load(root, ())
