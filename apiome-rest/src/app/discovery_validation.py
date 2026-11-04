"""Validation of emitted Google API Discovery documents — MFX-29.2 (#4174).

The rules a Google API Discovery document must keep. The export gate checks every Discovery export with them
through the alternate-validator seam (:mod:`app.export_validation`, target ``discovery``, MFX-29.3 #4175), and an
export that breaks one fails its job. Every problem has its rule (``keyword``) and a JSON Pointer:

1. **Metaschema** (``discovery.schema``) — the document validates against the Discovery metaschema
   (``data/discovery_v1_meta_schema.json``: the ``RestDescription``, ``RestResource``, ``RestMethod`` and
   ``JsonSchema`` schemas of the Discovery service's own description, tightened with the reference's rules —
   see ``scripts/generate_discovery_meta_schema.py``). When it does not, nothing else is checked.
2. **URLs** (``discovery.urls``) — ``rootUrl`` is an absolute ``http(s)`` URL ending in ``/``; ``servicePath`` is
   relative and empty or ending in ``/``; ``baseUrl`` / ``basePath``, when present, agree with them.
3. **Schemas** — each ``schemas`` entry's ``id`` is its key (``discovery.schema-id``); every ``$ref`` (in a
   schema, a request or a response) names a schema of the document (``discovery.ref``); every ``type`` /
   ``format`` pair is one of the type-and-format summary's (``discovery.type-format``).
4. **Methods** — method ids are unique (``discovery.method-id``); every ``{var}`` / ``{+var}`` of a path is a
   declared ``path`` parameter, and every ``path`` parameter is in the path and required
   (``discovery.path-parameter``); ``parameterOrder`` lists declared parameters, once each
   (``discovery.parameter-order``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Dict, Iterator, List, Mapping, Tuple

from jsonschema import Draft4Validator

from .discovery_schema import DISCOVERY_TYPE_FORMATS

__all__ = ["DiscoveryProblem", "check_discovery_files", "discovery_problems", "meta_schema"]

_TEMPLATE_VARIABLE = re.compile(r"\{\+?([^}]+)\}")
_ROOT_URL = re.compile(r"^https?://[^/\s]+/(\S*/)?$")


@dataclass(frozen=True)
class DiscoveryProblem:
    """One broken rule: its ``rule`` (``discovery.<name>``), a message and the JSON Pointer it is at."""

    rule: str
    message: str
    path: str
    file: str = ""


@lru_cache(maxsize=1)
def meta_schema() -> Dict[str, Any]:
    """The Discovery metaschema (draft-04), as shipped in ``app/data``."""
    text = resources.files("app").joinpath("data/discovery_v1_meta_schema.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def _validator() -> Draft4Validator:
    return Draft4Validator(meta_schema())


def discovery_problems(document: Any) -> List[DiscoveryProblem]:
    """Every rule ``document`` (a parsed Discovery document) breaks; ``[]`` when it is valid."""
    problems = [
        DiscoveryProblem("discovery.schema", error.message, _pointer(error.absolute_path))
        for error in sorted(_validator().iter_errors(document), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        return problems
    _check_urls(document, problems)
    _check_schemas(document, problems)
    _check_methods(document, problems)
    return problems


def check_discovery_files(files: Mapping[str, str]) -> List[DiscoveryProblem]:
    """Check an export: one ``.discovery.json`` file that parses and passes :func:`discovery_problems`."""
    documents = [path for path in files if path.endswith(".discovery.json")]
    if len(documents) != 1:
        return [DiscoveryProblem("discovery.files", f"the export must be one .discovery.json file, not "
                                 f"{len(documents)}", "", "")]
    path = documents[0]
    try:
        document = json.loads(files[path])
    except ValueError as exc:
        return [DiscoveryProblem("discovery.schema", f"the document is not JSON: {exc}", "", path)]
    return [DiscoveryProblem(p.rule, p.message, p.path, path) for p in discovery_problems(document)]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _check_urls(document: Mapping[str, Any], out: List[DiscoveryProblem]) -> None:
    root, service = document["rootUrl"], document["servicePath"]
    if not _ROOT_URL.match(root):
        out.append(DiscoveryProblem("discovery.urls", f"rootUrl {root!r} must be an absolute http(s) URL ending "
                                    "in '/'", "/rootUrl"))
    if service.startswith("/") or (service and not service.endswith("/")):
        out.append(DiscoveryProblem("discovery.urls", f"servicePath {service!r} must be relative and end in '/'",
                                    "/servicePath"))
    if "baseUrl" in document and document["baseUrl"] != root + service:
        out.append(DiscoveryProblem("discovery.urls", f"baseUrl must be rootUrl + servicePath ({root + service!r})",
                                    "/baseUrl"))
    if "basePath" in document and document["basePath"].strip("/") != service.strip("/"):
        out.append(DiscoveryProblem("discovery.urls", f"basePath must be '/' + servicePath ('/{service}')",
                                    "/basePath"))


def _check_schemas(document: Mapping[str, Any], out: List[DiscoveryProblem]) -> None:
    schemas = document.get("schemas") or {}
    for key, schema in schemas.items():
        if schema.get("id") != key:
            out.append(DiscoveryProblem("discovery.schema-id", f"schemas/{key} has the id {schema.get('id')!r}",
                                        f"/schemas/{_escape(key)}/id"))
        for pointer, sub in _schema_positions(schema, f"/schemas/{_escape(key)}"):
            _check_schema_position(sub, pointer, schemas, out)
    for pointer, method in _methods(document):
        for body in ("request", "response"):
            ref = (method.get(body) or {}).get("$ref")
            if ref is not None and ref not in schemas:
                out.append(DiscoveryProblem("discovery.ref", f"the {body} names the schema {ref!r}, which the "
                                            "document does not define", f"{pointer}/{body}/$ref"))
        for name, parameter in (method.get("parameters") or {}).items():
            _check_schema_position(parameter, f"{pointer}/parameters/{_escape(name)}", schemas, out)
    for name, parameter in (document.get("parameters") or {}).items():
        _check_schema_position(parameter, f"/parameters/{_escape(name)}", schemas, out)


def _check_schema_position(schema: Mapping[str, Any], pointer: str, schemas: Mapping[str, Any],
                           out: List[DiscoveryProblem]) -> None:
    ref = schema.get("$ref")
    if ref is not None and ref not in schemas:
        out.append(DiscoveryProblem("discovery.ref", f"$ref names the schema {ref!r}, which the document does not "
                                    "define", f"{pointer}/$ref"))
    kind = schema.get("type")
    if kind is not None and schema.get("format") not in DISCOVERY_TYPE_FORMATS.get(kind, frozenset()):
        out.append(DiscoveryProblem("discovery.type-format", f"type {kind!r} has no format "
                                    f"{schema.get('format')!r} in Discovery", f"{pointer}/format"))
    if kind is None and ref is None:
        out.append(DiscoveryProblem("discovery.type-format", "a schema needs a type or a $ref", pointer))


def _check_methods(document: Mapping[str, Any], out: List[DiscoveryProblem]) -> None:
    seen: Dict[str, str] = {}
    for pointer, method in _methods(document):
        method_id = method["id"]
        if method_id in seen:
            out.append(DiscoveryProblem("discovery.method-id", f"the method id {method_id!r} is also used at "
                                        f"{seen[method_id]}", f"{pointer}/id"))
        seen.setdefault(method_id, pointer)
        parameters = method.get("parameters") or {}
        in_path = _TEMPLATE_VARIABLE.findall(method["path"])
        for variable in in_path:
            if (parameters.get(variable) or {}).get("location") != "path":
                out.append(DiscoveryProblem("discovery.path-parameter", f"the path names {{{variable}}}, which is "
                                            "not a declared path parameter", f"{pointer}/path"))
        for name, parameter in parameters.items():
            if parameter.get("location") != "path":
                continue
            if name not in in_path:
                out.append(DiscoveryProblem("discovery.path-parameter", f"the path parameter {name!r} is not in "
                                            "the path", f"{pointer}/parameters/{_escape(name)}"))
            if parameter.get("required") is not True:
                out.append(DiscoveryProblem("discovery.path-parameter", f"the path parameter {name!r} must be "
                                            "required", f"{pointer}/parameters/{_escape(name)}/required"))
        order = method.get("parameterOrder") or []
        for index, name in enumerate(order):
            if name not in parameters or name in order[:index]:
                out.append(DiscoveryProblem("discovery.parameter-order", f"parameterOrder lists {name!r}, which is "
                                            "not a declared parameter or is listed twice",
                                            f"{pointer}/parameterOrder/{index}"))


# ---------------------------------------------------------------------------
# Walks
# ---------------------------------------------------------------------------


def _methods(document: Mapping[str, Any]) -> Iterator[Tuple[str, Mapping[str, Any]]]:
    """``(pointer, method)`` for every method, top-level and in every resource."""
    for name, method in (document.get("methods") or {}).items():
        yield f"/methods/{_escape(name)}", method

    def walk(resources_: Mapping[str, Any], pointer: str) -> Iterator[Tuple[str, Mapping[str, Any]]]:
        for name, resource in resources_.items():
            here = f"{pointer}/{_escape(name)}"
            for method_name, method in (resource.get("methods") or {}).items():
                yield f"{here}/methods/{_escape(method_name)}", method
            yield from walk(resource.get("resources") or {}, f"{here}/resources")

    yield from walk(document.get("resources") or {}, "/resources")


def _schema_positions(schema: Mapping[str, Any], pointer: str) -> Iterator[Tuple[str, Mapping[str, Any]]]:
    """``(pointer, schema)`` for ``schema`` and every schema inside it."""
    yield pointer, schema
    for name, sub in (schema.get("properties") or {}).items():
        yield from _schema_positions(sub, f"{pointer}/properties/{_escape(name)}")
    for keyword in ("items", "additionalProperties"):
        if isinstance(schema.get(keyword), dict):
            yield from _schema_positions(schema[keyword], f"{pointer}/{keyword}")


def _pointer(parts: Any) -> str:
    return "".join(f"/{_escape(str(part))}" for part in parts)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
