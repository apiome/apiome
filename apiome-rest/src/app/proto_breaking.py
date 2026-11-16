"""Protobuf breaking-change classifier — MFI-9.5 (#3768).

The breaking-change classifier SPI (MFI-3.3, :mod:`app.breaking_change`) grades a canonical
:class:`~app.diff.ModelDiff` *breaking-vs-safe* and anticipates a per-format classifier that
*wraps the format's authoritative tool* — for gRPC / Protocol Buffers, that tool is
**``buf breaking``**. This module is the Protobuf provider on that SPI, mirroring how MFI-10.5
wrapped GraphQL-Inspector and MFI-8.4 wrapped ``@asyncapi/diff``.

It has two layers, same shape as those providers:

* **A structural baseline** — :class:`ProtobufBreakingChangeClassifier` subclasses the
  format-agnostic :class:`~app.breaking_change.BuiltinBreakingChangeClassifier`, so its
  *synchronous, pure* :meth:`~app.breaking_change.BreakingChangeClassifier.classify` already
  grades a Protobuf diff from structure alone — and that baseline is already Protobuf-aware: the
  built-in ruleset treats a reused wire ``field_number`` and a changed ``type`` as
  :attr:`~app.breaking_change.Severity.BREAKING` and an added optional field as
  :attr:`~app.breaking_change.Severity.SAFE`. Registered under the ``protobuf`` format key (the
  one the MFI-9.2 normalizer emits), it is what the sync SPI dispatch
  (:func:`app.breaking_change.classify`) resolves for a Protobuf artifact even when no ``buf``
  binary is present. Since XPC-4.3 (#5747) the baseline is graded **per category**: the
  classifier takes a ``category`` (``FILE`` / ``PACKAGE`` / ``WIRE_JSON`` / ``WIRE``, default
  ``WIRE_JSON``) and adds the Protobuf rules of :mod:`app.proto_breaking_rules` — reserved
  numbers and names, deleted fields, ``json_name``, file and package moves, enum value numbers,
  ``oneof`` membership and labels — each with its category in its ``rule_id``
  (``protobuf.wire_json.json-name-changed``) and every category's grade in its rationale.

* **The ``buf breaking`` overlay** — :meth:`ProtobufBreakingChangeClassifier.classify_async`
  (and the module convenience :func:`classify_protobuf`) runs ``buf breaking`` over the new and
  baseline ``.proto`` sources at a **configurable strictness** (default ``WIRE_JSON`` for
  services), then *overlays* its authoritative verdict onto the structural grades. Unlike
  GraphQL-Inspector / ``@asyncapi/diff`` — whose JSON carries a schema-coordinate path that joins
  a verdict back onto a single canonical entity — ``buf breaking``'s machine output is
  *file-scoped* (a proto file plus a line/column and a rule ``type``), so it cannot pin a verdict
  to one canonical key. The overlay therefore applies ``buf``'s verdict at the granularity ``buf``
  provides: it is **authoritative for the overall breaking determination** at the chosen
  strictness, and where it finds the diff wire/JSON-compatible it *caps* the conservative
  structural over-approximations down to :attr:`~app.breaking_change.Severity.DANGEROUS`
  (compatible by the letter, review warranted). The per-change attribution stays the structural
  baseline's. The authoritative, fully-detailed ``buf`` finding list is exposed separately as a
  :class:`ProtoBreakingResult` (from :func:`run_buf_breaking`) for callers that need it.

The tool I/O is **async** (it shells out through :mod:`app.toolchain_runner`), so — exactly as
the GraphQL / AsyncAPI tool-backed grading is layered over the sync SPI — it **degrades
gracefully**: if the ``.proto`` sources are not supplied, or the bundled ``buf`` tool is not
installed, or it errors, the structural baseline stands and a deterministic result is still
returned.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    UnattributedFinding,
    _assemble_result,
    _classify_modified_attribute,
    _worst,
)
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange, ModelDiff, diff
from .proto_breaking_rules import (
    COMPATIBLE_RULE_ID,
    EXPLAINED_FIELD_EXTRAS,
    EXPLAINED_TYPE_EXTRAS,
    category_findings,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BufBreakingCategory",
    "BufBreakingStrictness",
    "DEFAULT_BREAKING_STRICTNESS",
    "BUF_BREAKING_RULE_PREFIX",
    "buf_breaking_module_yaml",
    "ProtoBreakingChange",
    "ProtoBreakingResult",
    "ProtoBreakingError",
    "parse_buf_breaking_output",
    "breaking_changes",
    "run_buf_breaking",
    "ProtobufBreakingChangeClassifier",
    "classify_protobuf",
    "coerce_category",
    "overlay_disagreement",
]


# ===========================================================================
# Strictness (buf breaking rule categories)
# ===========================================================================


class BufBreakingStrictness(str, Enum):
    """How strict ``buf breaking`` should be — its four nested rule categories, widest-last.

    ``buf``'s breaking categories form a containment hierarchy: each adds the changes the next
    *would not* catch. From least to most strict:

    * :attr:`WIRE` — only changes that break **binary wire** compatibility (a field's wire type
      changed, a number reused for an incompatible type). The smallest, runtime-only set.
    * :attr:`WIRE_JSON` — ``WIRE`` plus changes that break **JSON** compatibility (a field/enum
      value renamed, since JSON keys on names). The default for *services*: gRPC speaks both the
      binary and JSON/JSON-transcoded wire formats, so both must stay compatible.
    * :attr:`PACKAGE` — ``WIRE_JSON`` plus per-package source-level breaks (a deleted field/enum
      value/message, a moved declaration) that force consumers in the package to recompile.
    * :attr:`FILE` — the strictest: ``PACKAGE`` plus per-file source breaks. Any
      source-incompatible change is flagged.

    The string values are exactly the category names ``buf`` expects under ``breaking.use`` in
    ``buf.yaml`` (see :func:`buf_breaking_module_yaml`).
    """

    WIRE = "WIRE"
    WIRE_JSON = "WIRE_JSON"
    PACKAGE = "PACKAGE"
    FILE = "FILE"


#: The name the XPC-4.3 classifier API uses for the same four values.
BufBreakingCategory = BufBreakingStrictness

#: The default strictness. ``WIRE_JSON`` is the roadmap's "default for services": gRPC traffic is
#: both binary and (via transcoding) JSON, so both wire formats must stay compatible, while
#: source-level recompiles (``PACKAGE`` / ``FILE``) are not treated as hard breaks by default.
DEFAULT_BREAKING_STRICTNESS = BufBreakingStrictness.WIRE_JSON


def buf_breaking_module_yaml(
    strictness: BufBreakingStrictness = DEFAULT_BREAKING_STRICTNESS,
) -> str:
    """Build the ``buf`` v2 module config that enables ``buf breaking`` at ``strictness``.

    The same single-module layout MFI-9.1 builds with (:data:`app.proto_descriptor.BUF_MODULE_YAML`)
    plus a ``breaking.use`` block naming the one category for ``strictness``. ``buf breaking``
    reads its rule selection from the *input* (new) module's config, so this is written into the
    new module; the ``--against`` baseline module uses the plain build-only config.

    Args:
        strictness: The breaking category to enable. Defaults to
            :data:`DEFAULT_BREAKING_STRICTNESS` (``WIRE_JSON``).

    Returns:
        A ``buf.yaml`` body (version v2) with the breaking category enabled.
    """
    return (
        "version: v2\n"
        "modules:\n"
        "  - path: .\n"
        "breaking:\n"
        "  use:\n"
        f"    - {strictness.value}\n"
    )


# ===========================================================================
# buf breaking output -> typed changes
# ===========================================================================

#: Namespace every ``buf breaking``-sourced change's rule id lives under, so a Protobuf breaking
#: rule groups cleanly and can be told apart from the ``protobuf.buf.*`` lint namespace.
BUF_BREAKING_RULE_PREFIX = "protobuf.buf-breaking"

#: Every change ``buf breaking`` reports is, by construction, a compatibility **break** at the
#: configured strictness — the tool emits nothing for a safe change. So each maps uniformly to
#: :attr:`~app.breaking_change.Severity.BREAKING`; the *strictness* (WIRE → FILE) is what controls
#: which changes count as a break, not a per-finding severity (``buf`` reports none).
_BREAKING_SEVERITY: Severity = Severity.BREAKING

#: ``buf``'s exit code for "breaking changes were found" (as opposed to an operational failure) —
#: the same ``FileAnnotation`` exit code ``buf lint`` uses for violations.
_BUF_BREAKING_VIOLATIONS_EXIT = 100


class ProtoBreakingChange(BaseModel):
    """One incompatibility ``buf breaking`` reported between the baseline and the new ``.proto``s.

    :attr:`rule` is ``buf``'s breaking rule type re-namespaced ``protobuf.buf-breaking.<type>``
    (``FIELD_SAME_TYPE`` → ``protobuf.buf-breaking.field_same_type``) so it groups with the rest
    of the Protobuf rule space. :attr:`severity` is always
    :attr:`~app.breaking_change.Severity.BREAKING` — ``buf breaking`` reports only breaks.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="The proto file the break was reported in.")
    start_line: Optional[int] = Field(
        default=None, description="1-based line of the break in ``path``, when ``buf`` set one."
    )
    start_column: Optional[int] = Field(
        default=None, description="1-based column of the break, when ``buf`` set one."
    )
    rule: str = Field(
        description="The break's namespaced rule id, ``protobuf.buf-breaking.<type>``."
    )
    severity: Severity = Field(
        default=_BREAKING_SEVERITY,
        description="Compatibility severity; always ``breaking`` for a ``buf breaking`` finding.",
    )
    message: str = Field(
        default="", description="``buf``'s human-readable description of the break."
    )


