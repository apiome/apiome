"""Emitter SPI: canonical model → format — MFI-22.1 (#4002), MFX-1.1 (#3834).

The [normalizer SPI](./normalizer.py) turns a parsed source document *into* the
paradigm-agnostic :class:`~app.canonical_model.CanonicalApi`. *This* module is the
inverse contract — it turns a :class:`~app.canonical_model.CanonicalApi` back
*out* to a concrete API-description format (OpenAPI 3.1 first, via
:class:`app.openapi_emitter.OpenApiEmitter`; more formats later). Conversion
(catalog → OpenAPI, MFI-EPIC-22) is exactly *normalize one format → emit another*.

It provides four things every emitter needs so the same work is not written once
per output format:

* **The SPI** — :class:`Emitter`, a tiny abstract contract (``format`` +
  ``paradigm`` identity and a single :meth:`Emitter.emit` method) with a registry
  (:func:`register_emitter` / :func:`get_emitter`) mirroring the normalizer's.

* **Provenance** — :class:`Provenance`, :class:`ProvenanceRecord`, and
  :class:`ProvenanceTracker`. An emitter records, *per emitted construct*, whether
  each value came straight from the source model (:attr:`Provenance.SOURCE`), was
  derived from the model's structure (:attr:`Provenance.INFERRED`), or is a
  system-supplied fallback (:attr:`Provenance.DEFAULT`). That provenance feeds the
  fidelity analyzer (MFI-22.3), which flags everything that is *not* SOURCE as a
  place the conversion added information the original did not carry.

* **The result envelope** — :class:`EmitResult`, pairing the emitted ``document``
  with its ``provenance`` so callers get both in one deterministic return value.

* **Schema emission** — :class:`SchemaEmitter`, the inverse of
  :class:`app.normalizer.SchemaCoercer`: it maps the canonical type model
  (:class:`~app.canonical_model.TypeRef`, :class:`~app.canonical_model.Constraints`,
  named :class:`~app.canonical_model.Type`) back into JSON-Schema fragments.
  OpenAPI 3.1 schemas *are* JSON Schema, so this is reused verbatim by the OpenAPI
  emitter and is available to any future emitter of a JSON-Schema-based format.

An emitter is **pure** (no network/DB): given the same model it returns an equal
:class:`EmitResult`, performs no I/O, and emits collections in a deterministic
order so re-conversion is byte-stable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)

__all__ = [
    "EmitOptions",
    "EmittedFile",
    "CapabilityProfile",
    "EmitterDescriptor",
    "EmitterTarget",
    "Emitter",
    "register_emitter",
    "get_emitter",
    "get_emitter_instance",
    "available_emit_formats",
    "describe_emit_targets",
    "load_builtin_emitters",
    "Provenance",
    "ProvenanceRecord",
    "ProvenanceTracker",
    "LossKind",
    "Loss",
    "LossTracker",
    "EmitResult",
    "SchemaEmitter",
]


# ===========================================================================
# Provenance
# ===========================================================================


class Provenance(str, Enum):
    """Where an emitted value came from, for the fidelity analyzer (MFI-22.3).

    Conversion is lossy in *both* directions: a value in the output either was
    present in the source model, or the emitter had to invent it. Recording which
    is which lets the analyzer show a fidelity preview — "these fields are faithful,
    these were inferred/defaulted by the conversion".
    """

    SOURCE = "source"  # copied straight from a populated canonical field
    INFERRED = "inferred"  # derived from the model's structure (not stated outright)
    DEFAULT = "default"  # system-supplied fallback with no basis in the model


class ProvenanceRecord(BaseModel):
    """One ``(location, provenance)`` note about an emitted value.

    ``pointer`` is an RFC-6901 JSON Pointer into the emitted document (e.g.
    ``/info/title``, ``/paths/~1pets~1{id}/get/operationId``), so the analyzer can
    line a provenance note up with the exact construct it describes.
    """

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(
        description="RFC-6901 JSON Pointer to the value within the emitted document."
    )
    provenance: Provenance
    detail: Optional[str] = Field(
        default=None,
        description="Short human note on how the value was derived, when not SOURCE.",
    )


class ProvenanceTracker:
    """Accumulates :class:`ProvenanceRecord`s while an emitter walks the model.

    JSON Pointers are built with :meth:`child` so the escaping of ``~`` and ``/``
    (RFC 6901) happens in one place. :meth:`records` returns the notes sorted by
    pointer so a re-emission of the same model yields a byte-identical provenance
    list (determinism).
    """

    def __init__(self) -> None:
        self._records: List[ProvenanceRecord] = []

    @staticmethod
    def escape(token: str) -> str:
        """Escape one JSON-Pointer reference token (``~`` → ``~0``, ``/`` → ``~1``)."""
        return token.replace("~", "~0").replace("/", "~1")

    @classmethod
    def child(cls, pointer: str, *tokens: str) -> str:
        """Return ``pointer`` extended by one or more escaped path ``tokens``."""
        for token in tokens:
            pointer = f"{pointer}/{cls.escape(token)}"
        return pointer

    def record(
        self,
        pointer: str,
        provenance: Provenance,
        detail: Optional[str] = None,
    ) -> None:
        """Note the provenance of the value at ``pointer``."""
        self._records.append(
            ProvenanceRecord(pointer=pointer, provenance=provenance, detail=detail)
        )

    def records(self) -> List[ProvenanceRecord]:
        """Return the accumulated records, sorted by pointer for determinism."""
        return sorted(self._records, key=lambda r: r.pointer)


# ===========================================================================
# Projection losses (MFI-22.2)
# ===========================================================================


class LossKind(str, Enum):
    """How faithfully a source construct survived projection to OpenAPI.

    Where a :class:`Provenance` note annotates a value that *was* emitted, a
    :class:`Loss` records a source construct the projection could **not** carry
    faithfully. The paradigm projection strategies (MFI-22.2) report these so the
    fidelity analyzer (MFI-22.3) surfaces *what the conversion lost*, not only what
    it kept — subscriptions, streaming, and pub/sub become explicit losses rather
    than silent drops.
    """

    INFERRED = "inferred"  # emitted, but only via a synthesized/derived representation
    NA = "n/a"  # no OpenAPI representation at all — surfaced here rather than dropped


class Loss(BaseModel):
    """One fidelity loss a paradigm projection incurred (MFI-22.2).

    A projection emits a :class:`Loss` both when it had to *invent* a
    representation (:attr:`LossKind.INFERRED` — e.g. a synthesized HTTP binding for
    a gRPC method) and when a construct has *no* OpenAPI representation at all
    (:attr:`LossKind.NA` — e.g. a GraphQL subscription, gRPC streaming, or a
    pub/sub action). The ``NA`` case is the reason losses are a channel separate
    from :class:`Provenance`: an ``n/a`` construct produces no emitted value, so no
    JSON Pointer / provenance note can describe it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: LossKind
    subject: str = Field(
        description="Short slug for the lost/inferred construct kind, e.g. "
        "``graphql-subscription`` or ``synthesized-http-binding``.",
    )
    detail: str = Field(description="Human-readable explanation of the loss.")
    pointer: Optional[str] = Field(
        default=None,
        description="Source coordinate (a canonical ``key``) or emitted JSON "
        "Pointer the loss concerns, when one applies.",
    )


