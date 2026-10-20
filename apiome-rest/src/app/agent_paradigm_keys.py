"""Unique canonical keys for agent-descriptor entities — shared by MFI-18.1 / MFI-18.2.

An agent descriptor identifies its entities by a name the author chose — an A2A skill ``id``,
an ACP agent or capability ``name``. A descriptor that repeats one would collapse two entities
onto one canonical key, and the second would silently vanish from the catalog, the fingerprint
and every diff. :func:`unique_keys` keeps both: the first occurrence keeps its key, each repeat
is keyed ``<key>~2``, ``<key>~3`` … and points back at the first, so the lint packs can report
the repeat instead of the model hiding it.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

__all__ = ["unique_keys"]


def unique_keys(keys: Sequence[str]) -> List[Tuple[str, Optional[str]]]:
    """Make every key in ``keys`` unique, in order.

    Args:
        keys: Candidate canonical keys, possibly repeating.

    Returns:
        ``(unique_key, duplicate_of)`` per input key: ``duplicate_of`` is the first occurrence's
        key for a repeat, else ``None``.
    """
    counts: Dict[str, int] = {}
    out: List[Tuple[str, Optional[str]]] = []
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
        if counts[key] == 1:
            out.append((key, None))
        else:
            out.append((f"{key}~{counts[key]}", key))
    return out
