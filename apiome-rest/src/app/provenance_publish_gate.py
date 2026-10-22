"""Publish gate for inferred sources — the style-guide half of FMT-8.6 (#5467).

A catalog item is never published itself: it is converted into a Project (MFI-22.6), and the
Project's revisions are what publish. The publish precheck (:mod:`app.version_publish_prechecks`)
lints the revision's OpenAPI document, which no longer knows which of its operations were read
from a declaration and which Apiome inferred. This module carries that fact across the
conversion:

* it finds the catalog item the Project was converted from (``apiome.conversion_provenance``,
  newest conversion first);
* rebuilds that item's canonical model and runs the ``provenance.inferred-construct-ratio`` rule
  (:mod:`app.provenance_lint`) over it;
* and reports a blocking violation **only when the Project's resolved style guide sets that rule
  to** ``error``.

Under the default guide the rule is ``info`` and this gate never blocks, so publishing a Project
converted from a Postman collection behaves exactly as before. A team that wants published APIs
to come from declared sources raises the rule to ``error`` in its guide.

Best-effort like every lint step of the precheck: a missing conversion row, a deleted source
item or a model that cannot be rebuilt yields no violation rather than an error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from .inference_provenance import summarize_provenance
from .provenance_lint import INFERRED_RATIO_RULE_ID, inferred_ratio_message

logger = logging.getLogger(__name__)

__all__ = ["ProvenanceGateViolation", "converted_source_provenance_violation"]


@dataclass(frozen=True)
class ProvenanceGateViolation:
    """A blocking inferred-construct violation on a converted Project.

    Attributes:
        rule: Always :data:`~app.provenance_lint.INFERRED_RATIO_RULE_ID`.
        source_item_id: The catalog item the Project was converted from.
        source_item_name: Its display name, when known.
        message: The rule's finding message (``"62% of this item's constructs are inferred …"``).
    """

    rule: str
    source_item_id: str
    source_item_name: Optional[str]
    message: str


def converted_source_provenance_violation(
    *,
    db: Any,
    tenant_id: str,
    project_id: str,
    guide: Any,
) -> Optional[ProvenanceGateViolation]:
    """Return the blocking provenance violation for a converted Project, or ``None``.

    Args:
        db: The database facade (``get_conversions_for_project``, ``get_catalog_item_by_id``).
        tenant_id: The tenant.
        project_id: The Project about to publish.
        guide: The Project's resolved :class:`~app.style_guide_engine.CompiledStyleGuide`.

    Returns:
        A :class:`ProvenanceGateViolation` when the guide sets the rule to ``error`` and the
        Project's source catalog item has at least one inferred construct; ``None`` otherwise —
        including when the Project was not converted from a catalog item.
    """
    try:
        if guide is None or guide.severity_for(INFERRED_RATIO_RULE_ID) != "error":
            return None
        conversions = db.get_conversions_for_project(tenant_id, project_id) or []
        if not conversions:
            return None
        source_id = str(conversions[0].get("source_project_id") or "")
        item = db.get_catalog_item_by_id(source_id, tenant_id) if source_id else None
        if not item:
            return None
        # Imported lazily: rebuilding the model pulls in every import adapter.
        from .catalog_parsed_model import reconstruct_catalog_api

        summary = summarize_provenance(reconstruct_catalog_api(item))
    except Exception:  # noqa: BLE001 - a lint fault must never block publishing
        logger.warning(
            "Provenance publish gate could not read the source of project %s", project_id, exc_info=True
        )
        return None
    if not summary.inferred:
        return None
    return ProvenanceGateViolation(
        rule=INFERRED_RATIO_RULE_ID,
        source_item_id=source_id,
        source_item_name=item.get("name"),
        message=inferred_ratio_message(
            summary.inferred, summary.synthesized, summary.total, summary.inferred_percent
        ),
    )
