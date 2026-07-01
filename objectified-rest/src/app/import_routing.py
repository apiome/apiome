"""Project-vs-Catalog import routing — MFI-23.7 (#4016).

A finished import must become one of two things: a **publishable Project** (the
existing OpenAPI/Swagger path) or a **non-publishable catalog item** (MFI-23.1 —
the ``publishable = false`` slice of ``odb.projects``). This module is the single
decision point: given a resolved :class:`~app.import_source.ImportSource` adapter and
the :class:`~app.canonical_model.CanonicalApi` model it produced, it decides which,
and — crucially for the UI — *why*.

The rule (from the roadmap):

* **OpenAPI / Swagger / Arazzo** (including **TypeSpec-emitted OpenAPI**, which a TypeSpec
  adapter normalizes to an ``openapi-3.x`` format) → **Project** (``publishable``),
  exactly as today.
* **Everything else that is OpenAPI-worthy** — a non-OpenAPI import that still carries
  operations and/or types (gRPC, GraphQL, AsyncAPI, OData, …) → **catalog item**
  (non-publishable).
* **Pure data-schema sources** (Avro, Protobuf-schema, JSON-Schema, XSD) — types but no
  operations/channels → **catalog item**, additionally flagged **``schemas_only``** so
  the UI can say *why* it is not an API.

The branch is on the adapter's **emitted format** (``model.format``), not the source
tool, so a tool that emits OpenAPI (TypeSpec) routes to a Project while a tool that
emits anything else routes to the catalog — which is exactly the "and TypeSpec-emitted
OpenAPI" carve-out the ticket calls for.

The decision is **pure** (no I/O): it only reads the canonical model and the adapter's
descriptor, so it is fully unit-testable and the import pipeline (MFI-1.2) can record
it on the import summary for the UI to explain. When the canonical→catalog persistence
hook lands (a later format epic), it consumes :attr:`ImportRoutingDecision.publishable`
to call ``db.create_project(..., publishable=...)`` — ``True`` mints a Project, ``False``
mints a catalog item.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from .canonical_model import ApiParadigm, CanonicalApi
from .import_source import ImportSource

__all__ = [
    "PUBLISHABLE_FORMATS",
    "ImportTarget",
    "ImportRoutingDecision",
    "decide_import_routing",
]


#: Emitted canonical format keys whose import becomes a **publishable Project** — the
#: OpenAPI/Swagger/Arazzo family, as today. A non-OpenAPI source that *emits* one of these
#: (TypeSpec → ``openapi-3.x``) routes here too, because the branch is on the emitted
#: format, not the source tool. Every other format routes to the catalog.
PUBLISHABLE_FORMATS = frozenset({"openapi-3.0", "openapi-3.1", "swagger-2.0", "arazzo"})


class ImportTarget(str, Enum):
    """Where a finished import lands.

    ``PROJECT`` is the publishable artifact (the existing OpenAPI/Swagger path);
    ``CATALOG`` is the non-publishable catalog item (MFI-23.1). The string values are
    stable so they can be persisted on the import summary and read by the UI.
    """

    PROJECT = "project"
    CATALOG = "catalog"


@dataclass(frozen=True)
class ImportRoutingDecision:
    """The Project-vs-Catalog routing verdict for one import, with its reason.

    Frozen so a decision is an immutable record that can be stashed on the job
    summary and compared in tests. :attr:`reason` is human-readable and intended for
    the UI to surface ("why is this a catalog item and not a project?").

    Attributes:
        target: :class:`ImportTarget` — ``PROJECT`` or ``CATALOG``.
        publishable: ``True`` for a Project, ``False`` for a catalog item. This is the
            value the persistence hook passes to ``db.create_project(publishable=...)``.
        schemas_only: ``True`` when the source carries only data types (no operations
            or channels) — a pure data-schema source the UI flags "schemas-only".
            Always ``False`` for a Project.
        reason: A short, human-readable justification for the routing.
        source: The adapter key the import ran through (e.g. ``openapi``, ``grpc``).
        paradigm: The canonical paradigm value (e.g. ``rest``, ``rpc``, ``data_schema``).
        format: The emitted canonical format key the decision branched on.
        operation_count: Number of operations across all services in the model.
        type_count: Number of named data types in the model.
        channel_count: Number of event channels in the model.
    """

    target: ImportTarget
    publishable: bool
    schemas_only: bool
    reason: str
    source: str
    paradigm: str
    format: str
    operation_count: int
    type_count: int
    channel_count: int

    def as_dict(self) -> Dict[str, Any]:
        """Return the decision as a plain JSON-serializable mapping for the summary."""
        return {
            "target": self.target.value,
            "publishable": self.publishable,
            "schemas_only": self.schemas_only,
            "reason": self.reason,
            "source": self.source,
            "paradigm": self.paradigm,
            "format": self.format,
            "counts": {
                "operations": self.operation_count,
                "types": self.type_count,
                "channels": self.channel_count,
            },
        }


def decide_import_routing(
    adapter: ImportSource, model: CanonicalApi
) -> ImportRoutingDecision:
    """Decide whether an import becomes a publishable Project or a catalog item.

    Pure: reads only ``model`` and the ``adapter`` descriptor. The branch is on the
    emitted format (``model.format``) so OpenAPI/Swagger — including TypeSpec-emitted
    OpenAPI — becomes a Project and everything else becomes a catalog item, with the
    pure-data-schema case additionally flagged ``schemas_only``.

    Args:
        adapter: The resolved import-source adapter the document ran through.
        model: The canonical model the adapter normalized the document into.

    Returns:
        The :class:`ImportRoutingDecision` — target, ``publishable`` flag,
        ``schemas_only`` flag, and a human-readable reason — for the pipeline to
        record on the import summary.
    """
    fmt = (model.format or "").strip()
    fmt_key = fmt.lower()
    source = adapter.key or model.format
    paradigm = model.paradigm

    operation_count = len(model.operations())
    type_count = len(model.types)
    channel_count = len(model.channels)

    # --- OpenAPI/Swagger/Arazzo (incl. TypeSpec-emitted OpenAPI) → publishable Project ---
    if fmt_key in PUBLISHABLE_FORMATS:
        return ImportRoutingDecision(
            target=ImportTarget.PROJECT,
            publishable=True,
            schemas_only=False,
            reason=(
                f"{fmt} is an OpenAPI/Swagger/Arazzo description "
                "→ publishable Project (as today)."
            ),
            source=source,
            paradigm=paradigm.value,
            format=fmt,
            operation_count=operation_count,
            type_count=type_count,
            channel_count=channel_count,
        )

    # --- everything else → non-publishable catalog item -------------------------
    # "schemas-only" = a pure data-schema source: it carries types but exposes no
    # callable surface (no operations, no event channels). The DATA_SCHEMA paradigm
    # is the declared signal; the structural check (types but no ops/channels) backs
    # it up so a data-schema import that mis-declares its paradigm is still flagged.
    schemas_only = (
        paradigm == ApiParadigm.DATA_SCHEMA
        or (type_count > 0 and operation_count == 0 and channel_count == 0)
    )

    fmt_label = fmt or paradigm.value
    if schemas_only:
        reason = (
            f"{fmt_label} is a pure data-schema source "
            f"({type_count} type(s), no operations) → schemas-only catalog item."
        )
    elif operation_count > 0 or channel_count > 0:
        reason = (
            f"{fmt_label} is OpenAPI-worthy but not OpenAPI "
            f"({operation_count} operation(s), {type_count} type(s), "
            f"{channel_count} channel(s)) → catalog item."
        )
    else:
        # No callable surface and no types — nothing publishable to make a Project of.
        reason = (
            f"{fmt_label} carries no operations or types "
            "→ catalog item (nothing publishable detected)."
        )

    return ImportRoutingDecision(
        target=ImportTarget.CATALOG,
        publishable=False,
        schemas_only=schemas_only,
        reason=reason,
        source=source,
        paradigm=paradigm.value,
        format=fmt,
        operation_count=operation_count,
        type_count=type_count,
        channel_count=channel_count,
    )
