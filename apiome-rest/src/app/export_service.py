"""Export orchestration behind the Emitter SPI — MFX-1.3 (#3836).

Catalog conversion (MFI-22.5) and future export surfaces (REST export jobs, CLI
``apiome export``) resolve emitters through the registry
(:func:`app.emitter.get_emitter`) rather than importing concrete emitter classes.
This module is that seam — the export-side analogue of routing import through
:class:`app.import_source.ImportSource` adapters (MFI-1.1).

Callers pass a logical **target** — either an emitter's stable ``key`` (e.g.
``openapi``) or its registry ``format`` (e.g. ``openapi-3.1``) — and receive an
:class:`~app.emitter.EmitResult` from the registered emitter. The OpenAPI export
path that previously called :class:`app.openapi_emitter.OpenApiEmitter` directly
now flows through :func:`emit_canonical` so additional targets (AsyncAPI, GraphQL,
…) register once and are reachable without rewiring each caller.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .capnproto_emitter import CapnpEmitter
from .emitter import (
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    Emitter,
    available_emit_formats,
    coerce_emit_options,
    describe_emit_targets,
    get_emitter,
    load_builtin_emitters,
)
from .field_identity_store import (
    CAPNP_TARGET,
    PROTO3_TARGET,
    THRIFT_TARGET,
    load_persisted_field_numbers,
    persist_field_number_assignments,
)
from .proto_emitter import ProtoEmitter
from .thrift_emitter import ThriftEmitter

__all__ = [
    "ExportError",
    "ExportPersistenceContext",
    "resolve_emit_format",
    "ensure_target_available",
    "resolve_emitter",
    "resolve_emit_options",
    "emit_canonical",
]


class ExportError(Exception):
    """Raised when a canonical export cannot be routed to a registered emitter."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ExportPersistenceContext(BaseModel):
    """Optional tenant/artifact coordinates for persisting synthesized field identities.

    Used by the targets that number fields positionally: Protobuf (MFX-12.2), Thrift (MFX-25.2) and
    Cap'n Proto (MFX-30.2, which also keeps its file id there).
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(description="Owning tenant id.")
    artifact_id: str = Field(description="The artifact (project) id being exported.")


def _field_identity_target(emitter_cls: type[Emitter]) -> Optional[str]:
    """The field-identity store key for an emitter whose synthesized field numbers persist.

    Args:
        emitter_cls: The resolved emitter class.

    Returns:
        :data:`~app.field_identity_store.PROTO3_TARGET` for Protobuf,
        :data:`~app.field_identity_store.THRIFT_TARGET` for Thrift,
        :data:`~app.field_identity_store.CAPNP_TARGET` for Cap'n Proto, ``None`` for every other
        target.
    """
    if issubclass(emitter_cls, ProtoEmitter):
        return PROTO3_TARGET
    if issubclass(emitter_cls, ThriftEmitter):
        return THRIFT_TARGET
    if issubclass(emitter_cls, CapnpEmitter):
        return CAPNP_TARGET
    return None


def _with_persisted_field_numbers(
    emitter_cls: type[Emitter], options: Optional[EmitOptions], persisted: Dict[str, int]
) -> EmitOptions:
    """Return the emitter's options with stored field numbers merged under ``persisted_field_numbers``.

    Numbers already in the options (a caller's override) are kept unless the store has the same
    field, in which case the stored number wins — it is what earlier exports wrote.

    Args:
        emitter_cls: The resolved emitter class; its ``options_model`` declares the field.
        options: The validated options, or ``None``.
        persisted: ``field_key → number`` loaded from the store.

    Returns:
        A fresh ``emitter_cls.options_model`` instance.
    """
    raw = options.model_dump() if isinstance(options, EmitOptions) else {}
    merged = {**(raw.get("persisted_field_numbers") or {}), **persisted}
    return emitter_cls.options_model.model_validate({**raw, "persisted_field_numbers": merged})


def _available_target_labels() -> list[str]:
    """Return sorted human-facing target labels for error messages."""
    labels: set[str] = set(available_emit_formats())
    for entry in describe_emit_targets():
        labels.add(entry.descriptor.key)
        labels.add(entry.descriptor.format)
    return sorted(labels)


def resolve_emit_format(target: str) -> str:
    """Map a logical export target (emitter ``key`` or registry ``format``) to a format key.

    Args:
        target: Emitter key (``openapi``) or format key (``openapi-3.1``).

    Returns:
        The registry ``format`` key for the resolved emitter.

    Raises:
        ExportError: When ``target`` is empty or does not match any registered emitter.
    """
    load_builtin_emitters()
    key = (target or "").strip()
    if not key:
        raise ExportError("Export target is required.", status_code=400)

    if get_emitter(key) is not None:
        return key

    lowered = key.lower()
    if get_emitter(lowered) is not None:
        return lowered

    for entry in describe_emit_targets():
        descriptor = entry.descriptor
        if lowered in {descriptor.key.lower(), descriptor.format.lower()}:
            return descriptor.format

    available = ", ".join(_available_target_labels())
    raise ExportError(
        f"Unsupported export target {target!r}; available: {available}.",
        status_code=400,
    )


def resolve_emitter(target: str) -> Emitter:
    """Return an emitter instance for ``target``.

    Args:
        target: Emitter key or format key (see :func:`resolve_emit_format`).

    Raises:
        ExportError: When no emitter is registered for ``target``.
    """
    format_key = resolve_emit_format(target)
    emitter_cls = get_emitter(format_key)
    if emitter_cls is None:
        available = ", ".join(_available_target_labels())
        raise ExportError(
            f"Unsupported export target {target!r}; available: {available}.",
            status_code=400,
        )
    ensure_target_available(emitter_cls)
    return emitter_cls()


def ensure_target_available(emitter_cls: type[Emitter]) -> None:
    """Refuse a target this deployment cannot run, with the registry's reason (E1-6, #6221).

    Availability comes from the emitter's own descriptor (its ``required_tools`` checked against
    the toolchain runner) — the same ``available`` / ``unavailable_reason`` the target grid, the
    studio and ``apiome export targets`` show — so a target listed as unavailable is refused up
    front instead of starting and then failing mid-emit.

    Args:
        emitter_cls: The resolved emitter class.

    Raises:
        ExportError: (422) When the target is unavailable in this runtime.
    """
    descriptor = emitter_cls.descriptor()
    if not descriptor.available:
        raise ExportError(
            f"{descriptor.label} is not available in this deployment: "
            f"{descriptor.unavailable_reason or 'its toolchain is not installed.'}",
            status_code=422,
        )


def resolve_emit_options(
    target: str,
    raw: Optional[Dict[str, Any]] = None,
) -> EmitOptions:
    """Validate per-target emit options for ``target`` (MFX-1.4).

    Args:
        target: Emitter key or format key.
        raw: Caller-supplied option values (``None`` or ``{}`` → defaults).

    Returns:
        Validated options for the resolved emitter.

    Raises:
        ExportError: When ``target`` is unknown or options fail validation.
    """
    emitter_cls = type(resolve_emitter(target))
    try:
        return coerce_emit_options(emitter_cls, raw)
    except EmitOptionsError as exc:
        raise ExportError(str(exc), status_code=exc.status_code) from exc


def _normalize_opts(
    emitter_cls: type[Emitter],
    opts: Optional[Union[EmitOptions, Dict[str, Any]]],
) -> EmitOptions:
    """Coerce ``opts`` to a validated options instance for ``emitter_cls``."""
    if opts is None:
        return emitter_cls.default_options()
    if isinstance(opts, EmitOptions):
        if not isinstance(opts, emitter_cls.options_model):
            return emitter_cls.options_model.model_validate(opts.model_dump())
        return opts
    try:
        return coerce_emit_options(emitter_cls, opts)
    except EmitOptionsError as exc:
        raise ExportError(str(exc), status_code=exc.status_code) from exc


def emit_canonical(
    api: CanonicalApi,
    target: str,
    *,
    opts: Optional[Union[EmitOptions, Dict[str, Any]]] = None,
    persistence: Optional[ExportPersistenceContext] = None,
) -> EmitResult:
    """Emit ``api`` through the registered emitter for ``target``.

    Args:
        api: Canonical model to export.
        target: Emitter key or format key.
        opts: Optional per-target emit options — a validated :class:`EmitOptions`
            instance or a raw ``dict`` validated against the target's schema.
        persistence: When provided for a Protobuf, Thrift or Cap'n Proto export, load and persist
            stable synthesized field numbers (MFX-12.2, MFX-25.2) — for Cap'n Proto, ordinals and
            the file id (MFX-30.2).

    Returns:
        The emitter's :class:`~app.emitter.EmitResult`.

    Raises:
        ExportError: When ``target`` does not resolve or options fail validation.
    """
    emitter = resolve_emitter(target)
    emitter_cls = type(emitter)
    # A source-bound target (EDI X12, HL7 v2, …) cannot write a source imported in another format:
    # refuse with the reason rather than let the emitter fail mid-render (RC6-H4, #6211).
    unsupported = emitter_cls.source_unsupported_reason(api)
    if unsupported:
        raise ExportError(unsupported, status_code=422)
    options = _normalize_opts(emitter_cls, opts)

    identity_target = _field_identity_target(emitter_cls) if persistence is not None else None
    if persistence is not None and identity_target is not None:
        persisted = load_persisted_field_numbers(
            persistence.tenant_id,
            persistence.artifact_id,
            identity_target,
        )
        options = _with_persisted_field_numbers(emitter_cls, options, persisted)

    try:
        result = emitter.emit(api, opts=options)
    except EmitPreconditionError as exc:
        # X1 (#6222): the source lacks what the target writes — a refusal with the emitter's
        # reason (422), never a crash. `source_unsupported_reason` catches most of these first.
        raise ExportError(str(exc), status_code=422) from exc

    if persistence is not None and identity_target is not None and result.field_identity_assignments:
        persist_field_number_assignments(
            persistence.tenant_id,
            persistence.artifact_id,
            identity_target,
            result.field_identity_assignments,
        )

    return result
