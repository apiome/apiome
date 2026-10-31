"""Bare OpenAPI Overlay lint — ``POST /v1/lint/overlay`` (GVM-4.1, #5876).

An overlay uploaded without its base cannot be imported (``INPUT_OVERLAY_BASE_MISSING``), but it
can still be checked: is its version one Apiome reads, is every action well formed for that
revision, does every ``target`` and ``copy`` expression parse? This route runs
:func:`app.openapi_overlay.lint_bare_overlay` over a posted overlay and answers with the findings
and a per-rule status for the whole ``overlay`` pack. The two rules that need the base
(``overlay.unmatched-target``, ``overlay.extends-unresolved``) come back ``skipped`` with reason
``no-base`` — never ``passed``.

It reads nothing and writes nothing, so it needs only a signed-in session (like
``GET /v1/lint/rules``). ``apiome lint <file>`` (GOV-3.5) will call it for overlay files.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_session_credentials

__all__ = ["router"]

router = APIRouter(prefix="/v1/lint", tags=["lint"])

#: Largest overlay text the route accepts (characters).
MAX_OVERLAY_CHARS = 2_000_000


class OverlayLintRequest(BaseModel):
    """``POST /v1/lint/overlay``: the overlay to lint."""

    model_config = ConfigDict(extra="forbid")

    document: str = Field(min_length=1, description="The Overlay document, as YAML or JSON text.")
    filename: Optional[str] = Field(
        default=None, max_length=512, description="Its file name, used to label the findings."
    )


class OverlayLintFindingOut(BaseModel):
    """One finding of the ``overlay`` pack."""

    model_config = ConfigDict(populate_by_name=True)

    rule: str = Field(description="The `overlay.*` rule that fired.")
    severity: str = Field(description="The rule's default severity (error / warning).")
    message: str
    target: str = Field(default="", description="The action's `target`, when the finding is about an action.")
    action_index: int = Field(
        alias="actionIndex", description="0-based action index; -1 for a finding about the document itself."
    )


class OverlayLintRuleStatus(BaseModel):
    """Whether one ``overlay`` rule passed, failed or could not run."""

    model_config = ConfigDict(populate_by_name=True)

    rule_id: str = Field(alias="ruleId")
    status: Literal["passed", "failed", "skipped"]
    reason: Optional[str] = Field(
        default=None,
        description="Why a rule was skipped: `no-base` (it needs the base document) or "
        "`version-unsupported` (the overlay's version is not one Apiome reads).",
    )


class OverlayLintResponse(BaseModel):
    """The lint of one bare overlay."""

    model_config = ConfigDict(populate_by_name=True)

    version: Optional[str] = Field(default=None, description="The overlay's `overlay` marker, as written.")
    revision: Optional[str] = Field(
        default=None, description="The supported revision it selects (`1.0`, `1.1`, `1.2`), or null."
    )
    findings: List[OverlayLintFindingOut] = Field(default_factory=list)
    rules: List[OverlayLintRuleStatus] = Field(default_factory=list)


@router.post("/overlay", response_model=OverlayLintResponse, response_model_by_alias=True)
async def lint_overlay(
    body: OverlayLintRequest,
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> OverlayLintResponse:
    """Lint an OpenAPI Overlay on its own, without a base document (GVM-4.1).

    The version and structural rules run; `overlay.unmatched-target` and
    `overlay.extends-unresolved` are reported `skipped` (`no-base`) because only a base can decide
    them.

    Raises:
        HTTPException: 413 when the document is over the size limit; 422 when it is not YAML or
            JSON, or not a mapping.
    """
    from .import_ingestion import IngestionError, parse_document
    from .openapi_overlay import lint_bare_overlay, overlay_rule_for
    from .overlay_lint_rules import OVERLAY_RULES

    _ = auth_data
    if len(body.document) > MAX_OVERLAY_CHARS:
        raise HTTPException(status_code=413, detail=f"The overlay is over the {MAX_OVERLAY_CHARS}-character limit.")
    label = body.filename or "overlay"
    try:
        document = parse_document(body.document, source_label=label)
    except (IngestionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"The overlay is not valid YAML or JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise HTTPException(status_code=422, detail="An Overlay document must be a YAML or JSON object.")

    report = lint_bare_overlay(document, label=label)
    findings = []
    for finding in report.findings:
        rule = overlay_rule_for(finding.code)
        findings.append(
            OverlayLintFindingOut(
                rule=rule,
                severity=OVERLAY_RULES[rule][1],
                message=finding.message,
                target=finding.target,
                action_index=finding.action_index,
            )
        )
    return OverlayLintResponse(
        version=report.version,
        revision=report.revision,
        findings=findings,
        rules=[
            OverlayLintRuleStatus(rule_id=r["rule_id"], status=r["status"], reason=r["reason"]) for r in report.rules
        ],
    )
