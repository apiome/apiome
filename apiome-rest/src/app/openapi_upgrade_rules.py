"""The change vocabulary of the OpenAPI upgrade assistant — COA-2.6 (#7049).

An upgrade plan (:mod:`app.openapi_upgrade`) is a list of :class:`UpgradeChange` records, one
per rewrite the assistant makes, each naming the **rule** that made it. This module holds that
record, the :class:`ChangeLog` the hops append to, and :data:`UPGRADE_RULES` — the catalog of
every rule with a title and a one-line description. The catalog is what the REST response, the
CLI table, the UI dialog and the docs page group a plan by; a test keeps the docs page and the
catalog in step, and another fails if a hop records a rule the catalog does not name.

Everything here is pure data: no I/O, no mutation of the documents being upgraded.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "HOP_20_30",
    "HOP_30_31",
    "HOP_31_32",
    "UPGRADE_RULES",
    "ChangeLog",
    "UpgradeChange",
    "UpgradeRule",
]

#: Hop labels, in upgrade order. A plan from 2.0 to 3.2 runs all three.
HOP_20_30 = "2.0→3.0"
HOP_30_31 = "3.0→3.1"
HOP_31_32 = "3.1→3.2"


@dataclass(frozen=True)
class UpgradeRule:
    """One kind of rewrite the assistant can make.

    Attributes:
        rule: Stable kebab-case id (``nullable-to-type-array``).
        hop: The hop that applies it (:data:`HOP_20_30`, …).
        title: Short label for tables and the UI.
        description: One sentence on what the rewrite does.
    """

    rule: str
    hop: str
    title: str
    description: str


def _rules(*rules: UpgradeRule) -> Dict[str, UpgradeRule]:
    return {item.rule: item for item in rules}


#: Every rule a hop may record, keyed by id. Order is the order the docs page lists them in.
UPGRADE_RULES: Dict[str, UpgradeRule] = _rules(
    # -- every hop ------------------------------------------------------------------------
    UpgradeRule("openapi-version", "*", "Version string", "The `swagger` / `openapi` field names the new version."),
    # -- Swagger 2.0 → OpenAPI 3.0 --------------------------------------------------------
    UpgradeRule(
        "servers-from-host",
        HOP_20_30,
        "host → servers",
        "`host`, `basePath` and `schemes` become one `servers` entry per scheme.",
    ),
    UpgradeRule(
        "operation-schemes-to-servers",
        HOP_20_30,
        "Operation schemes → servers",
        "An operation's own `schemes` become that operation's `servers`.",
    ),
    UpgradeRule(
        "global-media-types",
        HOP_20_30,
        "consumes / produces removed",
        "Document-level `consumes` / `produces` are folded into each request body and response `content`.",
    ),
    UpgradeRule(
        "definition-to-component-schema",
        HOP_20_30,
        "definitions → components.schemas",
        "Each entry of `definitions` moves to `components.schemas`.",
    ),
    UpgradeRule(
        "parameter-to-component",
        HOP_20_30,
        "parameters → components.parameters",
        "Each reusable non-body parameter moves to `components.parameters`.",
    ),
    UpgradeRule(
        "body-parameter-inlined",
        HOP_20_30,
        "Reusable body / formData parameter inlined",
        "A reusable `body` or `formData` parameter has no 3.0 component; each operation that used it "
        "gets it inlined in its `requestBody`.",
    ),
    UpgradeRule(
        "response-to-component",
        HOP_20_30,
        "responses → components.responses",
        "Each reusable response moves to `components.responses`.",
    ),
    UpgradeRule(
        "security-definition-to-scheme",
        HOP_20_30,
        "securityDefinitions → securitySchemes",
        "Each security definition moves to `components.securitySchemes` "
        "(`basic` → `http`/`basic`, OAuth 2 `flow` → `flows`).",
    ),
    UpgradeRule(
        "ref-rewritten",
        HOP_20_30,
        "$ref rewritten",
        "A `#/definitions/`, `#/parameters/` or `#/responses/` reference points at its `#/components/…` home.",
    ),
    UpgradeRule(
        "parameter-type-to-schema",
        HOP_20_30,
        "Parameter type → schema",
        "A parameter's or header's inline `type`, `format`, `items`, `enum` … keywords move into a `schema`.",
    ),
    UpgradeRule(
        "collection-format-to-style",
        HOP_20_30,
        "collectionFormat → style / explode",
        "An array parameter's `collectionFormat` (default `csv`) becomes the matching `style` and `explode`.",
    ),
    UpgradeRule(
        "body-to-request-body",
        HOP_20_30,
        "body parameter → requestBody",
        "The `in: body` parameter becomes `requestBody`, one `content` entry per `consumes` media type.",
    ),
    UpgradeRule(
        "form-data-to-request-body",
        HOP_20_30,
        "formData parameters → requestBody",
        "`in: formData` parameters become one object schema under a form `requestBody`.",
    ),
    UpgradeRule(
        "response-schema-to-content",
        HOP_20_30,
        "Response schema → content",
        "A response's `schema` moves under `content`, one entry per `produces` media type.",
    ),
    UpgradeRule(
        "response-examples-to-content",
        HOP_20_30,
        "Response examples → content example",
        "A response's `examples` map (media type → value) becomes each media type's `example`.",
    ),
    UpgradeRule(
        "file-to-binary",
        HOP_20_30,
        "type: file → binary string",
        "`type: file` becomes `type: string, format: binary`.",
    ),
    UpgradeRule(
        "x-nullable-to-nullable",
        HOP_20_30,
        "x-nullable → nullable",
        "The common `x-nullable` extension becomes the 3.0 `nullable` keyword.",
    ),
    UpgradeRule(
        "discriminator-to-object",
        HOP_20_30,
        "discriminator → object",
        "A Swagger `discriminator` property name becomes `discriminator: {propertyName}`.",
    ),
    # -- OpenAPI 3.0 → 3.1 ----------------------------------------------------------------
    UpgradeRule(
        "nullable-to-type-array",
        HOP_30_31,
        "nullable → type array",
        '`nullable: true` adds `"null"` to `type` (and `null` to `enum`).',
    ),
    UpgradeRule(
        "nullable-to-any-of",
        HOP_30_31,
        "nullable → anyOf null",
        '`nullable: true` on a schema with no `type` wraps it in `anyOf: [<schema>, {type: "null"}]`.',
    ),
    UpgradeRule(
        "nullable-ref",
        HOP_30_31,
        "nullable next to $ref",
        "OpenAPI 3.0 ignored `nullable` next to `$ref`; the 3.1 form makes the reference accept `null` too. Review it.",
    ),
    UpgradeRule(
        "nullable-false-removed",
        HOP_30_31,
        "nullable: false removed",
        "`nullable: false` is the default and has no 3.1 keyword; it is removed.",
    ),
    UpgradeRule(
        "exclusive-bound-numeric",
        HOP_30_31,
        "Exclusive bound → number",
        "`exclusiveMinimum: true` + `minimum: n` becomes `exclusiveMinimum: n` (same for maximum).",
    ),
    UpgradeRule(
        "exclusive-flag-removed",
        HOP_30_31,
        "Exclusive flag removed",
        "A boolean `exclusiveMinimum` / `exclusiveMaximum` with no effect (false, or no bound) is removed.",
    ),
    UpgradeRule(
        "example-to-examples",
        HOP_30_31,
        "example → examples",
        "A schema's `example` becomes a one-item `examples` array (the JSON Schema 2020-12 keyword).",
    ),
)


@dataclass(frozen=True)
class UpgradeChange:
    """One rewrite in an upgrade plan.

    Attributes:
        hop: The hop that made it (:data:`HOP_20_30`, :data:`HOP_30_31`, :data:`HOP_31_32`).
        rule: The :data:`UPGRADE_RULES` id.
        pointer: JSON Pointer (RFC 6901, escaped, no ``#``) of the object changed, in the document
            as it entered the hop. ``""`` is the document root.
        summary: One human sentence naming what changed at ``pointer``.
        before: The keywords as they were (a small fragment, never the whole document).
        after: The keywords as they are now.
        target_pointer: Where the object lives after the hop when it moved (``/definitions/Pet`` →
            ``/components/schemas/Pet``); ``None`` when it stayed put.
        review: True when the rewrite may change what the document means and a person should look.
    """

    hop: str
    rule: str
    pointer: str
    summary: str
    before: Any = None
    after: Any = None
    target_pointer: Optional[str] = None
    review: bool = False

    def as_dict(self) -> Dict[str, Any]:
        """The change as a JSON-ready mapping (the REST and CLI shape)."""
        return {
            "hop": self.hop,
            "rule": self.rule,
            "title": UPGRADE_RULES[self.rule].title,
            "pointer": self.pointer,
            "target_pointer": self.target_pointer,
            "summary": self.summary,
            "before": self.before,
            "after": self.after,
            "review": self.review,
        }


@dataclass
class ChangeLog:
    """Collects the :class:`UpgradeChange` records of one hop, in the order they are made.

    Attributes:
        hop: The hop every recorded change belongs to.
        changes: The records so far.
    """

    hop: str
    changes: List[UpgradeChange] = field(default_factory=list)

    def record(
        self,
        rule: str,
        pointer: str,
        summary: str,
        *,
        before: Any = None,
        after: Any = None,
        target_pointer: Optional[str] = None,
        review: bool = False,
    ) -> None:
        """Append one change.

        Args:
            rule: A :data:`UPGRADE_RULES` id.
            pointer: Escaped JSON Pointer of the changed object in the hop's input document.
            summary: One sentence on what changed.
            before: The keywords before (deep-copied so later rewrites cannot alter the record).
            after: The keywords after (deep-copied).
            target_pointer: The object's new pointer when it moved.
            review: Whether a person should check the rewrite.

        Raises:
            KeyError: When ``rule`` is not in :data:`UPGRADE_RULES` (a programming error).
        """
        if rule not in UPGRADE_RULES:
            raise KeyError(f"unknown upgrade rule {rule!r}")
        self.changes.append(
            UpgradeChange(
                hop=self.hop,
                rule=rule,
                pointer=pointer,
                summary=summary,
                before=copy.deepcopy(before),
                after=copy.deepcopy(after),
                target_pointer=target_pointer,
                review=review,
            )
        )
