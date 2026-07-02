"""MCP capability-surface normalization (V2-MCP-16.4, #3660).

This is the layer that turns the two *raw* outputs of discovery — the
:class:`~app.mcp_client.handshake.InitializeResult` (server identity, declared
capabilities, instructions) and the :class:`~app.mcp_client.discovery.DiscoveryListings`
(the fully-paged ``tools``/``resources``/``resourceTemplates``/``prompts`` arrays,
each item still a verbatim wire ``dict``) — into a single canonical
:class:`DiscoverySurface`.

Three problems motivate a normalization step rather than passing raw blobs around:

1. **Field sets differ across protocol revisions.** A 2025-03-26 server omits the
   ``title`` field everywhere and the tool ``outputSchema``; a 2025-06-18 server
   includes them. Downstream diff/lint/store code needs a *stable shape* where the
   absent fields are simply ``None`` rather than missing keys, so it never has to
   branch on the wire revision. :class:`CapabilityItem` is that stable shape — a
   union of every promoted column, mirroring the ``apiome.mcp_capability_items`` table.
2. **Map ordering is not significant but byte-stability matters.** JSON objects are
   unordered maps, so the same logical server can return ``{"name":…,"title":…}`` or
   ``{"title":…,"name":…}``. Change detection (V2-MCP-18.1) compares *fingerprints*, so
   two byte-different-but-logically-identical surfaces must normalize to the same
   bytes. :meth:`DiscoverySurface.canonical_json` sorts object keys recursively
   (``sort_keys=True``) while preserving the server's *list* order (carried as each
   item's ``ordinal``), so map reordering is invisible to the fingerprint but a real
   reordering of items is not. The fingerprint is computed over a *semantic
   projection* of the surface (:data:`FINGERPRINT_FIELDS`), not the verbatim wire:
   only the fields that define the server's offering are hashed, and volatile
   metadata (the reserved ``_meta`` block, a resource's ``size`` hint, vendor
   extension keys) is excluded so it never flips ``surface_fingerprint``.
3. **The surface must round-trip to and from the normalized store.** Each item maps
   cleanly to one ``mcp_capability_items`` row (:meth:`CapabilityItem.to_row` /
   :meth:`CapabilityItem.from_row`) and the verbatim wire entry is preserved per item
   in ``raw`` so nothing is lost even for fields without a promoted column (a prompt's
   ``arguments``, a resource's ``mimeType``, …). ``surface.tools`` etc. reconstructed
   from their rows compare equal to the originals.

The surface-level identity fields (``serverInfo``, ``capabilities``, ``instructions``,
``protocol_version``) map to the parent ``mcp_endpoint_versions`` snapshot row rather
than to ``mcp_capability_items``; :meth:`DiscoverySurface.to_version_row` produces that
mapping. The item rows reference their snapshot through ``version_id``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .discovery import DiscoveryListings
from .handshake import InitializeResult, ServerInfo

# The four MCP capability kinds, as stored in ``mcp_capability_items.item_type``.
ITEM_TYPE_TOOL = "tool"
ITEM_TYPE_RESOURCE = "resource"
ITEM_TYPE_RESOURCE_TEMPLATE = "resource_template"
ITEM_TYPE_PROMPT = "prompt"

# All four kinds, in the deterministic order surfaces enumerate and emit them.
ITEM_TYPES: Tuple[str, ...] = (
    ITEM_TYPE_TOOL,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_PROMPT,
)

# ---------------------------------------------------------------------------
# Surface fingerprint (V2-MCP-18.1): the documented, semantically meaningful
# field list. Only these fields define "did the server's offering change?"; a
# fingerprint computed over them is identical for identical offerings across
# runs and hosts, yet flips when any one of them changes (e.g. a single tool
# description edit).
# ---------------------------------------------------------------------------

# The reserved MCP metadata key. Per the spec, ``_meta`` is the escape hatch every
# object may carry for implementation-specific, non-semantic data (progress tokens,
# trace ids, cursors, …). It is volatile by design, so it is stripped *recursively*
# from every value before fingerprinting and therefore never flips the fingerprint.
RESERVED_META_KEY = "_meta"

# Per capability kind, the wire field names that feed the fingerprint, in canonical
# emission order. Anything not listed here is excluded from the fingerprint: a
# resource's volatile ``size`` byte-count hint, any vendor extension keys, and the
# reserved ``_meta`` block. ``mimeType`` (resources/templates) and ``arguments``
# (prompts) have no promoted column and are read back from the verbatim ``raw`` entry;
# the rest come from the promoted, version-normalized attributes.
FINGERPRINT_FIELDS: Dict[str, Tuple[str, ...]] = {
    ITEM_TYPE_TOOL: (
        "name",
        "title",
        "description",
        "inputSchema",
        "outputSchema",
        "annotations",
    ),
    ITEM_TYPE_RESOURCE: ("name", "title", "description", "uri", "mimeType", "annotations"),
    ITEM_TYPE_RESOURCE_TEMPLATE: (
        "name",
        "title",
        "description",
        "uriTemplate",
        "mimeType",
        "annotations",
    ),
    ITEM_TYPE_PROMPT: ("name", "title", "description", "arguments"),
}

# The surface-level (non-item) fields that feed the fingerprint, for documentation
# and parity with :meth:`DiscoverySurface.canonical_dict`: the negotiated
# ``protocolVersion``; the server identity ``serverInfo`` (``name``/``title``/
# ``version``); the declared ``capabilities`` object; and free-text ``instructions``.
FINGERPRINT_SURFACE_FIELDS: Tuple[str, ...] = (
    "protocolVersion",
    "serverInfo",
    "capabilities",
    "instructions",
)


# ===========================================================================
# Capability item
# ===========================================================================


@dataclass(frozen=True)
class CapabilityItem:
    """One normalized capability (a tool, resource, resource template, or prompt).

    The shape is the *union* of every promoted ``mcp_capability_items`` column,
    discriminated by :attr:`item_type`; columns that do not apply to a kind are
    ``None`` (a prompt has no ``uri``; a resource has no ``input_schema``). Fields
    absent on older protocol revisions (``title`` everywhere, ``output_schema`` on
    tools) are likewise ``None``. The verbatim wire entry is always kept in
    :attr:`raw`, so no field is lost even when it lacks a promoted column.

    Attributes:
        item_type: One of ``tool``/``resource``/``resource_template``/``prompt``.
        name: Programmatic identifier (required for every kind on the wire).
        ordinal: Zero-based position within its kind's discovered list, preserving
            the server's ordering.
        title: Optional human-facing label (2025-06-18+); ``None`` on older servers.
        description: Optional free-text description.
        input_schema: Tool argument JSON Schema; ``None`` for non-tool kinds.
        output_schema: Optional tool structured-result JSON Schema (2025-06-18+);
            ``None`` on older servers / non-tool kinds.
        annotations: Optional behavioural hints (e.g. ``readOnlyHint``, ``audience``).
        uri: Concrete resource URI; ``None`` for non-resource kinds.
        uri_template: Resource-template URI Template (RFC 6570); ``None`` otherwise.
        raw: The verbatim wire object for this item, retained for full fidelity.
    """

    item_type: str
    name: str
    ordinal: int
    title: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    annotations: Optional[Dict[str, Any]] = None
    uri: Optional[str] = None
    uri_template: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    # -- Parsing (raw wire entry -> normalized item) ------------------------

    @classmethod
    def from_tool(cls, payload: Mapping[str, Any], ordinal: int) -> "CapabilityItem":
        """Normalize one ``tools/list`` entry into a ``tool`` item."""
        return cls(
            item_type=ITEM_TYPE_TOOL,
            name=_name(payload),
            ordinal=ordinal,
            title=_optional_str(payload.get("title")),
            description=_optional_str(payload.get("description")),
            input_schema=_optional_object(payload.get("inputSchema")),
            output_schema=_optional_object(payload.get("outputSchema")),
            annotations=_optional_object(payload.get("annotations")),
            raw=dict(payload),
        )

    @classmethod
    def from_resource(cls, payload: Mapping[str, Any], ordinal: int) -> "CapabilityItem":
        """Normalize one ``resources/list`` entry into a ``resource`` item."""
        return cls(
            item_type=ITEM_TYPE_RESOURCE,
            name=_name(payload),
            ordinal=ordinal,
            title=_optional_str(payload.get("title")),
            description=_optional_str(payload.get("description")),
            uri=_optional_str(payload.get("uri")),
            annotations=_optional_object(payload.get("annotations")),
            raw=dict(payload),
        )

    @classmethod
    def from_resource_template(
        cls, payload: Mapping[str, Any], ordinal: int
    ) -> "CapabilityItem":
        """Normalize one ``resources/templates/list`` entry into a template item."""
        return cls(
            item_type=ITEM_TYPE_RESOURCE_TEMPLATE,
            name=_name(payload),
            ordinal=ordinal,
            title=_optional_str(payload.get("title")),
            description=_optional_str(payload.get("description")),
            uri_template=_optional_str(payload.get("uriTemplate")),
            annotations=_optional_object(payload.get("annotations")),
            raw=dict(payload),
        )

    @classmethod
    def from_prompt(cls, payload: Mapping[str, Any], ordinal: int) -> "CapabilityItem":
        """Normalize one ``prompts/list`` entry into a ``prompt`` item.

        A prompt's ``arguments`` list has no promoted column; it is preserved
        verbatim in :attr:`raw`.
        """
        return cls(
            item_type=ITEM_TYPE_PROMPT,
            name=_name(payload),
            ordinal=ordinal,
            title=_optional_str(payload.get("title")),
            description=_optional_str(payload.get("description")),
            raw=dict(payload),
        )

    # -- Fingerprint projection (semantically meaningful fields only) -------

    def fingerprint_projection(self) -> Dict[str, Any]:
        """Return only this item's fingerprint-relevant fields (V2-MCP-18.1).

        The result is the kind-specific allow-list named in
        :data:`FINGERPRINT_FIELDS` and nothing else, so volatile or vendor-specific
        wire fields (a resource's ``size`` hint, the reserved ``_meta`` block,
        unknown extension keys) never influence the surface fingerprint. Promoted,
        version-normalized attributes supply most fields; ``mimeType`` and
        ``arguments`` — which have no promoted column — are read from :attr:`raw`.
        The reserved ``_meta`` key is stripped *recursively* from every included
        value (e.g. inside ``inputSchema`` or a prompt ``argument``).

        Returns:
            A JSON-ready dict whose keys are exactly ``FINGERPRINT_FIELDS[item_type]``
            (wire spelling, e.g. ``inputSchema``); absent fields are ``None``.
        """
        source: Dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": self.annotations,
            "uri": self.uri,
            "uriTemplate": self.uri_template,
            # No promoted column — recovered from the verbatim wire entry.
            "mimeType": _optional_str(self.raw.get("mimeType")),
            "arguments": self.raw.get("arguments"),
        }
        return {field_name: _strip_meta(source[field_name]) for field_name in FINGERPRINT_FIELDS[self.item_type]}

    # -- DB row mapping (item <-> mcp_capability_items row) -----------------

    def to_row(self, version_id: Any) -> Dict[str, Any]:
        """Map this item to an ``mcp_capability_items`` insert row.

        The DB assigns ``id`` and ``created_at``; this payload supplies every other
        column. ``raw`` is returned as a Python object (the caller serializes it to
        JSONB).

        Args:
            version_id: The owning ``mcp_endpoint_versions`` snapshot id.

        Returns:
            A dict keyed by column name, ready to insert.
        """
        return {
            "version_id": version_id,
            "item_type": self.item_type,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "annotations": self.annotations,
            "uri": self.uri,
            "uri_template": self.uri_template,
            "raw": self.raw,
            "ordinal": self.ordinal,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CapabilityItem":
        """Rebuild an item from an ``mcp_capability_items`` row (the inverse of
        :meth:`to_row`).

        Accepts the column names emitted by :meth:`to_row`; the DB-only ``id`` and
        ``created_at`` columns, if present, are ignored.
        """
        return cls(
            item_type=str(row["item_type"]),
            name=str(row["name"]),
            ordinal=int(row["ordinal"]),
            title=_optional_str(row.get("title")),
            description=_optional_str(row.get("description")),
            input_schema=_optional_object(row.get("input_schema")),
            output_schema=_optional_object(row.get("output_schema")),
            annotations=_optional_object(row.get("annotations")),
            uri=_optional_str(row.get("uri")),
            uri_template=_optional_str(row.get("uri_template")),
            raw=dict(row["raw"]) if isinstance(row.get("raw"), Mapping) else {},
        )


# ===========================================================================
# Discovery surface
# ===========================================================================


@dataclass(frozen=True)
class DiscoverySurface:
    """The canonical, version-tolerant capability surface of one MCP server.

    Combines the handshake identity fields with the four normalized capability
    lists in a single stable shape. The lists preserve the server's discovery
    order (also recorded as each item's :attr:`~CapabilityItem.ordinal`); object-key
    ordering within any item is *not* significant and is canonicalized away by
    :meth:`canonical_json`.

    Attributes:
        protocol_version: The negotiated MCP protocol version, or ``None`` if
            unknown.
        server_info: The parsed :class:`~app.mcp_client.handshake.ServerInfo`.
        capabilities: The server's declared capabilities object, verbatim.
        instructions: Free-text usage guidance the server advertised, if any.
        tools: Normalized ``tool`` items, in discovery order.
        resources: Normalized ``resource`` items, in discovery order.
        resource_templates: Normalized ``resource_template`` items, in order.
        prompts: Normalized ``prompt`` items, in discovery order.
    """

    protocol_version: Optional[str] = None
    server_info: ServerInfo = field(default_factory=ServerInfo)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    instructions: Optional[str] = None
    tools: Tuple[CapabilityItem, ...] = ()
    resources: Tuple[CapabilityItem, ...] = ()
    resource_templates: Tuple[CapabilityItem, ...] = ()
    prompts: Tuple[CapabilityItem, ...] = ()

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_discovery(
        cls,
        initialize: InitializeResult,
        listings: DiscoveryListings,
    ) -> "DiscoverySurface":
        """Build a surface from a handshake result and its discovery listings.

        This is the normal entry point: it pairs the
        :class:`~app.mcp_client.handshake.InitializeResult` (identity, capabilities,
        instructions, protocol version) with the
        :class:`~app.mcp_client.discovery.DiscoveryListings` (the raw, fully-paged
        item arrays), assigning each kind a zero-based ordinal in list order.

        Args:
            initialize: The negotiated handshake result.
            listings: The fully-paged raw listings discovered over the same session.

        Returns:
            The canonical :class:`DiscoverySurface`.
        """
        return cls(
            protocol_version=initialize.protocol_version,
            server_info=initialize.server_info,
            capabilities=dict(initialize.capabilities),
            instructions=initialize.instructions,
            tools=_normalize(listings.tools, CapabilityItem.from_tool),
            resources=_normalize(listings.resources, CapabilityItem.from_resource),
            resource_templates=_normalize(
                listings.resource_templates, CapabilityItem.from_resource_template
            ),
            prompts=_normalize(listings.prompts, CapabilityItem.from_prompt),
        )

    # -- Convenience accessors ---------------------------------------------

    def all_items(self) -> Tuple[CapabilityItem, ...]:
        """Every item across all four kinds, in deterministic (kind, ordinal) order."""
        return (
            *self.tools,
            *self.resources,
            *self.resource_templates,
            *self.prompts,
        )

    # -- Canonical serialization / fingerprint ------------------------------

    def canonical_dict(self) -> Dict[str, Any]:
        """Return the surface's *semantic projection* as a plain, JSON-ready dict.

        This is the input to the surface fingerprint (V2-MCP-18.1): the surface-level
        identity fields (:data:`FINGERPRINT_SURFACE_FIELDS` — ``protocolVersion``,
        ``serverInfo``, ``capabilities``, ``instructions``) plus each item's
        :meth:`~CapabilityItem.fingerprint_projection` (its allow-listed semantic
        fields only). Volatile and vendor-specific wire fields — the reserved
        ``_meta`` block (stripped recursively, including from ``capabilities``), a
        resource's ``size`` hint, unknown extension keys — are excluded, so they
        cannot affect the fingerprint.

        List order is the server's discovery order. Object-key ordering is *not*
        fixed here — it is canonicalized by :meth:`canonical_json` via ``sort_keys`` —
        so this dict alone is not byte-stable; use :meth:`canonical_json` for
        comparison/fingerprinting. The verbatim wire entry of each item remains
        available on :attr:`~CapabilityItem.raw` for storage/round-trip; only the
        fingerprint deliberately narrows to the semantic fields.
        """
        return {
            "protocolVersion": self.protocol_version,
            "serverInfo": {
                "name": self.server_info.name,
                "title": self.server_info.title,
                "version": self.server_info.version,
            },
            "capabilities": _strip_meta(self.capabilities),
            "instructions": self.instructions,
            "tools": [item.fingerprint_projection() for item in self.tools],
            "resources": [item.fingerprint_projection() for item in self.resources],
            "resourceTemplates": [item.fingerprint_projection() for item in self.resource_templates],
            "prompts": [item.fingerprint_projection() for item in self.prompts],
        }

    def canonical_json(self) -> str:
        """Serialize the semantic projection to byte-stable canonical JSON.

        Object keys are sorted recursively, so two surfaces that differ only in
        wire map ordering serialize to identical strings; list order (the server's
        item ordering) is preserved. Compact separators keep the output minimal.
        Because the source is :meth:`canonical_dict` (the semantic projection),
        volatile fields are already excluded.
        """
        return json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def fingerprint(self) -> str:
        """Return the stable SHA-256 ``surface_fingerprint`` (V2-MCP-18.1).

        The digest is taken over :meth:`canonical_json` — the byte-stable canonical
        form of the surface's *semantic projection*. Equal fingerprints mean two
        discoveries produced the same logical offering (identical across runs and
        hosts); a change to any semantically meaningful field — a tool description,
        an input schema, an added prompt argument, the server version — flips it,
        while a change confined to a volatile field (``_meta``, a resource ``size``
        hint, a vendor extension) does not. Recorded as ``surface_fingerprint`` on
        ``mcp_endpoint_versions``.
        """
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    # -- DB row mapping -----------------------------------------------------

    def to_capability_rows(self, version_id: Any) -> List[Dict[str, Any]]:
        """Map every item to its ``mcp_capability_items`` insert row.

        Rows are emitted in deterministic order — tools, then resources, then
        resource templates, then prompts, each in ordinal order — so a re-run over
        an unchanged surface produces an identical row sequence.

        Args:
            version_id: The owning ``mcp_endpoint_versions`` snapshot id stamped on
                every row.

        Returns:
            One row dict per item (see :meth:`CapabilityItem.to_row`).
        """
        return [item.to_row(version_id) for item in self.all_items()]

    def to_version_row(self) -> Dict[str, Any]:
        """Map the surface identity to ``mcp_endpoint_versions`` snapshot columns.

        Covers the columns derived from the surface itself (server identity,
        capabilities, instructions, protocol version, and the surface fingerprint);
        the caller supplies the remaining columns (``endpoint_id``, ``version_seq``,
        ``discovered_at``).
        """
        return {
            "protocol_version": self.protocol_version,
            "server_name": self.server_info.name,
            "server_title": self.server_info.title,
            "server_version": self.server_info.version,
            "instructions": self.instructions,
            "capabilities": self.capabilities,
            "surface_fingerprint": self.fingerprint(),
        }

    @classmethod
    def from_rows(
        cls,
        capability_rows: Sequence[Mapping[str, Any]],
        *,
        protocol_version: Optional[str] = None,
        server_info: Optional[ServerInfo] = None,
        capabilities: Optional[Mapping[str, Any]] = None,
        instructions: Optional[str] = None,
    ) -> "DiscoverySurface":
        """Reconstruct a surface from persisted ``mcp_capability_items`` rows.

        The inverse of :meth:`to_capability_rows`: rows are grouped by ``item_type``
        and each group sorted by ``ordinal``, so the item lists round-trip exactly
        regardless of the order the rows are read back. The surface-level identity
        fields live on the parent ``mcp_endpoint_versions`` row, so they are passed
        in separately (defaulting to empty when only the item store is being read).

        Args:
            capability_rows: ``mcp_capability_items`` rows for one snapshot.
            protocol_version: Snapshot protocol version, if known.
            server_info: Parsed snapshot server identity, if known.
            capabilities: Snapshot declared capabilities, if known.
            instructions: Snapshot instructions, if known.

        Returns:
            The reconstructed :class:`DiscoverySurface`.
        """
        by_type: Dict[str, List[CapabilityItem]] = {item_type: [] for item_type in ITEM_TYPES}
        for row in capability_rows:
            item = CapabilityItem.from_row(row)
            by_type.setdefault(item.item_type, []).append(item)
        for items in by_type.values():
            items.sort(key=lambda item: item.ordinal)

        return cls(
            protocol_version=protocol_version,
            server_info=server_info if server_info is not None else ServerInfo(),
            capabilities=dict(capabilities) if capabilities is not None else {},
            instructions=instructions,
            tools=tuple(by_type[ITEM_TYPE_TOOL]),
            resources=tuple(by_type[ITEM_TYPE_RESOURCE]),
            resource_templates=tuple(by_type[ITEM_TYPE_RESOURCE_TEMPLATE]),
            prompts=tuple(by_type[ITEM_TYPE_PROMPT]),
        )


# ===========================================================================
# Helpers
# ===========================================================================


def _normalize(raw_items: Sequence[Mapping[str, Any]], parser: Any) -> Tuple[CapabilityItem, ...]:
    """Apply ``parser`` to each raw wire entry, assigning zero-based ordinals."""
    return tuple(parser(item, ordinal) for ordinal, item in enumerate(raw_items))


def _strip_meta(value: Any) -> Any:
    """Recursively drop the reserved :data:`RESERVED_META_KEY` (``_meta``) from ``value``.

    Used to exclude the MCP metadata escape hatch from the fingerprint wherever it
    may appear — at the top level of a wire object, nested inside an ``inputSchema``,
    inside a prompt ``argument``, or inside ``capabilities``. Mappings are rebuilt as
    plain ``dict`` (so the result is JSON-serializable) with the ``_meta`` key removed
    and every remaining value recursed into; lists/tuples are recursed element-wise;
    scalars (and ``None``) are returned unchanged.

    Args:
        value: Any JSON-shaped value (``dict``/``list``/scalar/``None``).

    Returns:
        ``value`` with every ``_meta`` key removed at every depth.
    """
    if isinstance(value, Mapping):
        return {
            key: _strip_meta(val)
            for key, val in value.items()
            if key != RESERVED_META_KEY
        }
    if isinstance(value, (list, tuple)):
        return [_strip_meta(item) for item in value]
    return value


def _name(payload: Mapping[str, Any]) -> str:
    """Return the item's programmatic ``name`` as a string (``""`` when absent).

    ``name`` is required for every item kind on the wire and is ``NOT NULL`` in the
    store; a well-behaved server always sends it. A missing/blank name is coerced to
    ``""`` rather than dropping the item, so the surface never silently loses a
    capability and ordinals stay contiguous.
    """
    return _optional_str(payload.get("name")) or ""


def _optional_str(value: Any) -> Optional[str]:
    """Return ``value`` when it is a non-empty string, else ``None``."""
    return value if isinstance(value, str) and value != "" else None


def _optional_object(value: Any) -> Optional[Dict[str, Any]]:
    """Return a shallow ``dict`` copy when ``value`` is a JSON object, else ``None``.

    Promoted JSONB columns (``input_schema``, ``output_schema``, ``annotations``)
    hold objects; a non-object (or absent) wire value normalizes to ``None``.
    """
    return dict(value) if isinstance(value, Mapping) else None
