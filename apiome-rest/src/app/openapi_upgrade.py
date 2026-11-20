"""OpenAPI spec upgrade assistant: plan, then apply — COA-2.6 (#7049).

A user holding a Swagger 2.0 or OpenAPI 3.0 document gets a guided upgrade to 3.0, 3.1 or 3.2.
:func:`plan_upgrade` runs the hops between the document's version and the target, one after
another, and returns an :class:`UpgradePlan`: the upgraded document plus **every** rewrite the
hops made (:class:`~app.openapi_upgrade_rules.UpgradeChange`), each naming its rule, the
object it touched and what it looked like before and after. Nothing is written; applying the
plan (the REST ``…/apply`` route, :mod:`app.openapi_upgrade_routes`) re-runs it and stores the
result as a new version.

The hops:

* **2.0 → 3.0** — the structural rewrite (:mod:`app.openapi_upgrade_swagger2`).
* **3.0 → 3.1** — schemas move from the 3.0 dialect to JSON Schema 2020-12: ``nullable`` →
  ``type`` arrays (or ``anyOf`` with ``null``), boolean ``exclusiveMinimum`` /
  ``exclusiveMaximum`` → numbers, schema ``example`` → ``examples``
  (:func:`app.openapi_source_preservation.upgrade_schema_30_to_31` does the first two).
* **3.1 → 3.2** — the version string; every 3.1 document is a valid 3.2 document.

**Every change is listed.** :func:`unlisted_changes` compares each hop's input and output with
:func:`app.openapi_schema_dialect.changed_objects` and returns any changed object no record
covers; the tests hold it empty on the corpus. **The upgrade reverses.** :func:`downgrade_to_family`
takes an upgraded document back to the source family with the existing downgrades
(:mod:`app.openapi_downgrade`); the corpus tests check that the result matches the original.

Pure and deterministic: inputs are never mutated, and the same document and target always give
the same plan and the same :attr:`UpgradePlan.plan_digest`.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .emitter import LossTracker
from .openapi_document_walk import walk_document
from .openapi_downgrade import downgrade_remaining_schemas_30, downgrade_to_openapi_30, downgrade_to_swagger_2
from .openapi_schema_dialect import changed_objects
from .openapi_source_preservation import upgrade_schema_30_to_31
from .openapi_upgrade_rules import HOP_20_30, HOP_30_31, HOP_31_32, UPGRADE_RULES, ChangeLog, UpgradeChange
from .openapi_upgrade_swagger2 import upgrade_swagger2_to_30

__all__ = [
    "FAMILIES",
    "TARGET_VERSIONS",
    "UpgradeError",
    "UpgradePlan",
    "document_digest",
    "document_family",
    "downgrade_to_family",
    "plan_upgrade",
    "unlisted_changes",
]

#: Version families in upgrade order.
FAMILIES: Tuple[str, ...] = ("2.0", "3.0", "3.1", "3.2")

#: The version string each target family is written as (the latest patch release).
TARGET_VERSIONS: Dict[str, str] = {"3.0": "3.0.4", "3.1": "3.1.2", "3.2": "3.2.0"}

#: The hop that leaves each family.
_HOP_FROM: Dict[str, str] = {"2.0": HOP_20_30, "3.0": HOP_30_31, "3.1": HOP_31_32}


class UpgradeError(ValueError):
    """A document or target the assistant cannot plan for.

    Attributes:
        code: ``not-openapi`` (no ``swagger`` / ``openapi`` field), ``unsupported-version`` (a
            version outside 2.0–3.2) or ``target-older`` (the target is older than the document;
            use a downgrade export instead) or ``unknown-target``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class UpgradePlan:
    """A reviewed upgrade, before it is applied.

    Attributes:
        source_version: The document's declared version (``2.0``, ``3.0.3`` …).
        source_family: Its family (:data:`FAMILIES`).
        target: The target family.
        target_version: The version string the upgraded document declares.
        hops: The hops run, in order (empty when the document is already at the target family).
        changes: Every rewrite, in hop order then document order.
        document: The upgraded document.
        source_digest: :func:`document_digest` of the input document.
        plan_digest: Digest of (source digest, target, upgraded document); ``apply`` refuses a
            plan whose digest no longer matches what the source plans to now.
    """

    source_version: str
    source_family: str
    target: str
    target_version: str
    hops: List[str]
    changes: List[UpgradeChange]
    document: Dict[str, Any]
    source_digest: str
    plan_digest: str
    hop_inputs: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = field(default_factory=list, repr=False)

    @property
    def already_current(self) -> bool:
        """True when the document is already in the target family (nothing to upgrade)."""
        return not self.hops

    @property
    def review_count(self) -> int:
        """How many changes a person should check (``review``)."""
        return sum(1 for change in self.changes if change.review)

    def rule_counts(self) -> List[Dict[str, Any]]:
        """Changes per rule, in :data:`UPGRADE_RULES` order: ``[{rule, title, hop, count}]``."""
        counts: Dict[str, int] = {}
        for change in self.changes:
            counts[change.rule] = counts.get(change.rule, 0) + 1
        return [
            {"rule": rule, "title": spec.title, "hop": spec.hop, "count": counts[rule]}
            for rule, spec in UPGRADE_RULES.items()
            if rule in counts
        ]

    def as_dict(self, *, include_document: bool = True) -> Dict[str, Any]:
        """The plan as a JSON-ready mapping (the REST / CLI shape)."""
        out: Dict[str, Any] = {
            "source_version": self.source_version,
            "source_family": self.source_family,
            "target": self.target,
            "target_version": self.target_version,
            "hops": list(self.hops),
            "already_current": self.already_current,
            "change_count": len(self.changes),
            "review_count": self.review_count,
            "rules": self.rule_counts(),
            "changes": [change.as_dict() for change in self.changes],
            "source_digest": self.source_digest,
            "plan_digest": self.plan_digest,
        }
        if include_document:
            out["document"] = self.document
        return out


