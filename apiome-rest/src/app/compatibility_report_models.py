"""Response models every compatibility surface shares (XPC-4.5, #5749).

``evaluatedUnder`` says what a verdict was graded under — mode, transitivity, Protobuf category,
the formats compared, and whether the mode was actually applied — so a caller (the CLI, the CI
diff gate, the CDG-4 subject API) never has to guess. ``against`` names the revision a change was
found against when a transitive check compared more than the base.

Kept apart from :mod:`app.models` and :mod:`app.compatibility_modes` so both the route modules and
the central model module can import them without pulling in the classifiers.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

__all__ = ["ComparedRevisionOut", "EvaluatedUnderOut"]


class ComparedRevisionOut(BaseModel):
    """One stored revision the head was compared against."""

    model_config = ConfigDict(populate_by_name=True)

    revision_id: str = Field(
        validation_alias=AliasChoices("revisionId", "revision_id"),
        serialization_alias="revisionId",
        description="The revision (versions.id).",
    )
    version_label: str = Field(
        validation_alias=AliasChoices("versionLabel", "version_label"),
        serialization_alias="versionLabel",
        description="Its version label.",
    )
    role: Literal["base", "prior"] = Field(
        description="``base`` for the requested base; ``prior`` for an earlier revision a transitive check added."
    )


class EvaluatedUnderOut(BaseModel):
    """What a compatibility verdict was graded under."""

    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["BACKWARD", "FORWARD", "FULL", "NONE"] = Field(
        description="The compatibility mode requested, or the project's policy when the request named none."
    )
    transitive: bool = Field(
        description="Whether earlier revisions were checked too, not only the base."
    )
    category: Optional[Literal["WIRE", "WIRE_JSON", "PACKAGE", "FILE"]] = Field(
        default=None,
        description="The buf breaking category Protobuf changes were graded at; null when no Protobuf was compared.",
    )
    formats: List[str] = Field(
        default_factory=list, description="The source formats compared, e.g. ``avro`` or ``openapi``."
    )
    mode_applied: bool = Field(
        validation_alias=AliasChoices("modeApplied", "mode_applied"),
        serialization_alias="modeApplied",
        description=(
            "True when a mode-aware classifier (Avro, JSON Schema, AsyncAPI) graded the changes by "
            "``mode``. False means the format has no mode semantics and ``ruleset`` graded it."
        ),
    )
    category_applied: bool = Field(
        default=False,
        validation_alias=AliasChoices("categoryApplied", "category_applied"),
        serialization_alias="categoryApplied",
        description="True when Protobuf changes were graded at ``category``.",
    )
    ruleset: str = Field(
        description=(
            "The ruleset that graded the changes: a classifier id such as ``avro-compatibility`` or "
            "``buf-breaking``, ``builtin`` for the format-agnostic ruleset, or ``ctg`` for the "
            "OpenAPI change taxonomy."
        )
    )
    source: Dict[str, Literal["request", "policy"]] = Field(
        default_factory=dict,
        description="Where each of ``mode``, ``transitive`` and ``category`` came from.",
    )
    compared_revisions: List[ComparedRevisionOut] = Field(
        default_factory=list,
        validation_alias=AliasChoices("comparedRevisions", "compared_revisions"),
        serialization_alias="comparedRevisions",
        description="The stored revisions the head was compared against, base first.",
    )
    compared_revisions_truncated: bool = Field(
        default=False,
        validation_alias=AliasChoices("comparedRevisionsTruncated", "compared_revisions_truncated"),
        serialization_alias="comparedRevisionsTruncated",
        description="True when a transitive check stopped at its cap of earlier revisions.",
    )
