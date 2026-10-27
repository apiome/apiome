"""OData breaking-change classifier — MFI-11.5 (#3780).

OData defines its own compatibility contract: *OData Version 4.01 Part 1: Protocol*, §5.2 **Model
Versioning** (https://docs.oasis-open.org/odata/odata/v4.01/odata-v4.01-part1-protocol.html#sec_ModelVersioning)
lists the model changes a service may make without a new version — adding a property that is
nullable or has a default value, a navigation property that is nullable or collection-valued, a new
type, entity set, singleton, operation or import, a type definition or enumeration, a term, an
annotation. Every other change, such as removing a property or changing its type, is breaking, and
a service that makes one should version its metadata with the ``Core.SchemaVersion`` annotation, so
that clients pinned to the old version ask for it with ``$schemaversion``.

The format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) already
grades removals as breaking and new types / entity sets as safe. This classifier sharpens the rest:

==========================================  ==========  ==============================================
Rule                                        Severity    When
==========================================  ==========  ==============================================
``odata.property-added-nullable``           safe        a new nullable property (§5.2)
``odata.property-added-with-default``       safe        a new non-nullable property with a default
``odata.property-added-required``           breaking    a new non-nullable property with no default
``odata.property-type-changed``             breaking    a property's type changed
``odata.property-made-non-nullable``        breaking    a nullable property became non-nullable
``odata.property-made-nullable``            dangerous   a non-nullable property became nullable
``odata.key-changed``                       breaking    an entity type's key changed
``odata.navigation-added``                  safe        a new collection-valued or nullable navigation
``odata.navigation-added-required``         breaking    a new single-valued, non-nullable navigation
``odata.navigation-added-unknown``          dangerous   a new single-valued navigation whose
                                                        nullability the model does not record
``odata.navigation-removed``                breaking    a navigation property is gone
``odata.navigation-type-changed``           breaking    a navigation property's target type changed
``odata.navigation-partner-changed``        dangerous   a navigation property's partner changed
``odata.annotation-added``                  safe        annotations were only added (§5.2)
``odata.annotation-changed``                dangerous   an annotation was changed or removed
==========================================  ==========  ==============================================

**``$schemaversion``.** The schema version a v4 document declares (``@Core.SchemaVersion`` on its
schema, read from the model's canonical CSDL JSON) is compared across the diff. Every *breaking*
grade's rationale then says whether the version moved — ``Core.SchemaVersion moved from "1" to "2"``
(clients pinned with ``$schemaversion=1`` keep the old model) — or not, in which case §5.2's advice
to version the metadata is quoted. The grade itself is unchanged: the version tells clients how to
cope with a break, it does not undo it.

Facts the canonical model does not carry — a property's ``$DefaultValue``, a v4 navigation
property's ``$Nullable``, the schema version — are read from the target model's canonical CSDL JSON
(``raw["csdl_json"]``, v4 only) when it is present. v2/v3 navigation nullability comes from the
association end's multiplicity (``0..1`` / ``1`` / ``*``). Operation parameter rules of §5.2 are not
graded here: the canonical model does not carry v4 action / function parameters.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    _assemble_result,
    _worst,
)
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange, ModelDiff

__all__ = ["ODataBreakingChangeClassifier", "schema_versions"]

_FORMAT_KEY = "odata"

#: A grade: ``(severity, rule_id, rationale)``.
Grade = Tuple[Severity, str, str]

_SCHEMA_VERSION_TERMS = ("Org.OData.Core.V1.SchemaVersion", "Core.SchemaVersion")


# ---------------------------------------------------------------------------
# Reading the CSDL JSON the target model keeps
# ---------------------------------------------------------------------------


def _csdl(api: CanonicalApi) -> Mapping[str, Any]:
    """The model's canonical CSDL JSON (v4, when kept), else ``{}``."""
    raw = api.raw if isinstance(api.raw, Mapping) else {}
    csdl = raw.get("csdl_json")
    return csdl if isinstance(csdl, Mapping) else {}