def document_digest(document: Any) -> str:
    """A stable SHA-256 digest of a JSON value (sorted keys, compact separators)."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_family(document: Any) -> Tuple[str, str]:
    """The declared version of an OpenAPI / Swagger document and its family.

    Args:
        document: A parsed document.

    Returns:
        ``(declared_version, family)``.

    Raises:
        UpgradeError: ``not-openapi`` when neither ``swagger`` nor ``openapi`` is declared;
            ``unsupported-version`` for any other version.
    """
    if not isinstance(document, dict):
        raise UpgradeError("not-openapi", "The document is not an OpenAPI or Swagger object.")
    if "swagger" in document:
        declared = str(document.get("swagger"))
        if declared in ("2", "2.0"):
            return declared, "2.0"
        raise UpgradeError("unsupported-version", f"Swagger {declared} is not supported; only Swagger 2.0 is.")
    if "openapi" in document:
        declared = str(document.get("openapi"))
        for family in ("3.0", "3.1", "3.2"):
            if declared == family or declared.startswith(family + "."):
                return declared, family
        raise UpgradeError("unsupported-version", f"OpenAPI {declared} is not supported; 3.0, 3.1 and 3.2 are.")
    raise UpgradeError(
        "not-openapi", "The document declares neither swagger nor openapi; it is not an OpenAPI document."
    )


def plan_upgrade(document: Dict[str, Any], target: str) -> UpgradePlan:
    """Plan the upgrade of ``document`` to the ``target`` family.

    Args:
        document: A parsed Swagger 2.0 or OpenAPI 3.x document (not mutated).
        target: ``3.0``, ``3.1`` or ``3.2``.

    Returns:
        The :class:`UpgradePlan`. A document already in the target family gets a plan with no
        hops and no changes (``already_current``).

    Raises:
        UpgradeError: ``unknown-target``, ``not-openapi``, ``unsupported-version`` or
            ``target-older``.
    """
    if target not in TARGET_VERSIONS:
        raise UpgradeError("unknown-target", f"Target {target!r} is not one of {', '.join(TARGET_VERSIONS)}.")
    declared, family = document_family(document)
    if FAMILIES.index(target) < FAMILIES.index(family):
        raise UpgradeError(
            "target-older",
            f"The document is OpenAPI {declared}; {target} is older. Export it at {target} to downgrade instead.",
        )
    current = copy.deepcopy(document)
    hops: List[str] = []
    changes: List[UpgradeChange] = []
    hop_inputs: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    while FAMILIES.index(family) < FAMILIES.index(target):
        hop = _HOP_FROM[family]
        log = ChangeLog(hop)
        before = current
        if hop == HOP_20_30:
            current = upgrade_swagger2_to_30(before, log)
        elif hop == HOP_30_31:
            current = _upgrade_30_to_31(before, log)
        else:
            current = _upgrade_31_to_32(before, log)
        hops.append(hop)
        changes.extend(log.changes)
        hop_inputs.append((hop, before, current))
        family = FAMILIES[FAMILIES.index(family) + 1]
    if hops:
        # The 2.0 → 3.0 hop writes 3.0.4; a plan that stops at 3.0 says so already, others re-stamp.
        current["openapi"] = TARGET_VERSIONS[target]
    source_digest = document_digest(document)
    return UpgradePlan(
        source_version=declared,
        source_family=document_family(document)[1],
        target=target,
        target_version=str(current.get("openapi", declared)) if hops else declared,
        hops=hops,
        changes=changes,
        document=current,
        source_digest=source_digest,
        plan_digest=document_digest({"source": source_digest, "target": target, "document": current}),
        hop_inputs=hop_inputs,
    )


# =======================================================================================
# 3.0 → 3.1
# =======================================================================================


def _upgrade_30_to_31(document: Dict[str, Any], log: ChangeLog) -> Dict[str, Any]:
    """Return a 3.1 copy of an OpenAPI 3.0 document, recording each schema rewrite."""
    out = copy.deepcopy(document)
    _record_version(log, out, TARGET_VERSIONS["3.1"])
    out["openapi"] = TARGET_VERSIONS["3.1"]
    for node in walk_document(out):
        if node.kind == "schema":
            _upgrade_schema(node.value, node.pointer, log)
    return out


def _upgrade_schema(schema: Dict[str, Any], pointer: str, log: ChangeLog) -> None:
    """Rewrite one 3.0 Schema Object's own keywords to 2020-12 in place, recording each rule."""
    before = copy.deepcopy(schema)
    if "example" in schema and "examples" not in schema:
        value = schema.pop("example")
        schema["examples"] = [value]
        log.record(
            "example-to-examples",
            pointer,
            "example becomes a one-item examples array",
            before={"example": value},
            after={"examples": [value]},
        )
    nullable = before.get("nullable")
    upgrade_schema_30_to_31(schema)
    if nullable is True:
        if "$ref" in before:
            log.record(
                "nullable-ref",
                pointer,
                "nullable: true next to $ref (ignored by 3.0) now lets the reference accept null",
                before={"$ref": before["$ref"], "nullable": True},
                after=_pick(schema, "anyOf"),
                review=True,
            )
        elif "type" in before:
            log.record(
                "nullable-to-type-array",
                pointer,
                f"nullable: true becomes type {json.dumps(schema.get('type'))}",
                before=_pick(before, "type", "nullable", "enum"),
                after=_pick(schema, "type", "enum"),
            )
        else:
            log.record(
                "nullable-to-any-of",
                pointer,
                "nullable: true on a schema with no type becomes anyOf [schema, {type: null}]",
                before={"nullable": True},
                after={"anyOf": '[<schema>, {"type": "null"}]'},
            )
    elif nullable is not None:
        log.record(
            "nullable-false-removed", pointer, "nullable: false (the default) is removed", before={"nullable": nullable}
        )
    for exclusive, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        value = before.get(exclusive)
        if not isinstance(value, bool):
            continue
        if value and isinstance(before.get(bound), (int, float)):
            log.record(
                "exclusive-bound-numeric",
                pointer,
                f"{exclusive}: true with {bound}: {before[bound]} becomes {exclusive}: {before[bound]}",
                before=_pick(before, exclusive, bound),
                after=_pick(schema, exclusive, bound),
            )
        else:
            reason = "false is the default" if not value else f"there is no {bound}"
            log.record(
                "exclusive-flag-removed",
                pointer,
                f"{exclusive}: {str(value).lower()} is removed ({reason})",
                before={exclusive: value},
            )


