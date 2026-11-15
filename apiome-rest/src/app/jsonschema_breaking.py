"""JSON Schema breaking-change classifier: open vs closed content models — XPC-4.2 (#5746).

The format-agnostic baseline grades a JSON Schema diff from the canonical model alone, which has
no notion of a *content model*: it grades a property added to a closed schema
(``additionalProperties: false``) SAFE, though old readers reject data that carries it. This
classifier compares each type's actual schema with :func:`app.jsonschema_compatibility.compare_schemas`
(the Confluent / Apicurio rules) and grades every canonical change by the compatibility
**mode** it is configured with:

=====================================================  ==========
A finding …                                            Severity
=====================================================  ==========
breaks a direction the mode checks                     breaking
breaks only the other direction                        dangerous
cannot be proven either way (``review``)               dangerous
=====================================================  ==========

The default mode is ``BACKWARD`` — a Confluent registry's default level, and the line the Avro
classifier (:mod:`app.avro_breaking`) draws — so a property added to an *open* schema is breaking
while the same addition to a *closed* schema is dangerous, and the rationale names the content
model. Construct the classifier with ``mode="FORWARD"`` or ``mode="FULL"`` (``*_TRANSITIVE``
accepted) to grade by another mode; :func:`compatibility_findings` exposes the direction-tagged
findings for callers that evaluate several modes (XPC-4.5).

**Which schemas are compared.** An imported JSON Schema keeps its document on
:attr:`CanonicalApi.raw <app.canonical_model.CanonicalApi.raw>` (``source``): each ``$defs`` /
``definitions`` entry is a canonical type, and the root schema is one more. When either version
has no raw document, both are rebuilt from the canonical model with
:func:`app.canonical_json_schema.build_bundle_schemas` so the comparison stays like-for-like.
``$ref`` targets resolve inside each version's own document.

**How findings join changes.** A finding under a top-level property joins that field's change
(``User.email``), else its type's change (``User``). A type or field change no finding joins is
graded safe when both versions define the type (the check covered it); a type only one version
defines keeps the baseline grade. A finding that joins no change — an ``additionalProperties``
flip, which the canonical model does not carry — is kept in ``unattributed`` and still counts
toward the overall severity.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Mapping, Optional, Set, Tuple

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    UnattributedFinding,
    _assemble_result,
    _worst,
)
from .canonical_json_schema import build_bundle_schemas
from .canonical_model import CanonicalApi
from .diff import EntityCategory, ModelDiff
from .jsonschema_compatibility import REVIEW, SchemaFinding, compare_schemas, mode_directions

__all__ = [
    "JsonSchemaBreakingChangeClassifier",
    "JsonSchemaCompatibility",
    "compatibility_findings",
    "finding_severity",
    "type_schemas",
]

_COMPATIBLE_RULE = "jsonschema.compatible"

#: A finding together with the canonical type key it was found in.
TypedFinding = Tuple[str, SchemaFinding]

#: Mode → the words a rationale uses for what a finding in each direction breaks.
_DIRECTION_TEXT = {
    "backward": "breaks BACKWARD and FULL: the new schema rejects data the old one accepted",
    "forward": "breaks FORWARD and FULL: the old schema rejects data the new one accepts",
    REVIEW: "review: compatibility cannot be proven either way",
}


class JsonSchemaCompatibility:
    """Both versions' schemas, keyed by canonical type, ready to compare.

    Attributes:
        old_document: The document the old schemas' ``$ref``s resolve against.
        new_document: The document the new schemas' ``$ref``s resolve against.
        old_types: Canonical type key → the old version's schema.
        new_types: Canonical type key → the new version's schema.
    """

    def __init__(
        self,
        old_document: Mapping[str, Any],
        new_document: Mapping[str, Any],
        old_types: Dict[str, Any],
        new_types: Dict[str, Any],
    ) -> None:
        self.old_document = old_document
        self.new_document = new_document
        self.old_types = old_types
        self.new_types = new_types

    @property
    def shared(self) -> Set[str]:
        """The type keys both versions define (the ones compared)."""
        return set(self.old_types) & set(self.new_types)

    def findings(self) -> List[TypedFinding]:
        """Compare every shared type and return its findings, in type-key order."""
        out: List[TypedFinding] = []
        for key in sorted(self.shared):
            found = compare_schemas(
                self.old_types[key],
                self.new_types[key],
                old_document=self.old_document,
                new_document=self.new_document,
            )
            out += [(key, finding) for finding in found]
        return out


def _raw_document(model: CanonicalApi) -> Optional[Mapping[str, Any]]:
    """The JSON Schema document an import kept on ``raw["source"]``, or ``None``."""
    raw = model.raw if isinstance(model.raw, Mapping) else {}
    source = raw.get("source")
    return source if isinstance(source, Mapping) else None


def type_schemas(model: CanonicalApi, *, use_raw: bool = True) -> Tuple[Mapping[str, Any], Dict[str, Any]]:
    """Return a model's schema document and its schema per canonical type key.

    Args:
        model: A JSON Schema canonical model.
        use_raw: Read the imported document on ``raw`` when there is one; ``False`` always
            rebuilds the schemas from the canonical model.

    Returns:
        ``(document, schemas)``: the document local ``$ref``s resolve against, and each
        canonical type key mapped to its schema. With the raw document, a ``$defs`` /
        ``definitions`` entry maps to its type and the root schema to the type that is not one
        of them (mirroring :class:`app.jsonschema_import_source.JsonSchemaImportSource`).
    """
    document = _raw_document(model) if use_raw else None
    if document is not None:
        defs = document.get("$defs")
        if not isinstance(defs, Mapping):
            defs = document.get("definitions")
        defs = defs if isinstance(defs, Mapping) else {}
        schemas: Dict[str, Any] = {}
        for type_ in model.types:
            schemas[type_.key] = defs[type_.key] if type_.key in defs else document
        return document, schemas
    bundle = build_bundle_schemas(model)
    rebuilt = {"$defs": bundle.defs}
    return rebuilt, {
        key: bundle.defs[defs_key] for key, defs_key in bundle.defs_keys.items() if defs_key in bundle.defs
    }


def compatibility_findings(base: CanonicalApi, target: CanonicalApi) -> Tuple[List[TypedFinding], Set[str]]:
    """Compare two versions of a JSON Schema type by type.

    Args:
        base: The old version.
        target: The new version.

    Returns:
        ``(findings, compared type keys)``: each finding with the type key it was found in, and
        the type keys both versions define.
    """
    both_raw = _raw_document(base) is not None and _raw_document(target) is not None
    old_document, old_types = type_schemas(base, use_raw=both_raw)
    new_document, new_types = type_schemas(target, use_raw=both_raw)
    check = JsonSchemaCompatibility(old_document, new_document, old_types, new_types)
    return check.findings(), check.shared


def finding_severity(finding: SchemaFinding, mode: str) -> Severity:
    """Grade one finding under ``mode``: breaking when the mode checks its direction, else dangerous.

    Args:
        finding: A comparator finding.
        mode: A Confluent mode name (see :func:`app.jsonschema_compatibility.mode_directions`).

    Returns:
        :attr:`Severity.BREAKING` or :attr:`Severity.DANGEROUS`.
    """
    if finding.direction != REVIEW and finding.direction in mode_directions(mode):
        return Severity.BREAKING
    return Severity.DANGEROUS


def _rationale(type_key: str, finding: SchemaFinding) -> str:
    """One finding's sentence: what it breaks, then what changed in which type."""
    return f"{_DIRECTION_TEXT[finding.direction]} — {type_key}: {finding.message}"


