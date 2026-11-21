"""Reference emitter: canonical model → OpenAPI 3.1 — MFI-22.1 (#4002), MFX-1.1 (#3834).

The inverse of :class:`app.openapi_normalizer.OpenApiNormalizer` and the reference
implementation of the :class:`app.emitter.Emitter` SPI. It walks a
:class:`~app.canonical_model.CanonicalApi` and produces a schema-valid **OpenAPI
3.1** document:

* identity/title/version/description → ``info``; :class:`~app.canonical_model.Server`
  → ``servers`` (URL templates + variables);
* services' :class:`~app.canonical_model.Operation`\\s → ``paths`` (one path item
  per route, one method per operation, with ``operationId``/``summary``/``tags``);
* :class:`~app.canonical_model.Parameter`\\s → ``parameters``;
  :class:`~app.canonical_model.Message`\\s → ``requestBody`` / ``responses`` with
  media types and headers;
* named :class:`~app.canonical_model.Type`\\s → ``components.schemas`` (via
  :class:`app.emitter.SchemaEmitter` — OpenAPI 3.1 schemas *are* JSON Schema).

Two properties make the output trustworthy:

* **Deterministic.** Every collection is emitted in a stable order (services,
  operations, parameters, and component schemas by ``key``; media types and
  headers by name), so re-converting the same model yields a byte-identical
  document. Feed the result to :func:`app.openapi_validator.validate_openapi_document`
  to confirm it passes the OpenAPI 3.1 meta-schema.

* **Provenance-tracked.** Every emitted value is tagged
  :attr:`~app.emitter.Provenance.SOURCE` (came from the model),
  :attr:`~app.emitter.Provenance.INFERRED` (derived from the model's structure —
  e.g. an HTTP binding synthesized for a gRPC method, or a synthesized
  ``operationId``), or :attr:`~app.emitter.Provenance.DEFAULT` (a system fallback —
  e.g. the ``openapi`` version string, or an empty response ``description``). The
  fidelity analyzer (MFI-22.3) reads this to show what the conversion added.

Non-REST models are projected onto the OpenAPI (path/verb/response) vocabulary by a
per-paradigm :class:`app.projection.ProjectionStrategy` (MFI-22.2), selected from the
model's :class:`~app.canonical_model.ApiParadigm`. The strategy resolves each
operation's ``(method, path)`` binding — or declares the operation has no OpenAPI
representation — and records its *losses* on a :class:`~app.emitter.LossTracker`: an
RPC method with no ``http`` annotation gets a synthesized ``POST /{Service}/{Method}``,
gRPC streaming and GraphQL subscriptions and event pub/sub are surfaced as
:attr:`~app.emitter.LossKind.NA` losses (and, where they *are* emitted, ``x-``
extensions) rather than silently dropped, and a data-schema model with only ``types``
emits a components-only document. Those losses accompany the provenance in the
returned :class:`~app.emitter.EmitResult` for the fidelity analyzer (MFI-22.3).

The emitter is pure (no I/O). It self-registers under the ``openapi-3.1`` format
key so :func:`app.emitter.get_emitter` resolves it.

The ``openapi_version`` emit option (MFX-9.1) additionally lets a caller downgrade
the 3.1 output to **OpenAPI 3.0.3** or **Swagger 2.0** through
:mod:`app.openapi_downgrade`. Those older dialects cannot express every JSON-Schema
2020-12 construct, so each downgrade records the constructs it loses on the result's
:attr:`~app.emitter.EmitResult.losses` — the "3.0/2.0 downgrades flagged as lossy"
acceptance criterion — feeding the fidelity pack (MFX-9.2).

``openapi_version="3.2"`` (MFX-9.5) writes **OpenAPI 3.2.0** instead, carrying natively what the
canonical model holds that only 3.2 can express: a ``QUERY`` operation as the path item's ``query``
key, any other non-standard method under ``additionalOperations``, and the tag hierarchy an
imported 3.2 document declared (``tags`` with ``parent`` / ``summary`` / ``kind``). The 3.1 output
(and the 3.0 / 2.0 downgrades made from it) carries the methods on ``x-apiome-*`` extensions and has
no tag hierarchy; :class:`OpenApiFidelityRulePack` reports both for those versions.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Literal, Mapping, Optional, Set, Tuple, Union

from pydantic import Field, ValidationError

from .api_plans import PLANS_EXTENSION_KEY, PLANS_EXTRAS_KEY
from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    ParameterLocation,
    Server,
    Service,
    StreamingMode,
    Type,
)
from .conversion_verdicts import (
    agent_loss_items,
    envelope_verdicts,
    paradigm_change_verdict,
    rekey_verdicts,
    source_metadata_keys,
    source_metadata_verdict,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
    SchemaEmitter,
    _emit_constraints,
)
from .export_test_tools import ExportTestToolKind, test_tool, toolchain_check
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity
from .normalizer import Keys
from .openapi_downgrade import (
    OPENAPI_30_VERSION,
    SWAGGER_20_VERSION,
    downgrade_remaining_schemas_30,
    downgrade_to_openapi_30,
    downgrade_to_swagger_2,
)
from .openapi_ref_modes import apply_ref_mode
from .openapi_schema_dialect import record_declared_dialect_loss, record_schema_rewrites
from .openapi_source_preservation import (
    OPENAPI_SOURCE_EXTRA,
    gate_constructs,
    preserved_source,
    restore_source,
    source_family,
    upgrade_document_30_to_31,
)
from .projection import (
    X_EVENT_ACTION,
    X_STREAMING,
    ProjectionStrategy,
    RouteBinding,
    get_projection,
)
from .security_scheme_stubs import SECURITY_SCHEMES_EXTRAS_KEY

__all__ = ["OpenApiEmitOptions", "OpenApiEmitter", "OpenApiFidelityRulePack"]

#: Vendor extension an OpenAPI 3.1 schema carries a source field number on, so a
#: field number a source declares (e.g. a protobuf field number on a round-tripped
#: model) is preserved rather than dropped — the refinement the reference fidelity
#: rule pack advertises.
X_FIELD_NUMBER = "x-field-number"

# OpenAPI 3.1 path-item methods the emitter can emit natively. OpenAPI 3.2-only
# methods (QUERY, additionalOperations) are stashed on vendor extensions instead.
_OAS31_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
# Vendor extensions used when a 3.2-only HTTP method cannot be emitted as a native
# 3.1 path-item operation key (mirrors the UI 3.2→3.1 converter).
X_QUERY_OPERATION = "x-apiome-query-operation"
X_ADDITIONAL_OPERATIONS = "x-apiome-additional-operations"
#: The OpenAPI version string of the 3.2 output mode (MFX-9.5).
OPENAPI_32_VERSION = "3.2.0"
#: Canonical-model extra holding an imported 3.2 document's tag hierarchy (``parent``/``summary``/``kind``
#: per tag name), as :meth:`app.openapi_normalizer.OpenApiNormalizer._tag_hierarchy` records it.
TAG_HIERARCHY_EXTRAS_KEY = "tagHierarchy"

# Extracts the identifier-safe tokens of a path/key when synthesizing an
# ``operationId`` (drops slashes, dots, and ``{param}`` braces).
_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class OpenApiEmitOptions(EmitOptions):
    """Per-target options for :class:`OpenApiEmitter` (MFX-1.4)."""

    openapi_version: Literal["3.2", "3.1", "3.0", "2.0"] = Field(
        default="3.1",
        description=(
            "OpenAPI dialect to emit. ``3.1`` (default) is the native target; ``3.2`` "
            "(MFX-9.5) also writes 3.2-only constructs natively — ``query`` and "
            "``additionalOperations`` methods and the tag hierarchy; ``3.0`` and ``2.0`` "
            "(Swagger) are downgrades of the 3.1 output and lose 3.1-only constructs, each "
            "recorded as a fidelity loss (MFX-9.1)."
        ),
    )
    include_paths: bool = Field(
        default=True,
        description="Emit HTTP path operations. Disable for a components-only export.",
    )
    include_components: bool = Field(
        default=True,
        description="Emit ``components/schemas``. Disable for an operations-only export.",
    )
    include_projection_extensions: bool = Field(
        default=True,
        description=(
            "Include paradigm-projection ``x-`` vendor extensions "
            "(e.g. low-fidelity caveats for event/RPC sources)."
        ),
    )
    refs: Literal["bundle", "dereference", "split"] = Field(
        default="bundle",
        title="$ref handling",
        description=(
            "How shared objects are written. bundle (default): one file, shared objects under "
            "components, reached by $ref. dereference: one file, every $ref replaced by a copy of "
            "what it points at. split: a root file plus one file per path item and component, "
            "joined by relative $ref."
        ),
    )
    ref_cycles: Literal["keep-ref", "error"] = Field(
        default="keep-ref",
        title="Reference cycles",
        description=(
            "With dereference, what to do with a circular $ref, which can never be fully "
            "expanded. keep-ref (default): keep the $ref that closes the loop and report it. "
            "error: refuse the export."
        ),
    )


class OpenApiFidelityRulePack(CapabilityRulePack):
    """Reference fidelity rule pack for the OpenAPI 3.1 target — MFX-2.3 (#3840), MFX-9.2 (#3867).

    The worked example the SPI calls for: a :class:`~app.fidelity_rulepack.FidelityRulePack`
    shipped *alongside* its emitter that refines the profile-derived default wherever
    OpenAPI's six-axis :class:`~app.emitter.CapabilityProfile` is too coarse to
    describe how a construct actually degrades. The profile advertises ``events`` and
    ``operations`` as a flat yes and ``field_identity`` as a flat no — but OpenAPI's
    *native* (path/verb/response + JSON-Schema) vocabulary cannot carry an event
    channel, a pub/sub action, an RPC stream, or a field number, and only
    *projects* each onto a vendor extension or a non-normative path
    (:mod:`app.projection`). This pack (the MFX-9.2 fidelity pack) reports those
    projections as the honest losses they are:

    * **field numbers** (``field_identity = False``) — the capability default would
      ``DROP`` a source field number outright, but OpenAPI 3.1 schemas admit ``x-``
      vendor extensions, so the emitter preserves the number as an
      :data:`X_FIELD_NUMBER` extension. It is not *enforced* by the format, so the
      honest verdict is a lossless ``APPROX`` (``info``) — "carried, but only as
      documentation" — not a ``DROP``;

    * **event channels** (``events = True``) — OpenAPI has no channel object, so a
      channel is surfaced only as documentation (an ``APPROX``): see
      :meth:`channel_verdict`;

    * **pub/sub, GraphQL subscription, and RPC streaming operations** — pub/sub and
      streaming project to non-normative documentation only (``APPROX``) and a
      GraphQL subscription has no projection at all (``DROP``): see
      :meth:`operation_verdict`.

    Every faithfully-carried construct (a unary REST/RPC call, a GraphQL
    query/mutation, an ordinary record field) is inherited unchanged from the
    capability-derived default.
    """

    # Operation kinds that are event flows (a producer/consumer bound to a channel);
    # OpenAPI can only *document* them, never model their pub/sub semantics.
    _EVENT_OPERATION_KINDS = frozenset(
        {OperationKind.PUBLISH, OperationKind.SUBSCRIBE}
    )
    #: The OpenAPI version the report is computed for (:meth:`apply_options`); 3.1 by default.
    _version = "3.1"
    #: Whether the document is built from another format's model (:meth:`evaluate`); ``False`` until then.
    _rebuilt = False
    #: The source's format key, named in messages (:meth:`evaluate`).
    _source_format = ""
    #: Operation ``extras`` the writer carries (``http`` is an RPC method's own HTTP binding).
    _WRITTEN_OPERATION_EXTRAS = frozenset(
        {"operationId", "summary", "security", "http", OPENAPI_SOURCE_EXTRA}
    )
    #: The service a re-import files an untagged operation under.
    _DEFAULT_SERVICE = "default"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Predict where each operation is written, then walk the model — COA-3.1 (#7052).

        A model that carries its OpenAPI source (COA-2.1) is written back from it, and one authored
        as OpenAPI is written as it stands. A model imported from any other format is **rebuilt**:
        the writer places each operation with the paradigm's projection
        (:mod:`app.projection`) and a re-import keys it ``METHOD /path`` and groups it by its first
        tag, so both are known here, before the export runs. The re-keys, the source-format metadata
        OpenAPI has no field for and the envelope it must invent are reported from them.
        """
        self._source_format = api.format or ""
        # A model with no format, or an OpenAPI one with no source bag (authored in Apiome), is
        # OpenAPI's own: only another format's model is "rebuilt".
        self._rebuilt = (
            preserved_source(api) is None
            and bool(self._source_format)
            and not self._source_format.startswith("openapi")
        )
        self._operation_keys: Dict[str, Optional[str]] = {}
        self._rekeyed: Set[str] = set()
        self._service_keys: Set[str] = set()
        if self._rebuilt:
            projection = get_projection(api.paradigm)
            for service in api.services:
                for operation in service.operations:
                    binding = projection.route(operation, service, LossTracker())
                    self._operation_keys[operation.key] = (
                        Keys.operation_http(binding.method, binding.path) if binding else None
                    )
                    if binding is not None:
                        self._service_keys.add(
                            operation.tags[0] if operation.tags else self._DEFAULT_SERVICE
                        )
        report = super().evaluate(api)
        if not self._rebuilt or not api.agents:
            return report
        return LossinessReport(
            items=[*report.items, *agent_loss_items(api, target_label=self.target_label)]
        )

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for the chosen ``openapi_version`` — MFX-9.5 (#4342).

        Only the 3.2 output carries a ``QUERY`` / custom-method operation natively and the tag
        hierarchy; every other version reports them (:meth:`operation_verdict`,
        :meth:`root_verdicts`). Invalid options fall back to the defaults.
        """
        try:
            self._version = OpenApiEmitOptions.model_validate(dict(options)).openapi_version
        except ValidationError:
            self._version = "3.1"

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The tag hierarchy (``parent`` / ``summary`` / ``kind``), which only OpenAPI 3.2 can write.

        Below 3.2 a Tag Object has a name and a description only, so the hierarchy an imported 3.2
        document declared is dropped (``DROP``, info: navigation metadata, not the contract).
        """
        verdicts = list(super().root_verdicts(api))
        verdicts += self._rebuilt_root_verdicts(api)
        hierarchy = _tag_hierarchy(api)
        if hierarchy and self._version != "3.2":
            verdicts.append(
                FidelityVerdict.drop(
                    message=f"OpenAPI {self._version} tags have no parent, summary or kind; the tag "
                    f"hierarchy of {len(hierarchy)} tag(s) is dropped — export OpenAPI 3.2 to keep it",
                    severity=LossinessSeverity.INFO,
                    target_mapping="tag hierarchy → dropped (OpenAPI 3.2 only)",
                )
            )
        return verdicts

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """Refine event/subscription/streaming operations OpenAPI can only document.

        The profile-derived default reports every operation an unqualified ``OK``
        because OpenAPI's profile advertises both ``operations`` and ``events``. But
        three operation shapes have no *native* OpenAPI representation and are only
        projected onto its path/verb/response vocabulary (:mod:`app.projection`) —
        the event/RPC losses MFX-9.2 must surface:

        * a **pub/sub** operation (``PUBLISH`` / ``SUBSCRIBE``) is emitted as a
          *non-normative* documentation path carrying an :data:`X_EVENT_ACTION` note
          (:class:`~app.projection.EventProjection`); the action itself is not
          enforceable, so it is an ``APPROX``, not a clean carry;
        * a **GraphQL subscription** (``SUBSCRIPTION``) has no projection at all — it
          is not emitted (:class:`~app.projection.GraphProjection`) — so it is a
          ``DROP``;
        * an **RPC streaming** method (any non-event operation whose ``streaming`` is
          not ``NONE``) keeps its request/response shape but loses its streaming
          cardinality, surfaced only as an :data:`X_STREAMING` note
          (:class:`~app.projection.RpcProjection`) — an ``APPROX``.

        A ``QUERY`` or other non-standard HTTP method (MFX-9.5) is native only in OpenAPI 3.2; any
        other version carries it on an ``x-apiome-*`` path-item extension, which tools for that
        version do not read — an ``APPROX``.

        Every other operation (a unary REST/RPC call, a GraphQL query/mutation) is
        carried faithfully and defers to the inherited ``OK``.
        """
        method = (operation.http_method or "").lower()
        if method and method not in _OAS31_METHODS and self._version != "3.2":
            extension = X_QUERY_OPERATION if method == "query" else X_ADDITIONAL_OPERATIONS
            return FidelityVerdict.approx(
                message=f"OpenAPI {self._version} has no {method.upper()} method; the operation is "
                f"carried on the {extension} extension, which {self._version} tools do not read — "
                "export OpenAPI 3.2 to write it natively",
                target_mapping=f"{method.upper()} → {extension}",
            )
        if operation.kind in self._EVENT_OPERATION_KINDS:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no pub/sub semantics; the "
                f"{operation.kind.value!r} operation is emitted only as a "
                f"non-normative documentation path with an {X_EVENT_ACTION} note",
                target_mapping=f"pub/sub action → non-normative path + {X_EVENT_ACTION}",
            )
        if operation.kind is OperationKind.SUBSCRIPTION:
            return FidelityVerdict.drop(
                message=f"{self.target_label} cannot represent a GraphQL "
                "subscription; the operation has no path/verb projection and is "
                "not emitted",
            )
        if operation.streaming is not StreamingMode.NONE:
            return FidelityVerdict.approx(
                message=f"{self.target_label} cannot model "
                f"{operation.streaming.value} streaming; the operation keeps its "
                "request/response shape but the streaming cardinality is surfaced "
                f"only as an {X_STREAMING} note",
                target_mapping=f"{operation.streaming.value} streaming → {X_STREAMING}",
            )
        return super().operation_verdict(operation)

    # --- a document rebuilt from another format's model (COA-3.1, #7052) -----------------

    def _rebuilt_root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """What a rebuilt document changes about the envelope: paradigm, dialect, identity, version."""
        if not self._rebuilt:
            return self._carried_metadata_verdicts(
                [*source_metadata_keys(api.extras, {OPENAPI_SOURCE_EXTRA}),
                 *(key for server in api.servers for key in source_metadata_keys(server.extras))],
                noun="document",
            )
        verdicts: List[FidelityVerdict] = []
        paradigm = paradigm_change_verdict(api, ApiParadigm.REST, target_label=self.target_label)
        if paradigm is not None:
            verdicts.append(paradigm)
        else:
            verdicts.append(FidelityVerdict.approx(
                message=f"the {self._source_format} source is rebuilt as an OpenAPI {self._version} "
                "document from its model: it reads back as OpenAPI, in that dialect's structure",
                severity=LossinessSeverity.INFO,
                target_mapping=f"{self._source_format} → openapi-{self._version}",
            ))
        verdicts += envelope_verdicts(
            api, target_label=self.target_label, keeps_id=False, keeps_namespace=False,
            default_version=OpenApiEmitter.DEFAULT_INFO_VERSION,
        )
        metadata = source_metadata_verdict(
            [key for server in api.servers for key in source_metadata_keys(server.extras)],
            source_format=self._source_format, target_label=self.target_label, noun="document's servers",
        )
        if metadata is not None:
            verdicts.append(metadata)
        return verdicts

    def _carried_metadata_verdicts(self, keys: List[str], *, noun: str) -> List[FidelityVerdict]:
        """``APPROX`` for another format's metadata on a model that carries its OpenAPI document.

        An API gateway export (AWS API Gateway, Azure API Management) *is* an OpenAPI document with
        the gateway's vendor extensions, so it is written back from that document (COA-2.1) and the
        extensions survive; what the importer derived from the gateway's other files (a policy
        document) has no OpenAPI field. An OpenAPI reader interprets neither: the routing, policy and
        backend metadata does not read back.

        Args:
            keys: The metadata keys of the construct (:func:`~app.conversion_verdicts.source_metadata_keys`).
            noun: The construct they belong to.

        Returns:
            One ``info`` ``APPROX``, or ``[]`` for an OpenAPI source or a construct with no metadata.
        """
        if not self._source_format or self._source_format.startswith(("openapi", "swagger")) or not keys:
            return []
        names = sorted(set(keys))
        return [FidelityVerdict.approx(
            message=f"{self.target_label} has no field for the {self._source_format} metadata of this "
            f"{noun} ({', '.join(names[:4])}{f' and {len(names) - 4} more' if len(names) > 4 else ''}): "
            "vendor extensions of the source document are written back as they stand, metadata from "
            "the gateway's other files is not written, and an OpenAPI reader reads neither back as "
            f"{self._source_format} metadata",
            severity=LossinessSeverity.INFO,
            target_mapping=f"{self._source_format} metadata → vendor extensions",
        )]

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The operation's own verdict, plus what a rebuilt document changes about it.

        * an operation with no HTTP binding is placed on a synthesized one and reads back under that
          ``METHOD /path`` key (``DROP`` under the source key; the new key is a ``SYNTH`` of
          :meth:`synthesized_verdicts`);
        * an ``operationId`` and a response are synthesized where the source has none;
        * the source format's metadata on the operation, its parameters and messages is not written.
        """
        verdicts = [self.operation_verdict(operation)]
        if not self._rebuilt:
            carried = self._carried_metadata_verdicts(
                source_metadata_keys(operation.extras, self._WRITTEN_OPERATION_EXTRAS), noun="operation"
            )
            if carried:
                verdicts = [v for v in verdicts if v.kind is not LossinessKind.OK] + carried
            return verdicts
        emitted = self._operation_keys.get(operation.key)
        if emitted is None:
            return verdicts
        rekey = rekey_verdicts(
            operation.key, emitted, target_label=self.target_label, noun="operation",
            reason="places every operation on an HTTP method and path",
        )
        carried = len(verdicts)
        if rekey is not None and verdicts[0].kind is LossinessKind.OK:
            # An operation whose own verdict already says how it is reframed (a pub/sub or
            # streaming operation) needs no second line for its key.
            verdicts.append(rekey[0])
            self._rekeyed.add(operation.key)
        declared_id = operation.extras.get("operationId")
        if not (isinstance(declared_id, str) and declared_id):
            verdicts.append(FidelityVerdict.synth(
                message="the operation declares no operationId; one is synthesized from its method "
                "and path",
                target_mapping="operationId (synthesized)",
            ))
        if not any(m.role in (MessageRole.RESPONSE, MessageRole.ERROR) for m in operation.messages):
            verdicts.append(FidelityVerdict.synth(
                message=f"{self.target_label} requires a response and the operation declares none; "
                "an empty default response is written",
                target_mapping="responses.default (synthesized)",
            ))
        metadata = source_metadata_verdict(
            [
                *source_metadata_keys(operation.extras, self._WRITTEN_OPERATION_EXTRAS),
                *(k for p in operation.parameters for k in source_metadata_keys(p.extras)),
                *(k for m in operation.messages for k in source_metadata_keys(m.extras)),
            ],
            source_format=self._source_format, target_label=self.target_label, noun="operation",
        )
        if metadata is not None:
            verdicts.append(metadata)
        if len(verdicts) > carried:
            # Something about the operation changes, so a plain "carried" no longer describes it.
            verdicts = [v for v in verdicts if v.kind is not LossinessKind.OK]
        return verdicts

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The type's own verdict, plus the source-format metadata a rebuilt document leaves out."""
        verdicts = super().type_verdicts(type_)
        if not self._rebuilt:
            return verdicts
        metadata = source_metadata_verdict(
            [
                *source_metadata_keys(type_.extras),
                *(k for f in type_.fields for k in source_metadata_keys(f.extras)),
                *(k for v in type_.enum_values for k in source_metadata_keys(v.extras)),
            ],
            source_format=self._source_format, target_label=self.target_label, noun="type",
        )
        if metadata is None:
            return verdicts
        return [v for v in verdicts if v.kind is not LossinessKind.OK] + [metadata]

    def service_verdicts(self, service: Service) -> List[FidelityVerdict]:
        """A rebuilt document keeps a service only as the first tag of its operations.

        A service none of whose written operations is tagged with its key is not written (``DROP``):
        its operations read back under their own first tag, or under ``default``. One that survives
        as a tag keeps its name only (``APPROX``) when it has a description or metadata.
        """
        verdicts = list(super().service_verdicts(service))
        if not self._rebuilt:
            return verdicts
        if service.key not in self._service_keys:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no service construct — operations are grouped by "
                f"tag; service {service.key!r} is not written",
                severity=LossinessSeverity.INFO,
                target_mapping="service → dropped (operations grouped by tag)",
            ))
        elif service.description or source_metadata_keys(service.extras):
            verdicts.append(FidelityVerdict.approx(
                message=f"service {service.key!r} is kept only as the tag of its operations; its "
                "description and metadata are not written",
                severity=LossinessSeverity.INFO,
                target_mapping="service → operation tag",
            ))
        return verdicts

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The keys a rebuilt document's re-import adds: re-keyed operations and tag services."""
        pairs = list(super().synthesized_verdicts(api))
        if not self._rebuilt:
            return pairs
        for operation in api.operations():
            emitted = self._operation_keys.get(operation.key) if operation.key in self._rekeyed else None
            rekey = emitted and rekey_verdicts(
                operation.key, emitted, target_label=self.target_label, noun="operation",
                reason="places every operation on an HTTP method and path",
            )
            if rekey:
                pairs.append(rekey[1])
        source_services = {service.key for service in api.services}
        for key in sorted(self._service_keys - source_services):
            pairs.append((key, FidelityVerdict.synth(
                message=f"a reader groups operations by their first tag; the service {key!r} "
                "is read back from it",
                target_mapping="operation tag → service",
            )))
        return pairs

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        """OpenAPI has no event-channel construct; a channel survives only as notes.

        The profile advertises ``events``, so the default reports a channel a clean
        ``OK``. In truth OpenAPI has no channel object:
        :class:`~app.projection.EventProjection` surfaces a channel's address as the
        documentation path of its pub/sub operations and its message payloads stay
        faithful in ``components.schemas``, but the channel's protocol bindings and
        correlation ids have no representation and are dropped. The honest single
        verdict is therefore an ``APPROX`` (``warn``) — "carried as documentation
        only" — not the profile's ``OK``.
        """
        return FidelityVerdict.approx(
            message=f"{self.target_label} has no event-channel construct; the "
            "channel is surfaced only as a non-normative documentation path and its "
            "protocol bindings and correlation ids are dropped",
            target_mapping="event channel → documentation path (bindings dropped)",
        )

    def _field_identity_verdict(
        self, field: CanonicalField
    ) -> Optional[FidelityVerdict]:
        """Preserve a source field number as an ``x-field-number`` extension (``APPROX``).

        Overrides the base ``DROP`` for a present-but-unrepresentable field number:
        OpenAPI keeps the value on a vendor extension rather than discarding it, so
        the loss is a documentation-only approximation, not a drop. Fields with no
        source number need nothing (OpenAPI never *requires* one), so those defer to
        the inherited behaviour, which returns ``None``.
        """
        if field.field_number is not None:
            return FidelityVerdict.approx(
                message="OpenAPI 3.1 has no native field numbers; the source field "
                f"number is preserved as an {X_FIELD_NUMBER} extension",
                severity=LossinessSeverity.INFO,
                target_mapping=f"field number → {X_FIELD_NUMBER} extension",
            )
        return super()._field_identity_verdict(field)


class OpenApiEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an OpenAPI 3.1 document with provenance.

    Self-registers under ``openapi-3.1``. Primarily targets the REST paradigm but
    accepts any canonical model — non-REST operations get a best-effort HTTP
    binding so the acceptance-criterion RPC/data-schema coverage holds.
    """

    key = "openapi"
    format = "openapi-3.1"
    label = "OpenAPI 3.1"
    description = "Export as an OpenAPI 3.1 JSON document (JSON Schema components)."
    icon = "file-json"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = OpenApiEmitOptions
    #: MFX-44.1: interactive and reference docs, the format's lint; the mock is derived from the format.
    test_tools = (
        test_tool(ExportTestToolKind.SWAGGER_UI),
        test_tool(ExportTestToolKind.REDOC),
        toolchain_check("redocly", "lint"),
    )

    #: The OpenAPI version string this emitter targets natively (before any downgrade).
    OPENAPI_VERSION = "3.1.0"
    #: Primary output filename within a bundle.
    OUTPUT_PATH = "openapi.json"
    #: Output filename for a Swagger 2.0 downgrade.
    SWAGGER_OUTPUT_PATH = "swagger.json"
    #: Primary bundle media type.
    OUTPUT_MEDIA_TYPE = "application/vnd.oai.openapi+json"
    #: Bundle media type for a Swagger 2.0 downgrade (no OpenAPI vendor type applies).
    SWAGGER_MEDIA_TYPE = "application/json"
    #: ``info.version`` used when the model declares none (OAS requires the field).
    DEFAULT_INFO_VERSION = "0.0.0"
    #: Media type assumed when a message declares no ``content_types``.
    DEFAULT_MEDIA_TYPE = "application/json"
    #: ``description`` used for a response the model gives none (OAS requires it).
    DEFAULT_RESPONSE_DESCRIPTION = ""
    #: JSON-Pointer prefix component-type references are emitted with.
    REF_PREFIX = "#/components/schemas/"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """OpenAPI 3.1 carries operations, schemas, unions, and constraints."""
        return CapabilityProfile(
            operations=True,
            events=True,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[OpenApiFidelityRulePack]:
        """Return the reference OpenAPI fidelity rule pack (MFX-2.3)."""
        return OpenApiFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[OpenApiEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as an OpenAPI 3.1 document with per-construct provenance.

        The default target is the native OpenAPI 3.1. When ``opts.openapi_version`` is
        ``"3.0"`` or ``"2.0"``, the 3.1 document is downgraded to that dialect via
        :mod:`app.openapi_downgrade`, and every 3.1-only construct the older dialect
        cannot carry is recorded as a :class:`~app.emitter.Loss` on the result — the
        MFX-9.1 "downgrades flagged as lossy" behaviour.

        Args:
            api: The canonical model to convert.
            opts: Optional emit options. Defaults apply when omitted.

        Returns:
            An :class:`~app.emitter.EmitResult` whose primary file is a schema-valid
            document in the requested dialect and whose ``provenance`` records where
            each value came from. The output is deterministic for a given ``api``.
        """
        options = (
            opts
            if isinstance(opts, OpenApiEmitOptions)
            else OpenApiEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        tracker = ProvenanceTracker()
        losses = LossTracker()
        schema = SchemaEmitter(ref_prefix=self.REF_PREFIX)
        projection = get_projection(api.paradigm)

        # The version string is recorded in ``_apply_version`` so its provenance
        # pointer matches the emitted document (``/openapi`` vs ``/swagger``).
        document: Dict[str, Any] = {"openapi": self.OPENAPI_VERSION}

        document["info"] = self._info(api, tracker)

        servers = self._servers(api, tracker)
        if servers:
            document["servers"] = servers

        native_32 = options.openapi_version == "3.2"
        tags = self._tags(api, tracker, losses, native_32=native_32)
        if tags:
            document["tags"] = tags

        if options.include_paths:
            document["paths"] = self._paths(
                api, schema, tracker, projection, losses, native_32=native_32
            )
        else:
            document["paths"] = {}

        if options.include_components:
            components = self._components(api, schema, tracker)
            if components:
                document["components"] = components

        if options.include_projection_extensions:
            for key, value in sorted(projection.document_extensions(api, losses).items()):
                document[key] = value
                tracker.record(
                    ProvenanceTracker.child("", key),
                    Provenance.INFERRED,
                    f"{api.paradigm.value} projection document note",
                )

        # COA-2.1: an OpenAPI source's own objects are written back (verbatim where the model
        # was not edited). A 3.0 source emitted as 3.0 is restored after the downgrade so its
        # 3.0 schemas are not rewritten; every other source is restored first, so the 3.0
        # downgrade sees the restored schemas too.
        target = options.openapi_version
        preserved = preserved_source(api) if target != "2.0" else None
        family = source_family(preserved["version"]) if preserved else None
        restore_after_downgrade = family == "3.0" and target == "3.0"
        if preserved and not restore_after_downgrade:
            self._restore_source(document, api, tracker, losses, native_32=native_32)

        # COA-2.3: every schema rewrite between the OpenAPI 3.0 subset and JSON Schema 2020-12
        # is recorded. Snapshot the document before the version step; afterwards, each object
        # the rewrite changed and no loss names gets an inferred provenance note. A 3.0 source
        # written back as 3.0 is restored verbatim, so it has nothing to record.
        dialect_rewrite = _dialect_rewrite_detail(family, target, restore_after_downgrade)
        before_rewrite = copy.deepcopy(document) if dialect_rewrite else None

        document, path, media_type = self._apply_version(
            document, options.openapi_version, tracker, losses
        )

        if preserved:
            if restore_after_downgrade:
                self._restore_source(document, api, tracker, losses, native_32=native_32)
            elif family == "3.0":
                upgrade_document_30_to_31(document, losses)
            elif target == "3.0":
                downgrade_remaining_schemas_30(document, losses)
                record_declared_dialect_loss(preserved, losses)
            gate_constructs(document, target, losses)

        if before_rewrite is not None:
            record_schema_rewrites(
                before_rewrite, document, tracker, losses.records(), dialect_rewrite
            )
        elif target == "2.0" and preserved_source(api):
            losses.record(
                LossKind.NA,
                "openapi-swagger-2-source-constructs",
                "Swagger 2.0 output is built from the canonical model only: OpenAPI 3.x "
                "constructs such as callbacks, links, webhooks, examples, discriminators and "
                "extensions on the source are not written",
            )

        # APX-1.2 (#6099): the plans of the API products that include this revision. Written after
        # the dialect downgrade, which rebuilds the root, so every dialect (Swagger 2.0 too) keeps them.
        plans = (api.extras or {}).get(PLANS_EXTRAS_KEY)
        if plans:
            document[PLANS_EXTENSION_KEY] = plans
            tracker.record(
                ProvenanceTracker.child("", PLANS_EXTENSION_KEY),
                Provenance.INFERRED,
                "API product plans (APX-1.2)",
            )

        # COA-2.4: the bundled document as is, fully dereferenced, or split into files. Last, so
        # every dialect and every write-back above is shaped the same way.
        files = apply_ref_mode(
            document,
            mode=options.refs,
            cycle_policy=options.ref_cycles,
            root_path=path,
            media_type=media_type,
            losses=losses,
        )
        return EmitResult(
            files=files,
            media_type=media_type,
            provenance=tracker.records(),
            losses=losses.records(),
        )

    def _apply_version(
        self,
        document: Dict[str, Any],
        version: str,
        tracker: ProvenanceTracker,
        losses: LossTracker,
    ) -> Tuple[Dict[str, Any], str, str]:
        """Downgrade the 3.1 ``document`` to ``version`` and return its file identity.

        The native ``3.1`` target passes the document through unchanged. ``3.0`` and
        ``2.0`` (Swagger) run the corresponding :mod:`app.openapi_downgrade`
        projection, which records every 3.1-only construct it cannot carry on
        ``losses`` — the acceptance-criterion "downgrades flagged as lossy". The
        version-string provenance is recorded here so it points at the *emitted*
        document's version key (``/openapi`` for 3.x, ``/swagger`` for 2.0).

        Returns:
            A ``(document, path, media_type)`` triple for the downgraded output.
        """
        if version == "3.2":
            document["openapi"] = OPENAPI_32_VERSION
            tracker.record("/openapi", Provenance.DEFAULT, "OpenAPI 3.2 output mode (MFX-9.5)")
            return document, self.OUTPUT_PATH, self.OUTPUT_MEDIA_TYPE
        if version == "3.0":
            document = downgrade_to_openapi_30(document, losses)
            tracker.record(
                "/openapi",
                Provenance.DEFAULT,
                f"downgraded from {self.OPENAPI_VERSION} to OpenAPI {OPENAPI_30_VERSION}",
            )
            return document, self.OUTPUT_PATH, self.OUTPUT_MEDIA_TYPE
        if version == "2.0":
            document = downgrade_to_swagger_2(document, losses)
            tracker.record(
                "/swagger",
                Provenance.DEFAULT,
                f"downgraded from OpenAPI {self.OPENAPI_VERSION} to Swagger "
                f"{SWAGGER_20_VERSION}",
            )
            return document, self.SWAGGER_OUTPUT_PATH, self.SWAGGER_MEDIA_TYPE
        tracker.record("/openapi", Provenance.DEFAULT, "emitter target OpenAPI version")
        return document, self.OUTPUT_PATH, self.OUTPUT_MEDIA_TYPE

    # --- source preservation (COA-2.1) ---------------------------------------

    @staticmethod
    def _restore_source(
        document: Dict[str, Any],
        api: CanonicalApi,
        tracker: ProvenanceTracker,
        losses: LossTracker,
        *,
        native_32: bool,
    ) -> None:
        """Write the preserved OpenAPI source objects back into ``document``.

        See :mod:`app.openapi_source_preservation`. Each restored object is recorded with
        :attr:`~app.emitter.Provenance.SOURCE` provenance.
        """

        def operation_slot(
            item: Dict[str, Any], method: str
        ) -> Optional[Tuple[Dict[str, Any], str]]:
            """Where :meth:`_paths` placed the operation for ``method`` in ``item``."""
            if method in _OAS31_METHODS or (native_32 and method == "query"):
                return (item, method) if isinstance(item.get(method), dict) else None
            if method == "query":
                return (item, X_QUERY_OPERATION) if isinstance(item.get(X_QUERY_OPERATION), dict) else None
            bucket = item.get("additionalOperations" if native_32 else X_ADDITIONAL_OPERATIONS)
            if isinstance(bucket, dict) and isinstance(bucket.get(method.upper()), dict):
                return bucket, method.upper()
            return None

        for pointer in restore_source(document, api, operation_slot=operation_slot, losses=losses):
            tracker.record(pointer, Provenance.SOURCE, "preserved OpenAPI source object (COA-2.1)")

    # --- info ---------------------------------------------------------------

    def _info(self, api: CanonicalApi, tracker: ProvenanceTracker) -> Dict[str, Any]:
        """Emit the ``info`` object (title + version are required by OAS)."""
        info: Dict[str, Any] = {}

        if api.title:
            info["title"] = api.title
            tracker.record("/info/title", Provenance.SOURCE)
        else:
            info["title"] = api.identity.name
            tracker.record("/info/title", Provenance.INFERRED, "from identity.name")

        if api.version:
            info["version"] = api.version
            tracker.record("/info/version", Provenance.SOURCE)
        else:
            info["version"] = self.DEFAULT_INFO_VERSION
            tracker.record(
                "/info/version", Provenance.DEFAULT, "model declares no version"
            )

        if api.description:
            info["description"] = api.description
            tracker.record("/info/description", Provenance.SOURCE)

        return info

    # --- servers ------------------------------------------------------------

    def _servers(
        self, api: CanonicalApi, tracker: ProvenanceTracker
    ) -> List[Dict[str, Any]]:
        """Emit the ``servers`` array (inverse of the normalizer's server mapping)."""
        servers: List[Dict[str, Any]] = []
        for index, server in enumerate(api.servers):
            base = f"/servers/{index}"
            entry: Dict[str, Any] = {"url": server.url}
            tracker.record(f"{base}/url", Provenance.SOURCE)
            if server.description:
                entry["description"] = server.description
                tracker.record(f"{base}/description", Provenance.SOURCE)
            variables = self._server_variables(server, base, tracker)
            if variables:
                entry["variables"] = variables
            servers.append(entry)
        return servers

    def _server_variables(
        self, server: Server, base: str, tracker: ProvenanceTracker
    ) -> Dict[str, Any]:
        """Emit a server's ``variables`` map (OAS requires each to have a ``default``)."""
        variables: Dict[str, Any] = {}
        for variable in server.variables:
            ptr = ProvenanceTracker.child(base, "variables", variable.name)
            spec: Dict[str, Any] = {}
            if variable.default is not None:
                spec["default"] = variable.default
                tracker.record(f"{ptr}/default", Provenance.SOURCE)
            else:
                # `default` is required on a Server Variable Object.
                spec["default"] = ""
                tracker.record(
                    f"{ptr}/default", Provenance.DEFAULT, "variable declares no default"
                )
            if variable.enum is not None:
                spec["enum"] = list(variable.enum)
            if variable.description is not None:
                spec["description"] = variable.description
            variables[variable.name] = spec
        return variables

    # --- tags ---------------------------------------------------------------

    @staticmethod
    def _tags(
        api: CanonicalApi,
        tracker: ProvenanceTracker,
        losses: LossTracker,
        *,
        native_32: bool,
    ) -> List[Dict[str, Any]]:
        """The top-level ``tags`` an imported 3.2 document's hierarchy needs (MFX-9.5).

        In the 3.2 mode each tag with hierarchy metadata is written as a Tag Object with its
        ``parent`` / ``summary`` / ``kind``, sorted by name. Any other version has no such fields:
        nothing is written and the dropped hierarchy is recorded as a loss.

        Returns:
            The Tag Objects to write (empty when there is no hierarchy or the mode is not 3.2).
        """
        hierarchy = _tag_hierarchy(api)
        if not hierarchy:
            return []
        if not native_32:
            losses.record(
                LossKind.NA,
                "openapi-3.2-tag-hierarchy",
                f"the tag hierarchy of {len(hierarchy)} tag(s) (parent / summary / kind) has no "
                "OpenAPI 3.1 form and is not written",
            )
            return []
        tags: List[Dict[str, Any]] = []
        for index, name in enumerate(sorted(hierarchy)):
            meta = hierarchy[name]
            tag: Dict[str, Any] = {"name": name}
            for key in ("summary", "parent", "kind"):
                if isinstance(meta.get(key), str):
                    tag[key] = meta[key]
            tags.append(tag)
            tracker.record(f"/tags/{index}", Provenance.SOURCE, "OpenAPI 3.2 tag hierarchy")
        return tags

    # --- paths / operations -------------------------------------------------

    def _paths(
        self,
        api: CanonicalApi,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
        projection: "ProjectionStrategy",
        losses: LossTracker,
        *,
        native_32: bool = False,
    ) -> Dict[str, Any]:
        """Emit the ``paths`` object, one path item per route, one method per op.

        With ``native_32`` (the OpenAPI 3.2 mode, MFX-9.5) a ``QUERY`` operation is the path item's
        ``query`` key and any other non-standard method goes under ``additionalOperations``;
        otherwise both are stashed on ``x-apiome-*`` extensions and reported as a loss.

        Operations are processed in a deterministic (service key, operation key)
        order. Each operation's ``(method, path)`` binding — and whether it came
        from the source or was synthesized — is resolved by the paradigm
        ``projection``; an operation the projection declares un-representable
        (:meth:`app.projection.ProjectionStrategy.route` returns ``None``, e.g. a
        GraphQL subscription) is skipped here and reported as a loss by the
        projection. ``operationId``\\s declared in the source are reserved first so
        a synthesized id never collides with — nor mutates — an authored one.
        """
        pairs = self._sorted_operation_pairs(api)
        reserved: Set[str] = {
            op.extras["operationId"]
            for _, op in pairs
            if isinstance(op.extras.get("operationId"), str)
        }

        stubs = self._security_stubs(api)
        paths: Dict[str, Any] = {}
        for service, operation in pairs:
            binding = projection.route(operation, service, losses)
            if binding is None:
                # The projection declared this operation to have no OpenAPI
                # representation (and recorded the loss); do not emit a path.
                continue
            item = paths.setdefault(binding.path, {})
            op_ptr = ProvenanceTracker.child("/paths", binding.path, binding.method)
            if not binding.from_source:
                tracker.record(
                    op_ptr,
                    Provenance.INFERRED,
                    "synthesized HTTP binding for a non-REST operation",
                )
            operation_obj = self._operation(
                operation, binding.method, binding.path, op_ptr, reserved, schema, tracker
            )
            self._apply_extensions(operation_obj, binding, op_ptr, tracker)
            self._apply_security(operation_obj, operation, stubs, op_ptr, tracker)
            method = binding.method.lower()
            if method not in _OAS31_METHODS and native_32:
                self._place_oas32_operation(item, method, operation_obj, op_ptr, tracker)
                continue
            if method not in _OAS31_METHODS:
                self._stash_non_oas31_operation(
                    item, method, operation_obj, operation, losses
                )
                continue
            item[method] = operation_obj
        return paths

    @staticmethod
    def _place_oas32_operation(
        item: Dict[str, Any],
        method: str,
        operation_obj: Dict[str, Any],
        op_ptr: str,
        tracker: ProvenanceTracker,
    ) -> None:
        """Write a 3.2-only HTTP method natively: ``query``, else ``additionalOperations[<METHOD>]``.

        OpenAPI 3.2 reserves the nine fixed methods (``QUERY`` included) as path-item keys, so
        ``additionalOperations`` holds only the others, keyed by the method name as sent.
        """
        if method == "query":
            item["query"] = operation_obj
        else:
            item.setdefault("additionalOperations", {})[method.upper()] = operation_obj
        tracker.record(op_ptr, Provenance.SOURCE, "OpenAPI 3.2 native method")

    @staticmethod
    def _stash_non_oas31_operation(
        item: Dict[str, Any],
        method: str,
        operation_obj: Dict[str, Any],
        operation: Operation,
        losses: LossTracker,
    ) -> None:
        """Carry a 3.2-only HTTP method forward on ``x-apiome-*`` extensions."""
        if method == "query":
            item[X_QUERY_OPERATION] = operation_obj
            extension = X_QUERY_OPERATION
        else:
            additional = item.setdefault(X_ADDITIONAL_OPERATIONS, {})
            additional[method.upper()] = operation_obj
            extension = X_ADDITIONAL_OPERATIONS
        losses.record(
            LossKind.NA,
            "openapi-3.2-http-method",
            f"{method.upper()} {operation.http_path or operation.key} has no native "
            f"OpenAPI 3.1 path-item method; stashed on {extension}",
            pointer=operation.key,
        )

    @staticmethod
    def _apply_extensions(
        operation_obj: Dict[str, Any],
        binding: RouteBinding,
        op_ptr: str,
        tracker: ProvenanceTracker,
    ) -> None:
        """Merge a binding's ``x-`` specification extensions onto the operation.

        The projection uses these to surface paradigm nuance OpenAPI cannot model
        (a streaming cardinality, an event action). They are always
        :attr:`~app.emitter.Provenance.INFERRED` — derived from the model rather
        than an authored OpenAPI value — and merged in sorted key order for
        determinism.
        """
        for key, value in sorted(binding.extensions.items()):
            operation_obj[key] = value
            tracker.record(
                ProvenanceTracker.child(op_ptr, key),
                Provenance.INFERRED,
                "paradigm projection extension",
            )

    @staticmethod
    def _sorted_operation_pairs(api: CanonicalApi) -> List[Tuple[Service, Operation]]:
        """Return every ``(service, operation)`` in deterministic (service, op) order.

        The owning service travels with each operation because a projection may need
        it (the RPC projection names its synthesized ``/{Service}/{Method}`` route
        from the service key).
        """
        result: List[Tuple[Service, Operation]] = []
        for service in sorted(api.services, key=lambda s: s.key):
            for operation in sorted(service.operations, key=lambda o: o.key):
                result.append((service, operation))
        return result

    def _operation(
        self,
        operation: Operation,
        method: str,
        path: str,
        op_ptr: str,
        reserved: Set[str],
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit one Operation Object (id, summary, tags, params, body, responses)."""
        obj: Dict[str, Any] = {}

        declared_id = operation.extras.get("operationId")
        if isinstance(declared_id, str) and declared_id:
            obj["operationId"] = declared_id
            tracker.record(f"{op_ptr}/operationId", Provenance.SOURCE)
        else:
            synthesized = self._synth_operation_id(method, path, reserved)
            obj["operationId"] = synthesized
            reserved.add(synthesized)
            tracker.record(
                f"{op_ptr}/operationId",
                Provenance.INFERRED,
                "synthesized from method and path",
            )

        summary = operation.extras.get("summary")
        if isinstance(summary, str) and summary:
            obj["summary"] = summary
            tracker.record(f"{op_ptr}/summary", Provenance.SOURCE)
        if operation.description:
            obj["description"] = operation.description
            tracker.record(f"{op_ptr}/description", Provenance.SOURCE)
        if operation.deprecated:
            obj["deprecated"] = True
            tracker.record(f"{op_ptr}/deprecated", Provenance.SOURCE)
        if operation.tags:
            obj["tags"] = list(operation.tags)
            tracker.record(f"{op_ptr}/tags", Provenance.SOURCE)

        parameters = self._parameters(operation, op_ptr, schema, tracker)
        if parameters:
            obj["parameters"] = parameters

        request_body = self._request_body(operation, op_ptr, schema, tracker)
        if request_body is not None:
            obj["requestBody"] = request_body

        obj["responses"] = self._responses(operation, op_ptr, schema, tracker)
        return obj

    @staticmethod
    def _synth_operation_id(method: str, path: str, reserved: Set[str]) -> str:
        """Synthesize a unique ``operationId`` from ``method`` + ``path``.

        Deterministic (``GET /pets/{id}`` → ``getPetsId``) and disambiguated
        against ``reserved`` by a numeric suffix, so the result is stable and
        unique within the document.
        """
        tokens = _ID_TOKEN_RE.findall(path)
        base = method.lower() + "".join(token[:1].upper() + token[1:] for token in tokens)
        base = base or method.lower()
        candidate = base
        counter = 2
        while candidate in reserved:
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    def _parameters(
        self,
        operation: Operation,
        op_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> List[Dict[str, Any]]:
        """Emit an operation's ``parameters`` (path/query/header/cookie)."""
        parameters: List[Dict[str, Any]] = []
        for index, param in enumerate(sorted(operation.parameters, key=lambda p: p.key)):
            ptr = ProvenanceTracker.child(op_ptr, "parameters", str(index))
            entry: Dict[str, Any] = {"name": param.name, "in": param.location.value}
            # Path parameters are always required per the OpenAPI spec.
            if param.required or param.location is ParameterLocation.PATH:
                entry["required"] = True
            entry["schema"] = self._leaf_schema(
                schema.type_ref(param.type), param.constraints, param.default
            )
            if param.description:
                entry["description"] = param.description
            if param.deprecated:
                entry["deprecated"] = True
            tracker.record(ptr, Provenance.SOURCE)
            parameters.append(entry)
        return parameters

    # --- messages: request body & responses ---------------------------------

    def _request_body(
        self,
        operation: Operation,
        op_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Optional[Dict[str, Any]]:
        """Emit ``requestBody`` from the operation's REQUEST message, if any."""
        request = next(
            (m for m in operation.messages if m.role is MessageRole.REQUEST), None
        )
        if request is None:
            return None
        ptr = f"{op_ptr}/requestBody"
        body: Dict[str, Any] = {
            # requestBody.content is required; always emit at least one media type.
            "content": self._content(request, ptr, schema, tracker, force=True)
        }
        if request.description:
            body["description"] = request.description
        if request.required:
            # COA-3.1 (#7052): a required body was written as an optional one, and read back as one.
            body["required"] = True
        tracker.record(ptr, Provenance.SOURCE)
        return body

    def _responses(
        self,
        operation: Operation,
        op_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit the ``responses`` object from RESPONSE/ERROR messages.

        Each response gets a ``description`` (required by OAS — defaulted when the
        message has none). An operation with no response messages gets a single
        ``default`` response so the operation is still well-formed.
        """
        responses: Dict[str, Any] = {}
        messages = [
            m
            for m in operation.messages
            if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)
        ]
        for message in sorted(messages, key=lambda m: m.key):
            status, status_source = self._status_code(message)
            if status in responses:
                # Two messages collapsed to the same status key: keep the first
                # (deterministic by sort order) so the responses map stays valid.
                continue
            ptr = ProvenanceTracker.child(op_ptr, "responses", status)
            if not status_source:
                tracker.record(
                    ptr, Provenance.INFERRED, "status code inferred from message role"
                )
            responses[status] = self._response(message, ptr, schema, tracker)

        if not responses:
            ptr = ProvenanceTracker.child(op_ptr, "responses", "default")
            responses["default"] = {"description": self.DEFAULT_RESPONSE_DESCRIPTION}
            tracker.record(
                ptr, Provenance.DEFAULT, "operation declares no response messages"
            )
        return responses

    @staticmethod
    def _status_code(message: Message) -> Tuple[str, bool]:
        """Resolve a response message's status key and whether it came from source.

        A message with a ``status_code`` uses it (``True``); otherwise a success
        RESPONSE defaults to ``"200"`` and an ERROR to ``"default"`` (``False``).
        """
        if message.status_code:
            return message.status_code, True
        return ("default" if message.role is MessageRole.ERROR else "200"), False

    def _response(
        self,
        message: Message,
        ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit one Response Object (description, optional content + headers)."""
        response: Dict[str, Any] = {}
        if message.description:
            response["description"] = message.description
            tracker.record(f"{ptr}/description", Provenance.SOURCE)
        else:
            response["description"] = self.DEFAULT_RESPONSE_DESCRIPTION
            tracker.record(
                f"{ptr}/description", Provenance.DEFAULT, "response has no description"
            )

        content = self._content(message, ptr, schema, tracker, force=False)
        if content:
            response["content"] = content

        headers = self._headers(message, ptr, schema, tracker)
        if headers:
            response["headers"] = headers
        return response

    def _headers(
        self,
        message: Message,
        ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit a response message's header fields as an OAS ``headers`` map."""
        headers: Dict[str, Any] = {}
        for header in sorted(message.headers, key=lambda h: h.key):
            entry: Dict[str, Any] = {
                "schema": self._leaf_schema(
                    schema.type_ref(header.type), header.constraints, header.default
                )
            }
            if header.description:
                entry["description"] = header.description
            if header.deprecated:
                entry["deprecated"] = True
            headers[header.name] = entry
        if headers:
            tracker.record(f"{ptr}/headers", Provenance.SOURCE)
        return headers

    def _content(
        self,
        message: Message,
        base_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
        *,
        force: bool,
    ) -> Dict[str, Any]:
        """Emit a message's ``content`` map (one Media Type Object per media type).

        Args:
            force: When ``True`` a media type is always emitted (``requestBody``
                requires ``content``); when ``False`` an empty body yields ``{}``
                so the caller can omit ``content`` entirely.
        """
        payload_schema = self._payload_schema(message, schema)
        if payload_schema is None and not message.content_types and not force:
            return {}

        media_types = sorted(message.content_types) or [self.DEFAULT_MEDIA_TYPE]
        content: Dict[str, Any] = {}
        for media_type in media_types:
            media_obj: Dict[str, Any] = {}
            if payload_schema is not None:
                media_obj["schema"] = payload_schema
            content[media_type] = media_obj

        ptr = f"{base_ptr}/content"
        if message.content_types:
            tracker.record(ptr, Provenance.SOURCE)
        else:
            tracker.record(
                ptr, Provenance.INFERRED, f"default media type {self.DEFAULT_MEDIA_TYPE}"
            )
        return content

    @staticmethod
    def _payload_schema(
        message: Message, schema: SchemaEmitter
    ) -> Optional[Dict[str, Any]]:
        """Resolve a message's body schema from its ``payload`` ref or inline schema."""
        if message.payload is not None:
            return schema.type_ref(message.payload)
        if message.payload_schema is not None:
            return dict(message.payload_schema)
        return None

    # --- components ---------------------------------------------------------

    def _components(
        self, api: CanonicalApi, schema: SchemaEmitter, tracker: ProvenanceTracker
    ) -> Dict[str, Any]:
        """Emit ``components.schemas`` from the model's named types, and any security-scheme stubs."""
        schemas: Dict[str, Any] = {}
        for type_ in sorted(api.types, key=lambda t: t.key):
            schemas[type_.key] = schema.named_schema(type_)
            tracker.record(
                ProvenanceTracker.child("/components/schemas", type_.key),
                Provenance.SOURCE,
            )
        components: Dict[str, Any] = {"schemas": schemas} if schemas else {}
        stubs = self._security_stubs(api)
        if stubs:
            components["securitySchemes"] = {name: dict(stub) for name, stub in stubs.items()}
            for name in stubs:
                tracker.record(
                    ProvenanceTracker.child("/components/securitySchemes", name),
                    Provenance.INFERRED,
                    "security-scheme stub recorded at import (type only, no credential)",
                )
        return components

    @staticmethod
    def _security_stubs(api: CanonicalApi) -> Dict[str, Any]:
        """The MFI-32.5 ``securityScheme`` stubs a collection or capture import recorded."""
        stubs = (api.extras or {}).get(SECURITY_SCHEMES_EXTRAS_KEY)
        return dict(sorted(stubs.items())) if isinstance(stubs, dict) else {}

    @staticmethod
    def _apply_security(
        operation_obj: Dict[str, Any],
        operation: Operation,
        stubs: Dict[str, Any],
        op_ptr: str,
        tracker: ProvenanceTracker,
    ) -> None:
        """Add the operation's ``security`` requirement, naming only schemes that have a stub."""
        if not stubs:
            return
        # Only the operation's own declaration is a requirement; a model-wide observation
        # (`inferred_auth_schemes`) is a stub in components, never a claim about this call.
        declared = operation.extras.get("security")
        schemes = [name for name in declared if isinstance(name, str)] if isinstance(declared, list) else []
        required = [{name: []} for name in dict.fromkeys(schemes) if name in stubs]
        if required:
            operation_obj["security"] = required
            tracker.record(f"{op_ptr}/security", Provenance.SOURCE)

    # --- shared helpers -----------------------------------------------------

    @staticmethod
    def _leaf_schema(
        base: Dict[str, Any],
        constraints: Any,
        default: Any,
    ) -> Dict[str, Any]:
        """Compose constraints/default onto a use-site schema when it is a plain leaf.

        A ``$ref`` fragment cannot carry sibling keywords in JSON Schema, so
        constraints and defaults are only merged onto a plain (typed or empty)
        schema; on a reference leaf they are dropped to keep the output valid.
        """
        if "$ref" in base:
            return base
        base.update(_emit_constraints(constraints))
        if default is not None:
            base["default"] = default
        return base


def _tag_hierarchy(api: CanonicalApi) -> Dict[str, Dict[str, Any]]:
    """The tag hierarchy the model carries (tag name → ``parent``/``summary``/``kind``), or ``{}``."""
    hierarchy = (api.extras or {}).get(TAG_HIERARCHY_EXTRAS_KEY)
    if not isinstance(hierarchy, dict):
        return {}
    return {str(name): meta for name, meta in hierarchy.items() if isinstance(meta, dict) and meta}


def _dialect_rewrite_detail(
    family: Optional[str], target: str, restore_after_downgrade: bool
) -> Optional[str]:
    """What schema-dialect rewrite an emission makes, or ``None`` when it makes none (COA-2.3).

    Args:
        family: The preserved source's version family (``None`` for a non-OpenAPI model).
        target: The requested ``openapi_version``.
        restore_after_downgrade: Whether a 3.0 source is written back as 3.0 verbatim.

    Returns:
        The provenance detail for the rewrite: 3.0 → 2020-12 for a 3.0 source written at
        3.1 / 3.2, 2020-12 → 3.0 for anything written at 3.0; ``None`` otherwise (including
        Swagger 2.0, whose structural rewrite records its own losses).
    """
    if target == "3.0" and not restore_after_downgrade:
        return "schema rewritten from JSON Schema 2020-12 into the OpenAPI 3.0 schema dialect"
    if family == "3.0" and target in ("3.1", "3.2"):
        return "schema rewritten from the OpenAPI 3.0 schema dialect into JSON Schema 2020-12"
    return None
