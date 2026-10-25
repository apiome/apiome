"""AWS API Gateway export import source — FMT-7.1 (#5455).

Reads an exported API Gateway definition: a **REST API** (``GetExport`` with
``extensions=apigateway``) or an **HTTP API** (``ExportApi`` with ``includeExtensions``). Both
are OpenAPI (or Swagger 2.0) documents plus ``x-amazon-apigateway-*`` extensions, and in an AWS
estate they are the most accurate description of what an API does, because the extensions carry
the integration, authorizer, request-validator and CORS configuration a hand-written spec omits.

**Reuses the OpenAPI path.** ``parse`` is the OpenAPI adapter's loader, and the base document is
normalized by the OpenAPI normalizer, so paths, parameters, messages and schemas come out exactly
as an OpenAPI import of the same document would. ``x-amazon-apigateway-any-method`` (a route that
answers every method) is handed to the normalizer as an OpenAPI 3.2 ``additionalOperations``
entry, so it becomes an ``ANY /path`` operation.

**Then the extensions are interpreted** (see :mod:`app.aws_apigateway_extensions`), every result
labelled ``provenance: "declared"`` — the export states these facts, nothing is inferred:

* ``x-amazon-apigateway-integration`` → ``operation.extras["backend"]`` (kind, URI, method,
  connection, stage variables), with the verbatim integration (templates, mappings) under
  ``operation.extras["aws_apigateway"]["integration"]``;
* ``x-amazon-apigateway-authorizer`` / ``-authtype`` on a security scheme, and
  ``x-amazon-apigateway-auth`` / ``-api-key-required`` on an operation → canonical security,
  ``operation.extras["security"]`` (the shape :mod:`app.canonical_security` reads);
* ``x-amazon-apigateway-request-validator(s)`` → ``operation.extras["validation"]``;
* ``x-amazon-apigateway-cors`` → ``api.extras["cors"]``, and the REST-API mock ``OPTIONS``
  integration's ``Access-Control-Allow-*`` headers → that operation's ``extras["cors"]``.

Documented extensions the canonical model has no construct for (resource policy, gateway
responses, binary media types, …) and extensions nobody has seen before are kept verbatim in
extras and **reported** on ``api.extras["aws_apigateway"]["extensions"]``, which the coverage
ledger renders — never silently dropped.

**Detection is not greedy.** Only an OpenAPI/Swagger document carrying an AWS extension where AWS
writes one is claimed (:func:`app.aws_apigateway_extensions.has_aws_extensions`); a plain OpenAPI
document stays with the ``openapi`` adapter, which in turn steps down for documents this adapter
claims so the two are never reported as ambiguous.

The import routes to the catalog as a non-publishable item, like every non-OpenAPI format; the
convert flow turns it into a Project.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional

from .aws_apigateway_extensions import (
    ANY_METHOD,
    API_KEY_REQUIRED,
    AUTH,
    CORS,
    EXTENSION_PREFIX,
    INTEGRATION,
    INTERPRETED_EXTENSIONS,
    PRESERVED_EXTENSIONS,
    REQUEST_VALIDATOR,
    REQUEST_VALIDATORS,
    backend_for_integration,
    cors_from_mock_options,
    extension_sites,
    has_aws_extensions,
    integration_problems,
    is_openapi_document,
    security_for_scheme,
    validation_posture,
)
from .canonical_model import ApiParadigm, CanonicalApi, Operation, OperationKind, Service
from .document_markers import top_level_api_marker
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
    LintReport,
)
from .normalizer import Keys
from .openapi_fileset_bundle import bundle_openapi_fileset
from .openapi_import_source import OpenApiImportSource

__all__ = ["AWS_EXTRAS_KEY", "AwsApiGatewayImportSource", "FORMAT_KEY"]

#: The canonical ``format`` (and adapter key) of an API Gateway export.
FORMAT_KEY = "aws-apigateway"
#: Extras key of the API-level report and of each entity's verbatim extensions.
AWS_EXTRAS_KEY = "aws_apigateway"

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace", "query")


def _flavor(document: Mapping[str, Any]) -> str:
    """``http`` for an HTTP API export (v2 markers), else ``rest``."""
    if CORS in document or "x-amazon-apigateway-importexport-version" in document:
        return "http"
    paths = document.get("paths") if isinstance(document.get("paths"), Mapping) else {}
    if "/$default" in paths:
        return "http"
    for item in paths.values():
        for op in (item or {}).values() if isinstance(item, Mapping) else ():
            integration = op.get(INTEGRATION) if isinstance(op, Mapping) else None
            if isinstance(integration, Mapping) and str(integration.get("payloadFormatVersion")) == "2.0":
                return "http"
    schemes = _security_schemes(document)
    for scheme in schemes.values():
        authorizer = scheme.get("x-amazon-apigateway-authorizer") or {}
        if isinstance(authorizer, Mapping) and str(authorizer.get("type", "")).lower() == "jwt":
            return "http"
    return "rest"


def _security_schemes(document: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    components = document.get("components") if isinstance(document.get("components"), Mapping) else {}
    schemes = components.get("securitySchemes") or document.get("securityDefinitions") or {}
    return {str(k): v for k, v in schemes.items() if isinstance(v, Mapping)} if isinstance(schemes, Mapping) else {}


def _with_any_method_operations(document: Dict[str, Any]) -> Dict[str, Any]:
    """A copy whose ``any-method`` operations are OpenAPI 3.2 ``additionalOperations`` (``ANY``)."""
    prepared = copy.deepcopy(document)
    for item in (prepared.get("paths") or {}).values():
        if isinstance(item, dict) and isinstance(item.get(ANY_METHOD), dict):
            extra = item.setdefault("additionalOperations", {})
            if isinstance(extra, dict):
                extra.setdefault("ANY", item[ANY_METHOD])
    return prepared


def _other_extensions(node: Mapping[str, Any], handled: frozenset) -> Dict[str, Any]:
    """The ``x-*`` keys of ``node`` not in ``handled``, verbatim."""
    return {k: v for k, v in node.items() if isinstance(k, str) and k.startswith("x-") and k not in handled}


class AwsApiGatewayImportSource(ImportSource, register=True):
    """Adapter for exported AWS API Gateway REST and HTTP API definitions."""

    key = FORMAT_KEY
    label = "AWS API Gateway"
    description = (
        "Import an exported API Gateway REST or HTTP API (OpenAPI with x-amazon-apigateway-* "
        "extensions). Paths and schemas import as OpenAPI would; integrations, authorizers, "
        "request validators and CORS map to canonical backend, security, validation and CORS "
        "metadata, labelled declared. Unknown extensions are preserved and reported."
    )
    icon = "cloud"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (FORMAT_KEY,)
    file_extensions = (".json", ".yaml", ".yml")

    # --- detection -------------------------------------------------------------------

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim an OpenAPI/Swagger document carrying an AWS extension where AWS writes one."""
        document = payload.document
        if document is None and payload.text:
            if EXTENSION_PREFIX not in payload.text:
                return NO_MATCH
            try:
                document = OpenApiImportSource().parse(payload.text, source_label=payload.filename)
            except ImportSourceError:
                # Unparseable, but an OpenAPI document carrying the extensions is still ours:
                # claim it so the import reports the parse error rather than another format.
                if top_level_api_marker(payload.text) is not None:
                    return DetectionResult(
                        confidence=0.99,
                        format=FORMAT_KEY,
                        reason="OpenAPI document carrying `x-amazon-apigateway-*` extensions "
                        "(the document did not fully parse)",
                    )
                return NO_MATCH
        if not has_aws_extensions(document):
            return NO_MATCH
        return DetectionResult(
            confidence=0.99,
            format=FORMAT_KEY,
            reason="OpenAPI document carrying `x-amazon-apigateway-*` extensions",
        )

    # --- parsing ---------------------------------------------------------------------

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse an export (JSON or YAML) with the OpenAPI loader and check its extensions.

        Raises:
            ImportSourceError: ``INPUT_MALFORMED`` / ``INPUT_TRUNCATED`` / ``INPUT_ENCODING_INVALID``
                from the loader; ``FORMAT_MISMATCH`` for a document that is not an OpenAPI export
                with AWS extensions; ``INPUT_SEMANTIC_INVALID`` for an integration with no or an
                unknown ``type``.
        """
        try:
            document = OpenApiImportSource().parse(raw, source_label=source_label)
        except ImportSourceError as exc:
            if exc.code is None and "end of stream" in str(exc):
                raise ImportSourceError(f"AWS API Gateway export is truncated: {exc}", code="INPUT_TRUNCATED") from exc
            raise
        return self._checked(document, source_label=source_label)

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse a split export: the root definition plus sibling files it reaches by ``$ref``.

        Cross-file components are hoisted into the root
        (:func:`app.openapi_fileset_bundle.bundle_openapi_fileset`), so the bundled document is
        self-contained.
        """
        if not fileset.members:
            raise ImportSourceError("AWS API Gateway fileset has no members", code="INPUT_MALFORMED")
        root = fileset.root
        if root is None or root not in fileset.members:
            candidates = [p for p, text in sorted(fileset.members.items()) if EXTENSION_PREFIX in text]
            if not candidates:
                raise ImportSourceError(
                    "No member of the fileset carries `x-amazon-apigateway-*` extensions.",
                    code="FORMAT_MISMATCH",
                )
            root = candidates[0]
        document = bundle_openapi_fileset(fileset, root=root)
        return self._checked(document, source_label=source_label or root)

    @staticmethod
    def _checked(document: Any, *, source_label: Optional[str]) -> Dict[str, Any]:
        label = f" {source_label!r}" if source_label else ""
        if not is_openapi_document(document):
            raise ImportSourceError(
                f"Document{label} is not an OpenAPI 3.x or Swagger 2.0 export.", code="FORMAT_MISMATCH"
            )
        if not has_aws_extensions(document):
            raise ImportSourceError(
                f"Document{label} carries no `x-amazon-apigateway-*` extensions; import it as OpenAPI.",
                code="FORMAT_MISMATCH",
            )
        problems = integration_problems(document)
        if problems:
            raise ImportSourceError("; ".join(problems), code="INPUT_SEMANTIC_INVALID")
        return document

    # --- normalization ---------------------------------------------------------------

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the base document as OpenAPI, then interpret the AWS extensions.

        Raises:
            ImportSourceError: When ``native_ast`` is not a checked export (see :meth:`parse`).
        """
        document = self._checked(native_ast, source_label=None)
        model = OpenApiImportSource().normalize(_with_any_method_operations(document), include_raw=include_raw)
        model.format = FORMAT_KEY
        if include_raw:
            model.raw = document
        _interpret(model, document)
        return model

    def lint(self, model: CanonicalApi) -> LintReport:
        """Lint the base document with the OpenAPI linter (the export *is* OpenAPI)."""
        return OpenApiImportSource().lint(model)


# ---------------------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------------------


def _operation_security(
    op: Mapping[str, Any], document: Mapping[str, Any], schemes: Mapping[str, Mapping[str, Any]]
) -> Optional[List[Dict[str, Any]]]:
    """The declared security records for one operation, or ``None`` when nothing is declared."""
    requirements = op.get("security", document.get("security"))
    records: List[Dict[str, Any]] = []
    declared = requirements is not None
    for requirement in requirements or []:
        if not isinstance(requirement, Mapping):
            continue
        for name, scopes in requirement.items():
            scheme = schemes.get(str(name))
            if scheme is not None:
                records.append(security_for_scheme(str(name), scheme, list(scopes or [])))
    auth = op.get(AUTH)
    if isinstance(auth, Mapping) and isinstance(auth.get("type"), str):
        declared = True
        kind = auth["type"].strip().upper()
        if kind == "NONE":
            records = []
        elif kind in ("AWS_IAM", "AWSSIGV4"):
            records.append({"scheme": "awsSigv4", "name": AUTH, "scopes": [], "provenance": "declared"})
    if op.get(API_KEY_REQUIRED) is True:
        declared = True
        records.append(
            {"scheme": "apiKey", "name": API_KEY_REQUIRED, "scopes": [], "in": "header",
             "parameterName": "x-api-key", "provenance": "declared"}
        )
    records.sort(key=lambda r: (r["name"], r["scheme"]))
    return records if declared else None


def _interpret(model: CanonicalApi, document: Mapping[str, Any]) -> None:
    """Interpret every AWS extension of ``document`` onto ``model`` (in place)."""
    schemes = _security_schemes(document)
    validators = document.get(REQUEST_VALIDATORS) if isinstance(document.get(REQUEST_VALIDATORS), Mapping) else {}
    default_validator = document.get(REQUEST_VALIDATOR)
    ops: Dict[str, Operation] = {op.key: op for op in model.operations()}
    integration_counts: Dict[str, int] = {}

    paths = document.get("paths") if isinstance(document.get("paths"), Mapping) else {}
    for path, item in paths.items():
        if not isinstance(item, Mapping):
            continue
        entries = [(m, item[m]) for m in _HTTP_METHODS if isinstance(item.get(m), Mapping)]
        if isinstance(item.get(ANY_METHOD), Mapping):
            entries.append(("any", item[ANY_METHOD]))
        for method, op_obj in entries:
            key = Keys.operation_http(method, str(path))
            operation = ops.get(key)
            if operation is None:
                # Swagger 2.0 has no additionalOperations: add the ANY route by hand.
                operation = Operation(
                    key=key, name=key, kind=OperationKind.REQUEST_RESPONSE,
                    http_method=method.upper(), http_path=str(path),
                    description=op_obj.get("description") or op_obj.get("summary"),
                )
                if not model.services:
                    model.services.append(Service(key="default", name="default"))
                model.services[0].operations.append(operation)
                ops[key] = operation
            verbatim: Dict[str, Any] = {}
            integration = op_obj.get(INTEGRATION)
            if isinstance(integration, Mapping):
                backend = backend_for_integration(integration)
                operation.extras["backend"] = backend
                verbatim["integration"] = dict(integration)
                integration_counts[backend["kind"]] = integration_counts.get(backend["kind"], 0) + 1
                cors = cors_from_mock_options(integration) if method == "options" else None
                if cors:
                    operation.extras["cors"] = cors
            security = _operation_security(op_obj, document, schemes)
            if security is not None:
                operation.extras["security"] = security
            if isinstance(op_obj.get(AUTH), Mapping):
                verbatim["auth"] = dict(op_obj[AUTH])
            posture = validation_posture(op_obj.get(REQUEST_VALIDATOR, default_validator), validators)
            if posture:
                operation.extras["validation"] = posture
            others = _other_extensions(op_obj, INTERPRETED_EXTENSIONS)
            if others:
                verbatim["extensions"] = others
            path_extensions = _other_extensions(item, INTERPRETED_EXTENSIONS)
            if path_extensions:
                verbatim["pathExtensions"] = path_extensions
            if verbatim:
                operation.extras[AWS_EXTRAS_KEY] = verbatim

    # Server-level extensions (endpoint configuration) stay in the API report, not on
    # ``server.extras``: emitters copy server extras into their own server objects.
    server_extensions = {
        str(s.get("url")): found
        for s in document.get("servers") or [] if isinstance(s, Mapping)
        for found in [_other_extensions(s, frozenset())] if found
    }

    if isinstance(document.get(CORS), Mapping):
        model.extras["cors"] = {**document[CORS], "source": CORS, "provenance": "declared"}

    authorizers = [
        {"name": name, **dict(scheme.get("x-amazon-apigateway-authorizer") or {}),
         **({"authType": scheme["x-amazon-apigateway-authtype"]} if scheme.get("x-amazon-apigateway-authtype") else {})}
        for name, scheme in sorted(schemes.items())
        if scheme.get("x-amazon-apigateway-authorizer") or scheme.get("x-amazon-apigateway-authtype")
    ]
    sites = extension_sites(document)
    model.extras[AWS_EXTRAS_KEY] = {
        "flavor": _flavor(document),
        "provenance": "declared",
        "integrations": dict(sorted(integration_counts.items())),
        "authorizers": authorizers,
        "request_validators": {str(k): dict(v) for k, v in validators.items() if isinstance(v, Mapping)},
        "default_request_validator": default_validator if isinstance(default_validator, str) else None,
        "settings": {
            k: document[k]
            for k in sorted(document)
            if isinstance(k, str) and k.startswith("x-") and k not in INTERPRETED_EXTENSIONS
        },
        "server_extensions": dict(sorted(server_extensions.items())),
        "extensions": [
            {
                "name": name,
                "pointer": pointer,
                "status": "interpreted" if name in INTERPRETED_EXTENSIONS
                else "preserved" if name in PRESERVED_EXTENSIONS
                else "unknown",
            }
            for pointer, name in sorted(sites)
        ],
    }