class ProtoBreakingResult(BaseModel):
    """The outcome of comparing two ``.proto`` sets with ``buf breaking``.

    Plain Pydantic, so it round-trips losslessly to JSONB for persistence alongside a version
    diff. :attr:`changes` is in ``buf``'s emission order.
    """

    model_config = ConfigDict(frozen=True)

    strictness: BufBreakingStrictness = Field(
        description="The breaking strictness ``buf`` was run at."
    )
    changes: List[ProtoBreakingChange] = Field(
        default_factory=list, description="Every breaking change ``buf`` reported, in its order."
    )

    @property
    def has_breaking(self) -> bool:
        """Whether ``buf breaking`` reported at least one break at the configured strictness."""
        return bool(self.changes)

    @property
    def breaking(self) -> bool:
        """Alias of :attr:`has_breaking` — the publish-gate signal."""
        return self.has_breaking


class ProtoBreakingError(Exception):
    """Raised when ``buf breaking`` cannot be run (unavailable / times out / operational error).

    A non-zero exit caused by *breaking changes* is **not** an error — those are the findings and
    are returned normally; this is reserved for ``buf`` being absent, timing out, or failing to
    build one of the modules (a syntax error / unresolved import surfaced in ``diagnostics``).
    """

    def __init__(self, message: str, *, diagnostics: Optional[str] = None) -> None:
        self.diagnostics = diagnostics or None
        super().__init__(message if not diagnostics else f"{message}\n{diagnostics}")


