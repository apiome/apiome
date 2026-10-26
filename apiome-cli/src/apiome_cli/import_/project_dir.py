"""Pack a local project directory into an import archive — MFI-14.5 (#3798).

``apiome import <format> <directory>`` sends a directory the way an archive upload would: its
files are zipped in memory and posted as one ``.zip``, which the server unpacks into a file set
(MFI-29.1). Build output and tooling folders are left out, and for a TypeSpec project the root is
chosen the way the TypeSpec compiler chooses its entry point.
"""

from __future__ import annotations

import io
import json
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "MAX_PROJECT_BYTES",
    "MAX_PROJECT_FILES",
    "PackedProject",
    "ProjectDirectoryError",
    "pack_project_directory",
    "project_root",
]

#: Most files a packed directory may hold.
MAX_PROJECT_FILES = 2000

#: Most bytes (uncompressed) a packed directory may hold.
MAX_PROJECT_BYTES = 64 * 1024 * 1024

#: Folders never packed: dependencies, build output and caches.
_SKIPPED_DIRECTORIES = frozenset({"node_modules", "tsp-output", "__pycache__", "dist", "build"})

#: A fixed member timestamp, so packing the same directory twice gives the same bytes.
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ProjectDirectoryError(ValueError):
    """Raised when a directory cannot be packed (empty, too large, bad root)."""


@dataclass(frozen=True)
class PackedProject:
    """A directory packed for import.

    Attributes:
        archive: The ``.zip`` bytes.
        filename: The archive's name (``<directory>.zip``).
        root: The root document inside the archive, or ``None`` to let the server choose.
        members: The packed paths, in archive order.
        skipped: Paths left out (hidden or tooling folders), for the progress line.
    """

    archive: bytes
    filename: str
    root: str | None
    members: list[str]
    skipped: list[str] = field(default_factory=list)


def _skipped(relative: Path) -> bool:
    """Whether a path is hidden or inside a dependency / build folder."""
    return any(part.startswith(".") or part in _SKIPPED_DIRECTORIES for part in relative.parts)


def project_root(directory: Path, source_format: str, members: list[str]) -> str | None:
    """The root document for a packed directory, when the format has a convention for it.

    For ``typespec``: ``package.json``'s ``tspMain`` when it names a packed file, otherwise
    ``main.tsp`` — the compiler's own entry-point rules. Other formats return ``None`` so the
    server ranks the members.

    Args:
        directory: The project directory.
        source_format: The importer format key.
        members: The packed paths.

    Returns:
        A member path, or ``None``.
    """
    if source_format != "typespec":
        return None
    package = directory / "package.json"
    if package.is_file():
        try:
            main = json.loads(package.read_text(encoding="utf-8")).get("tspMain")
        except (ValueError, AttributeError, OSError):
            main = None
        if isinstance(main, str):
            normalized = posixpath.normpath(main.replace("\\", "/"))  # "./main.tsp" → "main.tsp"
            if normalized in members:
                return normalized
    return "main.tsp" if "main.tsp" in members else None


def pack_project_directory(directory: Path, source_format: str) -> PackedProject:
    """Zip a project directory for import.

    Args:
        directory: The directory to pack.
        source_format: The importer format key (decides the root convention).

    Returns:
        The packed project.

    Raises:
        ProjectDirectoryError: When the directory has no files, or more than
            :data:`MAX_PROJECT_FILES` files / :data:`MAX_PROJECT_BYTES` bytes.
    """
    members: list[str] = []
    skipped: list[str] = []
    total = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if _skipped(relative):
                if path.is_file():
                    skipped.append(relative.as_posix())
                continue
            if not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
            total += len(data)
            if len(members) >= MAX_PROJECT_FILES or total > MAX_PROJECT_BYTES:
                raise ProjectDirectoryError(
                    f"{directory} is too large to import as one project (at most "
                    f"{MAX_PROJECT_FILES} files and {MAX_PROJECT_BYTES // (1024 * 1024)} MiB)."
                )
            info = zipfile.ZipInfo(relative.as_posix(), date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
            members.append(relative.as_posix())
    if not members:
        raise ProjectDirectoryError(f"{directory} has no files to import.")
    return PackedProject(
        archive=buffer.getvalue(),
        filename=f"{directory.resolve().name}.zip",
        root=project_root(directory, source_format, members),
        members=members,
        skipped=sorted(skipped),
    )
