"""AsyncAPI diff / breaking-change classifier — MFI-8.4 (#3762).

The breaking-change classifier SPI (MFI-3.3, :mod:`app.breaking_change`) grades a canonical
:class:`~app.diff.ModelDiff` *breaking-vs-safe* and anticipates a per-format classifier that
*wraps the format's authoritative tool* — for event-driven APIs, that tool is
``@asyncapi/diff``. This module is the AsyncAPI provider on that SPI.

It has two layers, mirroring how MFI-8.3 layered native rules under Spectral:

* **A sharpened structural baseline** — :class:`AsyncApiBreakingChangeClassifier` subclasses
  the format-agnostic :class:`~app.breaking_change.BuiltinBreakingChangeClassifier` and, since
  XPC-4.4 (#5748), grades channels, operations, messages, payloads and servers per **side**
  (consumers vs producers) and compatibility **mode** (:mod:`app.asyncapi_compatibility_rules`):
  an address change, an action flipped send↔receive, a message removed from the union, a
  ``schemaFormat`` change, and a payload change graded by the payload's own Avro / JSON Schema /
  Protobuf check (:mod:`app.asyncapi_payload_compatibility`). Its *synchronous, pure*
  :meth:`classify` is what the sync SPI dispatch (:func:`app.breaking_change.classify`) resolves
  for an AsyncAPI artifact under both ``asyncapi-2`` and ``asyncapi-3``, even when no Node
  toolchain is present.

* **The ``@asyncapi/diff`` overlay** — :meth:`AsyncApiBreakingChangeClassifier.classify_async`
  (and the module convenience :func:`classify_asyncapi`) runs ``@asyncapi/diff`` over the two
  *already-validated and dereferenced* documents MFI-8.1 preserved on
  :attr:`app.canonical_model.CanonicalApi.raw`, then *overlays* its authoritative
  ``breaking`` / ``non-breaking`` verdict onto the structural grades. The tool's verdict wins
  for every change it classifies and can be joined back onto a canonical entity (a channel by
  its address, an operation by its name); ``unclassified`` changes — and any change the tool
  reports that does not join cleanly — keep the conservative structural grade. The result is a
  standard :class:`~app.breaking_change.ClassificationResult`, 1:1 with the diff's changes, so
  the severities surface on the diff view exactly like every other format's.

The tool I/O is **async** (it shells out through :mod:`app.toolchain_runner`), so — exactly
as MFI-8.3's Spectral half is opt-in over the sync lint engine — the tool-backed grading is an
async entry point layered over the sync SPI, which **degrades gracefully**: if the source
documents are absent, or the ``asyncapi-diff`` tool is not installed, or it errors, the
structural baseline stands and a deterministic result is still returned.
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .asyncapi_compatibility_rules import (
    ChangeFindings,
    attribute_severity,
    coerce_mode,
    evaluate,
    rationale,
    severity_under,
)
from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    UnattributedFinding,
    _assemble_result,
    _worst,
)
from .canonical_model import CanonicalApi
from .diff import EntityCategory, ModelDiff, diff
from .toolchain_runner import (
    ToolchainError,
    ToolchainRunner,
    ToolNotAvailableError,
    default_runner,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ASYNCAPI_DIFF_TOOL_KEY",
    "CHANGE_BREAKING",
    "CHANGE_NON_BREAKING",
    "CHANGE_UNCLASSIFIED",
    "AsyncApiDiffChange",
    "AsyncApiDiffResult",
    "AsyncApiDiffError",
    "run_asyncapi_diff",
    "AsyncApiBreakingChangeClassifier",
    "classify_asyncapi",
]


#: Registry key of the bundled Node wrapper tool (declared in :mod:`app.toolchain_packaging`).
ASYNCAPI_DIFF_TOOL_KEY = "asyncapi-diff"

#: The three change classes ``@asyncapi/diff`` assigns (its standard v2/v3 ruleset).
CHANGE_BREAKING = "breaking"
CHANGE_NON_BREAKING = "non-breaking"
CHANGE_UNCLASSIFIED = "unclassified"

_CHANGE_TYPES = (CHANGE_BREAKING, CHANGE_NON_BREAKING, CHANGE_UNCLASSIFIED)
_ACTIONS = ("add", "remove", "edit")

# How an ``@asyncapi/diff`` verdict maps onto the SPI severity. ``unclassified`` is absent on
# purpose: the tool has no compatibility opinion there, so such a change defers to the
# structural baseline rather than being forced to a (possibly wrong) tier.
_TOOL_SEVERITY: Dict[str, Severity] = {
    CHANGE_BREAKING: Severity.BREAKING,
    CHANGE_NON_BREAKING: Severity.SAFE,
}

# Ordinal rank of each severity (worst-last), for taking a worst-of aggregate locally without
# reaching into the SPI module's internals.
_SEVERITY_RANK: Dict[Severity, int] = {
    Severity.SAFE: 0,
    Severity.DANGEROUS: 1,
    Severity.BREAKING: 2,
}

# The v2 channel sub-keys that denote an operation (``channels.<addr>.publish|subscribe``).
_V2_OPERATION_ACTIONS = frozenset({"publish", "subscribe"})


# ===========================================================================
# Result models
# ===========================================================================


class AsyncApiDiffChange(BaseModel):
    """One change ``@asyncapi/diff`` reported between two documents.

    The :attr:`pointer` is the raw RFC-6901 JSON Pointer the tool emits (e.g.
    ``/channels/user~1signedup``); :attr:`path` is that pointer decoded into plain segments
    (``["channels", "user/signedup"]``, with ``~1``/``~0`` unescaped) by the Node wrapper, so
    the classifier can join a change onto a canonical entity without re-parsing pointers.
    """

    model_config = ConfigDict(frozen=True)

    action: str = Field(description="``add`` / ``remove`` / ``edit`` — the kind of change.")
    change_type: str = Field(
        description="``breaking`` / ``non-breaking`` / ``unclassified`` — the tool's verdict."
    )
    pointer: str = Field(description="Raw RFC-6901 JSON Pointer to the changed node.")
    path: List[str] = Field(
        default_factory=list,
        description="The pointer decoded into plain (unescaped) path segments.",
    )

    @property
    def is_breaking(self) -> bool:
        """Whether the tool classified this change as breaking."""
        return self.change_type == CHANGE_BREAKING


class AsyncApiDiffResult(BaseModel):
    """The outcome of diffing two AsyncAPI documents with ``@asyncapi/diff``."""

    model_config = ConfigDict(frozen=True)

    changes: List[AsyncApiDiffChange] = Field(
        default_factory=list, description="Every classified change, in the tool's order."
    )

    @property
    def breaking(self) -> List[AsyncApiDiffChange]:
        """The breaking changes."""
        return [c for c in self.changes if c.change_type == CHANGE_BREAKING]

    @property
    def non_breaking(self) -> List[AsyncApiDiffChange]:
        """The non-breaking changes."""
        return [c for c in self.changes if c.change_type == CHANGE_NON_BREAKING]

    @property
    def unclassified(self) -> List[AsyncApiDiffChange]:
        """The unclassified changes."""
        return [c for c in self.changes if c.change_type == CHANGE_UNCLASSIFIED]

    @property
    def has_breaking(self) -> bool:
        """Whether the tool found at least one breaking change."""
        return any(c.change_type == CHANGE_BREAKING for c in self.changes)


class AsyncApiDiffError(Exception):
    """The ``@asyncapi/diff`` tool was unavailable, timed out, or returned bad output.

    Reserved for *infrastructure* failures (mirroring :class:`app.asyncapi_parser.AsyncApiParseError`):
    the bundled tool is not installed in this runtime, it exceeded its timeout, or it produced
    output the wrapper contract does not describe. The classifier catches this and degrades to
    the structural baseline, so a caller rarely sees it; it is raised by the low-level
    :func:`run_asyncapi_diff` for callers that want the raw failure.
    """


# ===========================================================================
# Low-level tool invocation
# ===========================================================================


def _coerce_changes(raw: Any) -> List[AsyncApiDiffChange]:
    """Adapt the wrapper's ``changes`` array into typed, validated changes.

    Tolerant of an odd shape (a non-list, or entries missing fields / carrying an unknown
    action or type are skipped) so one malformed change never sinks an otherwise-usable diff.
    """
    if not isinstance(raw, list):
        return []
    out: List[AsyncApiDiffChange] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        change_type = entry.get("type")
        if action not in _ACTIONS or change_type not in _CHANGE_TYPES:
            continue
        path = entry.get("path")
        out.append(
            AsyncApiDiffChange(
                action=str(action),
                change_type=str(change_type),
                pointer=str(entry.get("pointer", "")),
                path=[str(segment) for segment in path] if isinstance(path, list) else [],
            )
        )
    return out


def _result_from_payload(payload: Any) -> AsyncApiDiffResult:
    """Build an :class:`AsyncApiDiffResult` from the wrapper's parsed JSON object.

    Raises:
        AsyncApiDiffError: If ``payload`` is not the object shape the wrapper guarantees.
    """
    if not isinstance(payload, dict):
        raise AsyncApiDiffError(
            "AsyncAPI diff tool returned an unexpected (non-object) result; the wrapper "
            "contract was violated"
        )
    return AsyncApiDiffResult(changes=_coerce_changes(payload.get("changes")))


async def run_asyncapi_diff(
    old_document: Dict[str, Any],
    new_document: Dict[str, Any],
    *,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
) -> AsyncApiDiffResult:
    """Diff two dereferenced AsyncAPI documents with ``@asyncapi/diff``.

    The two documents are the canonical JSON MFI-8.1 produced (``$ref``-resolved); they are
    handed to the bundled ``asyncapi-diff`` tool over ``stdin`` as ``{"old": ..., "new": ...}``
    and the tool's per-change ``breaking`` / ``non-breaking`` / ``unclassified`` verdict comes
    back as an :class:`AsyncApiDiffResult`.

    Args:
        old_document: The earlier / "from" dereferenced AsyncAPI document.
        new_document: The later / "to" dereferenced AsyncAPI document.
        runner: The toolchain runner to use; defaults to the shared
            :data:`app.toolchain_runner.default_runner`. Injectable for tests.
        timeout: Optional per-call timeout in seconds; falls back to the tool/service default.

    Returns:
        An :class:`AsyncApiDiffResult`.

    Raises:
        AsyncApiDiffError: For infrastructure failures only — the tool is not installed in this
            runtime, it exceeded its timeout, or it returned output the wrapper contract does
            not describe.
    """
    active_runner = runner if runner is not None else default_runner
    stdin = json.dumps({"old": old_document, "new": new_document})

    try:
        run_result = await active_runner.run(
            ASYNCAPI_DIFF_TOOL_KEY, [], stdin=stdin, timeout=timeout
        )
    except ToolNotAvailableError as exc:
        raise AsyncApiDiffError(
            "The AsyncAPI diff tool is not available in this runtime; AsyncAPI breaking-change "
            "classification falls back to the structural baseline (see the bundled toolchain "
            "packaging, MFI-5.2)."
        ) from exc
    except ToolchainError as exc:
        raise AsyncApiDiffError(f"The AsyncAPI diff tool failed: {exc}") from exc

    return _result_from_payload(run_result.parsed_json)


# ===========================================================================
# Joining a tool change onto a canonical entity coordinate
# ===========================================================================


def _channel_address(doc: Any, map_name: str) -> Optional[str]:
    """Return the canonical channel key (its ``address``) for a channel map entry.

    The ``@asyncapi/diff`` pointer addresses a channel by its *map name* (the key under
    ``channels``). In AsyncAPI 2 that map name *is* the wire address (and the canonical key);
    in AsyncAPI 3 the address is a separate ``address`` field. This reads the address from the
    document so both families join onto the canonical channel key
    (:func:`app.normalizer.Keys.channel`).

    Args:
        doc: The dereferenced AsyncAPI document the change came from.
        map_name: The channel's map name (the decoded pointer segment).

    Returns:
        The channel's ``address`` when the document declares one (v3), otherwise ``None`` so
        the caller falls back to the map name (which is the address in v2).
    """
    channels = doc.get("channels") if isinstance(doc, dict) else None
    spec = channels.get(map_name) if isinstance(channels, dict) else None
    address = spec.get("address") if isinstance(spec, dict) else None
    return address if isinstance(address, str) and address else None


def _v2_operation_key(doc: Any, address: str, action: str) -> str:
    """Return the canonical operation key for a v2 ``channels.<addr>.<publish|subscribe>``.

    Mirrors :func:`app.normalizer.Keys.operation_event`: the operation's ``operationId`` is the
    stable key when present, otherwise ``"{action} {address}"``.
    """
    channels = doc.get("channels") if isinstance(doc, dict) else None
    channel = channels.get(address) if isinstance(channels, dict) else None
    op_spec = channel.get(action) if isinstance(channel, dict) else None
    op_id = op_spec.get("operationId") if isinstance(op_spec, dict) else None
    if isinstance(op_id, str) and op_id:
        return op_id
    return f"{action} {address}"


def _coordinate_for(
    change: AsyncApiDiffChange, base_raw: Dict[str, Any], target_raw: Dict[str, Any]
) -> Optional[Tuple[EntityCategory, str]]:
    """Join one tool change onto the canonical ``(category, key)`` it grades, if any.

    Only the coordinates that map cleanly and stably onto a canonical entity are joined — a
    whole **channel** (by its address) and a whole **operation** (AsyncAPI 3 names them at the
    top level; AsyncAPI 2 carries them as ``publish``/``subscribe`` on a channel). Deeper edits
    (inside a payload, a server binding, document metadata) return ``None`` and keep the
    structural grade; those are precisely the changes ``@asyncapi/diff`` tends to leave
    ``unclassified`` anyway.

    Args:
        change: The tool change to locate.
        base_raw: The "from" document (a removed entity is read from here).
        target_raw: The "to" document (an added/edited entity is read from here).

    Returns:
        The canonical ``(EntityCategory, key)`` the change grades, or ``None`` when it does not
        join onto a diffed entity.
    """
    doc = base_raw if change.action == "remove" else target_raw
    path = change.path

    if len(path) == 2 and path[0] == "channels":
        map_name = path[1]
        address = _channel_address(doc, map_name) or map_name
        return (EntityCategory.CHANNEL, address)

    if len(path) == 2 and path[0] == "operations":
        return (EntityCategory.OPERATION, path[1])

    if len(path) == 3 and path[0] == "channels" and path[2] in _V2_OPERATION_ACTIONS:
        address = path[1]
        return (EntityCategory.OPERATION, _v2_operation_key(doc, address, path[2]))

    return None


def _verdict_index(
    diff_result: AsyncApiDiffResult,
    base_raw: Dict[str, Any],
    target_raw: Dict[str, Any],
) -> Dict[Tuple[EntityCategory, str], Tuple[Severity, str]]:
    """Index the tool's authoritative verdicts by the canonical coordinate they grade.

    Only ``breaking`` / ``non-breaking`` changes that join onto a canonical entity are kept
    (``unclassified`` is skipped — see :data:`_TOOL_SEVERITY`); when several changes map to one
    coordinate the worst severity wins. The value carries the severity and the original
    ``change_type`` label so the overlaid grade can name its source rule.
    """
    index: Dict[Tuple[EntityCategory, str], Tuple[Severity, str]] = {}
    for change in diff_result.changes:
        severity = _TOOL_SEVERITY.get(change.change_type)
        if severity is None:
            continue
        coordinate = _coordinate_for(change, base_raw, target_raw)
        if coordinate is None:
            continue
        existing = index.get(coordinate)
        if existing is None or _SEVERITY_RANK[severity] > _SEVERITY_RANK[existing[0]]:
            index[coordinate] = (severity, change.change_type)
    return index


# ===========================================================================
# The AsyncAPI breaking-change classifier
# ===========================================================================


class AsyncApiBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an AsyncAPI diff, sharpening the structural baseline with ``@asyncapi/diff``.

    Registered under ``asyncapi-3`` (this class) and ``asyncapi-2`` (the
    :class:`_AsyncApi2BreakingChangeClassifier` alias below). It **subclasses** the
    format-agnostic :class:`~app.breaking_change.BuiltinBreakingChangeClassifier` and sharpens
    its synchronous :meth:`classify` with the per-side channel, operation, message, payload and
    server rules of :mod:`app.asyncapi_compatibility_rules`, read by :attr:`mode` — the
    always-available, pure grading the sync :func:`app.breaking_change.classify` dispatch
    resolves for an AsyncAPI artifact. A change no rule covers keeps the baseline grade.

    The authoritative ``@asyncapi/diff`` grading is the async :meth:`classify_async`, which
    overlays the tool's verdict onto that sharpened baseline where it joins. It is separate
    because the tool shells out asynchronously (the SPI is sync), and it degrades gracefully
    back to the baseline when the documents or the tool are unavailable.
    """

    format = "asyncapi-3"
    classifier_id = "asyncapi-diff"

    #: The compatibility mode grades are read by when none is passed to the constructor.
    default_mode: ClassVar[str] = "BACKWARD"

    def __init__(self, mode: Optional[str] = None) -> None:
        """Create a classifier that reads per-side grades by ``mode``.

        Args:
            mode: ``BACKWARD`` (default: new consumers against old producers), ``FORWARD`` (old
                consumers against new producers) or ``FULL`` (both), optionally ``_TRANSITIVE``;
                any case.

        Raises:
            ValueError: If ``mode`` is not a known compatibility mode.
        """
        self.mode = coerce_mode(mode or self.default_mode)

    def classify(
        self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi
    ) -> ClassificationResult:
        """Grade every change with the baseline, sharpened by the AsyncAPI side rules.

        Args:
            model_diff: The diff to grade.
            base: The old version.
            target: The new version.

        Returns:
            The result, 1:1 with ``model_diff.changes``; server findings and payload findings on
            messages the diff does not list are in ``unattributed``.
        """
        baseline = [self.classify_change(change, base, target) for change in model_diff.changes]
        report = evaluate(model_diff, base, target)
        graded = [
            self._sharpened(classification, report.by_position[position])
            if position in report.by_position
            else classification
            for position, classification in enumerate(baseline)
        ]
        unattributed = [
            UnattributedFinding(
                severity=severity_under(finding, self.mode),
                rule_id=finding.rule_id,
                rationale=rationale(finding, self.mode),
                shape=shape,
            )
            for shape, finding in report.unattributed
        ]
        return _assemble_result(self, target, graded, unattributed)

    def _sharpened(
        self, baseline: ChangeClassification, found: ChangeFindings
    ) -> ChangeClassification:
        """Grade a change by its rule findings and the baseline grade of its unhandled moves.

        The severity is the worst over the findings (read by :attr:`mode`) and the attribute
        moves no rule handles; the rule id is the worst finding's (the baseline's when an
        unhandled move is worse), and the rationale lists every finding.
        """
        severities = [severity_under(f, self.mode) for f in found.findings]
        worst_finding = _worst(severities)
        first = next(f for f, s in zip(found.findings, severities) if s is worst_finding)
        reasons = list(dict.fromkeys(rationale(f, self.mode) for f in found.findings))
        rule_id = first.rule_id
        severity = worst_finding
        if found.unhandled:
            leftover = _worst([attribute_severity(moved) for moved in found.unhandled])
            names = ", ".join(sorted({moved.field for moved in found.unhandled}))
            reasons.append(f"also changed {names} (graded {leftover.value} by the baseline)")
            if _SEVERITY_RANK[leftover] > _SEVERITY_RANK[worst_finding]:
                severity, rule_id = leftover, f"modified-{leftover.value}"
        return baseline.model_copy(
            update={"severity": severity, "rule_id": rule_id, "rationale": "; ".join(reasons)}
        )

    async def classify_async(
        self,
        model_diff: ModelDiff,
        base: CanonicalApi,
        target: CanonicalApi,
        *,
        runner: Optional[ToolchainRunner] = None,
        timeout: Optional[float] = None,
    ) -> ClassificationResult:
        """Grade ``model_diff`` with the sharpened baseline, overlaid with ``@asyncapi/diff``.

        Starts from the sharpened structural grades (:meth:`classify`), then runs ``@asyncapi/diff`` over the two
        dereferenced documents on :attr:`app.canonical_model.CanonicalApi.raw` and replaces a
        change's grade with the tool's authoritative verdict wherever the tool *classified* the
        change (``breaking`` / ``non-breaking``) **and** it joins onto a canonical entity. Every
        other change — an ``unclassified`` one, a deep edit that does not join, or any change at
        all when the documents/tool are unavailable — keeps the conservative structural grade.

        Args:
            model_diff: The diff to grade (as produced by :func:`app.diff.diff`).
            base: The "from" model; its :attr:`~app.canonical_model.CanonicalApi.raw` is the
                "old" document fed to the tool.
            target: The "to" model; its ``raw`` is the "new" document, and its ``format`` tags
                the result.
            runner: Optional toolchain runner override (injectable for tests).
            timeout: Optional per-call diff timeout in seconds.

        Returns:
            A :class:`~app.breaking_change.ClassificationResult`, 1:1 with and in the same order
            as ``model_diff.changes``.
        """
        baseline = self.classify(model_diff, base, target)

        base_raw = base.raw
        target_raw = target.raw
        if not isinstance(base_raw, dict) or not isinstance(target_raw, dict):
            # No source documents retained (e.g. normalized with include_raw=False): the
            # structural baseline is the best we can do.
            return baseline

        try:
            diff_result = await run_asyncapi_diff(
                base_raw, target_raw, runner=runner, timeout=timeout
            )
        except AsyncApiDiffError as exc:
            logger.warning("asyncapi-diff unavailable; using structural baseline: %s", exc)
            return baseline

        index = _verdict_index(diff_result, base_raw, target_raw)
        if not index:
            return baseline

        classifications = [
            self._overlay(classification, index)
            for classification in baseline.classifications
        ]
        # Findings the tool cannot join (servers, unlisted payloads) stay as the baseline found them.
        return _assemble_result(self, target, classifications, baseline.unattributed)

    def _overlay(
        self,
        classification: ChangeClassification,
        index: Dict[Tuple[EntityCategory, str], Tuple[Severity, str]],
    ) -> ChangeClassification:
        """Replace a structural grade with the tool's verdict when one joins this change."""
        verdict = index.get((classification.category, classification.key))
        if verdict is None:
            return classification
        severity, change_type = verdict
        return ChangeClassification(
            category=classification.category,
            kind=classification.kind,
            key=classification.key,
            severity=severity,
            rule_id=f"asyncapi-diff.{change_type}",
            rationale=(
                f"@asyncapi/diff classified this {classification.kind.value} "
                f"{classification.category.value} as {change_type}."
            ),
        )



