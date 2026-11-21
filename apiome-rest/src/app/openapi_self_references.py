"""OpenAPI 3.2 ``$self`` reference resolution for the Catalog normalizer — COA-4.2 (#7059).

OpenAPI 3.2 lets a document name itself with ``$self``; every ``$ref`` is a URI reference
resolved against it. A ``$ref`` written as an absolute or relative URI can therefore point back
into the same document (``https://api.example.com/orders.yaml#/components/schemas/Customer``,
``./orders.yaml#/…``) or at another one (``common.yaml#/…``).

The Projects importer has resolved these since OA6 (#3503,
``apiome-ui/src/app/utils/openapi-self-references.ts``). This module is the Catalog side of the
same rule, so both import paths link the same references:

* a ``$ref`` that already starts with ``#`` is local and left alone;
* any other ``$ref`` is resolved against ``$self``: when it lands on the same document it is
  rewritten to its fragment (kept exactly as written, ``#`` when it has none);
* otherwise it is left as written and listed in :attr:`SelfReferenceResolution.external`;
* a document without ``$self`` is returned unchanged.

The function is pure: the input is never mutated.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, List, Optional
from urllib.parse import urldefrag, urljoin

__all__ = ["SelfReferenceResolution", "document_self", "resolve_self_references"]

#: Base used to resolve a relative ``$self``. Only the "same document or not" comparison is taken
#: from resolved URLs, so this placeholder never leaves the module (same as the Projects importer).
_PLACEHOLDER_BASE = "https://apiome.invalid/"


@dataclass
class SelfReferenceResolution:
    """The outcome of :func:`resolve_self_references`.

    Attributes:
        document: The document to normalize — a rewritten copy when any ``$ref`` changed, else
            the input itself.
        self_uri: The ``$self`` the references were resolved against, or ``None``.
        rewritten: How many ``$ref`` values were rewritten to a local fragment.
        external: Distinct ``$ref`` values that point at another document, as written, in
            first-seen order.
    """

    document: Any
    self_uri: Optional[str] = None
    rewritten: int = 0
    external: List[str] = field(default_factory=list)


def document_self(document: Any) -> Optional[str]:
    """Read a document's ``$self``.

    Args:
        document: A parsed OpenAPI document.

    Returns:
        The trimmed ``$self`` string, or ``None`` when it is absent, empty or not a string.
    """
    value = document.get("$self") if isinstance(document, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _same_document(reference: str, base: str) -> Optional[bool]:
    """Whether ``reference`` resolved against ``base`` names the document ``base`` names.

    Args:
        reference: A non-local ``$ref`` value.
        base: The absolute ``$self`` URL.

    Returns:
        ``True`` / ``False``, or ``None`` when the reference cannot be parsed.
    """
    try:
        target = urljoin(base, reference)
    except ValueError:
        return None
    return urldefrag(target).url == urldefrag(base).url


def resolve_self_references(document: Any) -> SelfReferenceResolution:
    """Resolve the ``$ref`` values of an OpenAPI document against its ``$self``.

    Args:
        document: A parsed OpenAPI document (never mutated).

    Returns:
        A :class:`SelfReferenceResolution`. Without ``$self`` the document is returned
        unchanged with nothing rewritten or listed.
    """
    self_uri = document_self(document)
    if self_uri is None:
        return SelfReferenceResolution(document=document)
    try:
        base = urljoin(_PLACEHOLDER_BASE, self_uri)
    except ValueError:
        return SelfReferenceResolution(document=document, self_uri=self_uri)

    working = copy.deepcopy(document)
    external: List[str] = []
    rewritten = 0
    stack: List[Any] = [working]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
            continue
        if not isinstance(node, dict):
            continue
        ref = node.get("$ref")
        if isinstance(ref, str) and ref and not ref.startswith("#"):
            same = _same_document(ref, base)
            if same:
                hash_at = ref.find("#")
                node["$ref"] = ref[hash_at:] if hash_at >= 0 else "#"
                rewritten += 1
            elif same is False and ref not in external:
                external.append(ref)
        stack.extend(reversed(list(node.values())))

    return SelfReferenceResolution(
        document=working if rewritten else document,
        self_uri=self_uri,
        rewritten=rewritten,
        external=external,
    )
