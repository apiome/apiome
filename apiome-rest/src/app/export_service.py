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

from .canonical_model import CanonicalApi
from .emitter import (
    EmitOptions,
    EmitOptionsError,
    EmitResult,
    Emitter,
    available_emit_formats,
    coerce_emit_options,
    describe_emit_targets,
    get_emitter,
    load_builtin_emitters,
)

__all__ = [
    "ExportError",
    "resolve_emit_format",
    "resolve_emitter",
    "resolve_emit_options",
    "emit_canonical",
]


class ExportError(Exception):
    """Raised when a canonical export cannot be routed to a registered emitter."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    return emitter_cls()


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
) -> EmitResult:
    """Emit ``api`` through the registered emitter for ``target``.

    Args:
        api: Canonical model to export.
        target: Emitter key or format key.
        opts: Optional per-target emit options — a validated :class:`EmitOptions`
            instance or a raw ``dict`` validated against the target's schema.

    Returns:
        The emitter's :class:`~app.emitter.EmitResult`.

    Raises:
        ExportError: When ``target`` does not resolve or options fail validation.
    """
    emitter = resolve_emitter(target)
    options = _normalize_opts(type(emitter), opts)
    return emitter.emit(api, opts=options)