def _join_keys(type_key: str, finding: SchemaFinding) -> List[Tuple[EntityCategory, str]]:
    """The canonical changes a finding may join, most specific first."""
    keys: List[Tuple[EntityCategory, str]] = []
    if finding.property_name is not None:
        keys.append((EntityCategory.FIELD, f"{type_key}.{finding.property_name}"))
    keys.append((EntityCategory.TYPE, type_key))
    return keys


def _owner(key: str, type_keys: Set[str]) -> Optional[str]:
    """The type a field key belongs to (the longest type key it extends)."""
    owners = [t for t in type_keys if key.startswith(t + ".")]
    return max(owners, key=len) if owners else None


class JsonSchemaBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a JSON Schema diff by the open/closed content model (see the module docstring)."""

    format = "json-schema"
    classifier_id = "jsonschema-compatibility"

    #: The compatibility mode grades are taken against when none is passed to the constructor.
    default_mode: ClassVar[str] = "BACKWARD"

    def __init__(self, mode: Optional[str] = None) -> None:
        """Create a classifier for ``mode``.

        Args:
            mode: ``BACKWARD`` (default), ``FORWARD`` or ``FULL``, optionally ``_TRANSITIVE``.

        Raises:
            ValueError: If ``mode`` is not a known compatibility mode.
        """
        self.mode = (mode or self.default_mode).strip().upper()
        mode_directions(self.mode)  # validate early

    def classify(self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
        """Grade every change with the baseline, then by the JSON Schema compatibility check.

        Args:
            model_diff: The diff to grade.
            base: The old version.
            target: The new version.

        Returns:
            The result, 1:1 with ``model_diff.changes``, with unjoined findings in ``unattributed``.
        """
        baseline = [self.classify_change(change, base, target) for change in model_diff.changes]
        findings, shared = compatibility_findings(base, target)

        index: Dict[Tuple[EntityCategory, str], List[int]] = {}
        for position, classification in enumerate(baseline):
            index.setdefault((classification.category, classification.key), []).append(position)
        joined: Dict[int, List[TypedFinding]] = {}
        unattributed: List[UnattributedFinding] = []
        for type_key, finding in findings:
            positions = next((index[key] for key in _join_keys(type_key, finding) if key in index), [])
            for position in positions:
                joined.setdefault(position, []).append((type_key, finding))
            if not positions:
                unattributed.append(
                    UnattributedFinding(
                        severity=finding_severity(finding, self.mode),
                        rule_id=finding.rule_id,
                        rationale=_rationale(type_key, finding),
                        shape="/".join((type_key,) + finding.path),
                    )
                )

        type_keys = {t.key for t in base.types} | {t.key for t in target.types}

        def covered(classification: ChangeClassification) -> bool:
            if classification.category is EntityCategory.TYPE:
                return classification.key in shared
            if classification.category is EntityCategory.FIELD:
                return _owner(classification.key, type_keys) in shared
            return False

        graded = [
            self._graded(c, joined[p]) if p in joined else (self._compatible(c) if covered(c) else c)
            for p, c in enumerate(baseline)
        ]
        return _assemble_result(self, target, graded, unattributed)

    def _graded(self, baseline: ChangeClassification, findings: List[TypedFinding]) -> ChangeClassification:
        """Grade a change by its joined findings: the worst severity, its first rule, every reason."""
        severities = [finding_severity(f, self.mode) for _, f in findings]
        worst = _worst(severities)
        first = next(f for (_, f), s in zip(findings, severities) if s is worst)
        reasons = list(dict.fromkeys(_rationale(t, f) for t, f in findings))
        return baseline.model_copy(
            update={"severity": worst, "rule_id": first.rule_id, "rationale": f"[{self.mode}] " + "; ".join(reasons)}
        )

    def _compatible(self, baseline: ChangeClassification) -> ChangeClassification:
        """A covered change with no finding: compatible in both directions."""
        return baseline.model_copy(
            update={
                "severity": Severity.SAFE,
                "rule_id": _COMPATIBLE_RULE,
                "rationale": "the JSON Schema check accepts it both ways (FULL compatible)",
            }
        )


class JsonSchemaAliasBreakingChangeClassifier(JsonSchemaBreakingChangeClassifier, register=True):
    """The same classifier under the ``jsonschema`` format alias."""

    format = "jsonschema"


class JsonSchema202012BreakingChangeClassifier(JsonSchemaBreakingChangeClassifier, register=True):
    """The same classifier under the ``json-schema-2020-12`` format the importer detects."""

    format = "json-schema-2020-12"
