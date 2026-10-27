"""RAML lint issues: AMF SHACL results plus hygiene — MFI-15.3 (#3801).

:func:`raml_lint_issues` turns a parsed :class:`~app.raml_parser.RamlDocument` into the issue
list the ``raml`` lint pack (:mod:`app.raml_lint`) reports, each ``{"rule", "path", "message"}``:

* **AMF SHACL validation** (:func:`app.raml_amf.validate_raml_set_with_amf`, when the server has
  AMF) — one issue per result, its rule picked by severity: ``raml.shacl-violation`` /
  ``raml.shacl-warning`` / ``raml.shacl-info``. The path is ``<file>:<line>:<column>``.
* **Hygiene** that AMF's RAML profile does not report (each found by running AMF 5.7.1 on RAML
  that breaks it: the documents conform):

  * ``raml.undeclared-security-scheme`` — a ``securedBy`` (API, resource or method) naming a
    scheme ``securitySchemes`` does not declare.
  * ``raml.unused-base-uri-parameter`` — a ``baseUriParameters`` entry ``baseUri`` never uses.
  * ``raml.unused-uri-parameter`` — a resource ``uriParameters`` entry its path never uses.
  * ``raml.method-without-responses`` — a method that declares no response.

  The first three read the root document as written; a scheme or parameter that lives in an
  ``!include``\\d file, or a library-qualified scheme (``lib.oauth``), is not judged.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

import yaml

from .raml_parser import RamlDocument
from .raml_traits import IncludeAsText

__all__ = [
    "MAX_REPORTED_ISSUES",
    "RULE_METHOD_WITHOUT_RESPONSES",
    "RULE_SHACL_BY_SEVERITY",
    "RULE_UNDECLARED_SECURITY_SCHEME",
    "RULE_UNUSED_BASE_URI_PARAMETER",
    "RULE_UNUSED_URI_PARAMETER",
    "hygiene_issues",
    "raml_lint_issues",
    "shacl_issues",
]

#: The SHACL rule for each AMF result severity.
RULE_SHACL_BY_SEVERITY = {
    "Violation": "raml.shacl-violation",
    "Warning": "raml.shacl-warning",
    "Info": "raml.shacl-info",
}
RULE_UNDECLARED_SECURITY_SCHEME = "raml.undeclared-security-scheme"
RULE_UNUSED_BASE_URI_PARAMETER = "raml.unused-base-uri-parameter"
RULE_UNUSED_URI_PARAMETER = "raml.unused-uri-parameter"
RULE_METHOD_WITHOUT_RESPONSES = "raml.method-without-responses"

#: Most issues recorded for one document (the rest are counted, not listed).
MAX_REPORTED_ISSUES = 50

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options", "trace", "connect"})
_TEMPLATE_RE = re.compile(r"\{\+?([^}]+)\}")


def _issue(rule: str, path: str, message: str) -> Dict[str, str]:
    return {"rule": rule, "path": path, "message": message}


def shacl_issues(results: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """One issue per AMF SHACL result.

    Args:
        results: :attr:`RamlDocument.shacl_results`.

    Returns:
        Issues whose path is ``<file>:<line>:<column>`` (just ``<file>``, or empty, when AMF did
        not locate the result) and whose message leads with the AMF constraint.
    """
    issues: List[Dict[str, str]] = []
    for result in results:
        rule = RULE_SHACL_BY_SEVERITY.get(str(result.get("severity")), "raml.shacl-violation")
        file = str(result.get("file") or "")
        line, column = result.get("line"), result.get("column")
        path = f"{file}:{line}:{column}" if file and line is not None else file
        constraint = result.get("constraint")
        message = str(result.get("message") or "")
        issues.append(_issue(rule, path, f"{constraint}: {message}" if constraint else message))
    return issues


def _load_root(raw: str) -> Optional[Mapping[str, Any]]:
    """The root document as written (``!include`` values kept as their text), or ``None``."""
    try:
        root = yaml.load(raw, Loader=IncludeAsText)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError:
        return None
    return root if isinstance(root, Mapping) else None


def _names(value: Any) -> List[str]:
    """The scheme names a ``securedBy`` lists (``null`` and parameterised ``{name: {...}}`` included)."""
    names: List[str] = []
    for entry in value if isinstance(value, list) else [value]:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, Mapping):
            names.extend(str(key) for key in entry)
    return names


class _Hygiene:
    """Walks one root document for the hygiene rules that read it as written."""

    def __init__(self, root: Mapping[str, Any]) -> None:
        self.root = root
        self.issues: List[Dict[str, str]] = []
        schemes = root.get("securitySchemes")
        # A list of single-key maps is the RAML 0.8 spelling; an `!include` (a string) is not judged.
        if isinstance(schemes, list):
            schemes = {key: value for entry in schemes if isinstance(entry, Mapping) for key, value in entry.items()}
        self.schemes: Optional[Set[str]] = set(schemes) if isinstance(schemes, Mapping) else None
        if self.schemes is None and "securitySchemes" not in root:
            self.schemes = set()

    def secured_by(self, holder: Mapping[str, Any], path: str, what: str) -> None:
        if self.schemes is None or "securedBy" not in holder:
            return
        for name in _names(holder["securedBy"]):
            if name in ("null", "None") or "." in name or name in self.schemes:
                continue
            self.issues.append(
                _issue(
                    RULE_UNDECLARED_SECURITY_SCHEME,
                    path,
                    f"{what} is secured by `{name}`, which `securitySchemes` does not declare.",
                )
            )

    def base_uri(self) -> None:
        parameters = self.root.get("baseUriParameters")
        base_uri = self.root.get("baseUri")
        if not isinstance(parameters, Mapping) or not isinstance(base_uri, str):
            return
        used = set(_TEMPLATE_RE.findall(base_uri))
        for name in parameters:
            if str(name) not in used:
                self.issues.append(
                    _issue(
                        RULE_UNUSED_BASE_URI_PARAMETER,
                        f"baseUriParameters/{name}",
                        f"base URI parameter `{name}` is not used in `baseUri` ({base_uri}).",
                    )
                )

    def resources(self, node: Mapping[str, Any], parent: str) -> None:
        for key, value in node.items():
            if not isinstance(key, str) or not key.startswith("/") or not isinstance(value, Mapping):
                continue
            path = parent + key
            self.secured_by(value, path, f"resource `{path}`")
            parameters = value.get("uriParameters")
            if isinstance(parameters, Mapping):
                used = set(_TEMPLATE_RE.findall(path))
                for name in parameters:
                    if str(name) not in used:
                        self.issues.append(
                            _issue(
                                RULE_UNUSED_URI_PARAMETER,
                                f"{path}/uriParameters/{name}",
                                f"URI parameter `{name}` of `{path}` is not used in its path.",
                            )
                        )
            for method, spec in value.items():
                if (
                    isinstance(method, str)
                    and method.lower().rstrip("?") in _HTTP_METHODS
                    and isinstance(spec, Mapping)
                ):
                    self.secured_by(spec, f"{path}/{method}", f"`{method.upper()} {path}`")
            self.resources(value, path)

    def run(self) -> List[Dict[str, str]]:
        self.secured_by(self.root, "securedBy", "the API")
        self.base_uri()
        self.resources(self.root, "")
        return self.issues


def hygiene_issues(document: RamlDocument) -> List[Dict[str, str]]:
    """The hygiene issues of a parsed document (see the module docstring).

    Args:
        document: The parsed document (``raw`` is the root document's text).

    Returns:
        The issues, root-document rules first, then methods without responses.
    """
    root = _load_root(document.raw)
    issues = _Hygiene(root).run() if root is not None else []
    for operation in document.operations:
        if not operation.response_types and not operation.untyped_response_statuses:
            issues.append(
                _issue(
                    RULE_METHOD_WITHOUT_RESPONSES,
                    f"{operation.path}/{operation.method.lower()}",
                    f"`{operation.method.upper()} {operation.path}` declares no response, so clients cannot "
                    f"tell what it returns.",
                )
            )
    return issues


def raml_lint_issues(document: RamlDocument) -> List[Dict[str, str]]:
    """Every lint issue of a parsed document: AMF SHACL results first, then hygiene."""
    return shacl_issues(document.shacl_results) + hygiene_issues(document)
