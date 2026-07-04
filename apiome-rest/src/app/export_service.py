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

from typing import Optional

from .canonical_model import CanonicalApi
from .emitter import (
    EmitOptions,
    EmitResult,
    Emitter,
    available_emit_formats,
    describe_emit_targets,
    get_emitter,
    load_builtin_emitters,
)

__all__ = [
    "ExportError",
    "resolve_emit_format",
    "resolve_emitter",
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


def emit_canonical(
    api: CanonicalApi,
    target: str,
    *,
    opts: Optional[EmitOptions] = None,
) -> EmitResult:
    """Emit ``api`` through the registered emitter for ``target``.

    Args:
        api: Canonical model to export.
        target: Emitter key or format key.
        opts: Optional per-target emit options.

    Returns:
        The emitter's :class:`~app.emitter.EmitResult`.

    Raises:
        ExportError: When ``target`` does not resolve to a registered emitter.
    """
    return resolve_emitter(target).emit(api, opts=opts)
