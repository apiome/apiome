"""Multi-document intake payload — MFI-29.1 / MFI-29.2.

An :class:`IntakeFileset` (alias :data:`Fileset`) is a root document plus its sibling
members — the shape archive intake produces and format adapters (gRPC, GraphQL, AsyncAPI)
consume via :meth:`~app.import_source.ImportSource.parse_fileset`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

__all__ = ["IntakeFileset", "Fileset"]


@dataclass(frozen=True)
class IntakeFileset:
    """A root document and every sibling file needed to parse it.

    Attributes:
        root: Module-relative path of the primary document inside the set.
        members: Every member keyed by its normalised relative path (POSIX).
    """

    root: str
    members: Dict[str, str]

    @classmethod
    def from_members(
        cls,
        members: Mapping[str, str],
        *,
        root: Optional[str] = None,
    ) -> "IntakeFileset":
        """Build a fileset, requiring *root* to exist in *members*."""
        if not members:
            raise ValueError("A fileset must contain at least one member")
        chosen = (root or "").strip()
        if not chosen:
            raise ValueError("A fileset root path is required")
        if chosen not in members:
            raise ValueError(f"Fileset root {chosen!r} is not among the members")
        return cls(root=chosen, members=dict(members))

    def root_content(self) -> str:
        """Return the root member's text."""
        return self.members[self.root]


#: Alias for :class:`IntakeFileset` used in SPI/issue docs (MFI-29.2).
Fileset = IntakeFileset