def parse_buf_breaking_output(stdout: str) -> List[Dict[str, Any]]:
    """Parse ``buf breaking --error-format=json`` newline-delimited JSON into finding dicts.

    ``buf`` writes one JSON object per breaking change (JSON Lines). Blank lines and any line that
    is not a JSON object are skipped, so a stray banner or progress line never derails parsing.

    Args:
        stdout: The captured ``buf breaking`` standard output.

    Returns:
        The list of parsed finding objects, in emission order.
    """
    findings: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            findings.append(obj)
    return findings


def _breaking_rule_id(raw_type: Any) -> str:
    """Normalize a ``buf`` breaking ``type`` (``FIELD_SAME_TYPE``) into a namespaced rule id.

    ``FIELD_SAME_TYPE`` → ``protobuf.buf-breaking.field_same_type``. A missing/blank type becomes
    ``protobuf.buf-breaking.unknown`` so the change still groups.
    """
    rule = str(raw_type).strip().lower() if raw_type is not None else ""
    return f"{BUF_BREAKING_RULE_PREFIX}.{rule or 'unknown'}"


def _coerce_int(value: Any) -> Optional[int]:
    """Return ``value`` if it is an ``int`` (not ``bool``), else ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def breaking_changes(report: Any) -> List[ProtoBreakingChange]:
    """Map ``buf breaking`` ``--error-format=json`` output into typed :class:`ProtoBreakingChange`\\s.

    Each ``buf`` finding carries ``path`` / ``start_line`` / ``start_column`` / ``type`` /
    ``message``; each becomes one :class:`ProtoBreakingChange` whose ``rule`` is the ``buf`` type
    re-namespaced ``protobuf.buf-breaking.<type>`` at
    :attr:`~app.breaking_change.Severity.BREAKING`.

    Args:
        report: The parsed ``buf breaking`` output. Accepted forms, all degrading gracefully: a
            list of finding mappings; a single such mapping; or the raw newline-delimited JSON
            string. Anything falsy yields no changes.

    Returns:
        One :class:`ProtoBreakingChange` per ``buf`` break, in input order.
    """
    changes: List[ProtoBreakingChange] = []
    for finding in _iter_findings(report):
        if not isinstance(finding, dict):
            continue
        path = finding.get("path")
        changes.append(
            ProtoBreakingChange(
                path=path.strip() if isinstance(path, str) and path.strip() else "(proto)",
                start_line=_coerce_int(finding.get("start_line")),
                start_column=_coerce_int(finding.get("start_column")),
                rule=_breaking_rule_id(finding.get("type")),
                severity=_BREAKING_SEVERITY,
                message=str(finding.get("message", "") or ""),
            )
        )
    return changes


def _iter_findings(report: Any) -> List[Any]:
    """Yield each ``buf breaking`` finding mapping from a list, a single mapping, or raw JSONL."""
    if not report:
        return []
    if isinstance(report, dict):
        return [report]
    if isinstance(report, (str, bytes)):
        text = report.decode("utf-8", "replace") if isinstance(report, bytes) else report
        return list(parse_buf_breaking_output(text))
    try:
        return list(report)
    except TypeError:
        return []


# ===========================================================================
# buf breaking runner (MFI-5.1 toolchain adapter)
# ===========================================================================


def _buf_breaking_spec() -> "Any":
    """Build the ``buf breaking`` :class:`~app.toolchain_runner.ToolSpec`.

    Derived from the bundled ``buf`` tool (so the deployment's ``APIOME_BUF_BIN`` override
    and pinned binary still apply), with a ``breaking`` leading verb and ``parses_json=False`` —
    ``buf``'s ``--error-format=json`` is *newline-delimited* JSON, parsed by
    :func:`parse_buf_breaking_output`, not a single JSON document.
    """
    from .proto_descriptor import BUF_TOOL_KEY
    from .toolchain_packaging import bundled_tool
    from .toolchain_runner import ToolSpec

    tool = bundled_tool(BUF_TOOL_KEY)
    executable = tool.executable if tool is not None else "buf"
    env_override_keys = (tool.env_override_key,) if tool is not None else ()
    default_timeout = tool.default_timeout_seconds if tool is not None else 60.0
    return ToolSpec(
        key=BUF_TOOL_KEY,
        executable=executable,
        description="buf breaking → breaking changes (MFI-9.5).",
        base_args=("breaking",),
        default_timeout_seconds=default_timeout,
        env_override_keys=env_override_keys,
        parses_json=False,
    )


async def run_buf_breaking(
    target_files: "Any",
    against_files: "Any",
    *,
    strictness: BufBreakingStrictness = DEFAULT_BREAKING_STRICTNESS,
    runner: "Any" = None,
    timeout: Optional[float] = None,
    policy: "Any" = None,
) -> ProtoBreakingResult:
    """Compare two ``.proto`` sets with ``buf breaking`` and return its breaking changes.

    The *new* (``target_files``) and *baseline* (``against_files``) sources are materialised into
    two private scratch ``buf`` modules — the new one carrying a ``buf.yaml`` that enables the one
    breaking category for ``strictness`` (``buf`` reads breaking rules from the input module), the
    baseline one carrying the plain build-only config — and
    ``buf breaking <new> --against <baseline> --error-format=json`` is run through the MFI-5.1
    toolchain runner (no-network sandbox). Breaking changes make ``buf`` exit non-zero (code 100);
    that is the *normal* outcome here — its JSON findings are read off stdout and returned. An
    operational failure (``buf`` absent, a timeout, a proto that does not build) raises
    :class:`ProtoBreakingError` instead.

    Args:
        target_files: The **new** ``.proto`` files (each
            :class:`~app.proto_descriptor.ProtoFile`). Must be non-empty.
        against_files: The **baseline** ``.proto`` files to compare against. Must be non-empty.
        strictness: The breaking strictness (see :class:`BufBreakingStrictness`). Defaults to
            :data:`DEFAULT_BREAKING_STRICTNESS` (``WIRE_JSON``).
        runner: The toolchain runner to use; defaults to the shared
            :data:`app.toolchain_runner.default_runner`. Injectable for tests.
        timeout: Optional per-call timeout in seconds; falls back to the tool/service default.
        policy: Optional sandbox policy override; falls back to the runner's default.

    Returns:
        A :class:`ProtoBreakingResult` (empty :attr:`~ProtoBreakingResult.changes` when the new
        set is compatible with the baseline at ``strictness``).

    Raises:
        ProtoBreakingError: If either file set is empty, ``buf`` is unavailable in this runtime
            (MFI-5.2), it times out, or it fails to build a module (syntax error / unresolved
            import).
        app.proto_descriptor.ProtoCompileError: If a file carries an unsafe/duplicate path.
    """
    # Imported lazily so importing this module (e.g. for classifier registration on the sync SPI
    # path) never pulls in the toolchain/descriptor machinery.
    from .proto_descriptor import BUF_MODULE_YAML, materialize_proto_module
    from .toolchain_runner import (
        ToolchainError,
        ToolExecutionError,
        ToolNotAvailableError,
        ToolTimeoutError,
        default_runner,
    )

    target_list = list(target_files)
    against_list = list(against_files)
    if not target_list:
        raise ProtoBreakingError("At least one new .proto file is required to compare")
    if not against_list:
        raise ProtoBreakingError("At least one baseline .proto file is required to compare against")

    active_runner = runner if runner is not None else default_runner
    spec = _buf_breaking_spec()

    with tempfile.TemporaryDirectory(prefix="apiome-proto-breaking-") as scratch:
        target_root = os.path.join(scratch, "target")
        against_root = os.path.join(scratch, "against")
        os.makedirs(target_root, exist_ok=True)
        os.makedirs(against_root, exist_ok=True)
        materialize_proto_module(
            target_root, target_list, buf_yaml=buf_breaking_module_yaml(strictness)
        )
        materialize_proto_module(against_root, against_list, buf_yaml=BUF_MODULE_YAML)
        args = [target_root, "--against", against_root, "--error-format=json"]

        try:
            result = await active_runner.run_spec(spec, args, timeout=timeout, policy=policy)
        except ToolNotAvailableError as exc:
            raise ProtoBreakingError(
                "The 'buf' tool is not available in this runtime; protobuf/gRPC breaking-change "
                "detection is unavailable here (see the bundled toolchain packaging, MFI-5.2)."
            ) from exc
        except ToolTimeoutError as exc:
            raise ProtoBreakingError(f"buf breaking timed out: {exc}") from exc
        except ToolExecutionError as exc:
            # A non-zero exit is buf's signal that it found breaking changes (exit 100): the
            # findings are the JSON on stdout. Anything else (a build/config failure) has no
            # parseable findings — surface its diagnostics as an operational error.
            findings = parse_buf_breaking_output(exc.stdout)
            if findings or exc.exit_code == _BUF_BREAKING_VIOLATIONS_EXIT:
                return ProtoBreakingResult(
                    strictness=strictness, changes=breaking_changes(findings)
                )
            diagnostics = (exc.stderr.strip() or exc.stdout.strip()) or None
            raise ProtoBreakingError(
                "buf breaking failed to process the supplied .proto files",
                diagnostics=diagnostics,
            ) from exc
        except ToolchainError as exc:
            raise ProtoBreakingError(f"buf breaking failed: {exc}") from exc

        # Exit 0 → no breaking changes at this strictness.
        return ProtoBreakingResult(
            strictness=strictness, changes=breaking_changes(result.stdout)
        )


# ===========================================================================
# The Protobuf breaking-change classifier
# ===========================================================================


def coerce_category(value: Any) -> BufBreakingStrictness:
    """Coerce a category name (any case) or enum member into a :class:`BufBreakingStrictness`.

    Args:
        value: ``"wire_json"``, ``"FILE"``, a member, or ``None`` for the default.

    Returns:
        The category; :data:`DEFAULT_BREAKING_STRICTNESS` for ``None`` / blank.

    Raises:
        ValueError: If ``value`` names no category.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_BREAKING_STRICTNESS
    if isinstance(value, BufBreakingStrictness):
        return value
    name = str(value).strip().upper()
    try:
        return BufBreakingStrictness(name)
    except ValueError:
        choices = ", ".join(c.value for c in BufBreakingStrictness)
        raise ValueError(f"Unknown buf breaking category {value!r}; expected one of {choices}") from None


