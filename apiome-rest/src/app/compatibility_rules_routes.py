"""``GET /v1/compatibility/rules`` — the published compatibility rule catalogue (XPC-4.5, #5749).

Every rule id the Avro, JSON Schema, Protobuf and AsyncAPI classifiers emit, with its severity per
compatibility mode (or per buf breaking category), its category and a description — the table
CDG-4's subject API, the docs and the UI render. The data is :mod:`app.compatibility_rule_catalogue`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_session_credentials
from .compatibility_policy import (
    COMPATIBILITY_MODES,
    DEFAULT_COMPATIBILITY_MODE,
    DEFAULT_PROTOBUF_CATEGORY,
    PROTOBUF_CATEGORIES,
)
from .compatibility_rule_catalogue import CatalogueEntry, entries_for_format

router = APIRouter(prefix="/v1/compatibility", tags=["compatibility"])


class CompatibilityRuleOut(BaseModel):
    """One rule in the catalogue."""

    model_config = ConfigDict(populate_by_name=True)

    rule_id: str = Field(
        serialization_alias="ruleId",
        description="The rule id; for a family (``isFamily: true``) the prefix every id in it starts with.",
    )
    is_family: bool = Field(
        default=False,
        serialization_alias="isFamily",
        description="True when ids in this family are built from a tool's own rule names.",
    )
    family: Literal["avro", "json-schema", "protobuf", "asyncapi"] = Field(
        description="The format family the rule belongs to."
    )
    formats: List[str] = Field(description="Every format key whose comparisons can emit the rule.")
    direction: Optional[str] = Field(
        default=None,
        description=(
            "What the rule breaks: ``backward`` / ``forward`` / ``either`` / ``review`` for data schemas, "
            "``consumer`` / ``producer`` / ``both`` for AsyncAPI; null for Protobuf."
        ),
    )
    severities: Optional[Dict[str, Literal["safe", "dangerous", "breaking"]]] = Field(
        default=None,
        description="Severity under each compatibility mode; null where modes do not apply (Protobuf).",
    )
    category: Optional[Literal["WIRE", "WIRE_JSON", "PACKAGE", "FILE"]] = Field(
        default=None,
        description="Protobuf only: the least strict buf category where the rule is at its worst.",
    )
    category_severities: Optional[Dict[str, Literal["safe", "dangerous", "breaking"]]] = Field(
        default=None,
        serialization_alias="categorySeverities",
        description="Protobuf only: severity under each buf breaking category.",
    )
    description: str = Field(description="What change the rule reports.")


class CompatibilityRuleCatalogueOut(BaseModel):
    """The rule catalogue, optionally narrowed to one format."""

    model_config = ConfigDict(populate_by_name=True)

    format: Optional[str] = Field(default=None, description="The ``?format=`` filter, when one was sent.")
    modes: List[str] = Field(description="The compatibility modes ``severities`` is keyed by.")
    categories: List[str] = Field(description="The buf breaking categories ``categorySeverities`` is keyed by.")
    defaults: Dict[str, Any] = Field(
        description="What a project gets without a policy: ``mode``, ``transitive`` and ``category``."
    )
    rules: List[CompatibilityRuleOut]


def rule_out(entry: CatalogueEntry) -> CompatibilityRuleOut:
    """Map a catalogue entry onto the response model."""
    return CompatibilityRuleOut(
        rule_id=entry.rule_id,
        is_family=entry.is_family,
        family=entry.family,  # type: ignore[arg-type]
        formats=list(entry.formats),
        direction=entry.direction,
        severities=entry.severities,  # type: ignore[arg-type]
        category=entry.category,  # type: ignore[arg-type]
        category_severities=entry.category_severities,  # type: ignore[arg-type]
        description=entry.description,
    )


@router.get("/rules", response_model=CompatibilityRuleCatalogueOut)
async def get_compatibility_rules(
    format: Optional[str] = Query(
        default=None,
        description=(
            "Narrow to one format family (``avro``, ``json-schema``, ``protobuf``, ``asyncapi``) or "
            "format key (``asyncapi-3``, ``jsonschema``). A format with no mode-aware rules returns "
            "an empty list."
        ),
    ),
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> CompatibilityRuleCatalogueOut:
    """List every compatibility rule id with its severity per mode, category and description.

    The same table the Compatibility modes docs page is generated from. Rules are grouped by
    family (Avro, JSON Schema, Protobuf, AsyncAPI) and sorted by id within each. Static reference
    data, identical for every tenant, so no tenant is named; ``diff:read`` and ``registry:read``
    API keys may call it.
    """
    _ = auth_data
    return CompatibilityRuleCatalogueOut(
        format=(format or "").strip() or None,
        modes=list(COMPATIBILITY_MODES),
        categories=list(PROTOBUF_CATEGORIES),
        defaults={
            "mode": DEFAULT_COMPATIBILITY_MODE,
            "transitive": False,
            "category": DEFAULT_PROTOBUF_CATEGORY,
        },
        rules=[rule_out(e) for e in entries_for_format(format)],
    )
