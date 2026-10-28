"""Lint the emitted export artifact — MFX-5.2 (#3853).

The Verify workbench's third lens (MFX-42.3) asks *"is the file this export writes good of its
kind?"* — a different question from validation (*"does it parse?"*, MFX-5.1) and fidelity (*"what
did the conversion lose?"*, MFX-2.5). It is answered with the **same MFI rule packs an import
runs**, so a GraphQL export is linted by the GraphQL pack, a Protobuf export by the Protobuf pack,
and every export by the unconditional common / examples / provenance packs:

1. **Read back** — the emitted bundle is re-imported through the import adapter for its format
   (:func:`app.roundtrip_matrix.import_adapter_for_emit` + :func:`~app.roundtrip_matrix.reimport_emitted`,
   the IXH-4.4 round-trip seams), giving the canonical model *of the artifact*, not of the source.
2. **Lint** — :func:`app.lint_engine.lint_canonical_model` runs over that model: the same engine,
   rule ids and scoring formula as an import, so the score and grade read the same as a catalog
   item's.

The lint is **advisory**: it never changes the verify verdict or blocks a delivery. It is also
best-effort: a target no import adapter can read back (a gateway config, a client collection
without an importer), or an artifact the adapter refuses, reports ``applicable: false`` with the
reason instead of a misleading clean score — and an unexpected fault degrades the same way rather
than failing the verify.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .emitter import EmitResult
from .import_source import ImportSourceError, get_import_source
from .lint_engine import get_paradigm_rule_pack, get_rule_pack, lint_canonical_model
from .roundtrip_matrix import SAMPLE_EMIT_KEYS, import_adapter_for_emit, reimport_emitted

logger = logging.getLogger(__name__)

__all__ = [
    "COMMON_PACK",
    "EmittedArtifactLint",
    "lint_emitted_artifact",
]

#: The pack name reported when no format or paradigm pack is registered for the artifact's format:
#: only the unconditional packs (common hygiene, examples, provenance) ran.
COMMON_PACK = "common"


class EmittedArtifactLint(BaseModel):
    """The emitted-artifact lint report for one verify (MFX-5.2 → the MFX-42.3 lint lens).

    ``applicable`` is false when the artifact could not be linted — no import adapter reads the
    target's format back, or the adapter refused the artifact — and ``reason`` says which. The
    lens then shows its "no lint pack ran" state instead of a clean score.
    """

    model_config = ConfigDict(extra="forbid")

    applicable: bool = Field(
        description="Whether the emitted artifact was linted (it could be read back into a model).",
    )
    pack: Optional[str] = Field(
        default=None,
        description="The format rule pack that ran (e.g. ``graphql``, ``protobuf``), or "
        "``common`` when only the unconditional packs apply to the artifact's format.",
    )
    score: Optional[int] = Field(
        default=None, description="The 0–100 quality score, when the pack computes one."
    )
    grade: Optional[str] = Field(
        default=None, description="The A–F letter grade, when the pack computes one."
    )
    findings: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The itemized lint findings (``severity``, ``rule``, ``message``, ``category``, "
        "``path``), in the engine's deterministic order.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Why the artifact was not linted, when ``applicable`` is false.",
    )


def _not_applicable(reason: str) -> EmittedArtifactLint:
    """A report for an artifact that could not be linted, saying why."""
    return EmittedArtifactLint(applicable=False, reason=reason)


def _pack_name(api: Any) -> str:
    """Name the pack that linted ``api``: its format pack, else its paradigm pack, else common."""
    for pack_cls in (get_rule_pack(getattr(api, "format", "") or ""), get_paradigm_rule_pack(api.paradigm)):
        if pack_cls is not None:
            return pack_cls.pack_id or pack_cls.format or pack_cls.paradigm or COMMON_PACK
    return COMMON_PACK


def lint_emitted_artifact(
    emit_key: str,
    emit_format: str,
    emit: EmitResult,
    *,
    multi_file: bool = False,
) -> EmittedArtifactLint:
    """Lint one emitted artifact with the MFI rule packs for its format.

    Args:
        emit_key: The emitter registry key (``graphql``).
        emit_format: The resolved emit format key (``graphql``, ``openapi-3.1``).
        emit: The emitted bundle (one or more files).
        multi_file: Whether the target writes a multi-file bundle (re-imported as a fileset).

    Returns:
        The lint report: score, grade and findings when the artifact could be read back, or
        ``applicable: false`` with the reason. Never raises.
    """
    if emit_key in SAMPLE_EMIT_KEYS or emit_format in SAMPLE_EMIT_KEYS:
        return _not_applicable("The sample target writes no lintable format.")
    adapter_key = import_adapter_for_emit(emit_key, emit_format)
    adapter = get_import_source(adapter_key) if adapter_key else None
    if adapter is None:
        return _not_applicable(
            f"No import adapter reads {emit_format!r} back, so no lint pack can run over it."
        )
    try:
        artifact_api = reimport_emitted(
            adapter, emit, multi_file=multi_file, source_label=f"lint:{emit_key}"
        )
    except (ImportSourceError, ValueError, TypeError) as exc:
        return _not_applicable(f"The emitted artifact could not be read back for linting: {exc}")
    except Exception:  # noqa: BLE001 - lint is advisory; a reader fault never fails a verify
        logger.warning("Emitted-artifact read-back failed for %s", emit_format, exc_info=True)
        return _not_applicable("The emitted artifact could not be read back for linting.")

    try:
        result = lint_canonical_model(artifact_api)
    except Exception:  # noqa: BLE001 - same: an engine fault degrades to "not linted"
        logger.warning("Emitted-artifact lint failed for %s", emit_format, exc_info=True)
        return _not_applicable("The lint engine could not lint this artifact.")

    return EmittedArtifactLint(
        applicable=True,
        pack=_pack_name(artifact_api),
        score=result.score,
        grade=result.grade,
        findings=[
            {
                "severity": finding.severity,
                "rule": finding.rule,
                "message": finding.message,
                "category": finding.category,
                "path": finding.path or None,
            }
            for finding in result.findings
        ],
    )