class LossTracker:
    """Accumulates :class:`Loss` records as a projection strategy walks a model.

    :meth:`records` returns the losses in a deterministic order (by kind, subject,
    pointer, detail) so a re-emission of the same model yields a byte-identical
    loss list.
    """

    def __init__(self) -> None:
        self._losses: List[Loss] = []

    def record(
        self,
        kind: LossKind,
        subject: str,
        detail: str,
        pointer: Optional[str] = None,
    ) -> None:
        """Note a fidelity loss of ``kind`` for ``subject``."""
        self._losses.append(
            Loss(kind=kind, subject=subject, detail=detail, pointer=pointer)
        )

    def records(self) -> List[Loss]:
        """Return the accumulated losses, sorted deterministically."""
        return sorted(
            self._losses,
            key=lambda loss: (loss.kind.value, loss.subject, loss.pointer or "", loss.detail),
        )


class EmittedFile(BaseModel):
    """One file in an emitter's output bundle (MFX-1.1).

    Single-file targets (OpenAPI JSON) return one entry; multi-file targets
    (protobuf packages, WSDL+XSD) return many. ``content`` is structured (``dict``)
    for JSON/YAML targets or plain text for others.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Relative path within the output bundle.")
    content: Any = Field(description="Structured document or plain-text payload.")
    media_type: Optional[str] = Field(
        default=None,
        description="Per-file media type when it differs from the bundle default.",
    )


class EmitOptions(BaseModel):
    """Per-target emit options passed to :meth:`Emitter.emit` (MFX-1.1).

    Concrete emitters extend this in later epics (MFX-1.4) with format-specific
    fields; the base model is an empty, validated envelope today.
    """

    model_config = ConfigDict(extra="forbid")


class EmitResult(BaseModel):
    """An emitter's output: emitted ``files``, bundle ``media_type``, and trails.

    Both halves are deterministic for a given input model, so two emissions of the
    same :class:`~app.canonical_model.CanonicalApi` compare equal. ``losses`` (added
    in MFI-22.2) carries the paradigm projection's fidelity losses alongside them.
    """

    model_config = ConfigDict(extra="forbid")

    files: List[EmittedFile] = Field(
        default_factory=list,
        description="Emitted artifacts, sorted by ``path`` for determinism.",
    )
    media_type: str = Field(
        default="application/json",
        description="Primary bundle media type (e.g. ``application/json``).",
    )
    provenance: List[ProvenanceRecord] = Field(
        default_factory=list,
        description="Per-construct provenance notes, sorted by JSON Pointer.",
    )
    losses: List[Loss] = Field(
        default_factory=list,
        description="Fidelity losses the paradigm projection incurred (MFI-22.2), "
        "sorted deterministically. Empty when the conversion was lossless.",
    )

    @property
    def document(self) -> Dict[str, Any]:
        """Primary structured document — the first file's content when it is a ``dict``.

        Retained for callers (conversion preview, fidelity analyzer) that predate
        the multi-file ``files`` envelope (MFX-1.1).
        """
        if not self.files:
            return {}
        content = self.files[0].content
        return content if isinstance(content, dict) else {}

    @classmethod
    def from_document(
        cls,
        document: Dict[str, Any],
        *,
        path: str = "openapi.json",
        media_type: str = "application/json",
        provenance: Optional[List[ProvenanceRecord]] = None,
        losses: Optional[List[Loss]] = None,
    ) -> "EmitResult":
        """Build a single-file :class:`EmitResult` from one structured document."""
        return cls(
            files=[EmittedFile(path=path, content=document, media_type=media_type)],
            media_type=media_type,
            provenance=provenance or [],
            losses=losses or [],
        )


# ===========================================================================
# Capability / fidelity profile (MFX-1.1)
# ===========================================================================


class CapabilityProfile(BaseModel):
    """Static declaration of which canonical constructs a target can represent.

    Consumed by the fidelity engine (MFX-EPIC-2) to predict loss *before* emit.
    Each flag is ``True`` when the target can carry the construct faithfully (not
    merely approximate or synthesize a stand-in).
    """

    model_config = ConfigDict(frozen=True)

    operations: bool = Field(
        default=False,
        description="HTTP/RPC operations (services, routes, bindings).",
    )
    events: bool = Field(
        default=False,
        description="Event channels, pub/sub actions, and async message flows.",
    )
    unions: bool = Field(
        default=False,
        description="Discriminated unions / one-of type alternatives.",
    )
    nullability: bool = Field(
        default=False,
        description="Explicit nullable / optional member semantics.",
    )
    constraints: bool = Field(
        default=False,
        description="Validation facets (min/max, pattern, format, enum).",
    )
    field_identity: bool = Field(
        default=False,
        description="Stable field identifiers (protobuf field numbers, Avro names).",
    )


class EmitterDescriptor(BaseModel):
    """Self-description of an export target for UI/CLI/REST enumeration (MFX-1.1)."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(description="Stable registry key, e.g. ``openapi``.")
    format: str = Field(
        description="Output format key this emitter produces, e.g. ``openapi-3.1``.",
    )
    label: str = Field(description="Human label for target cards / CLI listings.")
    description: str = Field(description="One-line description of what it exports.")
    icon: str = Field(
        description="Icon name (Lucide) the UI renders for this target's card.",
    )
    paradigm: ApiParadigm = Field(
        description="The canonical paradigm this emitter primarily targets.",
    )
    multi_file: bool = Field(
        description="Whether the emitter produces a multi-file bundle (vs one artifact).",
    )
    needs_toolchain: bool = Field(
        description="Whether emit hard-requires an external toolchain binary.",
    )
    available: bool = Field(
        default=True,
        description="Whether this emitter can run in the current runtime.",
    )
    unavailable_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason the target is unavailable, or ``null`` when available.",
    )


