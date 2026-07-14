"""Shared output parsers for external-linter adapters (CLX-2.1, #4851).

External tools emit JSON documents, newline-delimited JSON (JSONL), or SARIF 2.1.
This module is the single parse seam those adapters share: valid structured input
becomes raw finding mappings; malformed input raises :class:`AdapterOutputError`
so the runner can record a ``failed`` evidence outcome instead of inventing findings.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "AdapterOutputError",
    "NormalizedToolFinding",
    "parse_json_document",
    "parse_jsonl",
    "parse_sarif",
    "parse_tool_output",
    "OUTPUT_FORMAT_JSON",
    "OUTPUT_FORMAT_JSONL",
    "OUTPUT_FORMAT_SARIF",
    "OUTPUT_FORMATS",
]

OUTPUT_FORMAT_JSON = "json"
OUTPUT_FORMAT_JSONL = "jsonl"
OUTPUT_FORMAT_SARIF = "sarif"
OUTPUT_FORMATS = (OUTPUT_FORMAT_JSON, OUTPUT_FORMAT_JSONL, OUTPUT_FORMAT_SARIF)


class AdapterOutputError(ValueError):
    """Raised when tool stdout cannot be parsed as the declared output format.

    Carries a short ``reason`` so callers can stamp evidence diagnostics without
    dumping the raw (possibly huge) stdout into logs.
    """

    def __init__(self, format_name: str, reason: str) -> None:
        self.format_name = format_name
        self.reason = reason
        super().__init__(f"Invalid {format_name} tool output: {reason}")


#: One normalized finding mapping produced by the parsers. Keys are stable so
#: adapters and evidence builders can read them without format-specific branching.
NormalizedToolFinding = Dict[str, Any]


def parse_json_document(stdout: str) -> List[NormalizedToolFinding]:
    """Parse a single JSON document into a list of finding-like mappings.

    Accepted shapes:
    * a JSON array of objects → each object is one finding;
    * a JSON object with a ``findings`` / ``results`` / ``issues`` array → that array;
    * a single JSON object → one-element list.

    Args:
        stdout: Captured tool standard output.

    Returns:
        A list of mapping objects (empty when the document is an empty array).

    Raises:
        AdapterOutputError: When ``stdout`` is not valid JSON or does not yield mappings.
    """
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        doc = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise AdapterOutputError(OUTPUT_FORMAT_JSON, f"JSON decode failed: {exc}") from exc

    if isinstance(doc, list):
        return _require_dict_list(doc, OUTPUT_FORMAT_JSON)
    if isinstance(doc, dict):
        for key in ("findings", "results", "issues"):
            nested = doc.get(key)
            if isinstance(nested, list):
                return _require_dict_list(nested, OUTPUT_FORMAT_JSON)
        return [doc]
    raise AdapterOutputError(
        OUTPUT_FORMAT_JSON,
        f"expected object or array, got {type(doc).__name__}",
    )


def parse_jsonl(stdout: str) -> List[NormalizedToolFinding]:
    """Parse newline-delimited JSON (JSON Lines) into finding mappings.

    Blank lines are skipped. Unlike the tolerant Buf-era helper, a non-blank line
    that is not a JSON object is a hard error — conformance depends on noticing
    malformed output rather than silently dropping it.

    Args:
        stdout: Captured tool standard output.

    Returns:
        The list of parsed objects, in emission order.

    Raises:
        AdapterOutputError: When any non-blank line fails to parse as a JSON object.
    """
    findings: List[NormalizedToolFinding] = []
    for line_no, raw_line in enumerate((stdout or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise AdapterOutputError(
                OUTPUT_FORMAT_JSONL,
                f"line {line_no}: JSON decode failed: {exc}",
            ) from exc
        if not isinstance(obj, dict):
            raise AdapterOutputError(
                OUTPUT_FORMAT_JSONL,
                f"line {line_no}: expected object, got {type(obj).__name__}",
            )
        findings.append(obj)
    return findings


def parse_jsonl_tolerant(stdout: str) -> List[NormalizedToolFinding]:
    """Parse JSONL skipping blank lines and non-object lines (Buf lint compatibility).

    Buf historically ignores progress banners. Prefer :func:`parse_jsonl` for new
    adapters; this helper preserves the Buf mapping path.

    Args:
        stdout: Captured tool standard output.

    Returns:
        Parsed finding objects; malformed lines are skipped (never raises).
    """
    findings: List[NormalizedToolFinding] = []
    for line in (stdout or "").splitlines():
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


def parse_sarif(stdout: str) -> List[NormalizedToolFinding]:
    """Parse a SARIF 2.1 document into normalized findings preserving source rule IDs.

    Walks ``runs[].results[]``. For each result:

    * ``ruleId`` (or ``rule.id``) is kept verbatim as ``rule_id``;
    * ``message.text`` (or string message) → ``message``;
    * ``level`` → ``severity`` (``error`` / ``warning`` / ``note``→``info`` / ``none``→``info``);
    * first ``locations[].physicalLocation`` supplies ``path``, ``start_line``, ``start_column``.

    Args:
        stdout: Captured SARIF JSON text.

    Returns:
        One normalized finding dict per SARIF result.

    Raises:
        AdapterOutputError: When the document is not SARIF-shaped JSON.
    """
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        doc = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise AdapterOutputError(OUTPUT_FORMAT_SARIF, f"JSON decode failed: {exc}") from exc
    if not isinstance(doc, dict):
        raise AdapterOutputError(
            OUTPUT_FORMAT_SARIF, f"expected object, got {type(doc).__name__}"
        )
    runs = doc.get("runs")
    if runs is None:
        raise AdapterOutputError(OUTPUT_FORMAT_SARIF, "missing 'runs' array")
    if not isinstance(runs, list):
        raise AdapterOutputError(
            OUTPUT_FORMAT_SARIF, f"'runs' must be an array, got {type(runs).__name__}"
        )

    findings: List[NormalizedToolFinding] = []
    for run_index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise AdapterOutputError(
                OUTPUT_FORMAT_SARIF,
                f"runs[{run_index}] must be an object",
            )
        results = run.get("results") or []
        if not isinstance(results, list):
            raise AdapterOutputError(
                OUTPUT_FORMAT_SARIF,
                f"runs[{run_index}].results must be an array",
            )
        for result_index, result in enumerate(results):
            if not isinstance(result, dict):
                raise AdapterOutputError(
                    OUTPUT_FORMAT_SARIF,
                    f"runs[{run_index}].results[{result_index}] must be an object",
                )
            findings.append(_normalize_sarif_result(result))
    return findings


def parse_tool_output(stdout: str, output_format: str) -> List[NormalizedToolFinding]:
    """Dispatch to the parser for ``output_format``.

    Args:
        stdout: Captured tool standard output.
        output_format: One of :data:`OUTPUT_FORMATS`.

    Returns:
        Normalized finding mappings.

    Raises:
        AdapterOutputError: On malformed output.
        ValueError: When ``output_format`` is unknown.
    """
    if output_format == OUTPUT_FORMAT_JSON:
        return parse_json_document(stdout)
    if output_format == OUTPUT_FORMAT_JSONL:
        return parse_jsonl(stdout)
    if output_format == OUTPUT_FORMAT_SARIF:
        return parse_sarif(stdout)
    raise ValueError(f"Unknown output format {output_format!r}; expected one of {OUTPUT_FORMATS}")


def envelope_from_tool_finding(
    finding: Mapping[str, Any],
    *,
    default_severity: str = "warning",
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Project a normalized tool finding into the CLX-1.1 evidence envelope shape.

    Preserves the source ``rule_id`` and structured location. Unknown fields are ignored.

    Args:
        finding: A mapping from :func:`parse_sarif` / JSON / JSONL (or adapter-normalized).
        default_severity: Severity used when the finding carries none.
        category: Optional category stamp for the envelope.

    Returns:
        Envelope dict with ``rule_id``, ``message``, ``severity``, ``confidence``,
        ``category``, ``location``, ``remediation``, ``source_fingerprint``.
    """
    rule_id = finding.get("rule_id")
    if rule_id is None:
        rule_id = finding.get("ruleId") or finding.get("type") or finding.get("rule")
    message = finding.get("message")
    if isinstance(message, dict):
        message = message.get("text") or message.get("markdown") or str(message)
    severity = finding.get("severity") or finding.get("level") or default_severity
    severity = _normalize_severity(str(severity) if severity is not None else default_severity)

    path = finding.get("path")
    line = finding.get("start_line")
    if line is None:
        line = finding.get("line")
    column = finding.get("start_column")
    if column is None:
        column = finding.get("column")
    location: Dict[str, Any] = {}
    if path is not None:
        location["path"] = path
    if isinstance(line, int):
        location["start_line"] = line
    if isinstance(column, int):
        location["start_column"] = column
    if not location and finding.get("location") and isinstance(finding["location"], dict):
        location = dict(finding["location"])

    source_fp = finding.get("source_fingerprint")
    if source_fp is None and rule_id is not None:
        loc_key = json.dumps(location, sort_keys=True, separators=(",", ":"), default=str)
        source_fp = f"{rule_id}|{loc_key}|{message or ''}"

    return {
        "rule_id": str(rule_id) if rule_id is not None else None,
        "message": str(message) if message is not None else None,
        "severity": severity,
        "confidence": finding.get("confidence") or "medium",
        "category": category if category is not None else finding.get("category"),
        "location": location or None,
        "remediation": finding.get("remediation") or finding.get("helpUri"),
        "source_fingerprint": source_fp,
    }


