"""The generated table on *Pact Broker compatibility* — PFX-1.8 (#6921).

``apiome-docs/docs/ship/pact-broker/compatibility.mdx`` is hand-written prose around one region
this module writes from the catalog (:mod:`app.pact_broker_compat`): a count per status, then one
table per section listing every Pact Broker endpoint, the methods Apiome serves, its status and
what to use instead. ``scripts/generate_pact_broker_compat_doc.py`` rewrites the region, and
``tests/test_pact_broker_compat_doc.py`` fails when the committed page differs from a fresh render.
"""

from __future__ import annotations

from typing import List

from .pact_broker_compat import (
    COMPATIBILITY_PAGE,
    NOT_PLANNED,
    PACT_BROKER_VERSION,
    PARTIAL,
    PLANNED,
    SUPPORTED,
    BrokerEndpoint,
    endpoints_by_group,
    issue_url,
    status_counts,
)

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "REGENERATE_COMMAND",
    "apply_compat_table",
    "render_compat_table",
]

#: How to rewrite the region, as the marker tells a reader of the page source.
REGENERATE_COMMAND = "cd apiome-rest && uv run python scripts/generate_pact_broker_compat_doc.py"

BEGIN_MARKER = (
    f"{{/* pact-broker-compat:begin — generated, do not edit by hand. Regenerate with: {REGENERATE_COMMAND} */}}"
)
END_MARKER = "{/* pact-broker-compat:end */}"

#: How each status reads in the table.
_STATUS_LABEL = {
    SUPPORTED: "✅ Supported",
    PARTIAL: "◐ Partial",
    PLANNED: "🗓 Planned",
    NOT_PLANNED: "— Not planned",
}


def _cell(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _code(values: List[str]) -> str:
    """Render methods as inline code, or an em dash when there are none."""
    return " ".join(f"`{value}`" for value in values) if values else "—"


def _status(endpoint: BrokerEndpoint) -> str:
    """The status cell, with the tracking issue as a link when there is one."""
    label = _STATUS_LABEL[endpoint.status]
    if endpoint.tracking:
        label += f" ([{endpoint.tracking}]({issue_url(endpoint.tracking)}))"
    return label


def _notes(endpoint: BrokerEndpoint) -> str:
    """The notes cell: what calls it, why something is missing, and what to use instead."""
    parts = []
    if endpoint.used_by:
        parts.append(f"Used by {endpoint.used_by}.")
    if endpoint.note:
        parts.append(endpoint.note)
    if endpoint.alternative:
        alternative = endpoint.alternative
        parts.append(f"Use `{alternative}`." if alternative.startswith("/") else f"Use {alternative}.")
    return _cell(" ".join(parts)) or "—"


def render_compat_table() -> str:
    """Render the generated region, markers included, with no trailing newline.

    Returns:
        The begin marker, a summary line, one ``###`` section per catalog group with its table, and
        the end marker.
    """
    counts = status_counts()
    summary = ", ".join(f"**{counts[status]}** {status}" for status in (SUPPORTED, PARTIAL, PLANNED, NOT_PLANNED))
    lines = [
        BEGIN_MARKER,
        "",
        f"Checked against Pact Broker **{PACT_BROKER_VERSION}**: {sum(counts.values())} endpoints — {summary}.",
    ]
    for group, endpoints in endpoints_by_group().items():
        lines += [
            "",
            f"### {group}",
            "",
            "| Endpoint | Apiome serves | Not served | Status | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for endpoint in endpoints:
            lines.append(
                f"| `{endpoint.path or '/'}` — {_cell(endpoint.title)} "
                f"| {_code(list(endpoint.supported))} | {_code(list(endpoint.unsupported))} "
                f"| {_status(endpoint)} | {_notes(endpoint)} |"
            )
    lines += ["", END_MARKER]
    return "\n".join(lines)


def apply_compat_table(text: str) -> str:
    """Replace the generated region of the page with a fresh rendering.

    Args:
        text: The page's current text.

    Returns:
        The text with everything from :data:`BEGIN_MARKER` to :data:`END_MARKER` (inclusive)
        replaced by :func:`render_compat_table`.

    Raises:
        ValueError: When the page does not hold exactly one begin marker followed by one end marker.
    """
    begin = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if begin < 0 or end < begin or text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ValueError(f"{COMPATIBILITY_PAGE} must hold one '{BEGIN_MARKER}' followed by one '{END_MARKER}'.")
    return text[:begin] + render_compat_table() + text[end + len(END_MARKER) :]
