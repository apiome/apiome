"""Compatibility mode flags shared by ``apiome diff`` and ``apiome compat`` (XPC-4.5, #5749).

``--mode`` (BACKWARD / FORWARD / FULL / NONE, optionally ``_TRANSITIVE``), ``--transitive`` and
``--category`` (Protobuf: WIRE / WIRE_JSON / PACKAGE / FILE) are passed to the server as ``mode``,
``transitive`` and ``category``. A flag left off is left out of the request, so the server uses the
project's style-guide policy — which is how the CI diff gate reads the policy by default.

The server reports what it graded under in ``evaluatedUnder``; :func:`describe_evaluated_under`
turns that into the one line both commands print.
"""

from __future__ import annotations

from typing import Any, Optional

import typer

__all__ = [
    "CATEGORIES",
    "MODES",
    "describe_evaluated_under",
    "mode_request_fields",
    "normalize_category",
    "normalize_mode",
]

#: The compatibility modes the server accepts (each also as ``<MODE>_TRANSITIVE`` but ``NONE``).
MODES = ("BACKWARD", "FORWARD", "FULL", "NONE")
#: The buf breaking categories, least strict first.
CATEGORIES = ("WIRE", "WIRE_JSON", "PACKAGE", "FILE")
_TRANSITIVE = "_TRANSITIVE"


def normalize_mode(value: Optional[str]) -> Optional[str]:
    """Upper-case and check ``--mode``.

    Args:
        value: The flag value, any case, or ``None``.

    Returns:
        The mode name (``FULL_TRANSITIVE`` kept whole), or ``None`` when the flag was not given.

    Raises:
        typer.BadParameter: For a mode the server would reject.
    """
    if value is None or not value.strip():
        return None
    mode = value.strip().upper().replace("-", "_")
    plain = mode[: -len(_TRANSITIVE)] if mode.endswith(_TRANSITIVE) else mode
    if plain not in MODES or mode == f"NONE{_TRANSITIVE}":
        raise typer.BadParameter(
            "must be one of backward, forward, full or none (optionally with _transitive)",
            param_hint="--mode",
        )
    return mode


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Upper-case and check ``--category``.

    Raises:
        typer.BadParameter: For a category the server would reject.
    """
    if value is None or not value.strip():
        return None
    category = value.strip().upper().replace("-", "_")
    if category not in CATEGORIES:
        raise typer.BadParameter("must be one of wire, wire_json, package or file", param_hint="--category")
    return category


def mode_request_fields(
    mode: Optional[str], transitive: Optional[bool], category: Optional[str]
) -> dict[str, Any]:
    """The request-body fields for the flags that were given.

    Args:
        mode: ``--mode`` (unchecked); ``None`` when not given.
        transitive: ``--transitive`` / ``--no-transitive``; ``None`` when neither was given.
        category: ``--category`` (unchecked); ``None`` when not given.

    Returns:
        ``{"mode", "transitive", "category"}`` with only the given ones present.
    """
    fields: dict[str, Any] = {}
    checked_mode = normalize_mode(mode)
    checked_category = normalize_category(category)
    if checked_mode is not None:
        fields["mode"] = checked_mode
    if transitive is not None:
        fields["transitive"] = bool(transitive)
    if checked_category is not None:
        fields["category"] = checked_category
    return fields


def describe_evaluated_under(evaluated: Any) -> Optional[str]:
    """One line saying what a verdict was graded under, or ``None`` when the server sent nothing.

    Examples: ``Evaluated under FULL_TRANSITIVE (avro-compatibility; avro) against 2.0.0, 1.0.0`` or
    ``Evaluated under FORWARD — mode not applied: graded by ctg (openapi)``.

    Args:
        evaluated: The response's ``evaluatedUnder`` object.

    Returns:
        The line, or ``None``.
    """
    if not isinstance(evaluated, dict) or not evaluated.get("mode"):
        return None
    mode = str(evaluated["mode"])
    if evaluated.get("transitive") and mode != "NONE":
        mode += _TRANSITIVE
    formats = ", ".join(str(f) for f in evaluated.get("formats") or [])
    ruleset = str(evaluated.get("ruleset") or "?")
    detail = f"{ruleset}; {formats}" if formats else ruleset
    if evaluated.get("modeApplied"):
        line = f"Evaluated under {mode} ({detail})"
    else:
        line = f"Evaluated under {mode} — mode not applied: graded by {detail}"
    if evaluated.get("categoryApplied") and evaluated.get("category"):
        line += f", Protobuf category {evaluated['category']}"
    compared = [
        str(r.get("versionLabel"))
        for r in evaluated.get("comparedRevisions") or []
        if isinstance(r, dict) and r.get("versionLabel")
    ]
    if len(compared) > 1:
        line += f" against {', '.join(compared)}"
        if evaluated.get("comparedRevisionsTruncated"):
            line += " (more earlier revisions were not checked)"
    return line
