"""Safe relative paths for multi-file intake — MFI-9.1 / MFI-29.1.

Archive unpack and proto module materialisation share the same rules: paths must be
module-relative POSIX names — never absolute, never ``..``, within a depth cap, and
(optionally) matching an allowed suffix.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Optional, Sequence, Tuple

__all__ = [
    "IntakePathError",
    "validated_intake_path",
]

#: Default maximum directory depth (``a/b/c/file.ext`` → 3 components).
DEFAULT_MAX_PATH_DEPTH = 32


class IntakePathError(ValueError):
    """A member path failed intake validation."""


def validated_intake_path(
    path: str,
    *,
    required_suffix: Optional[str] = None,
    allowed_suffixes: Optional[Sequence[str]] = None,
    max_depth: int = DEFAULT_MAX_PATH_DEPTH,
    label: str = "Member",
) -> PurePosixPath:
    """Validate and normalise an archive/module member path.

    Args:
        path: The raw path from an archive entry or caller.
        required_suffix: When set, the path must end with this suffix (e.g. ``.proto``).
        allowed_suffixes: When set, the path must end with one of these suffixes.
        max_depth: Maximum number of path components (depth cap).
        label: Prefix for error messages (``Member`` vs ``Proto path``).

    Returns:
        The normalised :class:`PurePosixPath`.

    Raises:
        IntakePathError: On empty, absolute, traversing, over-deep, or wrong-suffix paths.
    """
    raw = (path or "").strip()
    if not raw:
        raise IntakePathError(f"{label} path must be non-empty")
    pure = PurePosixPath(raw.replace("\\", "/"))
    if pure.is_absolute():
        raise IntakePathError(f"{label} path must be relative, got absolute {path!r}")
    parts = pure.parts
    if not parts or any(part == ".." for part in parts):
        raise IntakePathError(f"{label} path must not escape the module root: {path!r}")
    if any(part in {"", ".", ".."} for part in parts):
        raise IntakePathError(f"{label} path is not a valid relative name: {path!r}")
    if len(parts) > max_depth:
        raise IntakePathError(
            f"{label} path exceeds the {max_depth}-level depth cap: {path!r}"
        )
    if required_suffix is not None and pure.suffix != required_suffix:
        raise IntakePathError(f"{label} path must end in {required_suffix}: {path!r}")
    if allowed_suffixes is not None:
        lower = str(pure).lower()
        if not any(lower.endswith(suffix.lower()) for suffix in allowed_suffixes):
            allowed = ", ".join(sorted(allowed_suffixes))
            raise IntakePathError(
                f"{label} path must end with one of ({allowed}), got {path!r}"
            )
    return pure


def normalised_member_name(pure: PurePosixPath) -> str:
    """Return the canonical forward-slash member key for a validated path."""
    return str(pure)
