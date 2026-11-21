"""CloudEvents 1.0 spec rules for an emitted structured-mode document — COA-3.4 (#7055).

The CloudEvents import parser (:mod:`app.cloudevents_parser`) is deliberately lenient: it reads
what a producer wrote, so it accepts an event with no ``id``, any ``specversion`` string, or
both ``data`` and ``data_base64``. An *export* has to meet the specification itself, so the
post-emit validator (:func:`app.export_validation.validate_emitted_artifact`, ``cloudevents``)
checks each emitted event against the rules of the CloudEvents 1.0 core specification and its
JSON event format, then re-imports the file.

The rules checked (each finding carries its rule id as ``rule``):

* ``cloudevents.document`` — the file is a JSON object (one event) or a non-empty array of
  objects (a batch, JSON format §4);
* ``cloudevents.specversion`` — ``specversion`` is ``"1.0"`` (``"0.3"`` is accepted for an
  event imported at that version and written back as read);
* ``cloudevents.required`` — ``id``, ``source`` and ``type`` are non-empty strings;
* ``cloudevents.attribute-type`` — the optional attributes have their spec types:
  ``subject`` / ``datacontenttype`` / ``dataschema`` non-empty strings, ``time`` an RFC 3339
  timestamp, ``data_base64`` a string;
* ``cloudevents.data-exclusive`` — ``data`` and ``data_base64`` are not both present;
* ``cloudevents.attribute-name`` — every other member is an extension attribute whose name is
  lower-case ASCII letters and digits (core §3.1.1);
* ``cloudevents.extension-value`` — an extension's value is a string, an integer, a boolean or
  ``null`` (the JSON format has no object, array or fractional attribute type).

Pure Python and deterministic; no network, no toolchain.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

__all__ = ["SUPPORTED_SPEC_VERSIONS", "cloudevents_spec_problems"]

#: The ``specversion`` values an export may carry. ``1.0`` is current; ``0.3`` round-trips an
#: event imported at that version.
SUPPORTED_SPEC_VERSIONS = ("1.0", "0.3")

# JSON format members that are not context attributes.
_DATA_MEMBERS = frozenset({"data", "data_base64"})
# Context attributes with a spec-defined type (core §3.1, plus the 0.3 ``datacontentencoding``).
_REQUIRED = ("id", "source", "type")
_OPTIONAL_STRINGS = ("subject", "datacontenttype", "dataschema", "datacontentencoding")
_KNOWN = frozenset({"specversion", "time", *_REQUIRED, *_OPTIONAL_STRINGS})
_ATTRIBUTE_NAME = re.compile(r"^[a-z0-9]+$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


def _problem(rule: str, message: str, *, file: Optional[str], path: str) -> Dict[str, Any]:
    """One finding in the shape :mod:`app.export_validation` turns into a ``ValidationFinding``."""
    return {"rule": rule, "message": message, "file": file, "path": path}


def _is_rfc3339(value: Any) -> bool:
    """Whether ``value`` is an RFC 3339 ``date-time`` string (the CloudEvents ``Timestamp`` type)."""
    if not isinstance(value, str) or not _RFC3339.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return False
    return True


def _event_problems(event: Mapping[str, Any], *, file: Optional[str], base: str) -> List[Dict[str, Any]]:
    """Check one event object against the CloudEvents core and JSON format rules.

    Args:
        event: The event object.
        file: The bundle file it came from, echoed into each finding.
        base: The JSON pointer of the event within the file (``""`` for a single event).

    Returns:
        The findings; empty when the event meets every rule.
    """
    problems: List[Dict[str, Any]] = []
    version = event.get("specversion")
    if version not in SUPPORTED_SPEC_VERSIONS:
        problems.append(
            _problem(
                "cloudevents.specversion",
                f"`specversion` must be one of {', '.join(SUPPORTED_SPEC_VERSIONS)} (found {version!r}).",
                file=file,
                path=f"{base}/specversion",
            )
        )
    for name in _REQUIRED:
        value = event.get(name)
        if not isinstance(value, str) or not value:
            problems.append(
                _problem(
                    "cloudevents.required",
                    f"The required attribute `{name}` must be a non-empty string.",
                    file=file,
                    path=f"{base}/{name}",
                )
            )
    for name in _OPTIONAL_STRINGS:
        if name in event and (not isinstance(event[name], str) or not event[name]):
            problems.append(
                _problem(
                    "cloudevents.attribute-type",
                    f"`{name}` must be a non-empty string when present.",
                    file=file,
                    path=f"{base}/{name}",
                )
            )
    if "time" in event and not _is_rfc3339(event["time"]):
        problems.append(
            _problem(
                "cloudevents.attribute-type",
                f"`time` must be an RFC 3339 timestamp (found {event['time']!r}).",
                file=file,
                path=f"{base}/time",
            )
        )
    if "data_base64" in event and not isinstance(event["data_base64"], str):
        problems.append(
            _problem(
                "cloudevents.attribute-type",
                "`data_base64` must be a Base64 string.",
                file=file,
                path=f"{base}/data_base64",
            )
        )
    if "data" in event and "data_base64" in event:
        problems.append(
            _problem(
                "cloudevents.data-exclusive",
                "An event must not carry both `data` and `data_base64`.",
                file=file,
                path=f"{base}/data_base64",
            )
        )
    for name, value in event.items():
        if name in _KNOWN or name in _DATA_MEMBERS:
            continue
        if not _ATTRIBUTE_NAME.match(name):
            problems.append(
                _problem(
                    "cloudevents.attribute-name",
                    f"Extension attribute `{name}` must use only lower-case ASCII letters and digits.",
                    file=file,
                    path=f"{base}/{name}",
                )
            )
        # ``bool`` is an ``int`` subclass, so booleans pass; floats, objects and arrays do not.
        if value is not None and not isinstance(value, (str, int)):
            problems.append(
                _problem(
                    "cloudevents.extension-value",
                    f"Extension attribute `{name}` must be a string, integer, boolean or null.",
                    file=file,
                    path=f"{base}/{name}",
                )
            )
    return problems


def cloudevents_spec_problems(content: Any, *, file: Optional[str] = None) -> List[Dict[str, Any]]:
    """Check one emitted CloudEvents JSON file against the CloudEvents 1.0 rules.

    Args:
        content: The file content — JSON text, or the already-structured document.
        file: The bundle-relative path, echoed into each finding.

    Returns:
        Findings as ``{"rule", "message", "file", "path"}`` dicts; empty when the file meets
        every rule listed in the module docstring.
    """
    if isinstance(content, str):
        try:
            document = json.loads(content)
        except json.JSONDecodeError as exc:
            return [_problem("cloudevents.document", f"The file is not JSON: {exc}", file=file, path="")]
    else:
        document = content
    if isinstance(document, dict):
        return _event_problems(document, file=file, base="")
    if isinstance(document, list) and document:
        problems: List[Dict[str, Any]] = []
        for index, event in enumerate(document):
            if not isinstance(event, dict):
                problems.append(
                    _problem(
                        "cloudevents.document", "A batch entry must be an event object.", file=file, path=f"/{index}"
                    )
                )
                continue
            problems.extend(_event_problems(event, file=file, base=f"/{index}"))
        return problems
    return [
        _problem(
            "cloudevents.document",
            "A CloudEvents file must be one event object or a non-empty array of events.",
            file=file,
            path="",
        )
    ]
