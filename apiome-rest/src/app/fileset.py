"""Multi-document intake payload — MFI-29.1 / MFI-29.2.

An :class:`IntakeFileset` (alias :data:`Fileset`) is a root document plus its sibling
members — the shape archive intake produces and format adapters (gRPC, GraphQL, AsyncAPI)
consume via :meth:`~app.import_source.ImportSource.parse_fileset`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

__all__ = ["IntakeFileset", "Fileset"]


@dataclass(frozen=True)
class IntakeFileset:
    """A root document and every sibling file needed to parse it.

    Attributes:
        root: Module-relative path of the primary document inside the set.
        members: Every member keyed by its normalised relative path (POSIX).
        binary_members: The exact bytes of every member that is not UTF-8 text (FMT-9.2: a set of
            binary Sparkplug payloads). Its ``members`` entry still holds the lossy text decode,
            so text-only adapters are unaffected; a binary-aware adapter reads the bytes from here
            (:meth:`member_bytes`). Members that are valid UTF-8 are not repeated here — their
            text re-encodes to the original bytes.
    """

    root: str
    members: Dict[str, str]
    binary_members: Dict[str, bytes] = field(default_factory=dict)

    @classmethod
    def from_members(
        cls,
        members: Mapping[str, str],
        *,
        root: Optional[str] = None,
        binary_members: Optional[Mapping[str, bytes]] = None,
    ) -> "IntakeFileset":
        """Build a fileset, requiring *root* to exist in *members*.

        Args:
            members: Member text keyed by path.
            root: The root member's path.
            binary_members: Exact bytes of the members that are not UTF-8 text; every key must
                also be a member.
        """
        if not members:
            raise ValueError("A fileset must contain at least one member")
        chosen = (root or "").strip()
        if not chosen:
            raise ValueError("A fileset root path is required")
        if chosen not in members:
            raise ValueError(f"Fileset root {chosen!r} is not among the members")
        binary = dict(binary_members or {})
        stray = sorted(set(binary) - set(members))
        if stray:
            raise ValueError(f"Binary member(s) {stray!r} are not among the members")
        return cls(root=chosen, members=dict(members), binary_members=binary)

    def root_content(self) -> str:
        """Return the root member's text."""
        return self.members[self.root]

    def member_bytes(self, path: str) -> bytes:
        """Return a member's exact bytes: the raw bytes of a binary member, else its UTF-8 text."""
        if path in self.binary_members:
            return self.binary_members[path]
        return self.members[path].encode("utf-8")


#: Alias for :class:`IntakeFileset` used in SPI/issue docs (MFI-29.2).
Fileset = IntakeFileset
