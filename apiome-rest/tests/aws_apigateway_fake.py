"""A moto-backed AWS estate for the API Gateway connector (CDG-1.3, #5954).

moto stands in for STS and for API Gateway's inventory calls (``GetRestApis``, ``GetStages``,
``GetApis``, ``GetAccount``, tags). It cannot stand in for the exports — moto's ``GetExport``
returns a bare Swagger document without ``x-amazon-apigateway-*`` extensions and ``ExportApi`` is
not implemented — so :func:`session_factory_with` answers ``GetExport`` / ``ExportApi`` from
fixture bytes through botocore's ``before-call`` hook, exactly where AWS would answer them. A hook
can also refuse any operation with an ``AccessDenied`` naming the permission, the way IAM does.

The estate: one REST API ``orders`` (stages ``prod`` and ``dev``, tagged ``apiome:owner=payments``)
and one HTTP API ``subscriptions`` (stage ``$default``) in ``eu-west-1``; ``us-east-1`` is empty.
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

import boto3
from moto import mock_aws

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "aws-apigateway"
REST_EXPORT = (EXAMPLES / "02-typical-rest-api-export.json").read_bytes()
HTTP_EXPORT_YAML = (EXAMPLES / "06-typical-http-api-export.yaml").read_text()
ROLE_ARN = "arn:aws:iam::123456789012:role/apiome-catalog"
EXTERNAL_ID = "apiome-ext-7c1d9a"
REGION = "eu-west-1"
EMPTY_REGION = "us-east-1"


def http_export_json() -> bytes:
    """The HTTP API fixture as the JSON ExportApi returns (``OutputType=JSON``)."""
    import json

    import yaml

    return json.dumps(yaml.safe_load(HTTP_EXPORT_YAML), indent=2).encode()


@contextmanager
def moto_estate(monkeypatch) -> Iterator[Dict[str, Any]]:
    """Start moto, build the estate and yield its ids.

    Yields:
        ``{rest_id, http_id, deployments: {stage: deploymentId}, exports: {(apiId, stage): bytes}}``.
    """
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        gw = boto3.client("apigateway", region_name=REGION)
        rest = gw.create_rest_api(name="orders", tags={"apiome:owner": "payments"})
        root = next(r for r in gw.get_resources(restApiId=rest["id"])["items"] if r["path"] == "/")
        resource = gw.create_resource(restApiId=rest["id"], parentId=root["id"], pathPart="orders")
        gw.put_method(restApiId=rest["id"], resourceId=resource["id"], httpMethod="GET", authorizationType="NONE")
        gw.put_integration(restApiId=rest["id"], resourceId=resource["id"], httpMethod="GET", type="MOCK")
        prod = gw.create_deployment(restApiId=rest["id"], stageName="prod")["id"]
        dev = gw.create_deployment(restApiId=rest["id"], stageName="dev")["id"]

        v2 = boto3.client("apigatewayv2", region_name=REGION)
        http = v2.create_api(Name="subscriptions", ProtocolType="HTTP", Tags={"apiome:owner": "subscriptions"})
        # moto models no v2 deployments: the session factory adds this id to GetStages.
        deployment = "h7x2k9"
        v2.create_stage(ApiId=http["ApiId"], StageName="$default", AutoDeploy=True)
        v2.create_api(Name="chat", ProtocolType="WEBSOCKET", RouteSelectionExpression="$request.body.action")

        yield {
            "rest_id": rest["id"],
            "http_id": http["ApiId"],
            "deployments": {"prod": prod, "dev": dev, "$default": deployment},
            "http_deployments": {(http["ApiId"], "$default"): deployment},
            "exports": {
                (rest["id"], "prod"): REST_EXPORT,
                (rest["id"], "dev"): REST_EXPORT,
                (http["ApiId"], "$default"): http_export_json(),
            },
        }


def _response(status: int = 200) -> Any:
    return SimpleNamespace(status_code=status, headers={}, content=b"")


def denied(action: str, resource: str) -> Tuple[Any, Dict[str, Any]]:
    """The ``(http, parsed)`` pair IAM's AccessDenied produces, naming ``action`` on ``resource``."""
    return (
        _response(403),
        {
            "Error": {
                "Code": "AccessDenied",
                "Message": f"User: arn:aws:iam::999999999999:user/apiome is not authorized to perform: {action} "
                f"on resource: {resource}",
            },
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
    )


def session_factory_with(
    exports: Dict[Tuple[str, str], bytes],
    *,
    http_deployments: Optional[Dict[Tuple[str, str], str]] = None,
    refuse: Optional[Dict[str, Tuple[str, str]]] = None,
    calls: Optional[list] = None,
) -> Callable[..., Any]:
    """A ``boto3.Session`` factory whose sessions answer exports from ``exports``.

    Args:
        exports: ``(apiId, stage) -> bytes`` served by ``GetExport`` / ``ExportApi``.
        http_deployments: ``(apiId, stage) -> deploymentId`` added to HTTP API ``GetStages``
            answers (moto does not model v2 deployments; AWS returns ``DeploymentId``).
        refuse: ``event name -> (action, resource)`` to answer with AccessDenied, e.g.
            ``{"before-call.sts.AssumeRole": ("sts:AssumeRole", ROLE_ARN)}``.
        calls: When given, every export call is appended as ``(operation, apiId, stage)``.
    """

    def remember(params: Dict[str, Any], context: Dict[str, Any], **_: Any) -> None:
        # before-call sees the serialized request; keep the API parameters for it.
        context["apiome_params"] = dict(params)

    def export(context: Dict[str, Any], operation: str, api_key: str, stage_key: str) -> Tuple[Any, Dict[str, Any]]:
        params = context["apiome_params"]
        api_id, stage = params[api_key], params.get(stage_key)
        if calls is not None:
            calls.append((operation, api_id, stage))
        return _response(), {"body": io.BytesIO(exports[(api_id, stage)]), "contentType": "application/json"}

    def factory(**kwargs: Any) -> Any:
        session = boto3.Session(**kwargs)
        events = session.events
        events.register("before-parameter-build.api-gateway.GetExport", remember)
        events.register("before-parameter-build.apigatewayv2.ExportApi", remember)
        events.register(
            "before-call.api-gateway.GetExport",
            lambda context, **_: export(context, "GetExport", "restApiId", "stageName"),
        )
        events.register(
            "before-call.apigatewayv2.ExportApi",
            lambda context, **_: export(context, "ExportApi", "ApiId", "StageName"),
        )
        def add_deployments(parsed: Dict[str, Any], context: Dict[str, Any], **_: Any) -> None:
            api_id = context.get("apiome_params", {}).get("ApiId")
            for stage in parsed.get("Items") or []:
                deployment_id = (http_deployments or {}).get((api_id, stage.get("StageName")))
                if deployment_id:
                    stage["DeploymentId"] = deployment_id

        events.register("before-parameter-build.apigatewayv2.GetStages", remember)
        events.register("after-call.apigatewayv2.GetStages", add_deployments)
        for event, (action, resource) in (refuse or {}).items():
            events.register(event, lambda action=action, resource=resource, **_: denied(action, resource))
        return session

    return factory