class EmitterTarget(BaseModel):
    """One registered export target: descriptor + capability profile (MFX-1.1)."""

    model_config = ConfigDict(frozen=True)

    descriptor: EmitterDescriptor
    capability_profile: CapabilityProfile


# ===========================================================================
# The SPI contract + registry
# ===========================================================================


class Emitter(ABC):
    """Service-provider contract: :class:`CanonicalApi` → an :class:`EmitResult`.

    A concrete emitter declares descriptor metadata (``key``/``label``/``icon``,
    :class:`~app.canonical_model.ApiParadigm`, single vs multi-file,
    toolchain requirement), a static :class:`CapabilityProfile`, which ``format``
    key it produces, and implements :meth:`emit`. It must be **deterministic and
    side-effect free** — given the same model it returns an equal result, performs
    no I/O, and emits every collection in a stable order so re-conversion is
    byte-stable.

    Subclasses register with :func:`register_emitter` (typically via the
    ``register=True`` flag on ``__init_subclass__``) and are looked up by
    ``format`` with :func:`get_emitter`.
    """

    #: Stable target key for cards/CLI, e.g. ``"openapi"``. Distinct from
    #: :attr:`format` when one logical target spans version-specific emitters.
    key: ClassVar[str] = ""
    #: Output format key this emitter produces, e.g. ``"openapi-3.1"``. Used as the
    #: registry key.
    format: ClassVar[str] = ""
    #: Human label for target cards / CLI listings.
    label: ClassVar[str] = ""
    #: One-line description of what the emitter exports.
    description: ClassVar[str] = ""
    #: Icon name (Lucide) the UI renders for this target's card.
    icon: ClassVar[str] = "file-output"
    #: The canonical paradigm this emitter primarily targets. An emitter may still
    #: accept models of other paradigms on a best-effort basis (a REST emitter can
    #: render RPC operations as HTTP endpoints, for instance).
    paradigm: ClassVar[ApiParadigm]
    #: Whether this emitter produces a multi-file bundle.
    multi_file: ClassVar[bool] = False
    #: Toolchain tool keys this emitter's emit **hard-requires**. When any is
    #: unavailable in the runtime, the descriptor reports ``available = False``.
    required_tools: ClassVar[Tuple[str, ...]] = ()

    def __init_subclass__(cls, *, register: bool = False, **kwargs: Any) -> None:
        """Optionally self-register a concrete subclass in the format registry.

        Args:
            register: When ``True``, the subclass is added to the global registry
                under its :attr:`format` key as soon as it is defined.
        """
        super().__init_subclass__(**kwargs)
        if register:
            register_emitter(cls)

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Return this emitter's static capability/fidelity profile (MFX-1.1)."""
        return CapabilityProfile()

    @classmethod
    def descriptor(cls) -> EmitterDescriptor:
        """Return this emitter's serializable :class:`EmitterDescriptor`."""
        from .toolchain_runner import is_tool_available

        missing = [tool for tool in cls.required_tools if not is_tool_available(tool)]
        available = not missing
        unavailable_reason = (
            None
            if available
            else (
                f"Requires the {', '.join(missing)} toolchain, which is not available "
                "in this runtime."
            )
        )
        return EmitterDescriptor(
            key=cls.key or cls.format,
            format=cls.format,
            label=cls.label or cls.key or cls.format,
            description=cls.description,
            icon=cls.icon,
            paradigm=cls.paradigm,
            multi_file=cls.multi_file,
            needs_toolchain=bool(cls.required_tools),
            available=available,
            unavailable_reason=unavailable_reason,
        )

    @abstractmethod
    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[EmitOptions] = None,
    ) -> EmitResult:
        """Emit ``api`` as one or more files, with per-construct provenance.

        Args:
            api: The canonical model to emit.
            opts: Optional per-target options (MFX-1.4 extends these).

        Returns:
            An :class:`EmitResult` whose ``files`` are valid artifacts in this
            emitter's :attr:`format` and whose ``provenance`` records where each
            emitted value came from.
        """
        raise NotImplementedError