def _pick(mapping: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """The given keys of ``mapping`` that are present."""
    return {key: mapping[key] for key in keys if key in mapping}


# =======================================================================================
# 3.1 → 3.2
# =======================================================================================


def _upgrade_31_to_32(document: Dict[str, Any], log: ChangeLog) -> Dict[str, Any]:
    """Return a 3.2 copy of an OpenAPI 3.1 document (3.2 is a superset; only the version changes)."""
    out = copy.deepcopy(document)
    _record_version(log, out, TARGET_VERSIONS["3.2"])
    out["openapi"] = TARGET_VERSIONS["3.2"]
    return out


def _record_version(log: ChangeLog, document: Dict[str, Any], version: str) -> None:
    """Record the ``openapi`` version-string change of one hop."""
    log.record(
        "openapi-version",
        "/openapi",
        f"openapi {document.get('openapi')} becomes {version}",
        before={"openapi": document.get("openapi")},
        after={"openapi": version},
    )


# =======================================================================================
# Checks: every change listed, and the upgrade reverses
# =======================================================================================


def unlisted_changes(plan: UpgradePlan) -> List[str]:
    """Pointers of objects a hop changed that no change record covers (empty when complete).

    A record covers a changed object when its ``pointer`` (or ``target_pointer``) is the object,
    an ancestor of it, or inside it. The 2.0 → 3.0 hop restructures the whole document, so it is
    checked by the round-trip test instead and skipped here.

    Args:
        plan: A plan from :func:`plan_upgrade`.

    Returns:
        ``"<hop> <pointer>"`` strings for every unlisted change.
    """
    missing: List[str] = []
    for hop, before, after in plan.hop_inputs:
        if hop == HOP_20_30:
            continue
        covered = [c.pointer for c in plan.changes if c.hop == hop]
        covered += [c.target_pointer for c in plan.changes if c.hop == hop and c.target_pointer]
        for pointer in changed_objects(before, after):
            if not any(
                pointer == target or pointer.startswith(target + "/") or target.startswith(pointer + "/")
                for target in covered
            ):
                missing.append(f"{hop} {pointer}")
    return missing


def downgrade_to_family(document: Dict[str, Any], family: str) -> Tuple[Dict[str, Any], LossTracker]:
    """Take an upgraded 3.1 / 3.2 document back to ``family`` with the existing downgrades.

    Used to show the upgrade reverses (the COA-2.6 acceptance criterion): for a 3.0 source the
    3.0 downgrade (plus :func:`downgrade_remaining_schemas_30` for schemas outside the paths and
    component schemas); for a 2.0 source the Swagger 2.0 downgrade; for 3.1 the 3.2 document
    with its version string set back (3.2 added nothing the upgrade wrote).

    Args:
        document: An upgraded document (3.1 or 3.2).
        family: The family to go back to (``2.0``, ``3.0`` or ``3.1``).

    Returns:
        ``(document, losses)`` — the losses the downgrade recorded.
    """
    losses = LossTracker()
    if family == "3.0":
        result = downgrade_to_openapi_30(document, losses)
        downgrade_remaining_schemas_30(result, losses)
        return result, losses
    if family == "2.0":
        return downgrade_to_swagger_2(document, losses), losses
    result = copy.deepcopy(document)
    result["openapi"] = TARGET_VERSIONS["3.1"]
    return result, losses
