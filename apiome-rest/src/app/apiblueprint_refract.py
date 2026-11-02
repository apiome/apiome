"""API Blueprint → API Elements (Refract) through ``drafter`` — MFI-16.1 (#3804).

``drafter`` (apiaryio/drafter, pinned in :mod:`app.toolchain_packaging` — :data:`DRAFTER_VERSION` —
and built from that tag in the runtime image) is the reference API
Blueprint parser. ``drafter -f json`` turns a blueprint into an **API Elements** parse result — a
Refract element tree of categories, resources, transitions, HTTP transactions, assets and MSON data
structures, plus the annotations MFI-16.3 already reports as lint.

This module keeps that tree and hashes it. :func:`refract_contract` reduces the tree to the API's
contract by dropping what the issue calls prose and examples, and what is not part of the API at all:

* **prose** — ``copy`` elements (the Markdown between sections), every ``description``, and the
  ``title`` of a group, resource, action or transaction (a heading). A ``title`` anywhere else is
  kept: on an ``hrefVariables`` member it is the parameter's *type*;
* **examples** — ``asset`` elements classed ``messageBody`` (example bodies; a ``messageBodySchema``
  asset is kept, it is a contract) and MSON ``samples``;
* **not the API** — ``annotation`` elements (drafter's warnings, which are lint) and ``sourceMap``
  attributes (positions in the source text).

:func:`refract_sha256` hashes what remains, serialized with sorted keys, so rewording a description,
editing an example body, re-indenting the blueprint or fixing a warning keeps the hash, and adding a
resource, changing a method, a status code, a header or an MSON property moves it.

The built-in reader (:mod:`app.apiblueprint_parser`) still builds the catalog model — mapping the
Refract tree onto the canonical model is MFI-16.2 — and an import never depends on ``drafter``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from .canonical_model import CanonicalApi
from .fingerprint import FingerprintHasher

__all__ = [
    "ApiBlueprintRefractHasher",
    "DRAFTER_VERSION",
    "REFRACT_ALGORITHM",
    "refract_contract",
    "refract_sha256",
]

def _pinned_drafter_version() -> str:
    """The drafter release the runtime image bundles (``toolchain_packaging``'s pin)."""
    from .toolchain_packaging import bundled_tool

    tool = bundled_tool("drafter")
    return tool.version if tool is not None and tool.version else "unknown"


#: The drafter release the hash is defined against — the bundled tool's pin, read from
#: :mod:`app.toolchain_packaging` so the two cannot drift. A different drafter can shape the tree
#: differently, so the version is recorded beside every hash.
DRAFTER_VERSION = _pinned_drafter_version()

#: Recorded beside the digest so a stored hash can be re-validated (and migrated) by algorithm.
REFRACT_ALGORITHM = "sha256-refract-contract-v1"

#: Elements dropped whole: prose and lint.
_DROPPED_ELEMENTS = frozenset({"copy", "annotation"})

#: ``meta`` keys that are prose on every element.
_PROSE_META = frozenset({"description"})

#: Elements whose ``meta.title`` is a heading (prose) rather than a type name.
_HEADED_ELEMENTS = frozenset({"category", "resource", "transition", "httpTransaction"})

#: ``attributes`` keys that are prose, examples or source positions.
_DROPPED_ATTRIBUTES = frozenset({"sourceMap", "samples", "description"})


def _classes(element: Mapping[str, Any]) -> list:
    """The plain class names of an element (``meta.classes``, a Refract array of strings)."""
    classes = (element.get("meta") or {}).get("classes")
    if isinstance(classes, Mapping):
        classes = classes.get("content")
    out = []
    for entry in classes if isinstance(classes, list) else []:
        out.append(entry.get("content") if isinstance(entry, Mapping) else entry)
    return out


def _is_dropped(value: Any) -> bool:
    """Whether a Refract element is prose, an example or lint (see the module docstring)."""
    if not isinstance(value, Mapping):
        return False
    element = value.get("element")
    if element in _DROPPED_ELEMENTS:
        return True
    return element == "asset" and "messageBody" in _classes(value)


def refract_contract(node: Any) -> Any:
    """Reduce a Refract tree (or any node of it) to the API's contract.

    Args:
        node: A drafter parse result, or any element, array or value inside one. Not mutated.

    Returns:
        A copy with prose, examples, annotations and source maps removed. An element whose ``meta``
        or ``attributes`` become empty loses that key, so a description-only difference leaves no
        trace.
    """
    if isinstance(node, list):
        return [refract_contract(item) for item in node if not _is_dropped(item)]
    if not isinstance(node, Mapping):
        return node
    reduced: dict = {}
    dropped_meta = _PROSE_META | ({"title"} if node.get("element") in _HEADED_ELEMENTS else frozenset())
    for key, value in node.items():
        if key == "meta" and isinstance(value, Mapping):
            meta = {k: refract_contract(v) for k, v in value.items() if k not in dropped_meta}
            if meta:
                reduced["meta"] = meta
        elif key == "attributes" and isinstance(value, Mapping):
            attributes = {k: refract_contract(v) for k, v in value.items() if k not in _DROPPED_ATTRIBUTES}
            if attributes:
                reduced["attributes"] = attributes
        elif key == "content" and _is_dropped(value):
            continue
        else:
            reduced[key] = refract_contract(value)
    return reduced


def refract_sha256(parse_result: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Hash a drafter parse result's contract.

    Args:
        parse_result: The ``parseResult`` element ``drafter -f json`` printed, or ``None``.

    Returns:
        64 lowercase hex digits, or ``None`` when there is no parse result.
    """
    if not isinstance(parse_result, Mapping) or parse_result.get("element") != "parseResult":
        return None
    blob = json.dumps(refract_contract(parse_result), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ApiBlueprintRefractHasher(FingerprintHasher, register=True):
    """Expose an API Blueprint import's Refract contract hash as ``FingerprintResult.format_hash``.

    Reads what the normalizer recorded (``extras["apib_refract_sha256"]``), so it needs no re-run of
    drafter; a model built without drafter yields ``None``.
    """

    format = "apiblueprint"
    algorithm = REFRACT_ALGORITHM

    def hash(self, api: CanonicalApi) -> Optional[str]:
        """Return the recorded Refract contract hash, or ``None``.

        Args:
            api: An API Blueprint canonical model.

        Returns:
            64 lowercase hex digits, or ``None``.
        """
        value = (api.extras or {}).get("apib_refract_sha256")
        return value if isinstance(value, str) and value else None
