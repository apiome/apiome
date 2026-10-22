"""AWS API Gateway emitter: canonical model → OpenAPI + ``x-amazon-apigateway-*`` — FMT-7.7 (#5461).

The inverse of :class:`app.aws_apigateway_import_source.AwsApiGatewayImportSource`. API
Gateway imports a REST API from an OpenAPI 3.0 document whose operations carry an
``x-amazon-apigateway-integration``, so the export is exactly that:

* the **document** is the OpenAPI 3.0 projection of the model (:class:`app.openapi_emitter.
  OpenApiEmitter` with ``openapi_version="3.0"``) — paths, parameters, request and response
  schemas survive, which is what sets this target apart from the routing-only gateways;
* every **operation** gets an integration: the one an AWS import recorded, verbatim, when the
  model came from API Gateway; otherwise an ``http_proxy`` integration to the operation's
  upstream — the backend a gateway import recorded on the service, else the model's first
  server — with each path parameter mapped through ``requestParameters``. A model with no
  upstream at all gets a ``mock`` integration, reported, rather than an invented URL;
* an operation that matches **any method** becomes ``x-amazon-apigateway-any-method``;
* an ``apiKey`` scheme a gateway import inferred (``key-auth``, a Tyk auth token) becomes API
  Gateway's ``api_key`` scheme; other gateway auth has no API Gateway declaration without an
  authorizer function, so it is a declared loss.

:func:`validate_aws_apigateway_document` is the product gate: an OpenAPI 3.0 document, every
operation integrated, every ``http`` / ``http_proxy`` integration with an absolute ``uri`` and an
``httpMethod``, every ``aws`` / ``aws_proxy`` integration with an ARN — plus a re-import.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit

from .aws_apigateway_extensions import (
    ANY_METHOD,
    API_KEY_REQUIRED,
    AUTH,
    AUTHORIZER,
    AUTHTYPE,
    CORS,
    INTEGRATION,
    INTEGRATION_TYPES,
    REQUEST_VALIDATOR,
    REQUEST_VALIDATORS,
)
from .canonical_model import ApiParadigm, CanonicalApi, Operation
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .gateway_emit_common import (
    later_duplicates,
    openapi_security_from_records,
    operation_upstream,
    record_method_path_collisions,
)
from .openapi_emitter import OpenApiEmitOptions, OpenApiEmitter

__all__ = [
    "AWS_APIGATEWAY_FORMAT_KEY",
    "AwsApiGatewayEmitOptions",
    "AwsApiGatewayEmitter",
    "AwsApiGatewayFidelityRulePack",
    "aws_document_violations",
    "validate_aws_apigateway_document",
]

#: Format / emitter key (the importer's key).
AWS_APIGATEWAY_FORMAT_KEY = "aws-apigateway"

_LABEL = "AWS API Gateway export"

#: The non-standard methods the OpenAPI projection parks under this key in a 3.0 document.
_ADDITIONAL_OPERATIONS = "x-apiome-additional-operations"

#: OpenAPI operation methods.
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

#: ``{name}`` path parameter.
_PATH_PARAM_RE = re.compile(r"\{([^}/]+)\}")

#: Verbatim AWS extras key the importer writes on each operation.
_AWS_EXTRAS = "aws_apigateway"


class AwsApiGatewayFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for AWS API Gateway export (FMT-7.7).

    The document *is* OpenAPI 3.0, so the profile-derived verdicts are honest for types,
    unions, nullability and constraints. What the pack adds is the routing truth: an
    operation with no HTTP binding has no method to integrate, and an event channel has no
    REST API to belong to.
    """

    target_label = "AWS API Gateway"

    def operation_verdict(self, operation: Operation):  # type: ignore[override]
        """An operation with no HTTP binding cannot be integrated; it is dropped."""
        if not operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} integrates HTTP methods; operation {operation.key!r} "
                "declares no HTTP binding and is dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        if operation.key in getattr(self, "_duplicates", set()):
            return FidelityVerdict.drop(
                message=f"{self.target_label} holds one operation per method and path; {operation.key!r} "
                "repeats an earlier one and is merged into it",
                target_mapping="duplicate operation → dropped",
            )
        if getattr(self, "_source_format", None) != AWS_APIGATEWAY_FORMAT_KEY:
            return FidelityVerdict.approx(
                message=f"operation carried to {self.target_label}, but it is rebuilt through the OpenAPI 3.0 "
                "projection with a gateway backend attached, and gateway route attributes of the source are "
                "not carried",
                target_mapping="operation → rebuilt operation",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")

    def evaluate(self, api: CanonicalApi):  # type: ignore[override]
        """Remember the source format, then walk the model."""
        self._source_format = api.format
        self._duplicates = later_duplicates(api)
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi):  # type: ignore[override]
        """A model from another format comes back as this product's artifact (format, report)."""
        verdicts = list(super().root_verdicts(api))
        if api.format != AWS_APIGATEWAY_FORMAT_KEY:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"the artifact is rebuilt as a {self.target_label} export; its format and gateway "
                    "report come back as this product's",
                    target_mapping="artifact → rebuilt artifact",
                )
            )
        return verdicts