def _require_dict_list(items: Sequence[Any], format_name: str) -> List[NormalizedToolFinding]:
    out: List[NormalizedToolFinding] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise AdapterOutputError(
                format_name,
                f"item[{index}] must be an object, got {type(item).__name__}",
            )
        out.append(item)
    return out


def _normalize_sarif_result(result: Mapping[str, Any]) -> NormalizedToolFinding:
    rule_id = result.get("ruleId")
    if rule_id is None:
        rule = result.get("rule")
        if isinstance(rule, dict):
            rule_id = rule.get("id")
    message = result.get("message")
    if isinstance(message, dict):
        message = message.get("text") or message.get("markdown")
    elif message is not None and not isinstance(message, str):
        message = str(message)

    path: Optional[str] = None
    start_line: Optional[int] = None
    start_column: Optional[int] = None
    locations = result.get("locations") or []
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, dict):
            phys = first.get("physicalLocation") or {}
            if isinstance(phys, dict):
                artifact = phys.get("artifactLocation") or {}
                if isinstance(artifact, dict):
                    uri = artifact.get("uri")
                    if isinstance(uri, str):
                        path = uri
                region = phys.get("region") or {}
                if isinstance(region, dict):
                    if isinstance(region.get("startLine"), int):
                        start_line = region["startLine"]
                    if isinstance(region.get("startColumn"), int):
                        start_column = region["startColumn"]

    normalized: NormalizedToolFinding = {
        "rule_id": rule_id,
        "message": message,
        "severity": _normalize_severity(str(result.get("level") or "warning")),
        "path": path,
        "start_line": start_line,
        "start_column": start_column,
    }
    help_uri = result.get("helpUri")
    if help_uri is not None:
        normalized["remediation"] = help_uri
    return normalized


def _normalize_severity(level: str) -> str:
    lowered = level.strip().lower()
    if lowered in ("error", "warning", "info"):
        return lowered
    if lowered in ("note", "none"):
        return "info"
    if lowered == "fail":
        return "error"
    return "warning"
