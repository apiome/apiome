"""Per-format conversion packs (MFI-22.8, #4009).

The generic projection (MFI-22.2, :mod:`app.projection`) is keyed by *paradigm*: every RPC
source becomes ``POST /{Service}/{Method}``, every event source becomes illustrative ``POST``
paths. A **conversion pack** refines that projection for one *source format*, and is the one
place a format's catalog → OpenAPI behavior is defined — the "migrate-to-OpenAPI" notes the
RAML (MFI-15.5), API Blueprint (MFI-16.4) and WADL (§9.3) epics carried each resolve to their
pack here rather than to a migrator of their own.

A pack can do four things, all optional:

1. **Refine the model** before it is emitted (:meth:`ConversionPack.refine_model`) — e.g. the
   gRPC pack reads ``google.api.http`` and the Smithy pack reads ``@http``, so an annotated
   method converts to its declared ``GET /v1/orders/{id}`` instead of a synthesized ``POST``.
2. **Cap the fidelity tier** (:meth:`ConversionPack.tier_ceiling`) where the analyzer's
   per-construct score overstates the result: an AsyncAPI document's pub/sub semantics have no
   OpenAPI representation however well its schemas survive, and an unannotated gRPC service's
   synthesized paths are not an HTTP API anyone designed. The cap is stated as a loss, never
   applied silently.
3. **Name an authoritative external converter** (:class:`ExternalConverter`) to run through the
   toolchain runner (MFI-EPIC-5) when it is installed — ``Microsoft.OpenApi.OData``,
   ``smithy-openapi``, ``protoc-gen-openapiv2``, SOFA. None ships in the runtime image today, so
   every pack converts natively and reports the converter as unavailable; installing one is a
   packaging change (register the tool key), not a code change.
4. **Declare its documented losses and expected tier** — what the format is known to lose on the
   way to OpenAPI, and the tier its golden fixture converts at
   (``tests/test_conversion_packs.py`` holds each pack to it).

:func:`resolve_conversion_pack` picks the pack for a source; :func:`app.conversion_job.preview_conversion`
applies it on the lossy path. A format with no pack converts exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, FrozenSet, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .conversion_pack_sources import (
    proto_http_bindings,
    smithy_http_bindings,
    smithy_unconverted_traits,
)
from .emitter import Loss, LossKind
from .fidelity import (
    LOSS_PENALTY,
    TIER_HIGH_MIN,
    TIER_MEDIUM_MIN,
    FidelityReport,
    FidelityTier,
    band_for_score,
)
from .toolchain_runner import ToolchainError, ToolchainRunner, default_runner, is_tool_available

__all__ = [
    "ConversionPack",
    "ConversionPackInfo",
    "ExternalConverter",
    "ExternalConverterInfo",
    "PackRefinement",
    "apply_source_losses",
    "apply_tier_ceiling",
    "conversion_packs",
    "refine_with_pack",
    "resolve_conversion_pack",
    "run_external_converter",
    "valid_component_keys",
]

#: Order of the tiers, best first — a ceiling only ever lowers a tier.
_TIER_RANK: Dict[FidelityTier, int] = {
    FidelityTier.HIGH: 2,
    FidelityTier.MEDIUM: 1,
    FidelityTier.LOW: 0,
}

#: The highest score each tier admits, for capping a score to a ceiling.
_TIER_MAX_SCORE: Dict[FidelityTier, int] = {
    FidelityTier.HIGH: 100,
    FidelityTier.MEDIUM: TIER_HIGH_MIN - 1,
    FidelityTier.LOW: TIER_MEDIUM_MIN - 1,
}

#: Seconds an external converter may run before the pack falls back to the native projection.
EXTERNAL_CONVERTER_TIMEOUT_SECONDS = 60.0


# ===========================================================================
# What a pack reports
# ===========================================================================


class ExternalConverterInfo(BaseModel):
    """How a pack's authoritative external converter fared on this conversion."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(description="The toolchain-runner tool key, e.g. ``smithy-openapi``.")
    name: str = Field(description="What the converter is, e.g. ``Smithy smithy-openapi plugin``.")
    reference: str = Field(description="Where the converter's mapping is documented.")
    available: bool = Field(description="Whether the tool is installed in this runtime.")
    used: bool = Field(description="Whether its document is the one this conversion returned.")
    fallback_reason: Optional[str] = Field(
        default=None,
        description="Why the native projection was used instead, when it was.",
    )