def _schemas(csdl: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    """``namespace → schema`` of a CSDL JSON document."""
    return {ns: schema for ns, schema in csdl.items() if not ns.startswith("$") and isinstance(schema, Mapping)}


def schema_versions(api: CanonicalApi) -> Dict[str, str]:
    """The ``Core.SchemaVersion`` each schema of a model declares (``namespace → version``).

    Read from the model's canonical CSDL JSON: ``@Core.SchemaVersion`` (or an alias-qualified
    spelling ending in ``.SchemaVersion`` whose namespace is the Core vocabulary). Empty when the
    model keeps no CSDL JSON or declares no version.
    """
    versions: Dict[str, str] = {}
    for namespace, schema in _schemas(_csdl(api)).items():
        for key, value in schema.items():
            term = key[1:] if key.startswith("@") else ""
            if term in _SCHEMA_VERSION_TERMS or (term.endswith(".SchemaVersion") and "Core" in term):
                versions[namespace] = str(value)
    return versions


def _member(api: CanonicalApi, type_key: str, member: str) -> Mapping[str, Any]:
    """The CSDL JSON of a structured type's member (``{}`` when unknown)."""
    namespace, _, name = type_key.rpartition(".")
    for ns, schema in _schemas(_csdl(api)).items():
        if namespace and ns != namespace:
            continue
        structured = schema.get(name)
        if isinstance(structured, Mapping) and isinstance(structured.get(member), Mapping):
            return structured[member]
    return {}


# ---------------------------------------------------------------------------
# Property (field) changes
# ---------------------------------------------------------------------------


def _type_ref(projection: Any) -> Mapping[str, Any]:
    """A field self-projection's ``type`` (``{}`` when absent)."""
    if isinstance(projection, Mapping) and isinstance(projection.get("type"), Mapping):
        return projection["type"]
    return {}


def _shape(type_ref: Mapping[str, Any]) -> Any:
    """A type reference without its nullability: what values of it look like."""
    return {key: value for key, value in type_ref.items() if key != "nullable"}


def _field_parts(key: str) -> Tuple[str, str]:
    """``Shop.Product.Name`` → ``("Shop.Product", "Name")``."""
    type_key, _, name = key.rpartition(".")
    return type_key, name


def grade_added_property(change: EntityChange, target: CanonicalApi) -> Grade:
    """Grade a new property per §5.2: nullable or defaulted is safe, anything else breaking."""
    type_key, name = _field_parts(change.key)
    if _type_ref(change.after).get("nullable", True) is not False:
        return (
            Severity.SAFE,
            "odata.property-added-nullable",
            f"nullable property {name!r} was added to {type_key!r}; OData §5.2 lists this as a safe change",
        )
    default = _member(target, type_key, name).get("$DefaultValue")
    if default is not None or (isinstance(change.after, Mapping) and change.after.get("default") is not None):
        return (
            Severity.SAFE,
            "odata.property-added-with-default",
            f"property {name!r} was added to {type_key!r} with a default value; OData §5.2 lists this as safe",
        )
    return (
        Severity.BREAKING,
        "odata.property-added-required",
        f"non-nullable property {name!r} was added to {type_key!r} with no default; OData §5.2 allows only "
        "nullable or defaulted additions, and clients that create or replace entities without it fail",
    )


def grade_modified_property(change: EntityChange) -> Optional[Grade]:
    """Grade a property whose type or nullability moved, or ``None`` for the baseline."""
    type_change = next((f for f in change.fields if f.field == "type"), None)
    if type_change is None:
        return None
    before = type_change.before if isinstance(type_change.before, Mapping) else {}
    after = type_change.after if isinstance(type_change.after, Mapping) else {}
    type_key, name = _field_parts(change.key)
    grades: List[Grade] = []
    if _shape(before) != _shape(after):
        grades.append(
            (
                Severity.BREAKING,
                "odata.property-type-changed",
                f"property {name!r} of {type_key!r} changed type; OData §5.2 names changing a property's type "
                "as breaking",
            )
        )
    was_nullable, is_nullable = before.get("nullable", True) is not False, after.get("nullable", True) is not False
    if was_nullable and not is_nullable:
        grades.append(
            (
                Severity.BREAKING,
                "odata.property-made-non-nullable",
                f"property {name!r} of {type_key!r} became non-nullable; clients that send null or omit it fail",
            )
        )
    elif is_nullable and not was_nullable:
        grades.append(
            (
                Severity.DANGEROUS,
                "odata.property-made-nullable",
                f"property {name!r} of {type_key!r} became nullable; clients that assume a value may now receive null",
            )
        )
    return _combine(grades) if grades else None


# ---------------------------------------------------------------------------
# Entity-type extras: key, navigation properties, annotations
# ---------------------------------------------------------------------------


def _extras(projection: Any) -> Dict[str, Any]:
    if isinstance(projection, Mapping) and isinstance(projection.get("extras"), Mapping):
        return dict(projection["extras"])
    return {}


def _navigations(extras: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        str(nav.get("name")): nav
        for nav in extras.get("odata_navigation_properties") or []
        if isinstance(nav, Mapping) and nav.get("name")
    }


def _navigation_nullability(nav: Mapping[str, Any], csdl_member: Mapping[str, Any]) -> Optional[bool]:
    """Whether a single-valued navigation property is nullable; ``None`` when not recorded."""
    multiplicity = str(nav.get("multiplicity") or "").strip()
    if multiplicity:  # v2/v3 association end
        return multiplicity == "0..1"
    if csdl_member:  # v4 CSDL JSON: `$Nullable` is written only when true
        return bool(csdl_member.get("$Nullable"))
    return None


def grade_navigation_changes(
    type_key: str, before: Mapping[str, Any], after: Mapping[str, Any], target: CanonicalApi
) -> List[Grade]:
    """Grade every navigation property added, removed or changed on one entity type."""
    old, new = _navigations(before), _navigations(after)
    grades: List[Grade] = []
    for name in sorted(old.keys() - new.keys()):
        grades.append(
            (
                Severity.BREAKING,
                "odata.navigation-removed",
                f"navigation property {name!r} was removed from {type_key!r}; clients that expand or follow it fail",
            )
        )
    for name in sorted(new.keys() - old.keys()):
        nav = new[name]
        if str(nav.get("type") or "").startswith("Collection("):
            grades.append(
                (
                    Severity.SAFE,
                    "odata.navigation-added",
                    f"collection-valued navigation property {name!r} was added to {type_key!r}; OData §5.2 lists "
                    "this as safe",
                )
            )
            continue
        nullable = _navigation_nullability(nav, _member(target, type_key, name))
        if nullable is True:
            grades.append(
                (
                    Severity.SAFE,
                    "odata.navigation-added",
                    f"nullable navigation property {name!r} was added to {type_key!r}; OData §5.2 lists this as safe",
                )
            )
        elif nullable is False:
            grades.append(
                (
                    Severity.BREAKING,
                    "odata.navigation-added-required",
                    f"non-nullable navigation property {name!r} was added to {type_key!r}; OData §5.2 allows only "
                    "nullable or collection-valued additions",
                )
            )
        else:
            grades.append(
                (
                    Severity.DANGEROUS,
                    "odata.navigation-added-unknown",
                    f"single-valued navigation property {name!r} was added to {type_key!r}; it is safe only if "
                    "nullable (OData §5.2), which the model does not record",
                )
            )
    for name in sorted(old.keys() & new.keys()):
        if old[name].get("type") != new[name].get("type"):
            grades.append(
                (
                    Severity.BREAKING,
                    "odata.navigation-type-changed",
                    f"navigation property {name!r} of {type_key!r} now targets {new[name].get('type')!r} instead "
                    f"of {old[name].get('type')!r}",
                )
            )
        elif old[name].get("partner") != new[name].get("partner"):
            grades.append(
                (
                    Severity.DANGEROUS,
                    "odata.navigation-partner-changed",
                    f"navigation property {name!r} of {type_key!r} changed its partner",
                )
            )
    return grades


def grade_annotations(type_key: str, before: Any, after: Any) -> Optional[Grade]:
    """Grade an ``odata_annotations`` move: only additions are safe (§5.2)."""
    old = dict(before) if isinstance(before, Mapping) else {}
    new = dict(after) if isinstance(after, Mapping) else {}
    if old == new:
        return None
    if all(key in new and new[key] == value for key, value in old.items()):
        return (
            Severity.SAFE,
            "odata.annotation-added",
            f"annotations were added to {type_key!r}; OData §5.2 lists adding annotations as safe",
        )
    return (
        Severity.DANGEROUS,
        "odata.annotation-changed",
        f"an annotation of {type_key!r} was changed or removed; clients that read it may behave differently",
    )


def grade_entity_type(change: EntityChange, target: CanonicalApi) -> Optional[Grade]:
    """Grade an entity type whose only move is its extras, or ``None`` for the baseline."""
    if {f.field for f in change.fields} != {"extras"}:
        return None
    before, after = _extras(change.before), _extras(change.after)
    grades: List[Grade] = []
    if before.pop("odata_key_properties", None) != (key := after.pop("odata_key_properties", None)):
        grades.append(
            (
                Severity.BREAKING,
                "odata.key-changed",
                f"the key of {change.key!r} changed to {key!r}; entity URLs and references built from the old "
                "key break",
            )
        )
    grades.extend(grade_navigation_changes(change.key, before, after, target))
    before.pop("odata_navigation_properties", None)
    after.pop("odata_navigation_properties", None)
    annotation = grade_annotations(
        change.key, before.pop("odata_annotations", None), after.pop("odata_annotations", None)
    )
    if annotation is not None:
        grades.append(annotation)
    if before != after:
        return None  # something else moved too: the baseline grades the whole type
    return _combine(grades) if grades else None


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


# ---------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------


def _schema_version_note(base: CanonicalApi, target: CanonicalApi) -> str:
    """What the schema versions say about a breaking diff (appended to each breaking rationale)."""
    old, new = schema_versions(base), schema_versions(target)
    moved = [
        f"{ns}: {old.get(ns)!r} → {new.get(ns)!r}" for ns in sorted(set(old) | set(new)) if old.get(ns) != new.get(ns)
    ]
    if moved:
        return (
            f" — Core.SchemaVersion moved ({'; '.join(moved)}): clients pinned with $schemaversion to the old "
            "version keep the old model"
        )
    return (
        " — Core.SchemaVersion did not change: OData §5.2 asks a service that makes breaking changes to version "
        "its metadata (Core.SchemaVersion) so clients can request the old model with $schemaversion"
    )


class ODataBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an OData diff by OData §5.2 Model Versioning (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "odata-model-versioning"

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change; changes this classifier does not recognise use the baseline."""
        graded: Optional[Grade] = None
        if change.category is EntityCategory.FIELD and change.kind is ChangeKind.ADDED:
            graded = grade_added_property(change, target)
        elif change.category is EntityCategory.FIELD and change.kind is ChangeKind.MODIFIED:
            graded = grade_modified_property(change)
        elif change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
            graded = grade_entity_type(change, target)
        if graded is None:
            return super().classify_change(change, base, target)
        severity, rule_id, rationale = graded
        return ChangeClassification(
            category=change.category,
            kind=change.kind,
            key=change.key,
            severity=severity,
            rule_id=rule_id,
            rationale=rationale,
        )

    def classify(self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
        """Grade every change, then note the ``Core.SchemaVersion`` story on each breaking grade."""
        classifications = [self.classify_change(change, base, target) for change in model_diff.changes]
        if any(c.severity is Severity.BREAKING for c in classifications):
            note = _schema_version_note(base, target)
            classifications = [
                c.model_copy(update={"rationale": c.rationale + note}) if c.severity is Severity.BREAKING else c
                for c in classifications
            ]
        return _assemble_result(self, target, classifications)
