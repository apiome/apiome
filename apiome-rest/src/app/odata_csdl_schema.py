"""OASIS OData CSDL JSON schema validation — MFI-11.1 (#3776).

OData publishes its metadata format twice: as CSDL XML and as **CSDL JSON**, and the OASIS
standard ships a JSON Schema for the JSON form. This module validates a CSDL JSON document
(read as uploaded, or produced from v4 CSDL XML by :mod:`app.odata_csdl_json`) against that
schema, the way :mod:`app.odcs_schema` validates data contracts: the published file is vendored
byte for byte and run, so validation is fully offline.

* ``data/odata_csdl_4_01_schema.json`` — OASIS *OData Common Schema Definition Language (CSDL)
  JSON Representation Version 4.01*, OASIS Standard,
  https://docs.oasis-open.org/odata/odata-csdl-json/v4.01/os/schemas/csdl.schema.json
  (JSON Schema draft-04; it accepts ``$Version`` ``4.0`` and ``4.01``).

  Copyright © OASIS Open 2020. All Rights Reserved. Distributed under the OASIS IPR Policy
  (https://www.oasis-open.org/policies-guidelines/ipr/), which permits copying and
  distributing the document provided this notice is included.

Violations do not refuse an import: a real service that strays from the schema in a detail
still imports, and its violations are recorded on the catalog item and surfaced by the
``odata.csdl-schema`` lint rule (:mod:`app.odata_lint`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from jsonschema.exceptions import ValidationError, best_match
from jsonschema.validators import Draft4Validator

__all__ = [
    "CSDL_SCHEMA_PATH",
    "MAX_REPORTED_VIOLATIONS",
    "CsdlViolation",
    "validate_csdl_json",
]

#: The vendored OASIS CSDL JSON schema.
CSDL_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "odata_csdl_4_01_schema.json"

#: Most violations recorded for one document (the rest are counted, not listed).
MAX_REPORTED_VIOLATIONS = 50


@dataclass(frozen=True)
class CsdlViolation:
    """One place a CSDL JSON document departs from the OASIS schema.

    Attributes:
        path: JSON pointer to the offending value (``/ODataDemo/Product/ID/$Type``; ``""`` for
            the document itself).
        message: The schema's complaint.
    """

    path: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        """The violation as ``{"path": ..., "message": ...}``."""
        return {"path": self.path, "message": self.message}


@lru_cache(maxsize=1)
def _validator() -> Draft4Validator:
    """The schema validator (built once; the schema is about 25 KB)."""
    schema = json.loads(CSDL_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft4Validator(schema)


def _pointer(parts: Any) -> str:
    """A JSON pointer for a ``jsonschema`` error path."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _branch_name(branch: Mapping[str, Any]) -> str:
    """The model element a ``oneOf`` / ``anyOf`` branch describes (``EntityType``, ``Action``…)."""
    ref = branch.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    return str(branch.get("description") or "")


def _expected_names(instance: Any) -> Tuple[str, ...]:
    """The element names an instance can be, read from the instance itself.

    ``$Kind`` names it outright. Members that may omit it are told apart by what they carry:
    an action / function import by ``$Action`` / ``$Function``, an action or function by its
    overload array, and otherwise a property, entity set or singleton.
    """
    if isinstance(instance, list):
        kinds = {item.get("$Kind") for item in instance if isinstance(item, Mapping)}
        return tuple(sorted(str(kind) for kind in kinds if kind)) or ("Action", "Function")
    if not isinstance(instance, Mapping):
        return ()
    if isinstance(instance.get("$Kind"), str):
        return (instance["$Kind"],)
    if "$Action" in instance:
        return ("ActionImport",)
    if "$Function" in instance:
        return ("FunctionImport",)
    return ("Property", "EntitySet", "Singleton")


def _specific(error: ValidationError) -> ValidationError:
    """The most specific cause of an error.

    A CSDL member is checked against every member kind (``oneOf``), so a broken entity type
    first fails as "not valid under any of the given schemas". The branch that describes the
    member's own kind (its ``$Kind``, or the members it carries) holds the real complaint, so
    the search follows that branch down; when no branch matches the kind, the kind itself is
    what is wrong. Remaining ties go to :func:`jsonschema.exceptions.best_match`.
    """
    while error.context and error.validator in ("oneOf", "anyOf"):
        branches = error.schema.get(error.validator) or []
        expected = _expected_names(error.instance)
        chosen = [
            sub
            for sub in error.context
            if sub.relative_schema_path
            and isinstance(sub.relative_schema_path[0], int)
            and sub.relative_schema_path[0] < len(branches)
            and _branch_name(branches[sub.relative_schema_path[0]]) in expected
        ]
        if not chosen:
            return error
        error = best_match(chosen) or chosen[0]
    return error


def validate_csdl_json(document: Mapping[str, Any]) -> Tuple[Tuple[CsdlViolation, ...], int]:
    """Validate a CSDL JSON document against the OASIS schema.

    Args:
        document: The CSDL JSON document.

    Returns:
        ``(violations, total)``: up to :data:`MAX_REPORTED_VIOLATIONS` violations sorted by
        path then message, and how many there were in all.
    """
    found: List[CsdlViolation] = []
    for error in _validator().iter_errors(document):
        cause = _specific(error)
        path, message = _pointer(cause.absolute_path), cause.message
        kind = cause.instance.get("$Kind") if isinstance(cause.instance, Mapping) else None
        if cause.validator in ("oneOf", "anyOf") and isinstance(kind, str):
            # No member kind matched: the `$Kind` itself is unknown here.
            path, message = f"{path}/$Kind", f"{kind!r} is not a CSDL member kind allowed here"
        found.append(CsdlViolation(path=path, message=message))
    found.sort(key=lambda v: (v.path, v.message))
    return tuple(found[:MAX_REPORTED_VIOLATIONS]), len(found)