def _without(extras: Any, keys: frozenset) -> Dict[str, Any]:
    """An ``extras`` dict with ``keys`` removed (``{}`` for anything that is not a dict)."""
    return {k: v for k, v in extras.items() if k not in keys} if isinstance(extras, dict) else {}


def _same_core(before: Any, after: Any) -> bool:
    """Whether two ``TypeRef`` dicts name the same element type (nullability / list ignored)."""

    def core(ref: Any) -> Any:
        while isinstance(ref, dict) and isinstance(ref.get("item"), dict):
            ref = ref["item"]
        return ref.get("name") if isinstance(ref, dict) else None

    return core(before) == core(after)


#: Label rules whose finding accounts for a ``type`` move that only changes nullability / list
#: wrapping (``optional`` → ``repeated``, ``required`` → ``optional``).
_LABEL_SLUGS = frozenset({"cardinality-changed", "required-changed", "presence-changed"})


class ProtobufBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a Protobuf diff per ``buf breaking`` category, optionally confirmed by ``buf``.

    Registered under the ``protobuf`` format key (the one the MFI-9.2 normalizer emits). It
    **subclasses** the format-agnostic
    :class:`~app.breaking_change.BuiltinBreakingChangeClassifier` and sharpens it with the
    Protobuf rules of :mod:`app.proto_breaking_rules` (XPC-4.3): reserved numbers and names,
    deleted fields, ``json_name``, file and package moves, enum value numbers, ``oneof``
    membership and labels, each graded at :attr:`category` (``WIRE`` / ``WIRE_JSON`` /
    ``PACKAGE`` / ``FILE``, default ``WIRE_JSON``). Every grade's rationale starts with the
    category it was taken at, and a Protobuf finding's rationale also lists its grade under the
    other three.

    The synchronous :meth:`classify` needs no ``buf`` binary — it is what the sync
    :func:`app.breaking_change.classify` dispatch resolves for a Protobuf artifact. The async
    :meth:`classify_async` additionally runs ``buf breaking`` at the same category and overlays
    its verdict, degrading back to :meth:`classify` when the sources or the tool are missing.
    """

    format = "protobuf"
    classifier_id = "buf-breaking"

    def __init__(self, category: Any = None) -> None:
        """Create a classifier that grades at ``category``.

        Args:
            category: A :class:`BufBreakingStrictness` or its name in any case; ``None`` selects
                :data:`DEFAULT_BREAKING_STRICTNESS` (``WIRE_JSON``).

        Raises:
            ValueError: If ``category`` names no category.
        """
        self.category = coerce_category(category)

    def classify(
        self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi
    ) -> ClassificationResult:
        """Grade every change at :attr:`category` with the baseline and the Protobuf rules.

        A change a Protobuf finding joins takes the worst of its findings' grades at the
        category, plus — for an added or modified change — the baseline grade of whatever else
        moved on it. A modified change whose every movement the rules explain without a finding
        (a reservation added) is safe. A finding that joins no change (a message moved to
        another file, which is not part of the diff) is reported in ``unattributed``.

        Args:
            model_diff: The diff to grade (as produced by :func:`app.diff.diff`).
            base: The "from" model.
            target: The "to" model.

        Returns:
            The :class:`~app.breaking_change.ClassificationResult`, 1:1 with
            ``model_diff.changes``.
        """
        category = self.category.value
        found = category_findings(base, target)
        index: Dict[tuple, List[int]] = {}
        for position, change in enumerate(model_diff.changes):
            index.setdefault((change.category, change.key), []).append(position)

        joined: Dict[int, List[Any]] = {}
        unattributed: List[UnattributedFinding] = []
        for finding in found.findings:
            positions = sorted({p for join in finding.joins for p in index.get(join, [])})
            for position in positions:
                joined.setdefault(position, []).append(finding)
            if not positions:
                unattributed.append(
                    UnattributedFinding(
                        severity=finding.severity(category),
                        rule_id=finding.rule_id,
                        rationale=finding.rationale(category),
                        shape=finding.subject,
                    )
                )

        graded = [
            self._grade_change(change, joined.get(position, []), found, base, target)
            for position, change in enumerate(model_diff.changes)
        ]
        return _assemble_result(self, target, graded, unattributed)

    def _grade_change(
        self,
        change: EntityChange,
        findings: List[Any],
        found: Any,
        base: CanonicalApi,
        target: CanonicalApi,
    ) -> ChangeClassification:
        """Grade one change from its joined findings and the baseline of what they leave."""
        category = self.category.value
        baseline = self.classify_change(change, base, target)
        residual = self._residual(change, findings, found, baseline)
        if not findings:
            if residual is None:
                return baseline.model_copy(
                    update={
                        "severity": Severity.SAFE,
                        "rule_id": COMPATIBLE_RULE_ID,
                        "rationale": f"[{category}] {change.key}: only reservations or oneof "
                        "declarations moved; compatible under every category",
                    }
                )
            return baseline.model_copy(update={"rationale": f"[{category}] {baseline.rationale}"})

        severities = [f.severity(category) for f in findings]
        if residual is not None:
            severities.append(residual)
        worst = _worst(severities)
        lead = next((f for f in findings if f.severity(category) is worst), None)
        reasons = list(dict.fromkeys(f.rationale(category) for f in findings))
        if lead is None:  # the baseline residue is worse than every finding
            reasons.append(f"[{category}] {baseline.rationale}")
        return baseline.model_copy(
            update={
                "severity": worst,
                "rule_id": lead.rule_id if lead is not None else baseline.rule_id,
                "rationale": "; ".join(reasons),
            }
        )

    @staticmethod
    def _residual(
        change: EntityChange, findings: List[Any], found: Any, baseline: ChangeClassification
    ) -> Optional[Severity]:
        """The baseline grade of the part of ``change`` no Protobuf rule explains.

        Returns:
            ``None`` when the rules explain all of it (a removal a finding joined, or a
            modification confined to the explained ``extras`` keys); otherwise the baseline's
            severity over the remaining attribute moves (an addition keeps its baseline grade).
        """
        if change.kind is ChangeKind.REMOVED:
            return None if findings else baseline.severity
        if change.kind is ChangeKind.ADDED or not change.fields:
            return baseline.severity
        if change.category not in (EntityCategory.FIELD, EntityCategory.TYPE):
            return baseline.severity
        labelled = any(f.slug in _LABEL_SLUGS for f in findings)
        explained = (
            EXPLAINED_FIELD_EXTRAS if change.category is EntityCategory.FIELD else EXPLAINED_TYPE_EXTRAS
        )
        left: List[Severity] = []
        for moved in change.fields:
            if moved.field == "extras" and _without(moved.before, explained) == _without(
                moved.after, explained
            ):
                continue
            if moved.field == "type" and labelled and _same_core(moved.before, moved.after):
                continue
            if moved.field == "enum_values" and change.key in found.explained_enum_values:
                continue
            left.append(_classify_modified_attribute(moved))
        return _worst(left) if left else None

    async def classify_async(
        self,
        model_diff: ModelDiff,
        base: CanonicalApi,
        target: CanonicalApi,
        *,
        against_files: "Any" = None,
        target_files: "Any" = None,
        strictness: Any = None,
        runner: "Any" = None,
        timeout: Optional[float] = None,
        policy: "Any" = None,
    ) -> ClassificationResult:
        """Grade ``model_diff`` structurally, overlaid with ``buf breaking`` at the same category.

        Starts from :meth:`classify` at the category, then — when the new and baseline
        ``.proto`` sources are supplied — runs ``buf breaking`` at that category and overlays
        its authoritative verdict:

        * If ``buf`` reports **any** break, the structural per-change grades are kept (``buf``'s
          file-scoped output cannot pin a verdict to one canonical key) and each ``buf`` finding
          is added to ``unattributed`` as breaking, so the overall severity is breaking.
        * If ``buf`` reports **none**, any structural
          :attr:`~app.breaking_change.Severity.BREAKING` grade is capped to
          :attr:`~app.breaking_change.Severity.DANGEROUS`.

        Either way, when ``buf`` and the structural rules disagree about whether the diff
        breaks, the rationales say so (see :func:`overlay_disagreement`).

        Every fall-through case — no sources supplied, or the ``buf`` tool unavailable/erroring —
        keeps the structural grades unchanged, and a deterministic result is still returned.

        Args:
            model_diff: The diff to grade (as produced by :func:`app.diff.diff`).
            base: The "from" / earlier model; its ``.proto`` sources are ``against_files``.
            target: The "to" / later model; its ``.proto`` sources are ``target_files``, and its
                ``format`` tags the result.
            against_files: The baseline (``base``) ``.proto`` files
                (:class:`~app.proto_descriptor.ProtoFile`\\s). When omitted, the overlay is skipped.
            target_files: The new (``target``) ``.proto`` files. When omitted, the overlay is
                skipped.
            strictness: The category to grade and run ``buf`` at; ``None`` keeps
                :attr:`category`.
            runner: Optional toolchain runner override (injectable for tests).
            timeout: Optional per-call breaking timeout in seconds.
            policy: Optional sandbox policy override.

        Returns:
            A :class:`~app.breaking_change.ClassificationResult`, 1:1 with and in the same order as
            ``model_diff.changes``.
        """
        category = self.category if strictness is None else coerce_category(strictness)
        classifier = self if category is self.category else type(self)(category)
        baseline = classifier.classify(model_diff, base, target)

        if not against_files or not target_files:
            # No source protos to compare; the structural baseline is the best we can do.
            return baseline

        try:
            result = await run_buf_breaking(
                target_files,
                against_files,
                strictness=category,
                runner=runner,
                timeout=timeout,
                policy=policy,
            )
        except ProtoBreakingError as exc:
            logger.warning(
                "buf breaking unavailable; using structural baseline: %s", exc
            )
            return baseline

        return classifier._overlay(baseline, result, target)

    def _overlay(
        self,
        baseline: ClassificationResult,
        result: ProtoBreakingResult,
        target: CanonicalApi,
    ) -> ClassificationResult:
        """Overlay ``buf breaking``'s authoritative verdict onto the structural ``baseline``."""
        category = self.category.value
        disagreement = overlay_disagreement(baseline, result)
        note = f" ({disagreement})" if disagreement else ""
        unattributed = list(baseline.unattributed)
        if result.has_breaking:
            # buf confirms a break at this category. Keep the structural per-change grades and
            # list buf's findings, which make the overall verdict breaking (buf is authoritative
            # even if its file-scoped finding did not join the change the structural pass flagged).
            classifications = list(baseline.classifications)
            for change in result.changes:
                where = f"{change.path}:{change.start_line}" if change.start_line else change.path
                unattributed.append(
                    UnattributedFinding(
                        severity=change.severity,
                        rule_id=change.rule,
                        rationale=f"[{category}] buf breaking at {where}: {change.message}{note}",
                        shape=change.path,
                    )
                )
        else:
            # buf authoritatively finds the new set compatible with the baseline at this
            # category: nothing is a hard break, so cap structural over-approximations.
            classifications = [
                self._cap_dangerous(classification, note)
                for classification in baseline.classifications
            ]
            unattributed = [self._cap_unattributed(f, note) for f in unattributed]
        return _assemble_result(self, target, classifications, unattributed)

    def _cap_dangerous(
        self, classification: ChangeClassification, note: str = ""
    ) -> ChangeClassification:
        """Cap a structural :attr:`Severity.BREAKING` grade down to ``DANGEROUS``.

        Used when ``buf breaking`` authoritatively found no break at the configured category: a
        change the structural rules called breaking is, per ``buf``, compatible by the letter
        (e.g. a wire-compatible field deletion) — so it is downgraded to ``DANGEROUS`` (review
        warranted). Safe/dangerous grades are returned unchanged.
        """
        if classification.severity is not Severity.BREAKING:
            return classification
        return ChangeClassification(
            category=classification.category,
            kind=classification.kind,
            key=classification.key,
            severity=Severity.DANGEROUS,
            rule_id=f"{self.classifier_id}.wire-compatible",
            rationale=(
                f"[{self.category.value}] buf breaking found this {classification.kind.value} "
                f"{classification.category.value} compatible; review warranted but it "
                f"is not a hard break at this category (structural rule "
                f"{classification.rule_id}){note}"
            ),
        )

    def _cap_unattributed(self, finding: UnattributedFinding, note: str) -> UnattributedFinding:
        """Cap a structural unattributed :attr:`Severity.BREAKING` finding to ``DANGEROUS``."""
        if finding.severity is not Severity.BREAKING:
            return finding
        return finding.model_copy(
            update={"severity": Severity.DANGEROUS, "rationale": finding.rationale + note}
        )


