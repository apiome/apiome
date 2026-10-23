"""ROS 2 interface import source — FMT-9.3 (#5470).

The :class:`~app.import_source.ImportSource` adapter for ROS 2 interface definitions: a single
``.msg``, ``.srv`` or ``.action`` file, or an interface **package** as a fileset (``package.xml``
beside its ``msg/``, ``srv/`` and ``action/`` files), read by :mod:`app.ros2_parser` and normalized
onto the **rpc** paradigm by :mod:`app.ros2_normalizer`: messages become records, services
request/response operations, and actions a goal operation plus a feedback channel.

References resolve within the import; a reference to a package outside it is kept as a declared
unresolved reference when the package is a standard ROS 2 interface package or a declared
dependency, and refused (``INPUT_REFERENCE_UNRESOLVED``) otherwise.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Optional

from . import ros2_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .ros2_parser import (
    FORMAT_KEY,
    INTERFACE_SUFFIXES,
    PACKAGE_MANIFEST,
    Ros2Document,
    Ros2ParseError,
    has_interface_lines,
    is_package_manifest,
    parse_ros2_fileset,
    parse_ros2_text,
)

__all__ = ["Ros2ImportSource"]


def _as_import_error(exc: Ros2ParseError) -> ImportSourceError:
    """Carry the reader's taxonomy code onto the adapter error."""
    return ImportSourceError(str(exc), code=exc.code)


def _has_interface_suffix(filename: Optional[str]) -> bool:
    return PurePosixPath((filename or "").strip().lower()).suffix in INTERFACE_SUFFIXES


class Ros2ImportSource(ImportSource, register=True):
    """Adapter for ROS 2 ``.msg`` / ``.srv`` / ``.action`` files and interface packages."""

    key = FORMAT_KEY
    label = "ROS 2 interfaces"
    description = (
        "Import ROS 2 interface files (.msg, .srv, .action) or a whole interface package: messages "
        "become types, services request/response operations, actions a goal operation and a "
        "feedback channel."
    )
    icon = "bot"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = (FORMAT_KEY, "ros2-interface")
    file_extensions = INTERFACE_SUFFIXES + (".xml", ".zip", ".tar.gz", ".tgz")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim interface text by its line grammar, or an interface package's ``package.xml``.

        Every content line of an interface is a field or a constant, so text whose lines *all*
        read as ROS 2 fields and constants is claimed with confidence (more so with a ``.msg`` /
        ``.srv`` / ``.action`` name). A file with that name whose lines only partly read is still
        claimed, weakly, so the reader can say which line is wrong.
        """
        text = payload.text
        if text is None:
            return NO_MATCH
        filename = payload.filename
        if (filename and PurePosixPath(filename).name == PACKAGE_MANIFEST and is_package_manifest(text)) or (
            not _has_interface_suffix(filename) and is_package_manifest(text)
        ):
            return DetectionResult(
                confidence=0.9, format=FORMAT_KEY, reason="package.xml of a rosidl interface package"
            )
        readable, unreadable = has_interface_lines(text)
        named = _has_interface_suffix(filename)
        if readable and not unreadable:
            if named:
                return DetectionResult(
                    confidence=0.95, format=FORMAT_KEY, reason="ROS 2 interface file of field and constant lines"
                )
            return DetectionResult(confidence=0.86, format=FORMAT_KEY, reason="every line is a ROS 2 field or constant")
        if named and readable:
            return DetectionResult(confidence=0.6, format=FORMAT_KEY, reason="ROS 2 interface file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Ros2Document:
        """Parse one interface file, carrying the reader's taxonomy code."""
        try:
            return parse_ros2_text(raw, label=source_label)
        except Ros2ParseError as exc:
            raise _as_import_error(exc) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Ros2Document:
        """Parse an interface package (``package.xml`` plus its interface files).

        Raises:
            ImportSourceError: When a member cannot be read or a reference cannot be resolved.
        """
        try:
            return parse_ros2_fileset(fileset, label=source_label)
        except Ros2ParseError as exc:
            raise _as_import_error(exc) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize parsed ROS 2 interfaces onto the rpc paradigm.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed ROS 2 document.
        """
        if not isinstance(native_ast, Ros2Document):
            raise ImportSourceError("ROS 2 source must be a Ros2Document (see app.ros2_parser)")
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