class AwsApiGatewayEmitOptions(EmitOptions):
    """Per-target options for :class:`AwsApiGatewayEmitter`."""

    integration_type: str = "http_proxy"
    pretty_print: bool = True


class _AwsWriter:
    """Add API Gateway integrations to the OpenAPI 3.0 projection of a model."""

    def __init__(self, api: CanonicalApi, options: AwsApiGatewayEmitOptions) -> None:
        self.api = api
        self.options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.operations: Dict[Tuple[str, str], Operation] = {
            ((op.http_method or "").upper(), op.http_path or ""): op for op in api.operations() if op.http_path
        }

    def build(self) -> Dict[str, Any]:
        """The OpenAPI 3.0 document with integrations."""
        if not self.operations:
            raise ValueError(
                "AWS API Gateway export requires at least one HTTP operation: a REST API integrates "
                "methods, and a model with none has nothing to integrate."
            )
        record_method_path_collisions(self.api, self.losses, label="API Gateway OpenAPI")
        projection = OpenApiEmitter().emit(self.api, opts=OpenApiEmitOptions(openapi_version="3.0"))
        for loss in projection.losses:
            self.losses.record(loss.kind, loss.subject, loss.detail, loss.pointer)
        content = projection.files[0].content
        document = copy.deepcopy(content if isinstance(content, dict) else json.loads(str(content)))
        for path, item in (document.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            extra = item.pop(_ADDITIONAL_OPERATIONS, None)
            if isinstance(extra, dict):
                for method, op in extra.items():
                    if str(method).upper() == "ANY":
                        item[ANY_METHOD] = op
                    else:
                        self.losses.record(
                            LossKind.NA,
                            "unsupported-method",
                            f"{method} {path}: API Gateway has no {method} method; the operation is not emitted.",
                            f"{method} {path}",
                        )
            for method in (*_HTTP_METHODS, ANY_METHOD):
                op = item.get(method)
                if isinstance(op, dict):
                    verb = "ANY" if method == ANY_METHOD else method.upper()
                    op[INTEGRATION] = self._integration(path, verb)
                    self._security(op, path, verb, document)
                    self._operation_id(op, path, verb)
                    self._operation_verbatim(op, item, path, verb)
        self._api_verbatim(document)
        return document

    def _operation_verbatim(self, op: Dict[str, Any], item: Dict[str, Any], path: str, verb: str) -> None:
        """Re-attach the operation- and path-level extensions an AWS import kept verbatim."""
        operation = self.operations.get((verb, path))
        verbatim = operation.extras.get(_AWS_EXTRAS) if operation is not None else None
        if not isinstance(verbatim, Mapping):
            return
        posture = operation.extras.get("validation") if operation is not None else None
        default = self.api.extras.get(_AWS_EXTRAS, {}).get("default_request_validator")
        if (
            isinstance(posture, Mapping)
            and isinstance(posture.get("validator"), str)
            and posture["validator"] != default
        ):
            op[REQUEST_VALIDATOR] = posture["validator"]
        if isinstance(verbatim.get("auth"), Mapping):
            op[AUTH] = copy.deepcopy(dict(verbatim["auth"]))
        for key, value in (verbatim.get("extensions") or {}).items():
            op.setdefault(str(key), copy.deepcopy(value))
        for key, value in (verbatim.get("pathExtensions") or {}).items():
            item.setdefault(str(key), copy.deepcopy(value))

    def _api_verbatim(self, document: Dict[str, Any]) -> None:
        """Re-attach the API-level settings, validators, CORS and authorizers of an AWS import."""
        report = self.api.extras.get(_AWS_EXTRAS)
        if not isinstance(report, Mapping):
            return
        for key, value in (report.get("settings") or {}).items():
            document.setdefault(str(key), copy.deepcopy(value))
        validators = report.get("request_validators")
        if isinstance(validators, Mapping) and validators:
            document[REQUEST_VALIDATORS] = copy.deepcopy(dict(validators))
        if isinstance(report.get("default_request_validator"), str):
            document[REQUEST_VALIDATOR] = report["default_request_validator"]
        cors = self.api.extras.get("cors")
        if isinstance(cors, Mapping) and cors.get("source") == CORS:
            document[CORS] = {k: copy.deepcopy(v) for k, v in cors.items() if k not in ("source", "provenance")}
        schemes = document.get("components", {}).get("securitySchemes", {})
        for authorizer in report.get("authorizers") or []:
            if not isinstance(authorizer, Mapping):
                continue
            name = str(authorizer.get("name"))
            body = {k: copy.deepcopy(v) for k, v in authorizer.items() if k not in ("name", "authType")}
            if name in schemes:
                if body:
                    schemes[name][AUTHORIZER] = body
                if authorizer.get("authType"):
                    schemes[name][AUTHTYPE] = authorizer["authType"]
            else:
                self.losses.record(
                    LossKind.NA,
                    "authorizer-not-emitted",
                    f"Authorizer {name!r} belongs to a security scheme the exported document does not "
                    "declare; it is not emitted.",
                    name,
                )

    def _integration(self, path: str, verb: str) -> Dict[str, Any]:
        """The integration of one method."""
        operation = self.operations.get((verb, path))
        method_key = ANY_METHOD if verb == "ANY" else verb.lower()
        pointer = f"/paths/{path.replace('~', '~0').replace('/', '~1')}/{method_key}/{INTEGRATION}"
        verbatim = operation.extras.get(_AWS_EXTRAS) if operation is not None else None
        if isinstance(verbatim, Mapping) and isinstance(verbatim.get("integration"), Mapping):
            self.tracker.record(pointer, Provenance.SOURCE, "Integration recorded by the AWS API Gateway import.")
            return copy.deepcopy(dict(verbatim["integration"]))
        base = self._base(operation)
        if base is None:
            self.losses.record(
                LossKind.INFERRED,
                "mock-integration",
                f"{verb} {path}: the model records no upstream for this operation, so it is integrated "
                "as a mock that answers 200; point it at a backend before deploying.",
                f"{verb} {path}",
            )
            self.tracker.record(pointer, Provenance.DEFAULT, "Mock integration: no upstream known.")
            return {
                "type": "mock",
                "requestTemplates": {"application/json": '{"statusCode": 200}'},
                "responses": {"default": {"statusCode": "200"}},
                "passthroughBehavior": "when_no_match",
            }
        integration: Dict[str, Any] = {
            "type": self.options.integration_type,
            "httpMethod": verb,
            "uri": base + path,
            "passthroughBehavior": "when_no_match",
        }
        params = _PATH_PARAM_RE.findall(path)
        if params:
            integration["requestParameters"] = {
                f"integration.request.path.{name}": f"method.request.path.{name}" for name in params
            }
        self.losses.record(
            LossKind.INFERRED,
            "synthesized-integration",
            f"{verb} {path}: integrated as {self.options.integration_type} to {base + path}, derived from "
            "the model's recorded upstream or server; the source declared no integration.",
            f"{verb} {path}",
        )
        self.tracker.record(pointer, Provenance.INFERRED, "Integration derived from the model's upstream.")
        return integration

    def _base(self, operation: Optional[Operation]) -> Optional[str]:
        return operation_upstream(self.api, operation) if operation is not None else None

    def _security(self, op: Dict[str, Any], path: str, verb: str, document: Dict[str, Any]) -> None:
        """Write the operation's security: declared schemes back, gateway-inferred keys as ``api_key``.

        Records an AWS (or APIM) import declared are rebuilt into ``securitySchemes`` with their
        authorizers; an ``api-key-required`` record becomes the flag again; an ``apiKey`` a
        gateway import inferred (``key-auth``) becomes API Gateway's ``api_key`` scheme. Anything
        else needs an authorizer function the model does not describe, and is declared.
        """
        operation = self.operations.get((verb, path))
        records = operation.extras.get("security") if operation is not None else None
        if not isinstance(records, list) or "security" in op:
            return
        declared = [r for r in records if isinstance(r, Mapping) and r.get("name") not in (AUTH, API_KEY_REQUIRED)]
        if any(isinstance(r, Mapping) and r.get("name") == API_KEY_REQUIRED for r in records):
            op[API_KEY_REQUIRED] = True
        leftovers = openapi_security_from_records(
            document,
            op,
            [r for r in declared if r.get("provenance") == "declared"],
            extension_keys={"authType": AUTHTYPE, "authorizer": AUTHORIZER},
        )
        inferred = [r for r in declared if r.get("provenance") != "declared"] + list(leftovers)
        for hint in inferred:
            scheme = hint.get("scheme")
            if scheme == "apiKey" and hint.get("provenance") != "declared":
                schemes = document.setdefault("components", {}).setdefault("securitySchemes", {})
                schemes.setdefault("api_key", {"type": "apiKey", "name": "x-api-key", "in": "header"})
                op.setdefault("security", []).append({"api_key": []})
            else:
                self.losses.record(
                    LossKind.NA,
                    "auth-not-emitted",
                    f"{verb} {path}: authentication {hint.get('plugin') or hint.get('name')!r} "
                    f"({scheme or 'no canonical scheme'}) has no API Gateway declaration without an "
                    "authorizer function the model does not describe; it is not emitted.",
                    f"{verb} {path}",
                )

    def _operation_id(self, op: Dict[str, Any], path: str, verb: str) -> None:
        """Keep an ``operationId`` only when the model declared one.

        The OpenAPI projection invents an id for an operation that has none (``getOrders``); a
        re-import would then rename the operation after it, so an invented id is removed.
        """
        operation = self.operations.get((verb, path))
        if operation is not None and operation.name == f"{verb} {path}":
            op.pop("operationId", None)


class AwsApiGatewayEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an API Gateway-importable OpenAPI 3.0 document."""

    key = AWS_APIGATEWAY_FORMAT_KEY
    format = AWS_APIGATEWAY_FORMAT_KEY
    label = "AWS API Gateway"
    description = (
        "Export as an API Gateway REST API definition (openapi.json): the OpenAPI 3.0 projection of "
        "the model, with an x-amazon-apigateway-integration on every operation — the recorded one, "
        "or an http_proxy to the recorded upstream."
    )
    icon = "cloud"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = AwsApiGatewayEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """OpenAPI 3.0 underneath: operations, unions, nullability and constraints carry."""
        return CapabilityProfile(
            operations=True, events=False, unions=True, nullability=True, constraints=True, field_identity=False
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the API Gateway degradation rules."""
        return AwsApiGatewayFidelityRulePack

    def emit(
        self, api: CanonicalApi, *, opts: Optional[Union[AwsApiGatewayEmitOptions, EmitOptions]] = None
    ) -> EmitResult:
        """Emit ``api`` as one ``openapi.json``.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown integration type.
            ValueError: When ``api`` has no HTTP operation.
        """
        from .emitter import EmitOptionsError

        try:
            options = (
                opts
                if isinstance(opts, AwsApiGatewayEmitOptions)
                else AwsApiGatewayEmitOptions.model_validate(opts.model_dump() if opts else {})
            )
        except ValueError as exc:
            raise EmitOptionsError(f"Invalid AWS API Gateway emit options: {exc}") from exc
        if options.integration_type not in ("http", "http_proxy"):
            raise EmitOptionsError("integration_type must be http or http_proxy")
        writer = _AwsWriter(api, options)
        document = writer.build()
        content = json.dumps(document, indent=2 if options.pretty_print else None, ensure_ascii=False)
        return EmitResult(
            files=[EmittedFile(path="openapi.json", content=content + "\n", media_type="application/json")],
            media_type="application/json",
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


# ===========================================================================
# Product gate
# ===========================================================================


def aws_document_violations(document: Any) -> List[str]:
    """The API Gateway import rules a document breaks.

    Args:
        document: The parsed OpenAPI document.

    Returns:
        One message per violation; empty when valid.
    """
    errors: List[str] = []
    if not isinstance(document, Mapping) or not str(document.get("openapi") or "").startswith("3.0"):
        return ["openapi: API Gateway imports OpenAPI 3.0 documents"]
    paths = document.get("paths")
    if not isinstance(paths, Mapping) or not paths:
        return ["paths: at least one path is required"]
    for path, item in paths.items():
        if not isinstance(item, Mapping):
            continue
        for method in (*_HTTP_METHODS, ANY_METHOD):
            op = item.get(method)
            if not isinstance(op, Mapping):
                continue
            where = f"{method} {path}"
            integration = op.get(INTEGRATION)
            if not isinstance(integration, Mapping):
                errors.append(f"{where}: every method needs an {INTEGRATION}")
                continue
            kind = str(integration.get("type") or "").lower()
            if kind not in INTEGRATION_TYPES:
                errors.append(f"{where}: integration type {kind!r} is not one of {', '.join(INTEGRATION_TYPES)}")
            elif kind in ("http", "http_proxy"):
                uri = integration.get("uri")
                if not isinstance(uri, str) or urlsplit(uri).scheme not in ("http", "https"):
                    errors.append(f"{where}: an {kind} integration needs an absolute http(s) uri")
                if not integration.get("httpMethod"):
                    errors.append(f"{where}: an {kind} integration needs an httpMethod")
            elif kind in ("aws", "aws_proxy"):
                uri = integration.get("uri")
                if not isinstance(uri, str) or not uri.startswith("arn:"):
                    errors.append(f"{where}: an {kind} integration needs an ARN uri")
    return errors


def validate_aws_apigateway_document(content: str, *, source_label: str = "emitted") -> None:
    """Validate emitted text as an API Gateway-importable OpenAPI document.

    Raises:
        ValueError: When the text does not re-import, or breaks an API Gateway import rule.
    """
    from .aws_apigateway_import_source import AwsApiGatewayImportSource
    from .import_source import ImportSourceError

    try:
        AwsApiGatewayImportSource().parse(content, source_label=source_label)
    except ImportSourceError as exc:
        raise ValueError(f"Invalid AWS API Gateway definition: {exc}") from exc
    violations = aws_document_violations(json.loads(content))
    if violations:
        raise ValueError("Invalid AWS API Gateway definition: " + "; ".join(violations))
