"""
Style-guide maturity ladders — GVM-1.1 (#5854).

A ladder is the ordered list of levels a team climbs under a style guide (Bronze → Silver →
Gold). Each level states, on top of everything the levels below it require:

* **rules** — ``[{ruleId, maxSeverity}]``: the worst finding severity the rule may still
  produce at this level (``error`` | ``warning`` | ``info`` | ``none``; ``none`` = the rule must
  be clean);
* **axes** — ``[{axis, minGrade?, minScore?}]``: CLX axis floors (the axis must be assessed);
* **evidence** — required evidence (``review_approved`` | ``verification_passing``);
* **waiversSatisfy** — whether an effective waiver counts as satisfying a rule requirement.

Ladders are **cumulative**: level *n* implicitly includes every requirement of level *n−1*, so a
level lists only what it adds. :func:`validate_ladder` enforces that by refusing a level that
*relaxes* a lower one (a looser ``maxSeverity``, a worse grade, a lower score, or turning
``waiversSatisfy`` on after a lower level turned it off). It also checks every ``ruleId``
against the GOV-1.2 rule registry and every ``axis`` against the CLX axis vocabulary
(:data:`app.axis_score.AXIS_KEYS`) — the database only pins the JSON shape.

This module is pure (no DB access). Persistence lives in :mod:`app.database`, the routes in
:mod:`app.style_guide_routes`, and the snapshot writers in :mod:`app.style_guide_revisions` and
:mod:`app.lint_policy_service`. Evaluation against findings is GVM-1.2.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

__all__ = [
    "EVIDENCE_KINDS",
    "GRADE_ORDER",
    "LadderValidationError",
    "SEVERITY_ORDER",
    "default_ladder_template",
    "ladder_content_fingerprint",
    "ladder_from_row",
    "validate_ladder",
]

#: ``maxSeverity`` values ordered strictest → loosest. ``none`` = no finding of the rule at all.
SEVERITY_ORDER: tuple = ("none", "info", "warning", "error")

#: Letter grades ordered best → worst (same order as :mod:`app.policy_evaluate`).
GRADE_ORDER: tuple = ("A", "B", "C", "D", "F")

#: Evidence a level may require.
EVIDENCE_KINDS: tuple = ("review_approved", "verification_passing")

#: ``detail.code`` values a refused ladder carries (all HTTP 422).
CODE_INVALID = "ladder-invalid"
CODE_EMPTY = "ladder-empty"
CODE_DUPLICATE_LEVEL = "ladder-duplicate-level"
CODE_DUPLICATE_RULE = "ladder-duplicate-rule"
CODE_DUPLICATE_AXIS = "ladder-duplicate-axis"
CODE_UNKNOWN_RULE = "ladder-unknown-rule"
CODE_UNKNOWN_AXIS = "ladder-unknown-axis"
CODE_AXIS_THRESHOLD_MISSING = "ladder-axis-threshold-missing"
CODE_NOT_CUMULATIVE = "ladder-level-not-cumulative"


@dataclass
class LadderValidationError(ValueError):
    """A ladder the application refuses to store.

    Attributes:
        code: Stable machine code (``ladder-*``), returned as ``detail.code``.
        message: Human-readable reason naming the level (and rule / axis) at fault.
        pointer: JSON Pointer into the request body (e.g. ``/levels/1/rules/0/ruleId``).
        level: Key of the offending level, when one is at fault.
        rule: The rule id, axis key or field the error is about, when applicable.
    """

    code: str
    message: str
    pointer: str
    level: Optional[str] = None
    rule: Optional[str] = None

    def __str__(self) -> str:
        return self.message

    def as_detail(self) -> Dict[str, Any]:
        """Return the ``HTTPException.detail`` payload for this error."""
        detail: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "pointer": self.pointer,
        }
        if self.level is not None:
            detail["level"] = self.level
        if self.rule is not None:
            detail["rule"] = self.rule
        return detail


def _canonical_json(value: Any) -> str:
    """Canonical JSON for fingerprinting: sorted keys, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def ladder_content_fingerprint(ladder: Mapping[str, Any]) -> str:
    """SHA-256 hex over a normalized ladder's ``{name, levels}``.

    Args:
        ladder: A ladder as returned by :func:`validate_ladder` or :func:`ladder_from_row`.

    Returns:
        The hex digest stored in ``style_guide_ladders.content_fingerprint``.
    """
    body = {"name": ladder.get("name"), "levels": list(ladder.get("levels") or [])}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def ladder_from_row(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Project a ``style_guide_ladders`` row onto the frozen ``{name, levels}`` snapshot.

    Args:
        row: The guide's ladder row, or ``None`` when the guide has none.

    Returns:
        ``{"name", "levels"}``, or ``None`` for no ladder. A row whose ``levels`` is empty or
        not a list is also ``None``: an empty ladder is never reported as a ladder whose every
        level is satisfied.
    """
    if not isinstance(row, Mapping):
        return None
    levels = row.get("levels")
    if not isinstance(levels, list) or not levels:
        return None
    return {"name": str(row.get("name") or ""), "levels": [dict(lv) for lv in levels]}


def _field(raw: Mapping[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    """Read a field by its camelCase or snake_case name."""
    if camel in raw:
        return raw[camel]
    return raw.get(snake, default)


def _normalize_level(
    raw: Any,
    index: int,
    *,
    registered_rule_ids: frozenset,
    axis_keys: frozenset,
) -> Dict[str, Any]:
    """Validate one level's own content (not the cumulative rule) and canonicalize it.

    Args:
        raw: The level object from the request.
        index: Its position in ``levels`` (for the pointer).
        registered_rule_ids: Every rule id the ladder may reference.
        axis_keys: Every axis key the ladder may reference.

    Returns:
        The level with rules sorted by ``ruleId``, axes by ``axis`` and evidence de-duplicated
        and sorted, so equal ladders fingerprint equally.

    Raises:
        LadderValidationError: On a malformed field, a duplicate, an unknown rule or axis, or
            an axis entry without a threshold.
    """
    base = f"/levels/{index}"
    if not isinstance(raw, Mapping):
        raise LadderValidationError(CODE_INVALID, "A level must be an object", base)
    key = raw.get("key")
    if not isinstance(key, str) or not key.strip():
        raise LadderValidationError(CODE_INVALID, "A level needs a key", f"{base}/key")
    key = key.strip()
    label = raw.get("label")
    label = label.strip() if isinstance(label, str) and label.strip() else key

    rules: List[Dict[str, Any]] = []
    seen_rules: set = set()
    for i, rule in enumerate(raw.get("rules") or []):
        pointer = f"{base}/rules/{i}"
        rule_id = _field(rule, "ruleId", "rule_id") if isinstance(rule, Mapping) else None
        if not isinstance(rule_id, str) or not rule_id:
            raise LadderValidationError(
                CODE_INVALID, f"Level '{key}': a rule needs a ruleId", f"{pointer}/ruleId", key
            )
        if rule_id not in registered_rule_ids:
            raise LadderValidationError(
                CODE_UNKNOWN_RULE,
                f"Level '{key}': unknown rule id '{rule_id}'",
                f"{pointer}/ruleId",
                key,
                rule_id,
            )
        if rule_id in seen_rules:
            raise LadderValidationError(
                CODE_DUPLICATE_RULE,
                f"Level '{key}': rule '{rule_id}' is listed twice",
                f"{pointer}/ruleId",
                key,
                rule_id,
            )
        seen_rules.add(rule_id)
        severity = _field(rule, "maxSeverity", "max_severity")
        if severity not in SEVERITY_ORDER:
            raise LadderValidationError(
                CODE_INVALID,
                f"Level '{key}': maxSeverity of '{rule_id}' must be one of "
                + ", ".join(SEVERITY_ORDER),
                f"{pointer}/maxSeverity",
                key,
                rule_id,
            )
        rules.append({"ruleId": rule_id, "maxSeverity": severity})

    axes: List[Dict[str, Any]] = []
    seen_axes: set = set()
    for i, axis_raw in enumerate(raw.get("axes") or []):
        pointer = f"{base}/axes/{i}"
        axis = axis_raw.get("axis") if isinstance(axis_raw, Mapping) else None
        if not isinstance(axis, str) or axis not in axis_keys:
            raise LadderValidationError(
                CODE_UNKNOWN_AXIS,
                f"Level '{key}': unknown axis '{axis}'",
                f"{pointer}/axis",
                key,
                axis if isinstance(axis, str) else None,
            )
        if axis in seen_axes:
            raise LadderValidationError(
                CODE_DUPLICATE_AXIS,
                f"Level '{key}': axis '{axis}' is listed twice",
                f"{pointer}/axis",
                key,
                axis,
            )
        seen_axes.add(axis)
        entry: Dict[str, Any] = {"axis": axis}
        grade = _field(axis_raw, "minGrade", "min_grade")
        score = _field(axis_raw, "minScore", "min_score")
        if grade is not None:
            if grade not in GRADE_ORDER:
                raise LadderValidationError(
                    CODE_INVALID,
                    f"Level '{key}': minGrade of '{axis}' must be one of "
                    + ", ".join(GRADE_ORDER),
                    f"{pointer}/minGrade",
                    key,
                    axis,
                )
            entry["minGrade"] = grade
        if score is not None:
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not (
                0 <= score <= 100
            ):
                raise LadderValidationError(
                    CODE_INVALID,
                    f"Level '{key}': minScore of '{axis}' must be a number from 0 to 100",
                    f"{pointer}/minScore",
                    key,
                    axis,
                )
            entry["minScore"] = int(score) if float(score).is_integer() else float(score)
        if "minGrade" not in entry and "minScore" not in entry:
            raise LadderValidationError(
                CODE_AXIS_THRESHOLD_MISSING,
                f"Level '{key}': axis '{axis}' needs minGrade or minScore",
                pointer,
                key,
                axis,
            )
        axes.append(entry)

    evidence: List[str] = []
    for i, kind in enumerate(raw.get("evidence") or []):
        if kind not in EVIDENCE_KINDS:
            raise LadderValidationError(
                CODE_INVALID,
                f"Level '{key}': evidence must be one of " + ", ".join(EVIDENCE_KINDS),
                f"{base}/evidence/{i}",
                key,
                kind if isinstance(kind, str) else None,
            )
        if kind not in evidence:
            evidence.append(kind)

    waivers = _field(raw, "waiversSatisfy", "waivers_satisfy", False)
    if not isinstance(waivers, bool):
        raise LadderValidationError(
            CODE_INVALID,
            f"Level '{key}': waiversSatisfy must be true or false",
            f"{base}/waiversSatisfy",
            key,
        )

    return {
        "key": key,
        "label": label,
        "rules": sorted(rules, key=lambda r: r["ruleId"]),
        "axes": sorted(axes, key=lambda a: a["axis"]),
        "evidence": sorted(evidence),
        "waiversSatisfy": waivers,
    }


def _check_cumulative(levels: Sequence[Mapping[str, Any]]) -> None:
    """Refuse a level that relaxes a requirement of any level below it.

    Walks the levels lowest first, accumulating the effective requirements (the strictest
    value seen so far for each rule and axis). A level may restate a requirement at the same
    strength or tighten it; anything looser is a ``ladder-level-not-cumulative`` error.

    Raises:
        LadderValidationError: Naming the first relaxing level and the rule / axis / field.
    """
    rule_floor: Dict[str, tuple] = {}  # ruleId -> (severity rank, level key)
    grade_floor: Dict[str, tuple] = {}  # axis -> (grade rank, level key)
    score_floor: Dict[str, tuple] = {}  # axis -> (score, level key)
    waivers_off_at: Optional[str] = None

    for index, level in enumerate(levels):
        key = level["key"]
        for i, rule in enumerate(level["rules"]):
            rank = SEVERITY_ORDER.index(rule["maxSeverity"])
            prior = rule_floor.get(rule["ruleId"])
            if prior and rank > prior[0]:
                raise LadderValidationError(
                    CODE_NOT_CUMULATIVE,
                    f"Level '{key}' relaxes rule '{rule['ruleId']}' to maxSeverity "
                    f"'{rule['maxSeverity']}'; level '{prior[1]}' already requires "
                    f"'{SEVERITY_ORDER[prior[0]]}'",
                    f"/levels/{index}/rules/{i}/maxSeverity",
                    key,
                    rule["ruleId"],
                )
            if not prior or rank < prior[0]:
                rule_floor[rule["ruleId"]] = (rank, key)
        for i, axis in enumerate(level["axes"]):
            name = axis["axis"]
            if "minGrade" in axis:
                rank = GRADE_ORDER.index(axis["minGrade"])
                prior = grade_floor.get(name)
                if prior and rank > prior[0]:
                    raise LadderValidationError(
                        CODE_NOT_CUMULATIVE,
                        f"Level '{key}' relaxes axis '{name}' to minGrade "
                        f"'{axis['minGrade']}'; level '{prior[1]}' already requires "
                        f"'{GRADE_ORDER[prior[0]]}'",
                        f"/levels/{index}/axes/{i}/minGrade",
                        key,
                        name,
                    )
                if not prior or rank < prior[0]:
                    grade_floor[name] = (rank, key)
            if "minScore" in axis:
                score = axis["minScore"]
                prior = score_floor.get(name)
                if prior and score < prior[0]:
                    raise LadderValidationError(
                        CODE_NOT_CUMULATIVE,
                        f"Level '{key}' relaxes axis '{name}' to minScore {score}; "
                        f"level '{prior[1]}' already requires {prior[0]}",
                        f"/levels/{index}/axes/{i}/minScore",
                        key,
                        name,
                    )
                if not prior or score > prior[0]:
                    score_floor[name] = (score, key)
        if level["waiversSatisfy"] and waivers_off_at is not None:
            raise LadderValidationError(
                CODE_NOT_CUMULATIVE,
                f"Level '{key}' lets waivers satisfy rules; level '{waivers_off_at}' "
                "already requires them to be fixed",
                f"/levels/{index}/waiversSatisfy",
                key,
                "waiversSatisfy",
            )
        if not level["waiversSatisfy"] and waivers_off_at is None:
            waivers_off_at = key


def validate_ladder(
    raw: Mapping[str, Any],
    *,
    registered_rule_ids: Iterable[str],
    axis_keys: Iterable[str],
) -> Dict[str, Any]:
    """Validate a ladder document and return its canonical ``{name, levels}`` form.

    Args:
        raw: ``{"name": str, "levels": [level, ...]}`` with levels lowest first.
        registered_rule_ids: Rule ids a level may reference (the GOV-1.2 registry).
        axis_keys: Axis keys a level may reference (the CLX axis vocabulary).

    Returns:
        The normalized ladder: trimmed name, each level canonicalized (see
        :func:`_normalize_level`), order preserved.

    Raises:
        LadderValidationError: The first problem found, with a JSON Pointer into ``raw``.
    """
    if not isinstance(raw, Mapping):
        raise LadderValidationError(CODE_INVALID, "A ladder must be an object", "")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LadderValidationError(CODE_INVALID, "A ladder needs a name", "/name")
    raw_levels = raw.get("levels")
    if not isinstance(raw_levels, list):
        raise LadderValidationError(CODE_INVALID, "levels must be an array", "/levels")
    if not raw_levels:
        raise LadderValidationError(
            CODE_EMPTY, "A ladder needs at least one level", "/levels"
        )

    rule_ids = frozenset(registered_rule_ids)
    axes = frozenset(axis_keys)
    levels: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for index, raw_level in enumerate(raw_levels):
        level = _normalize_level(
            raw_level, index, registered_rule_ids=rule_ids, axis_keys=axes
        )
        if level["key"] in seen_keys:
            raise LadderValidationError(
                CODE_DUPLICATE_LEVEL,
                f"Level key '{level['key']}' is used twice",
                f"/levels/{index}/key",
                level["key"],
            )
        seen_keys.add(level["key"])
        levels.append(level)

    _check_cumulative(levels)
    return {"name": name.strip(), "levels": levels}


def default_ladder_template(
    descriptors: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """The read-only Bronze / Silver / Gold template of the built-in Apiome Recommended guide.

    * **Bronze** — no error-severity findings, except documentation rules: every
      non-documentation rule is capped at ``warning``.
    * **Silver** — Bronze, plus quality ≥ B and no errors at all (documentation rules capped
      at ``warning`` too).
    * **Gold** — Silver, plus quality ≥ A, the security axis assessed at A with every security
      rule clean (``none``), and an approved review.

    Waivers satisfy rule requirements at every level. The template is never applied to a
    tenant: it is returned beside the built-in guide's ``ladder: null`` so an editor can start
    from it.

    Args:
        descriptors: Rule descriptors (``rule_id`` / ``category``); defaults to the GOV-1.2
            registry. Injected by tests.

    Returns:
        A validated ``{name, levels}`` ladder.
    """
    if descriptors is None:
        from .lint_rule_registry import builtin_rule_descriptors

        descriptors = builtin_rule_descriptors()
    from .axis_score import AXIS_KEYS

    def capped(rules: Iterable[Any], severity: str) -> List[Dict[str, str]]:
        return [{"ruleId": d.rule_id, "maxSeverity": severity} for d in rules]

    documentation = [d for d in descriptors if d.category == "documentation"]
    others = [d for d in descriptors if d.category != "documentation"]
    security = [d for d in descriptors if d.category == "security"]
    raw = {
        "name": "Apiome maturity",
        "levels": [
            {
                "key": "bronze",
                "label": "Bronze",
                "rules": capped(others, "warning"),
                "waiversSatisfy": True,
            },
            {
                "key": "silver",
                "label": "Silver",
                "rules": capped(documentation, "warning"),
                "axes": [{"axis": "quality", "minGrade": "B"}],
                "waiversSatisfy": True,
            },
            {
                "key": "gold",
                "label": "Gold",
                "rules": capped(security, "none"),
                "axes": [
                    {"axis": "quality", "minGrade": "A"},
                    {"axis": "security", "minGrade": "A"},
                ],
                "evidence": ["review_approved"],
                "waiversSatisfy": True,
            },
        ],
    }
    return validate_ladder(
        raw,
        registered_rule_ids=[d.rule_id for d in descriptors],
        axis_keys=AXIS_KEYS,
    )
