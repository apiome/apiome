"""XML-RPC spec rules for an emitted message — COA-3.4 (#7055).

The post-emit validator for the ``xmlrpc`` target
(:func:`app.export_validation.validate_emitted_artifact`) checks an emitted file against the
XML-RPC specification before it re-imports it. Two independent authorities are used:

* the **structure** the specification sets out — a ``methodCall`` (one non-empty
  ``methodName`` made of ``A-Z a-z 0-9 _ . : /``, optional ``params``) or a
  ``methodResponse``;
* the **value types**, checked by Python's own XML-RPC unmarshaller
  (:func:`xmlrpc.client.loads`), a reference implementation independent of Apiome's reader: an
  unknown value tag, an ``<int>`` that is not an integer, a ``<boolean>`` other than ``0`` /
  ``1``, a ``<double>`` that is not a number or bad Base64 is rejected.

The text is first parsed by :func:`app.secure_xml.parse_xml` (no DTDs, no entity expansion, a
depth limit), so the stdlib unmarshaller only ever sees a document that is already known to be
safe XML.

Each finding carries its rule id as ``rule``: ``xmlrpc.document``, ``xmlrpc.method-name`` or
``xmlrpc.value``.
"""

from __future__ import annotations

import re
import xmlrpc.client
from typing import Any, Dict, List, Optional

from .secure_xml import SecureXmlError, parse_xml

__all__ = ["xmlrpc_spec_problems"]

#: The characters the XML-RPC specification allows in a ``methodName``.
_METHOD_NAME = re.compile(r"^[A-Za-z0-9_.:/]+$")


def _problem(rule: str, message: str, *, file: Optional[str]) -> Dict[str, Any]:
    """One finding in the shape :mod:`app.export_validation` turns into a ``ValidationFinding``."""
    return {"rule": rule, "message": message, "file": file, "path": None}


def _local(tag: str) -> str:
    """The local name of a (possibly namespaced) element tag."""
    return tag.rsplit("}", 1)[-1]


def xmlrpc_spec_problems(content: str, *, file: Optional[str] = None) -> List[Dict[str, Any]]:
    """Check one emitted XML-RPC message against the XML-RPC specification.

    Args:
        content: The message text.
        file: The bundle-relative path, echoed into each finding.

    Returns:
        Findings as ``{"rule", "message", "file", "path"}`` dicts; empty when the message meets
        every rule in the module docstring.
    """
    try:
        root = parse_xml(content, source_label=file)
    except SecureXmlError as exc:
        return [_problem("xmlrpc.document", f"The message is not safe, well-formed XML: {exc}", file=file)]

    root_tag = _local(root.tag)
    if root_tag not in ("methodCall", "methodResponse"):
        return [
            _problem(
                "xmlrpc.document",
                f"The root element must be `methodCall` or `methodResponse` (found `{root_tag}`).",
                file=file,
            )
        ]

    problems: List[Dict[str, Any]] = []
    if root_tag == "methodCall":
        names = [child for child in root if isinstance(child.tag, str) and _local(child.tag) == "methodName"]
        if len(names) != 1:
            problems.append(
                _problem("xmlrpc.method-name", "A `methodCall` must have exactly one `methodName`.", file=file)
            )
        else:
            name = (names[0].text or "").strip()
            if not _METHOD_NAME.match(name):
                problems.append(
                    _problem(
                        "xmlrpc.method-name",
                        f"`methodName` {name!r} must be non-empty and use only A-Z, a-z, 0-9, "
                        "underscore, dot, colon and slash.",
                        file=file,
                    )
                )

    try:
        xmlrpc.client.loads(content, use_builtin_types=True)
    except xmlrpc.client.Fault:
        # A well-formed ``<fault>`` response is a legal message; the unmarshaller raises it by design.
        pass
    except Exception as exc:  # noqa: BLE001 — any unmarshalling failure means an illegal value
        problems.append(_problem("xmlrpc.value", f"A value does not read as XML-RPC: {exc}", file=file))
    return problems