# Format-key → emitter-class registry, mirroring the normalizer registry so the
# conversion pipeline can resolve an emitter by target format key.
_REGISTRY: Dict[str, type[Emitter]] = {}
_builtins_loaded = False


def register_emitter(cls: type[Emitter]) -> type[Emitter]:
    """Register a concrete emitter class under its :attr:`Emitter.format` key.

    Args:
        cls: A concrete :class:`Emitter` subclass with a non-empty ``format``.

    Returns:
        ``cls`` unchanged, so this can also be used as a class decorator.

    Raises:
        ValueError: If ``cls.format`` is empty, or a *different* class is already
            registered under the same key (re-registering the same class is a
            no-op so module re-import is safe).
    """
    key = cls.format
    if not key:
        raise ValueError(f"{cls.__name__} must set a non-empty `format` to register")
    existing = _REGISTRY.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"format {key!r} already registered to {existing.__name__}; "
            f"cannot re-register to {cls.__name__}"
        )
    _REGISTRY[key] = cls
    return cls


def load_builtin_emitters() -> None:
    """Import built-in emitter modules so they self-register.

    Idempotent and cheap after the first call. Kept lazy so adapter modules can
    import this one without a cycle.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    from . import openapi_emitter as _openapi  # noqa: F401
    from . import sample_emitter as _sample  # noqa: F401


def get_emitter(format_key: str) -> Optional[type[Emitter]]:
    """Return the emitter class registered for ``format_key``, or ``None``."""
    load_builtin_emitters()
    return _REGISTRY.get(format_key)


def get_emitter_instance(format_key: str) -> Optional[Emitter]:
    """Return an instance of the emitter registered for ``format_key``, or ``None``."""
    cls = get_emitter(format_key)
    return cls() if cls is not None else None


def available_emit_formats() -> List[str]:
    """Return the sorted list of format keys that have a registered emitter."""
    load_builtin_emitters()
    return sorted(_REGISTRY)


def describe_emit_targets() -> List[EmitterTarget]:
    """Return every registered emitter's descriptor + capability profile, sorted by key.

    This is the **target list** the UI (target cards), the CLI (``export --list``),
    and REST enumerate — the registry's public view (MFX-1.1).
    """
    load_builtin_emitters()
    targets = [
        EmitterTarget(
            descriptor=_REGISTRY[format_key].descriptor(),
            capability_profile=_REGISTRY[format_key].capability_profile(),
        )
        for format_key in sorted(_REGISTRY)
    ]
    return sorted(targets, key=lambda target: target.descriptor.key)


# ===========================================================================
# Schema emission (canonical type model → JSON-Schema fragment)
# ===========================================================================


# :class:`Constraints` attribute → JSON-Schema keyword. The exact inverse of
# :data:`app.normalizer._CONSTRAINT_KEYWORDS`; the draft 2020-12 / OpenAPI-3.1
# numeric spellings are emitted (``exclusiveMinimum``/``exclusiveMaximum`` as
# numbers, not the OpenAPI-3.0 booleans).
_CONSTRAINT_ATTRS: Tuple[Tuple[str, str], ...] = (
    ("minimum", "minimum"),
    ("maximum", "maximum"),
    ("exclusive_minimum", "exclusiveMinimum"),
    ("exclusive_maximum", "exclusiveMaximum"),
    ("multiple_of", "multipleOf"),
    ("min_length", "minLength"),
    ("max_length", "maxLength"),
    ("pattern", "pattern"),
    ("min_items", "minItems"),
    ("max_items", "maxItems"),
    ("unique_items", "uniqueItems"),
    ("enum", "enum"),
    ("format", "format"),
)

# JSON-Schema scalar primitive names a :class:`TypeRef.name` may carry directly
# (as opposed to naming a component type). Mirrors ``app.normalizer._SCALAR_TYPES``.
_PRIMITIVE_NAMES = frozenset({"string", "number", "integer", "boolean", "null"})

# Python type → JSON-Schema scalar ``type``, used to recover an enum's base type
# from its literal values (the canonical ENUM keeps values, not a declared type).
_PY_TO_JSON_TYPE: Tuple[Tuple[type, str], ...] = (
    (bool, "boolean"),  # bool before int — bool *is* an int subclass in Python
    (int, "integer"),
    (float, "number"),
    (str, "string"),
)


def _emit_constraints(constraints: Optional[Constraints]) -> Dict[str, Any]:
    """Emit a :class:`Constraints` back into its JSON-Schema keywords.

    Args:
        constraints: The canonical constraints, or ``None``.

    Returns:
        A dict of JSON-Schema constraint keywords (empty when ``constraints`` is
        ``None`` or carries no set facet).
    """
    result: Dict[str, Any] = {}
    if constraints is None:
        return result
    for attr, keyword in _CONSTRAINT_ATTRS:
        value = getattr(constraints, attr)
        if value is not None:
            result[keyword] = value
    return result


class SchemaEmitter:
    """Map the canonical type model back into JSON-Schema fragments.

    The inverse of :class:`app.normalizer.SchemaCoercer`. It is created once per
    emission with the JSON-Pointer ``ref_prefix`` that named-type references should
    use (``#/components/schemas/`` for OpenAPI) and exposes two operations:

    * :meth:`type_ref` — emit a :class:`~app.canonical_model.TypeRef` *use site*
      (a field type, a parameter type, a payload) as a schema fragment, preserving
      list nesting and (for reference members) nullability;
    * :meth:`named_schema` — emit a named :class:`~app.canonical_model.Type`
      (RECORD/ENUM/UNION/MAP/ALIAS/SCALAR) as a component schema.

    OpenAPI 3.1 schemas *are* JSON Schema (draft 2020-12), so the fragments this
    produces are valid at both layers.
    """

    def __init__(self, ref_prefix: str = "#/components/schemas/") -> None:
        """Create a schema emitter.

        Args:
            ref_prefix: JSON-Pointer prefix a named-type ``$ref`` is built with, so
                a :class:`TypeRef` naming a component type becomes
                ``{"$ref": f"{ref_prefix}{name}"}``.
        """
        self.ref_prefix = ref_prefix

    # --- use-site emission --------------------------------------------------

    def type_ref(self, ref: TypeRef) -> Dict[str, Any]:
        """Emit a use-site :class:`TypeRef` as a JSON-Schema fragment.

        * a list ref (``item`` set) → ``{"type": "array", "items": <inner>}``;
        * a primitive ref (``name`` in :data:`_PRIMITIVE_NAMES`) → ``{"type": name}``;
        * a named-type ref → ``{"$ref": "<ref_prefix><name>"}``;
        * a bare/typeless ref (neither ``name`` nor ``item``) → ``{}`` (any value).

        A :class:`TypeRef`'s ``nullable`` is *not* rendered as a ``"null"`` type
        here. The normalizer sets ``nullable=True`` for every optional member (a
        field absent from its parent's ``required`` list), conflating "optional"
        with "may be null"; injecting ``"null"`` would stamp a spurious null type
        onto ordinary optional fields. Member optionality is instead expressed by
        the caller through ``required`` membership (see :meth:`_record`), matching
        the normalizer's inverse. The residual case — a member that is genuinely
        nullable *and* required — is not distinctly representable in the canonical
        model, so it is emitted as an optional member.

        Args:
            ref: The use-site type reference.

        Returns:
            A JSON-Schema fragment.
        """
        if ref.is_list():
            inner = self.type_ref(ref.item) if ref.item is not None else {}
            return {"type": "array", "items": inner}

        if ref.name is None:
            # Typeless use site (e.g. a permissive/free-form value): any schema.
            return {}

        if ref.name in _PRIMITIVE_NAMES:
            return {"type": ref.name}

        # A named component type.
        return {"$ref": f"{self.ref_prefix}{ref.name}"}

    # --- named-type emission ------------------------------------------------

    def named_schema(self, type_: Type) -> Dict[str, Any]:
        """Emit a named :class:`Type` as a component schema.

        The emitted shape is the inverse of
        :meth:`app.normalizer.SchemaCoercer.named_type`:

        * ``RECORD`` → ``{"type": "object", "properties": {...}, "required": [...]}``
          (``required`` lists the non-nullable fields);
        * ``ENUM`` → ``{"type": <inferred scalar>, "enum": [...]}``;
        * ``UNION`` → ``{"oneOf": [{"$ref": ...}, ...]}``;
        * ``MAP`` → ``{"type": "object", "additionalProperties": <value schema>}``;
        * ``ALIAS`` → the aliased ref's schema (typically an array);
        * ``SCALAR`` → a constrained leaf (``{"format": ...}`` etc.).

        ``description``/``deprecated`` are attached when set. Field-level
        ``description``/``default``/``deprecated``/constraints are emitted too.

        Args:
            type_: The named canonical type.

        Returns:
            The component JSON-Schema fragment for ``type_``.
        """
        if type_.kind is TypeKind.RECORD:
            schema = self._record(type_)
        elif type_.kind is TypeKind.ENUM:
            schema = self._enum(type_)
        elif type_.kind is TypeKind.UNION:
            schema = {
                "oneOf": [
                    {"$ref": f"{self.ref_prefix}{member}"}
                    for member in type_.union_members
                ]
            }
        elif type_.kind is TypeKind.MAP:
            value_schema = (
                self.type_ref(type_.value_type) if type_.value_type is not None else {}
            )
            schema = {"type": "object", "additionalProperties": value_schema}
        elif type_.kind is TypeKind.ALIAS:
            schema = self.type_ref(type_.aliased) if type_.aliased is not None else {}
        else:  # TypeKind.SCALAR
            schema = _emit_constraints(type_.constraints)

        if type_.description:
            schema["description"] = type_.description
        if type_.deprecated:
            schema["deprecated"] = True
        return schema

    def _record(self, type_: Type) -> Dict[str, Any]:
        """Emit a RECORD type as an object schema with properties + required."""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for field in type_.fields:
            properties[field.name] = self._field_schema(field)
            # A non-nullable field is a required member; the normalizer set
            # `nullable=False` exactly for members in the source `required` array.
            if field.type.nullable is False:
                required.append(field.name)
        schema: Dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def _field_schema(self, field: Any) -> Dict[str, Any]:
        """Emit one RECORD field (its type plus per-field facets)."""
        schema = self.type_ref(field.type)
        # Constraints/description/default/deprecated only compose onto a plain
        # (non-``$ref``) fragment; a `$ref` leaf keeps siblings out per JSON
        # Schema, so they are dropped there to stay schema-valid.
        if "$ref" not in schema:
            schema.update(_emit_constraints(field.constraints))
            if field.default is not None:
                schema["default"] = field.default
            if field.description:
                schema["description"] = field.description
            if field.deprecated:
                schema["deprecated"] = True
        return schema

    @staticmethod
    def _enum(type_: Type) -> Dict[str, Any]:
        """Emit an ENUM type, recovering its base scalar type from its values."""
        values = [ev.value if ev.value is not None else ev.name for ev in type_.enum_values]
        schema: Dict[str, Any] = {}
        json_type = SchemaEmitter._infer_scalar_type(values)
        if json_type is not None:
            schema["type"] = json_type
        schema["enum"] = values
        return schema

    @staticmethod
    def _infer_scalar_type(values: List[Any]) -> Optional[str]:
        """Infer a single JSON-Schema scalar ``type`` covering ``values``.

        Returns the shared scalar type when every value maps to the same one, else
        ``None`` (a mixed/empty enum is left untyped, which is still valid).
        """
        found: set = set()
        for value in values:
            for py_type, json_type in _PY_TO_JSON_TYPE:
                if isinstance(value, py_type):
                    found.add(json_type)
                    break
            else:
                return None  # a value of no known scalar type → leave untyped
        return found.pop() if len(found) == 1 else None
