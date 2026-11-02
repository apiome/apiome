"""COBOL copybook record-layout hash — MFI-21.1 (#3991).

The semantic fingerprint (:func:`~app.fingerprint.canonical_fingerprint`) flips on any structural
change, a renamed item included. A copybook has a second notion of identity that matters more to
the programs reading its files: **are the bytes laid out the same way?** Two copybooks that put
the same kinds of storage at the same offsets read each other's records, whatever their items are
called — renaming ``CUST-NAME`` to ``CUSTOMER-NAME``, renumbering ``05`` levels to ``10``, or
adding an 88-level condition changes nothing a program reads off the file.

:class:`CobolCopybookLayoutHasher` hashes exactly that. For every item, in source order, it takes
the item's depth, its offset and lengths, its storage (the ``PICTURE`` / ``USAGE`` size and
basis, the digit and decimal counts, the sign), its ``OCCURS`` bounds, whether a ``DEPENDING ON``
controls it, and which earlier sibling (by position) it ``REDEFINES`` — and never its name,
level number or conditions. Equal layout hashes mean byte-compatible records under the
assumptions :data:`~app.cobolcopybook_layout.LAYOUT_ASSUMPTIONS` names.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

from .canonical_model import CanonicalApi
from .cobolcopybook_layout import FieldLayout, compute_layout
from .cobolcopybook_parser import CobolField, field_from_template
from .fingerprint import FingerprintHasher

__all__ = [
    "LAYOUT_HASH_ALGORITHM",
    "CobolCopybookLayoutHasher",
    "layout_signature",
    "record_tree",
]

#: Algorithm label recorded beside the hash (``FingerprintResult.format_algorithm``).
LAYOUT_HASH_ALGORITHM = "cobol-record-layout-sha256"


def record_tree(api: CanonicalApi) -> Optional[CobolField]:
    """The copybook record a canonical model was normalized from.

    Args:
        api: A model the copybook normalizer built (it records ``extras["cobolcopybook_tree"]``).

    Returns:
        The rebuilt level-01 :class:`~app.cobolcopybook_parser.CobolField`, or ``None`` when the model
        carries no (readable) tree — another format, or a hand-built model.
    """
    template = api.extras.get("cobolcopybook_tree")
    if not isinstance(template, Mapping):
        return None
    try:
        return field_from_template(template)
    except ValueError:
        return None


def _item_signature(
    field: CobolField, layout: Optional[FieldLayout], depth: int, redefines_index: Optional[int]
) -> Dict[str, Any]:
    """The name-blind facts of one item that decide how its bytes are read."""
    size = layout.picture if layout is not None else None
    return {
        "depth": depth,
        "group": bool(field.children),
        "offset": layout.offset if layout is not None else None,
        "offset_variable": bool(layout and layout.offset_variable),
        "length": layout.length if layout is not None else None,
        "total_length": layout.total_length if layout is not None else None,
        "min_total_length": layout.min_total_length if layout is not None else None,
        "basis": size.basis if size is not None else None,
        "digits": size.digits if size is not None else None,
        "decimals": size.decimals if size is not None else None,
        "signed": bool(size and size.signed),
        "text": bool(field.picture and any(c in field.picture.upper() for c in "XA")),
        "occurs_min": field.occurs_min,
        "occurs_max": field.occurs_max,
        "depending": field.depending_on is not None,
        "redefines": redefines_index,
    }


def layout_signature(root: CobolField) -> List[Dict[str, Any]]:
    """Every item's name-blind layout facts, in source order.

    Args:
        root: The level-01 item.

    Returns:
        One dict per item (the root first). A ``REDEFINES`` is recorded as the position of the
        sibling it redefines among its parent's children, so renaming that sibling does not change it.
    """
    layouts = compute_layout(root)
    signature: List[Dict[str, Any]] = []

    def walk(field: CobolField, depth: int, redefines_index: Optional[int]) -> None:
        signature.append(_item_signature(field, layouts.get(id(field)), depth, redefines_index))
        positions = {child.name: index for index, child in enumerate(field.children)}
        for child in field.children:
            walk(child, depth + 1, positions.get(child.redefines) if child.redefines else None)

    walk(root, 0, None)
    return signature


class CobolCopybookLayoutHasher(FingerprintHasher, register=True):
    """SHA-256 over a copybook's record layout, blind to names (see the module docstring)."""

    format = "cobolcopybook"
    algorithm = LAYOUT_HASH_ALGORITHM

    def hash(self, api: CanonicalApi) -> Optional[str]:
        """Hash the layout of the record ``api`` was normalized from.

        Args:
            api: A copybook canonical model.

        Returns:
            The hex SHA-256 of :func:`layout_signature`, or ``None`` when the model carries no tree.
        """
        root = record_tree(api)
        if root is None:
            return None
        payload = json.dumps(layout_signature(root), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