class _AsyncApi2BreakingChangeClassifier(
    AsyncApiBreakingChangeClassifier, register=True
):
    """Alias registration of :class:`AsyncApiBreakingChangeClassifier` under ``asyncapi-2``.

    AsyncAPI 2.x and 3.x normalize into the same canonical shape and ``@asyncapi/diff`` ships a
    ruleset for both, so the v2 and v3 grading is identical; this thin subclass only adds the
    second registry key.
    """

    format = "asyncapi-2"


# ===========================================================================
# Convenience entry point
# ===========================================================================


async def classify_asyncapi(
    base: CanonicalApi,
    target: CanonicalApi,
    *,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
    mode: Optional[str] = None,
) -> ClassificationResult:
    """Diff ``base`` → ``target`` and grade it with ``@asyncapi/diff`` in one call.

    The async, tool-backed counterpart of :func:`app.breaking_change.classify_models` for event
    APIs: it computes the canonical :class:`~app.diff.ModelDiff` and grades it via
    :meth:`AsyncApiBreakingChangeClassifier.classify_async`, degrading to the structural
    baseline when the documents or the tool are unavailable.

    Args:
        base: The earlier / "from" model.
        target: The later / "to" model.
        runner: Optional toolchain runner override (injectable for tests).
        timeout: Optional per-call diff timeout in seconds.
        mode: The compatibility mode the side rules are read by (``BACKWARD`` by default).

    Returns:
        The :class:`~app.breaking_change.ClassificationResult` for the diff of the two models.
    """
    model_diff = diff(base, target)
    classifier = AsyncApiBreakingChangeClassifier(mode)
    return await classifier.classify_async(
        model_diff, base, target, runner=runner, timeout=timeout
    )
