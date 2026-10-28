"""Generated target × fidelity-tier table for the *Export catalog items* guide — X7 (#6228).

The Export dialog and the Export studio badge every target card with a fidelity tier —
``lossless``, ``lossy`` or ``types-only`` — computed for the source being exported
(:func:`app.export_fidelity.build_target_fidelity`). A reader choosing a format before opening
either screen asks the same question in general: *what does Avro keep of a REST API?* This module
answers it once per target, for four small reference sources (a REST API, an RPC service, an event
API and a set of types), and writes the answer into the guide page between two markers.

The table is derived, never typed: it walks the same emitter registry ``GET /export/targets``
walks (internal targets excluded), asks each emitter whether it can export the source at all
(:meth:`app.emitter.Emitter.source_unsupported_reason`), and runs the same prediction engine for the
tier. A tier that changes in the engine, or a target added to the registry, moves the page in the
same commit — ``tests/test_export_target_tiers_doc.py`` regenerates the region in memory and fails
when the committed copy differs.

Deployment toolchains are deliberately left out. Whether a target's tool is installed is a fact
about one server, not about the format, so a page built from it would change from machine to
machine; the guide says in prose that such targets are greyed out with the reason.

Everything here is pure and deterministic — same registry in, same bytes out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .docs_site import DOCS_SITE_PAGES_ROOT
from .emitter import describe_emit_targets, get_emitter, load_builtin_emitters
from .export_fidelity import build_target_fidelity
from .format_matrix import INTERNAL_FORMAT_KEYS

__all__ = [
    "EXPORT_TARGET_TIERS_PAGE",
    "REGENERATE_COMMAND",
    "BEGIN_MARKER",
    "END_MARKER",
    "ReferenceSource",
    "TargetTierRow",
    "reference_sources",
    "collect_target_tier_rows",
    "render_target_tier_table",
    "apply_target_tier_table",
]

#: Path of the guide page that carries the table, relative to the monorepo root.
EXPORT_TARGET_TIERS_PAGE = f"{DOCS_SITE_PAGES_ROOT}/ship/export-catalog-items.mdx"

#: The one command that rewrites the table. Quoted in the page and in the drift test's message.
REGENERATE_COMMAND = "cd apiome-rest && uv run python scripts/generate_export_target_tiers_doc.py"

#: MDX comments around the generated region. Everything between them is replaced on regeneration;
#: everything outside them is hand-written and left untouched.
BEGIN_MARKER = (
    "{/* export-target-tiers:begin — generated, do not edit by hand. Regenerate with: "
    f"{REGENERATE_COMMAND} */}}"
)
END_MARKER = "{/* export-target-tiers:end */}"

#: How each paradigm reads in the table's *Kind* column (the same words as *Export a spec*).
_PARADIGM_LABELS: Dict[ApiParadigm, str] = {
    ApiParadigm.REST: "REST",
    ApiParadigm.RPC: "RPC",
    ApiParadigm.EVENT: "Events",
    ApiParadigm.GRAPH: "Graph",
    ApiParadigm.DATA_SCHEMA: "Data schema",
    ApiParadigm.AGENT: "Agent tools",
}

#: The cell for a source the target cannot export at all; the reason follows the table.
_NOT_OFFERED = "not offered"


@dataclass(frozen=True)
class ReferenceSource:
    """One column of the table: a small source every target is measured against.

    Attributes:
        heading: The column heading, e.g. ``From a REST API``.
        description: One sentence saying what the source contains, printed under the table.
        api: The canonical model handed to the fidelity engine.
    """

    heading: str
    description: str
    api: CanonicalApi


@dataclass(frozen=True)
class TargetTierRow:
    """One row of the table: a target and its tier for each reference source.

    Attributes:
        label: The target's card label, e.g. ``Apache Avro``.
        kind: The target's paradigm as the *Kind* column prints it.
        tiers: One cell per reference source, in column order: a tier value, or
            :data:`_NOT_OFFERED` when the target refuses that source.
        reasons: The distinct refusal sentences, in column order of first appearance.
    """

    label: str
    kind: str
    tiers: Tuple[str, ...]
    reasons: Tuple[str, ...]


def _pet_types() -> List[Type]:
    """The record and enum every reference source shares.

    Returns:
        ``Pet`` — a required id, a length-limited name, an optional tag and a status — and the
        ``PetStatus`` enum it refers to.
    """
    pet = Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="Pet.id",
                name="id",
                type=TypeRef(name="integer", nullable=False),
                constraints=Constraints(format="int64"),
            ),
            CanonicalField(
                key="Pet.name",
                name="name",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(max_length=64),
            ),
            CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string")),
            CanonicalField(key="Pet.status", name="status", type=TypeRef(name="PetStatus")),
        ],
    )
    status = Type(
        key="PetStatus",
        name="PetStatus",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="PetStatus.available", name="available"),
            EnumValue(key="PetStatus.sold", name="sold"),
        ],
    )
    return [pet, status]


def _rest_api() -> CanonicalApi:
    """A REST API: ``GET /pets/{petId}`` and ``POST /pets`` over the shared types."""
    get_pet = Operation(
        key="GET /pets/{petId}",
        name="getPet",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{petId}",
        parameters=[
            Parameter(
                key="GET /pets/{petId}#path.petId",
                name="petId",
                location=ParameterLocation.PATH,
                type=TypeRef(name="integer", nullable=False),
                required=True,
            )
        ],
        messages=[
            Message(
                key="GET /pets/{petId}#response.200",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="Pet"),
                status_code="200",
                content_types=["application/json"],
            )
        ],
    )
    create_pet = Operation(
        key="POST /pets",
        name="createPet",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="POST",
        http_path="/pets",
        messages=[
            Message(
                key="POST /pets#request",
                role=MessageRole.REQUEST,
                payload=TypeRef(name="Pet"),
                required=True,
                content_types=["application/json"],
            ),
            Message(
                key="POST /pets#response.201",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="Pet"),
                status_code="201",
                content_types=["application/json"],
            ),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pet Store"),
        services=[Service(key="pets", name="pets", operations=[get_pet, create_pet])],
        types=_pet_types(),
    )


def _rpc_api() -> CanonicalApi:
    """An RPC service: one ``GetPet`` call with no HTTP method or path."""
    request = Type(
        key="GetPetRequest",
        name="GetPetRequest",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="GetPetRequest.id",
                name="id",
                type=TypeRef(name="integer", nullable=False),
                field_number=1,
            )
        ],
    )
    get_pet = Operation(
        key="PetService.GetPet",
        name="GetPet",
        kind=OperationKind.REQUEST_RESPONSE,
        messages=[
            Message(key="PetService.GetPet#request", role=MessageRole.REQUEST, payload=TypeRef(name="GetPetRequest")),
            Message(key="PetService.GetPet#response", role=MessageRole.RESPONSE, payload=TypeRef(name="Pet")),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="Pet service"),
        services=[Service(key="PetService", name="PetService", operations=[get_pet])],
        types=[request, *_pet_types()],
    )


def _event_api() -> CanonicalApi:
    """An event API: one ``pets.adopted`` channel and the operation that publishes to it."""
    adopted = Type(
        key="PetAdopted",
        name="PetAdopted",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="PetAdopted.petId", name="petId", type=TypeRef(name="integer", nullable=False)),
            CanonicalField(key="PetAdopted.status", name="status", type=TypeRef(name="PetStatus")),
        ],
    )
    publish = Operation(
        key="publishPetAdopted",
        name="publishPetAdopted",
        kind=OperationKind.PUBLISH,
        channel_ref="pets.adopted",
        messages=[
            Message(key="publishPetAdopted#event", role=MessageRole.EVENT, payload=TypeRef(name="PetAdopted"))
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3.0",
        identity=ApiIdentity(name="Pet events"),
        channels=[Channel(key="pets.adopted", address="pets.adopted", protocol="kafka")],
        services=[Service(key="pet-events", name="pet-events", operations=[publish])],
        types=[adopted, _pet_types()[1]],
    )


def _types_only_api() -> CanonicalApi:
    """A schema with types and no operations or channels."""
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="json-schema",
        identity=ApiIdentity(name="Pet schema"),
        types=_pet_types(),
    )


def reference_sources() -> List[ReferenceSource]:
    """The table's columns, in the order they are printed.

    Returns:
        A REST API, an RPC service, an event API and a types-only schema, each built fresh.
    """
    return [
        ReferenceSource(
            heading="From a REST API",
            description="an OpenAPI 3.1 API with `GET /pets/{petId}` and `POST /pets`",
            api=_rest_api(),
        ),
        ReferenceSource(
            heading="From an RPC service",
            description="a Protobuf service with one `GetPet` call",
            api=_rpc_api(),
        ),
        ReferenceSource(
            heading="From an event API",
            description="an AsyncAPI 3.0 API that publishes to one `pets.adopted` channel",
            api=_event_api(),
        ),
        ReferenceSource(
            heading="From types only",
            description="a JSON Schema with the types and no operations or channels",
            api=_types_only_api(),
        ),
    ]


def _escape_cell(text: str) -> str:
    """Make ``text`` safe inside a Markdown table cell or list item.

    Args:
        text: Registry prose (a label or a refusal sentence).

    Returns:
        The text with pipes escaped and whitespace collapsed to single spaces.
    """
    return " ".join(text.replace("|", "\\|").split())


def collect_target_tier_rows(sources: Optional[Sequence[ReferenceSource]] = None) -> List[TargetTierRow]:
    """Measure every export target against every reference source.

    Args:
        sources: The columns; defaults to :func:`reference_sources`.

    Returns:
        One row per target ``GET /export/targets`` offers, sorted by label (case-insensitive).
    """
    load_builtin_emitters()
    columns = list(sources) if sources is not None else reference_sources()
    rows: List[TargetTierRow] = []
    for target in describe_emit_targets():
        descriptor = target.descriptor
        if descriptor.key in INTERNAL_FORMAT_KEYS:
            continue
        emitter_cls = get_emitter(descriptor.format)
        if emitter_cls is None:  # pragma: no cover - registry/describe are always in sync
            continue
        tiers: List[str] = []
        reasons: List[str] = []
        for source in columns:
            refusal = emitter_cls.source_unsupported_reason(source.api)
            if refusal:
                tiers.append(_NOT_OFFERED)
                if refusal not in reasons:
                    reasons.append(refusal)
            else:
                tiers.append(build_target_fidelity(source.api, emitter_cls).tier.value)
        rows.append(
            TargetTierRow(
                label=descriptor.label,
                kind=_PARADIGM_LABELS.get(descriptor.paradigm, descriptor.paradigm.value),
                tiers=tuple(tiers),
                reasons=tuple(reasons),
            )
        )
    rows.sort(key=lambda row: row.label.casefold())
    return rows


def render_target_tier_table() -> str:
    """Render the generated region, markers included.

    Returns:
        The begin marker, a sentence naming the reference sources, the table, the list of refusal
        reasons and the end marker, each block separated by a blank line, with no trailing newline.
    """
    sources = reference_sources()
    rows = collect_target_tier_rows(sources)

    described = "; ".join(f"**{source.heading}** is {source.description}" for source in sources)
    lines: List[str] = [
        BEGIN_MARKER,
        "",
        f"Each of the {len(rows)} targets, measured against four small sources: {described}. "
        "All of them share a `Pet` record (a required id, a name of up to 64 characters, an optional "
        "tag and a status) and a `PetStatus` enum.",
        "",
        "| Target | Kind | " + " | ".join(source.heading for source in sources) + " |",
        "| --- | --- | " + " | ".join("---" for _ in sources) + " |",
    ]
    for row in rows:
        cells = [f"`{tier}`" if tier != _NOT_OFFERED else tier for tier in row.tiers]
        lines.append(f"| {_escape_cell(row.label)} | {row.kind} | " + " | ".join(cells) + " |")

    refused = [row for row in rows if row.reasons]
    if refused:
        lines += ["", "Why a target is not offered for a source:", ""]
        lines += [
            f"- **{_escape_cell(row.label)}** — " + " ".join(_escape_cell(reason) for reason in row.reasons)
            for row in refused
        ]
    lines += ["", END_MARKER]
    return "\n".join(lines)


def apply_target_tier_table(text: str) -> str:
    """Replace the generated region of the guide page with a fresh rendering.

    Args:
        text: The page's current text.

    Returns:
        The text with everything from :data:`BEGIN_MARKER` to :data:`END_MARKER` (inclusive)
        replaced by :func:`render_target_tier_table`.

    Raises:
        ValueError: When the page does not hold exactly one begin marker followed by one end marker.
    """
    begin = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if begin < 0 or end < begin or text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ValueError(
            f"{EXPORT_TARGET_TIERS_PAGE} must hold one '{BEGIN_MARKER}' followed by one '{END_MARKER}'."
        )
    return text[:begin] + render_target_tier_table() + text[end + len(END_MARKER) :]