class ConversionPackInfo(BaseModel):
    """The pack that shaped a conversion, as the dry-run response reports it (MFI-22.8)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="The pack's stable key, e.g. ``grpc``.")
    label: str = Field(description="Human-readable name, e.g. ``gRPC / Protobuf``.")
    strategy: str = Field(
        description="``external`` when the authoritative converter produced the document, "
        "``native`` when the canonical-model projection did."
    )
    expected_tiers: List[FidelityTier] = Field(
        description="The tiers this format is expected to convert at (its golden fixture's)."
    )
    refinements: List[str] = Field(
        default_factory=list,
        description="What the pack changed before emitting, one sentence each.",
    )
    documented_losses: List[str] = Field(
        default_factory=list,
        description="What this format is known to lose on the way to OpenAPI.",
    )
    external_converter: Optional[ExternalConverterInfo] = Field(
        default=None,
        description="The authoritative converter the pack wraps, when it names one.",
    )


@dataclass(frozen=True)
class ExternalConverter:
    """An authoritative converter a pack wraps through the toolchain runner.

    The contract is the one the bundled wrapper scripts (``apiome-rest/toolchain/*.mjs``)
    already follow: the registered tool reads the **source document on stdin** and writes the
    **OpenAPI document as JSON on stdout**. Anything else — not installed, non-zero exit, a
    timeout, output that is not an OpenAPI object — falls back to the native projection with
    the reason recorded on :class:`ExternalConverterInfo`.

    Attributes:
        tool: The toolchain-runner key the converter is registered under.
        name: What it is, for the response and the docs.
        reference: Where its mapping is specified.
    """

    tool: str
    name: str
    reference: str


@dataclass
class PackRefinement:
    """The outcome of :func:`refine_with_pack`: the model to emit and what changed in it."""

    api: CanonicalApi
    refinements: List[str] = field(default_factory=list)


# ===========================================================================
# The SPI
# ===========================================================================


class ConversionPack:
    """One source format's refinement of the catalog → OpenAPI projection.

    Subclass with ``register=True`` to add a pack. Class attributes describe the pack; the two
    hooks default to "change nothing", so a pack that only documents its format is valid.
    """

    #: Stable key, reported on the dry-run response.
    key: ClassVar[str] = ""
    #: Human-readable name.
    label: ClassVar[str] = ""
    #: Source-format keys (adapter keys *and* canonical ``model.format`` values) it claims.
    formats: ClassVar[FrozenSet[str]] = frozenset()
    #: Tiers its golden fixture converts at. More than one for a "medium-high" format.
    expected_tiers: ClassVar[Tuple[FidelityTier, ...]] = ()
    #: What the format is known to lose, one sentence each.
    documented_losses: ClassVar[Tuple[str, ...]] = ()
    #: The authoritative converter it wraps, if there is one.
    external_converter: ClassVar[Optional[ExternalConverter]] = None

    _registry: ClassVar[Dict[str, "ConversionPack"]] = {}

    def __init_subclass__(cls, register: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if register:
            if not cls.key or not cls.formats or not cls.expected_tiers:
                raise TypeError(f"{cls.__name__} must declare key, formats and expected_tiers")
            if cls.key in ConversionPack._registry:
                raise ValueError(f"Conversion pack {cls.key!r} is already registered")
            ConversionPack._registry[cls.key] = cls()

    def refine_model(self, api: CanonicalApi, source_text: Optional[str]) -> PackRefinement:
        """Return the model to emit — a refined copy, never ``api`` mutated in place.

        Args:
            api: The normalized source model.
            source_text: The source document the model was normalized from, when it is text.

        Returns:
            The model to emit and a sentence per change made. The default changes nothing.
        """
        return PackRefinement(api=api)

    def source_losses(self, source_text: Optional[str]) -> List[Loss]:
        """Losses only the source text reveals — constructs the normalizer does not model.

        Args:
            source_text: The source document, when it is text.

        Returns:
            Losses to add to the report (charged like the projection's own). Default none.
        """
        return []

    def tier_ceiling(self, api: CanonicalApi) -> Optional[Tuple[FidelityTier, Loss]]:
        """The highest tier this conversion may report, and the loss that says why.

        Args:
            api: The model that was emitted (after :meth:`refine_model`).

        Returns:
            ``(ceiling, loss)``, or ``None`` when the analyzer's tier stands.
        """
        return None

    def info(
        self,
        *,
        refinements: List[str],
        converter: Optional[ExternalConverterInfo],
    ) -> ConversionPackInfo:
        """Describe this pack's part in one conversion."""
        return ConversionPackInfo(
            key=self.key,
            label=self.label,
            strategy="external" if converter is not None and converter.used else "native",
            expected_tiers=list(self.expected_tiers),
            refinements=refinements,
            documented_losses=list(self.documented_losses),
            external_converter=converter,
        )


def conversion_packs() -> List[ConversionPack]:
    """Return every registered pack, sorted by key."""
    return [ConversionPack._registry[key] for key in sorted(ConversionPack._registry)]


def resolve_conversion_pack(
    source_format: Optional[str], api_format: Optional[str]
) -> Optional[ConversionPack]:
    """Pick the pack for a conversion, by the catalog item's format or the model's.

    The item's ``source_format`` (an adapter key — ``grpc``) is tried first, then the
    canonical ``model.format`` (``protobuf``, ``asyncapi-3``), both case-insensitively.

    Returns:
        The pack, or ``None`` when no pack claims the format (the generic projection applies).
    """
    for candidate in (source_format, api_format):
        key = (candidate or "").strip().lower()
        if not key:
            continue
        for pack in conversion_packs():
            if key in pack.formats:
                return pack
    return None


# ===========================================================================
# Applying a pack
# ===========================================================================


#: The pattern OpenAPI 3.1 requires of a ``components`` key.
_COMPONENT_KEY_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_INVALID_COMPONENT_CHARS_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _component_key(key: str) -> str:
    """A valid ``components.schemas`` key for ``key``, keeping as much of it as reads well.

    An XML-qualified name (``http://example.com/orders.Order``, as WSDL/WADL normalize) keeps
    its local part (``orders.Order``); anything else has each run of forbidden characters
    replaced by ``_`` (``Map_['null', 'string']`` → ``Map_null_string``).
    """
    candidate = key.rsplit("/", 1)[-1] if "/" in key else key
    candidate = re.sub(r"_{2,}", "_", _INVALID_COMPONENT_CHARS_RE.sub("_", candidate)).strip("_")
    return candidate or "Schema"


def _component_key_renames(api: CanonicalApi) -> Dict[str, str]:
    """Map every type key OpenAPI would reject to a valid, unique replacement."""
    taken = {type_.key for type_ in api.types if _COMPONENT_KEY_RE.match(type_.key)}
    renames: Dict[str, str] = {}
    for type_ in sorted(api.types, key=lambda t: t.key):
        if _COMPONENT_KEY_RE.match(type_.key):
            continue
        base = _component_key(type_.key)
        candidate, suffix = base, 2
        while candidate in taken:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        taken.add(candidate)
        renames[type_.key] = candidate
    return renames


def _rename_references(node: Any, renames: Dict[str, str]) -> Any:
    """Rewrite type keys, ``TypeRef`` names and ``$ref`` pointers through ``renames``.

    Walks a ``model_dump`` of the model. Only the values of ``key``/``name`` entries, the
    entries of a ``union_members`` list and ``#/components/schemas/…`` ``$ref`` strings are
    rewritten — the places a type is named or referenced — and only when they equal a renamed
    key exactly. A renamed key always contains a
    character no identifier or field name can, so no unrelated value can match.
    """
    if isinstance(node, list):
        return [_rename_references(item, renames) for item in node]
    if not isinstance(node, dict):
        return node
    updated: Dict[str, Any] = {}
    for field_name, value in node.items():
        if field_name in ("key", "name") and isinstance(value, str) and value in renames:
            updated[field_name] = renames[value]
        elif field_name == "union_members" and isinstance(value, list):
            updated[field_name] = [
                renames.get(member, member) if isinstance(member, str) else member
                for member in value
            ]
        elif field_name == "$ref" and isinstance(value, str):
            prefix = "#/components/schemas/"
            target = value[len(prefix) :] if value.startswith(prefix) else None
            updated[field_name] = prefix + renames[target] if target in renames else value
        else:
            updated[field_name] = _rename_references(value, renames)
    return updated


def valid_component_keys(api: CanonicalApi) -> Tuple[CanonicalApi, Dict[str, str]]:
    """Return ``api`` with every type key OpenAPI rejects renamed, and the renames made.

    OpenAPI 3.1 requires ``components`` keys to match ``^[a-zA-Z0-9._-]+$``; WSDL and WADL
    normalize XML-qualified names (``http://example.com/orders.Order``) and Avro can name a map
    after its value union, so their conversions were not valid documents. Renaming in the model
    — rather than in the emitted document — keeps every ``$ref`` and every provenance pointer
    the emitter records consistent with the names it emits.

    Returns:
        ``(api, {})`` untouched when every key is valid; otherwise a renamed copy and the map.
    """
    renames = _component_key_renames(api)
    if not renames:
        return api, {}
    dumped = _rename_references(api.model_dump(mode="python"), renames)
    return CanonicalApi.model_validate(dumped), renames


def refine_with_pack(
    pack: Optional[ConversionPack], api: CanonicalApi, source_text: Optional[str]
) -> PackRefinement:
    """Run ``pack``'s model refinement, then make every component key valid OpenAPI.

    With no pack, ``api`` passes through untouched — a format without a pack converts exactly
    as it did before MFI-22.8.
    """
    if pack is None:
        return PackRefinement(api=api)
    refinement = pack.refine_model(api, source_text)
    renamed, renames = valid_component_keys(refinement.api)
    if renames:
        first_old, first_new = next(iter(sorted(renames.items())))
        count = len(renames)
        refinement = PackRefinement(
            api=renamed,
            refinements=[
                *refinement.refinements,
                f"Renamed {count} schema name{'s' if count != 1 else ''} OpenAPI does not allow "
                f"(e.g. {first_old!r} → {first_new!r}).",
            ],
        )
    return refinement


def apply_source_losses(
    report: FidelityReport, pack: Optional[ConversionPack], source_text: Optional[str]
) -> FidelityReport:
    """Add ``pack``'s source-only losses to ``report``, charged as the analyzer charges them.

    Each loss costs :data:`app.fidelity.LOSS_PENALTY` for its kind — an ``n/a`` loss 5 points,
    an ``inferred`` one nothing — and the grade/tier are re-banded from the new score.

    Returns:
        The report, unchanged when the pack reports no source losses.
    """
    losses = pack.source_losses(source_text) if pack is not None else []
    if not losses:
        return report
    charge = sum(LOSS_PENALTY[loss.kind] for loss in losses)
    score = max(0, min(100, round(report.score - charge)))
    grade, tier = band_for_score(score)
    return report.model_copy(
        update={
            "score": score,
            "grade": grade,
            "tier": tier,
            "losses": [*report.losses, *losses],
            "penalty": round(report.penalty + charge),
        }
    )


def apply_tier_ceiling(
    report: FidelityReport, pack: Optional[ConversionPack], api: CanonicalApi
) -> FidelityReport:
    """Hold ``report`` to ``pack``'s tier ceiling, stating the cap as a loss.

    The score is lowered to the ceiling tier's top score and the grade/tier re-banded by the
    analyzer's own rules (:func:`app.fidelity.band_for_score`), so the three stay consistent.
    The loss explaining the ceiling is added whenever the ceiling *applies* to the source —
    even when the analyzer's tier was already at or under it — because it is a true statement
    about the conversion either way.

    Returns:
        The report, unchanged when the pack sets no ceiling for this model.
    """
    ceiling = pack.tier_ceiling(api) if pack is not None else None
    if ceiling is None:
        return report
    tier, loss = ceiling
    score = report.score
    if _TIER_RANK[report.tier] > _TIER_RANK[tier]:
        score = min(score, _TIER_MAX_SCORE[tier])
    grade, banded_tier = band_for_score(score)
    return report.model_copy(
        update={
            "score": score,
            "grade": grade,
            "tier": banded_tier,
            "losses": [*report.losses, loss],
            "penalty": max(report.penalty, 100 - score),
        }
    )


def run_external_converter(
    pack: Optional[ConversionPack],
    source_text: Optional[str],
    *,
    runner: Optional[ToolchainRunner] = None,
    available: Optional[Callable[[str], bool]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[ExternalConverterInfo]]:
    """Run ``pack``'s authoritative converter when it is installed.

    Never raises: every failure is a native fallback whose reason is reported.

    Args:
        pack: The resolved pack (``None`` → nothing to run).
        source_text: The source document; a converter needs text on stdin.
        runner: The toolchain runner (injectable for tests).
        available: The availability probe; defaults to
            :func:`app.toolchain_runner.is_tool_available` (injectable for tests).

    Returns:
        ``(document, info)`` — the converter's OpenAPI document when it was used, else
        ``None``; and the converter's report, or ``None`` when the pack names no converter.
    """
    converter = pack.external_converter if pack is not None else None
    if converter is None:
        return None, None

    def _info(*, used: bool, reason: Optional[str], is_available: bool) -> ExternalConverterInfo:
        return ExternalConverterInfo(
            tool=converter.tool,
            name=converter.name,
            reference=converter.reference,
            available=is_available,
            used=used,
            fallback_reason=reason,
        )

    probe = available if available is not None else is_tool_available
    if not probe(converter.tool):
        return None, _info(
            used=False,
            is_available=False,
            reason=f"{converter.name} is not installed in this runtime; converted natively.",
        )
    if not source_text:
        return None, _info(
            used=False,
            is_available=True,
            reason="The source is not text, so it cannot be handed to the converter.",
        )
    try:
        document = _run_on_worker(converter.tool, source_text, runner)
    except (ToolchainError, ValueError) as exc:
        return None, _info(
            used=False,
            is_available=True,
            reason=f"{converter.name} failed ({exc}); converted natively.",
        )
    return document, _info(used=True, is_available=True, reason=None)


def _run_on_worker(
    tool: str, source_text: str, runner: Optional[ToolchainRunner]
) -> Dict[str, Any]:
    """Run the converter on a dedicated thread with its own event loop.

    The convert path is synchronous and may itself be called from a running loop, so the
    runner's coroutine cannot be awaited in place — the same arrangement as the TypeSpec
    native emit (:func:`app.conversion_passthrough._emit_typespec_on_worker`).

    Raises:
        ToolchainError: The tool failed or timed out.
        ValueError: Its stdout was not a JSON OpenAPI object.
    """
    box: Dict[str, Any] = {}

    async def _call() -> Dict[str, Any]:
        active = runner or default_runner
        result = await active.run(
            tool, (), stdin=source_text, timeout=EXTERNAL_CONVERTER_TIMEOUT_SECONDS
        )
        document = json.loads(result.stdout)
        if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3."):
            raise ValueError("the converter did not print an OpenAPI 3.x document")
        return document

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(_call())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=_worker, name="conversion-pack-converter", daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        error = box["error"]
        if isinstance(error, json.JSONDecodeError):
            raise ValueError("the converter's output was not JSON") from error
        raise error
    return box["value"]


# ===========================================================================
# The packs
# ===========================================================================


def _with_http_bindings(
    api: CanonicalApi, binding_for: Callable[[str, str], Optional[Dict[str, str]]]
) -> Tuple[CanonicalApi, int]:
    """Copy ``api`` with ``extras["http"]`` set on each operation ``binding_for`` resolves.

    Args:
        api: The source model (left untouched).
        binding_for: ``(service_name, operation_name) -> extras["http"]`` or ``None``.

    Returns:
        The refined copy and how many operations gained a binding.
    """
    refined = api.model_copy(deep=True)
    count = 0
    for service in refined.services:
        for operation in service.operations:
            if isinstance(operation.extras.get("http"), dict):
                continue
            binding = binding_for(service.name, operation.name)
            if binding is not None:
                operation.extras = {**operation.extras, "http": binding}
                count += 1
    return refined, count


def _has_http_binding(api: CanonicalApi) -> bool:
    """Whether any operation in ``api`` carries an explicit ``extras["http"]`` binding."""
    return any(isinstance(op.extras.get("http"), dict) for op in api.operations())


class ODataPack(ConversionPack, register=True):
    """OData — the OASIS OData → OpenAPI mapping. Entity sets, singletons, actions and
    functions already normalize to REST operations with their own paths and methods."""

    key = "odata"
    label = "OData"
    formats = frozenset({"odata", "odata-v2", "odata-v3", "odata-v4", "edmx", "csdl"})
    expected_tiers = (FidelityTier.HIGH,)
    documented_losses = (
        "System query options ($filter, $select, $expand, …) are not enumerated as parameters.",
        "Navigation-property paths beyond one level are not expanded into their own operations.",
    )
    external_converter = ExternalConverter(
        tool="odata-openapi",
        name="Microsoft.OpenApi.OData (OASIS OData to OpenAPI mapping v1.0)",
        reference="https://docs.oasis-open.org/odata/odata-openapi/v1.0/odata-openapi-v1.0.html",
    )


class SmithyPack(ConversionPack, register=True):
    """Smithy — ``@http`` bindings honored, as the ``smithy-openapi`` plugin does."""

    key = "smithy"
    label = "Smithy"
    formats = frozenset({"smithy"})
    expected_tiers = (FidelityTier.HIGH, FidelityTier.MEDIUM)
    documented_losses = (
        "@endpoint and @hostLabel traits have no OpenAPI representation (smithy-openapi drops them too).",
        "An operation without @http is projected as POST /{Service}/{Operation}.",
    )
    external_converter = ExternalConverter(
        tool="smithy-openapi",
        name="Smithy smithy-openapi plugin",
        reference="https://smithy.io/2.0/guides/model-translations/converting-to-openapi.html",
    )

    def refine_model(self, api: CanonicalApi, source_text: Optional[str]) -> PackRefinement:
        bindings = smithy_http_bindings(source_text)
        refined, count = _with_http_bindings(
            api,
            lambda _service, op: bindings[op].as_extras() if op in bindings else None,
        )
        notes = [f"Honored {count} @http trait binding{'s' if count != 1 else ''}."] if count else []
        return PackRefinement(api=refined if count else api, refinements=notes)

    def source_losses(self, source_text: Optional[str]) -> List[Loss]:
        # The traits that do not convert are charged as losses, not capped: they cost the
        # conversion a host prefix, not an operation.
        details = {
            "endpoint": "@endpoint host prefixes have no OpenAPI representation.",
            "hostLabel": "@hostLabel members are bound into the host, which OpenAPI paths cannot express.",
        }
        return [
            Loss(kind=LossKind.NA, subject=f"smithy-{name}-trait", detail=details[name])
            for name in smithy_unconverted_traits(source_text)
        ]


class GrpcPack(ConversionPack, register=True):
    """gRPC / Protobuf — ``google.api.http`` bindings honored, as ``protoc-gen-openapiv2``
    and gnostic do. A service with methods but no binding at all is capped at ``low``: its
    synthesized ``POST /{Service}/{Method}`` paths describe a transport, not an HTTP API."""

    key = "grpc"
    label = "gRPC / Protobuf"
    formats = frozenset({"grpc", "protobuf", "proto", "proto3", "connectrpc"})
    expected_tiers = (FidelityTier.MEDIUM,)
    documented_losses = (
        "Streaming methods have no OpenAPI representation (surfaced as x-apiome-streaming).",
        "Only a rule's primary binding becomes an operation; additional_bindings are reported, not emitted.",
        "Without google.api.http annotations every method is a synthesized POST, and the tier is capped at low.",
    )
    external_converter = ExternalConverter(
        tool="protoc-gen-openapiv2",
        name="grpc-gateway protoc-gen-openapiv2",
        reference="https://github.com/grpc-ecosystem/grpc-gateway",
    )

    def refine_model(self, api: CanonicalApi, source_text: Optional[str]) -> PackRefinement:
        bindings = proto_http_bindings(source_text)
        refined, count = _with_http_bindings(
            api,
            lambda service, op: bindings[(service, op)].as_extras()
            if (service, op) in bindings
            else None,
        )
        notes: List[str] = []
        if count:
            notes.append(f"Honored {count} google.api.http binding{'s' if count != 1 else ''}.")
        extra = sum(binding.extra_bindings for binding in bindings.values())
        if extra:
            notes.append(
                f"Reported {extra} additional_bindings entr{'ies' if extra != 1 else 'y'}; "
                "only each rule's primary binding is emitted."
            )
        return PackRefinement(api=refined if count else api, refinements=notes)

    def tier_ceiling(self, api: CanonicalApi) -> Optional[Tuple[FidelityTier, Loss]]:
        if not api.operations() or _has_http_binding(api):
            return None
        return FidelityTier.LOW, Loss(
            kind=LossKind.INFERRED,
            subject="grpc-no-http-annotations",
            detail="No method carries a google.api.http annotation, so every path is a "
            "synthesized POST /{Service}/{Method}; annotate the methods for a REST surface.",
        )


class GraphQLPack(ConversionPack, register=True):
    """GraphQL — the SOFA-style projection: queries as ``GET``, mutations as ``POST``."""

    key = "graphql"
    label = "GraphQL"
    formats = frozenset({"graphql", "gql", "sdl"})
    expected_tiers = (FidelityTier.MEDIUM,)
    documented_losses = (
        "Subscriptions have no OpenAPI representation and are not converted.",
        "Field selection is lost: each root field returns its full type.",
    )
    external_converter = ExternalConverter(
        tool="sofa-openapi",
        name="SOFA (GraphQL to REST/OpenAPI)",
        reference="https://github.com/Urigo/sofa",
    )


class _EventPack(ConversionPack):
    """Shared behavior of the event packs: a schemas-only conversion, capped at ``low``."""

    def tier_ceiling(self, api: CanonicalApi) -> Optional[Tuple[FidelityTier, Loss]]:
        if not api.operations():
            return None
        return FidelityTier.LOW, Loss(
            kind=LossKind.NA,
            subject="event-schemas-only",
            detail=f"{self.label} describes publish/subscribe messaging, which OpenAPI cannot "
            "express. Only the message schemas convert faithfully; the channel operations are "
            "illustrative POST paths.",
        )


class AsyncApiPack(_EventPack, register=True):
    """AsyncAPI — native schemas-only projection, tier ``low`` with a strong warning."""

    key = "asyncapi"
    label = "AsyncAPI"
    formats = frozenset({"asyncapi", "asyncapi-2", "asyncapi-3"})
    expected_tiers = (FidelityTier.LOW,)
    documented_losses = (
        "Publish/subscribe actions, channel bindings and servers' protocols have no OpenAPI counterpart.",
    )


class CloudEventsPack(_EventPack, register=True):
    """CloudEvents — native schemas-only projection, tier ``low`` with a strong warning."""

    key = "cloudevents"
    label = "CloudEvents"
    formats = frozenset({"cloudevents"})
    expected_tiers = (FidelityTier.LOW,)
    documented_losses = ("Event delivery (source, type routing, transport bindings) has no OpenAPI counterpart.",)


class WsdlPack(ConversionPack, register=True):
    """WSDL / SOAP — native projection off the canonical model."""

    key = "wsdl"
    label = "WSDL / SOAP"
    formats = frozenset({"wsdl", "wsdl-1.1", "wsdl-2.0", "wsdl2"})
    expected_tiers = (FidelityTier.MEDIUM,)
    documented_losses = (
        "The SOAP envelope, headers and faults are not modelled; each operation is a JSON POST.",
    )


class AvroPack(ConversionPack, register=True):
    """Avro (and Avro IDL) — record schemas become ``components.schemas``."""

    key = "avro"
    label = "Avro"
    formats = frozenset({"avro", "avsc", "avro-idl", "avdl"})
    expected_tiers = (FidelityTier.HIGH,)
    documented_losses = ("Logical types without a JSON Schema format keep only their base type.",)


class RamlPack(ConversionPack, register=True):
    """RAML — native projection; replaces the MFI-15.5 migrate-to-OpenAPI note."""

    key = "raml"
    label = "RAML"
    formats = frozenset({"raml", "raml-0.8", "raml-1.0"})
    expected_tiers = (FidelityTier.HIGH,)
    documented_losses = ("Resource types and traits are applied, not preserved as reusable definitions.",)


class ApiBlueprintPack(ConversionPack, register=True):
    """API Blueprint — native projection; replaces the MFI-16.4 ``apib2swagger`` migrate note."""

    key = "apiblueprint"
    label = "API Blueprint"
    formats = frozenset({"apiblueprint", "api-blueprint", "apib"})
    expected_tiers = (FidelityTier.HIGH,)
    documented_losses = ("Example transactions are not carried over as OpenAPI examples.",)


class WadlPack(ConversionPack, register=True):
    """WADL — native projection; replaces the §9.3 migrate-to-OpenAPI note."""

    key = "wadl"
    label = "WADL"
    formats = frozenset({"wadl"})
    expected_tiers = (FidelityTier.HIGH, FidelityTier.MEDIUM)
    documented_losses = ("Representations without an XML Schema type convert as untyped bodies.",)
