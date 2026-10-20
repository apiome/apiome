"""Wire models for the Backstage and Compass import — CDG-5.5 (#5983).

Shared by :mod:`app.catalog_migration_store` (which builds them) and
:mod:`app.catalog_migration_routes` (which serves them). JSON is camelCase.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .entity_owners import EntityOwnerRef

__all__ = [
    "CODE_COMPONENT_NOT_FOUND",
    "CODE_DECIDED",
    "CODE_INVALID",
    "CODE_RUN_NOT_FOUND",
    "CODE_SLUG_TAKEN",
    "CODE_SUGGESTION_NOT_FOUND",
    "CODE_TOO_LARGE",
    "AcceptInput",
    "CompassUploadInput",
    "ComponentLink",
    "ComponentOut",
    "MigrationError",
    "MigrationRun",
    "MigrationRunList",
    "MigrationSuggestion",
    "UnmappedFieldOut",
]

CODE_INVALID = "migration-invalid"
CODE_TOO_LARGE = "migration-too-large"
CODE_RUN_NOT_FOUND = "migration-not-found"
CODE_SUGGESTION_NOT_FOUND = "migration-suggestion-not-found"
CODE_DECIDED = "migration-suggestion-decided"
CODE_SLUG_TAKEN = "migration-slug-taken"
CODE_COMPONENT_NOT_FOUND = "component-not-found"


class MigrationError(ValueError):
    """A refusal with a stable code (one of the ``CODE_*`` constants).

    Attributes:
        code: The machine code.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CompassUploadInput(_CamelModel):
    """An uploaded Compass export."""

    filename: str = Field(default="compass-export.json", min_length=1, max_length=255)
    content: str = Field(description="The export's JSON text, as uploaded.", max_length=5 * 1024 * 1024 + 1)


class AcceptInput(_CamelModel):
    """Overrides for accepting a suggestion; everything defaults to what the import read."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=128)
    as_component: bool = Field(
        default=False,
        description="For a component matched to an existing Project or catalog item: register it as a "
        "component of its own instead of applying it to the match.",
    )


class UnmappedFieldOut(_CamelModel):
    """A field the import read but could not map. Values are never stored."""

    entity: str
    field: str
    reason: str


class ComponentLink(_CamelModel):
    """A component's link."""

    type: Literal["chat", "on_call", "document", "repository", "dashboard", "other"]
    url: str
    title: Optional[str] = None


class MigrationSuggestion(_CamelModel):
    """One staged component or team."""

    id: str
    kind: Literal["component", "team"]
    source: Literal["backstage", "compass"]
    external_ref: str = Field(description="Its reference in its own catalog.")
    name: str
    slug: str
    status: Literal["suggested", "accepted", "dismissed"]
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="What accepting writes: description, category, type, links, ownerRef, references "
        "(components); description, contactEmail, chatUrl, oncallUrl, docsUrl (teams).",
    )
    match: Optional[Dict[str, Any]] = Field(
        default=None, description="`{kind, id, name, slug}` of the Project or catalog item the component already is."
    )
    entity: Optional[Dict[str, Any]] = Field(
        default=None, description="`{kind, id, slug}` of what accepting made or applied to."
    )
    decided_at: Optional[str] = None


class MigrationRun(_CamelModel):
    """One import report."""

    id: str
    source: Literal["backstage", "compass"]
    label: str
    repository_id: Optional[str] = None
    branch: Optional[str] = None
    counts: Dict[str, int] = Field(default_factory=dict)
    unmapped: List[UnmappedFieldOut] = Field(default_factory=list)
    unmapped_total: int = 0
    pending: int = Field(default=0, description="Suggestions still waiting for a decision.")
    suggestions: Optional[List[MigrationSuggestion]] = Field(
        default=None, description="Present on a single report's read."
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MigrationRunList(_CamelModel):
    """Every import report of a tenant, newest first."""

    runs: List[MigrationRun]


class ComponentOut(_CamelModel):
    """An accepted component (the ``component`` entity kind)."""

    id: str
    slug: str
    name: str
    description: Optional[str] = None
    category: Literal["component", "system", "domain"]
    component_type: Optional[str] = None
    lifecycle: Optional[str] = None
    parent_ref: Optional[str] = None
    links: List[ComponentLink] = Field(default_factory=list)
    source: Literal["backstage", "compass"]
    external_ref: str
    owner: Optional[EntityOwnerRef] = Field(
        default=None, description="The confirmed owner, else the oldest suggestion."
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
