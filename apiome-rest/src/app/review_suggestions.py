"""Suggested changes on a review — COL-4.2 (#4526): codes, refusal, and models.

A **suggestion** is a reviewer's concrete edit to one class or property of the version under
review: an RFC 6902 patch (:mod:`app.suggestion_patch`) over the element's canonical JSON —
``{"description", "schema"}`` for a class, ``{"description", "data"}`` for a property. The author
applies or rejects it in one click; applying merges it onto the element as it is now with the
merge-session engine, so an edit made since is merged around or reported (``stale``), never
silently overwritten. Storage is apiome-db V376.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_FORBIDDEN",
    "CODE_INVALID_PATCH",
    "CODE_NOT_OPEN",
    "CODE_STALE",
    "CODE_SUGGESTION_NOT_FOUND",
    "CODE_TARGET_NOT_FOUND",
    "ELEMENT_FIELDS",
    "MAX_NOTE_LENGTH",
    "SuggestionApplyResult",
    "SuggestionCreate",
    "SuggestionDecision",
    "SuggestionRecord",
    "SuggestionStatus",
    "SuggestionTargetType",
    "SuggestionValidationError",
]

CODE_SUGGESTION_NOT_FOUND = "suggestion-not-found"
CODE_FORBIDDEN = "suggestion-forbidden"
CODE_NOT_OPEN = "suggestion-not-open"
CODE_STALE = "suggestion-stale"
CODE_INVALID_PATCH = "suggestion-invalid-patch"
CODE_TARGET_NOT_FOUND = "suggestion-target-not-found"

#: The longest note or rejection reason. Mirrors V376's checks.
MAX_NOTE_LENGTH = 5_000

SuggestionTargetType = Literal["class", "property"]
SuggestionStatus = Literal["open", "applied", "rejected", "stale"]

#: The keys of each element's canonical JSON; a patch may change their values, never the set.
ELEMENT_FIELDS: Dict[str, tuple] = {
    "class": ("description", "schema"),
    "property": ("description", "data"),
}


class SuggestionValidationError(Exception):
    """A suggestion request refused, carrying a stable ``code`` (and conflict paths when stale)."""

    def __init__(self, code: str, message: str, conflict_paths: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.conflict_paths = list(conflict_paths or [])


class SuggestionCreate(BaseModel):
    """A reviewer's proposed edit."""

    model_config = ConfigDict(extra="forbid")

    target_type: SuggestionTargetType = Field(description="`class` or `property`.")
    target_id: str = Field(description="The class or class-property id, in the reviewed version.")
    patch: List[Dict[str, Any]] = Field(
        min_length=1,
        max_length=50,
        description=(
            "RFC 6902 operations (`add`, `remove`, `replace`, `test`) over the element's canonical "
            "JSON — `{description, schema}` for a class, `{description, data}` for a property."
        ),
    )
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH, description="Why.")


class SuggestionDecision(BaseModel):
    """An optional reason recorded with a rejection."""

    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)


class SuggestionRecord(BaseModel):
    """One stored suggestion."""

    model_config = ConfigDict(extra="forbid")

    id: str
    review_id: str
    version_id: str
    author_id: Optional[str] = Field(default=None, description="Who proposed it.")
    author_name: Optional[str] = None
    target_type: SuggestionTargetType
    target_id: str
    target_label: str = Field(description="`Pet` for a class, `Pet.name` for a property.")
    note: Optional[str] = None
    base: Dict[str, Any] = Field(description="The element when the suggestion was made.")
    patch: List[Dict[str, Any]]
    proposed: Dict[str, Any] = Field(description="`base` with `patch` applied — what the author sees as the diff.")
    status: SuggestionStatus
    conflict_paths: List[str] = Field(default_factory=list, description="Why it went stale.")
    stale: bool = Field(
        default=False,
        description=(
            "For an open suggestion: true when the element changed since it was made in a way that "
            "overlaps it, so applying would conflict. Always false once decided."
        ),
    )
    decided_by: Optional[str] = None
    decided_by_name: Optional[str] = None
    decided_at: Optional[datetime] = None
    reason: Optional[str] = None
    created_at: datetime


class SuggestionApplyResult(BaseModel):
    """The outcome of applying a suggestion."""

    model_config = ConfigDict(extra="forbid")

    suggestion: SuggestionRecord
    element: Dict[str, Any] = Field(description="The element as written.")
    merged_around: bool = Field(
        description="True when the element had other edits since the suggestion, which were kept."
    )