def overlay_disagreement(
    structural: ClassificationResult, result: ProtoBreakingResult
) -> Optional[str]:
    """Say whether ``buf breaking`` and the structural rules disagree about a diff breaking.

    Args:
        structural: The structural grading (:meth:`ProtobufBreakingChangeClassifier.classify`)
            at the category ``buf`` ran at.
        result: ``buf breaking``'s result at that category.

    Returns:
        ``None`` when both call the diff breaking or both call it compatible; otherwise one
        sentence naming which side found the break and the category.
    """
    if structural.breaking == result.has_breaking:
        return None
    category = result.strictness.value
    if result.has_breaking:
        rules = ", ".join(sorted({c.rule for c in result.changes}))
        return f"disagreement: buf breaking finds a {category} break ({rules}) the structural rules grade non-breaking"
    rules = ", ".join(
        sorted(
            {c.rule_id for c in structural.classifications if c.severity is Severity.BREAKING}
            | {f.rule_id for f in structural.unattributed if f.severity is Severity.BREAKING}
        )
    )
    return f"disagreement: the structural rules find a {category} break ({rules}) buf breaking does not"


# ===========================================================================
# Convenience entry point
# ===========================================================================


async def classify_protobuf(
    base: CanonicalApi,
    target: CanonicalApi,
    *,
    against_files: "Any",
    target_files: "Any",
    strictness: Any = None,
    runner: "Any" = None,
    timeout: Optional[float] = None,
    policy: "Any" = None,
) -> ClassificationResult:
    """Diff ``base`` → ``target`` and grade it with ``buf breaking`` in one call.

    The async, tool-backed counterpart of :func:`app.breaking_change.classify_models` for
    Protobuf: it computes the canonical :class:`~app.diff.ModelDiff` and grades it via
    :meth:`ProtobufBreakingChangeClassifier.classify_async`, degrading to the structural baseline
    when the ``.proto`` sources or the tool are unavailable.

    Args:
        base: The earlier / "from" model.
        target: The later / "to" model.
        against_files: The baseline (``base``) ``.proto`` files
            (:class:`~app.proto_descriptor.ProtoFile`\\s).
        target_files: The new (``target``) ``.proto`` files.
        strictness: The category to grade and run ``buf`` at (a :class:`BufBreakingStrictness`
            or its name); ``None`` grades at :data:`DEFAULT_BREAKING_STRICTNESS`.
        runner: Optional toolchain runner override (injectable for tests).
        timeout: Optional per-call breaking timeout in seconds.
        policy: Optional sandbox policy override.

    Returns:
        The :class:`~app.breaking_change.ClassificationResult` for the diff of the two models.
    """
    model_diff = diff(base, target)
    classifier = ProtobufBreakingChangeClassifier(strictness)
    return await classifier.classify_async(
        model_diff,
        base,
        target,
        against_files=against_files,
        target_files=target_files,
        runner=runner,
        timeout=timeout,
        policy=policy,
    )
