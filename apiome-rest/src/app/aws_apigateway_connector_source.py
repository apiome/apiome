"""AWS API Gateway connector source — CDG-1.3 (#5954).

FMT-7.1 (:mod:`app.aws_apigateway_import_source`) reads an exported REST or HTTP API with its
``x-amazon-apigateway-*`` extensions, but someone has to export each API by hand, per stage, and
the catalog goes stale. This source pulls the exports live.

**Access: assume a role, never store keys.** The connector's scope names an IAM role in the
tenant's account and the external id its trust policy requires::

    {"roleArn": "arn:aws:iam::123456789012:role/apiome-catalog",
     "externalId": "apiome-7c1d…", "regions": ["eu-west-1", "us-east-1"]}

Apiome calls ``sts:AssumeRole`` from its own AWS identity (the deployment's default credential
chain: environment, instance profile or workload identity) and uses the temporary credentials
for one sync. A connector of this kind stores no credential at all — ``PUT …/credentials`` is
refused — so no long-lived key ever reaches Apiome. AWS documents the external id as a
non-secret, so it lives in the scope.

**Required permissions** (:data:`REQUIRED_POLICY`): ``apigateway:GET`` on ``/account``,
``/restapis``, ``/restapis/*``, ``/apis`` and ``/apis/*`` in each region. They are checked when
the connector is created (or its scope changes) by a dry run (:func:`check_aws_connection`):
assume the role, call ``GetAccount``, then list one REST and one HTTP API per region. A denial is
reported by the action and resource AWS names, for example ``apigateway:GET on
arn:aws:apigateway:eu-west-1::/restapis``.

**Inventory.** Per region: ``GetRestApis`` + ``GetStages`` for REST APIs and ``GetApis`` +
``GetStages`` for HTTP APIs (WebSocket APIs cannot be exported and are reported as a finding).
**Each deployed stage is one catalog item**: its ``environment`` is the stage name, its invoke URL
is in ``hosts``, and its ``deploymentId`` is the remote revision, so a stage whose deployment has
not changed is skipped by the newer-than gate and listed as unchanged with that reason. A stage
with no deployment cannot be exported and is a finding. A region with no APIs is a successful run
with no candidates, plus an ``region-empty`` finding so the empty result is visible.

**Definitions.** ``GetExport`` (``exportType=oas30``, ``extensions=apigateway``) for a REST API
stage and ``ExportApi`` (``Specification=OAS30``, ``IncludeExtensions=true``) for an HTTP API
stage. The bytes go to the FMT-7.1 adapter unchanged.

**Owners.** An API tag ``apiome:owner`` (value: a team slug) becomes a CDG-2.2 *suggested* owner
on the item's ``deployment``; a malformed value is a finding.

**Failures.** A refusal from AWS raises :class:`~app.refresh_source.RefreshSourceError` with AWS's
HTTP status and, for an access denial, the missing permission named. A deployment with no AWS
identity of its own fails with ``invalid-configuration``.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from .catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from .catalog_connectors import CODE_CHECK_FAILED, CODE_INVALID, ConnectorError, suggested_owner
from .refresh_source import (
    ERROR_CLASS_AUTH,
    ERROR_CLASS_UNEXPECTED,
    FetchedDocument,
    RefreshCandidate,
    RefreshSourceError,
)

__all__ = [
    "AwsApiGatewaySource",
    "ERROR_CLASS_INVALID_CONFIGURATION",
    "KIND",
    "OWNER_TAG",
    "REQUIRED_ACTIONS",
    "REQUIRED_POLICY",
    "check_aws_connection",
    "session_factory",
    "validate_aws_scope",
]

KIND = "aws-apigateway"

#: The API tag whose value names a suggested owner team.
OWNER_TAG = "apiome:owner"

#: Error class for a connector or deployment that cannot address AWS at all.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"

#: Finding codes (``summary.findings[].code``).
FINDING_REGION_EMPTY = "region-empty"
FINDING_STAGE_NOT_DEPLOYED = "stage-not-deployed"
FINDING_WEBSOCKET_SKIPPED = "websocket-api-not-exported"
FINDING_OWNER_TAG_INVALID = "owner-tag-invalid"

#: The session name every assumed-role session carries (visible in the tenant's CloudTrail).
ROLE_SESSION_NAME = "apiome-catalog-connector"
#: How long the assumed credentials last; one sync must finish within it.
ROLE_SESSION_SECONDS = 3600

#: The calls a sync makes, with the IAM action and resource each needs (``{region}`` filled in).
REQUIRED_ACTIONS: Tuple[Tuple[str, str, str], ...] = (
    ("sts:AssumeRole", "sts:AssumeRole", "<roleArn> (trust policy, with the external id)"),
    ("apigateway:GetAccount", "apigateway:GET", "arn:aws:apigateway:{region}::/account"),
    ("apigateway:GetRestApis", "apigateway:GET", "arn:aws:apigateway:{region}::/restapis"),
    ("apigateway:GetStages / GetExport", "apigateway:GET", "arn:aws:apigateway:{region}::/restapis/*"),
    ("apigatewayv2:GetApis", "apigateway:GET", "arn:aws:apigateway:{region}::/apis"),
    ("apigatewayv2:GetStages / ExportApi", "apigateway:GET", "arn:aws:apigateway:{region}::/apis/*"),
)

#: The permissions policy to attach to the role (read-only; the connector never writes).
REQUIRED_POLICY: Dict[str, Any] = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ApiomeCatalogRead",
            "Effect": "Allow",
            "Action": "apigateway:GET",
            "Resource": [
                "arn:aws:apigateway:*::/account",
                "arn:aws:apigateway:*::/restapis",
                "arn:aws:apigateway:*::/restapis/*",
                "arn:aws:apigateway:*::/apis",
                "arn:aws:apigateway:*::/apis/*",
            ],
        }
    ],
}

_ROLE_ARN = re.compile(r"^arn:aws(?:-[a-z]+)*:iam::(\d{12}):role/[\w+=,.@/-]{1,512}$")
_EXTERNAL_ID = re.compile(r"^[\w+=,.@:/-]{2,1224}$")
_REGION = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d{1,2}$")
_MAX_REGIONS = 32
_DENIED = re.compile(r"perform: (?P<action>\S+)(?: on resource: (?P<resource>\S+))?")
_DENIED_CODES = frozenset(
    {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedException", "Forbidden"}
)
_BOTO_CONFIG = Config(retries={"mode": "standard", "max_attempts": 4}, connect_timeout=10, read_timeout=60)

#: Builds a boto3 session (``boto3.Session(**kwargs)``). Module-level so tests can substitute one
#: that runs against moto or answers exports from fixtures.
session_factory: Callable[..., Any] = boto3.Session


def _session(**kwargs: Any) -> Any:
    """A session from the current :data:`session_factory` (looked up at call time)."""
    return session_factory(**kwargs)


# ---------------------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------------------


def validate_aws_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check an ``aws-apigateway`` scope: ``roleArn``, ``externalId`` and ``regions``.

    Raises:
        ConnectorError: ``connector-invalid`` for a base URL (AWS endpoints are fixed), an unknown
            key, a malformed role ARN or external id, or a missing or malformed region list.
    """
    if base_url:
        raise ConnectorError(CODE_INVALID, "An aws-apigateway connector takes no base URL; AWS endpoints are fixed.")
    unknown = sorted(set(scope) - {"roleArn", "externalId", "regions"})
    if unknown:
        raise ConnectorError(CODE_INVALID, f"Unknown aws-apigateway scope key(s): {', '.join(unknown)}.")
    if not isinstance(scope.get("roleArn"), str) or not _ROLE_ARN.fullmatch(scope["roleArn"]):
        raise ConnectorError(CODE_INVALID, "roleArn must be an IAM role ARN (arn:aws:iam::<account>:role/<name>).")
    if not isinstance(scope.get("externalId"), str) or not _EXTERNAL_ID.fullmatch(scope["externalId"]):
        raise ConnectorError(
            CODE_INVALID, "externalId is required: 2-1224 characters of letters, digits and +=,.@:/-_ ."
        )
    regions = scope.get("regions")
    if (
        not isinstance(regions, list)
        or not regions
        or len(regions) > _MAX_REGIONS
        or not all(isinstance(r, str) and _REGION.fullmatch(r) for r in regions)
        or len(set(regions)) != len(regions)
    ):
        raise ConnectorError(CODE_INVALID, f"regions must list 1-{_MAX_REGIONS} distinct AWS regions (e.g. eu-west-1).")


# ---------------------------------------------------------------------------------------
# AWS calls and error mapping
# ---------------------------------------------------------------------------------------


def _aws_error(exc: Exception, *, action: str, resource: str) -> RefreshSourceError:
    """Translate a boto error into a :class:`RefreshSourceError`, naming a denied permission."""
    if isinstance(exc, NoCredentialsError):
        return RefreshSourceError(
            "This Apiome deployment has no AWS identity to assume the role from; give it one "
            "(environment, instance profile or workload identity).",
            error_class=ERROR_CLASS_INVALID_CONFIGURATION,
        )
    if isinstance(exc, ClientError):
        error = exc.response.get("Error") or {}
        code = str(error.get("Code") or "")
        message = str(error.get("Message") or exc)
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if code in _DENIED_CODES or status == 403:
            match = _DENIED.search(message)
            denied_action = match.group("action") if match else action
            denied_resource = (match.group("resource") if match else None) or resource
            return RefreshSourceError(
                f"Missing permission {denied_action} on {denied_resource}: {message}",
                http_status=status or 403,
                error_class=ERROR_CLASS_AUTH,
            )
        return RefreshSourceError(f"AWS refused {action} on {resource} ({code}): {message}", http_status=status)
    if isinstance(exc, BotoCoreError):
        return RefreshSourceError(f"AWS did not answer {action}: {type(exc).__name__}: {exc}")
    return RefreshSourceError(f"{action} failed: {type(exc).__name__}", error_class=ERROR_CLASS_UNEXPECTED)


def _call(action: str, resource: str, fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Call one AWS operation, translating every boto error (see :func:`_aws_error`)."""
    try:
        return fn(**kwargs)
    except (ClientError, BotoCoreError) as exc:
        raise _aws_error(exc, action=action, resource=resource) from exc


def assume_role(scope: Mapping[str, Any]) -> Any:
    """Assume the connector's role and return a session on the temporary credentials.

    Raises:
        RefreshSourceError: ``auth`` naming ``sts:AssumeRole`` when the trust policy refuses
            Apiome or the external id; ``invalid-configuration`` without an AWS identity.
    """
    role_arn = str(scope["roleArn"])
    regions = list(scope.get("regions") or [])
    sts = _session().client("sts", region_name=regions[0] if regions else "us-east-1", config=_BOTO_CONFIG)
    response = _call(
        "sts:AssumeRole",
        role_arn,
        sts.assume_role,
        RoleArn=role_arn,
        RoleSessionName=ROLE_SESSION_NAME,
        ExternalId=str(scope["externalId"]),
        DurationSeconds=ROLE_SESSION_SECONDS,
    )
    creds = response["Credentials"]
    return _session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _arn(region: str, path: str) -> str:
    return f"arn:aws:apigateway:{region}::{path}"


def check_aws_connection(connector: Mapping[str, Any]) -> None:
    """The creation-time dry run: assume the role, ``GetAccount``, list one API of each kind.

    Raises:
        ConnectorError: ``connector-check-failed`` with ``reason`` set to the missing permission
            (``sts:AssumeRole``, ``apigateway:GET on arn:aws:apigateway:eu-west-1::/account``, …).
    """
    scope = connector.get("scope") if isinstance(connector.get("scope"), Mapping) else {}
    try:
        session = assume_role(scope)
        for region in scope.get("regions") or []:
            v1 = session.client("apigateway", region_name=region, config=_BOTO_CONFIG)
            v2 = session.client("apigatewayv2", region_name=region, config=_BOTO_CONFIG)
            _call("apigateway:GET", _arn(region, "/account"), v1.get_account)
            _call("apigateway:GET", _arn(region, "/restapis"), v1.get_rest_apis, limit=1)
            _call("apigateway:GET", _arn(region, "/apis"), v2.get_apis, MaxResults="1")
    except RefreshSourceError as exc:
        match = re.match(r"Missing permission (\S+ on \S+?): ", str(exc))
        reason = match.group(1) if match else exc.error_class
        raise ConnectorError(CODE_CHECK_FAILED, f"The AWS dry run failed: {exc}", reason=reason) from exc


def _pages(fetch: Callable[[Optional[str]], Tuple[List[Dict[str, Any]], Optional[str]]]) -> Iterator[Dict[str, Any]]:
    """Every item of a paged AWS list, following its continuation token."""
    token: Optional[str] = None
    seen = set()
    while True:
        items, token = fetch(token)
        yield from items
        if not token or token in seen:
            return
        seen.add(token)


# ---------------------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------------------


class AwsApiGatewaySource(ConnectorRefreshSource):
    """``aws-apigateway``: every deployed stage of every REST and HTTP API in the scoped regions.

    Args:
        connector: The connector row (scope: ``roleArn``, ``externalId``, ``regions``).
        credentials: Always ``None`` — this kind stores none.
    """

    def __init__(self, connector: Mapping[str, Any], credentials: Optional[Dict[str, str]] = None) -> None:
        super().__init__(connector, credentials)
        self.findings: List[Dict[str, Any]] = []
        self._session: Any = None

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    def _client(self, service: str, region: str) -> Any:
        if self._session is None:
            self._session = assume_role(self.scope)
        return self._session.client(service, region_name=region, config=_BOTO_CONFIG)

    def _account(self) -> Optional[str]:
        match = _ROLE_ARN.fullmatch(str(self.scope.get("roleArn") or ""))
        return match.group(1) if match else None

    def _owners(self, tags: Mapping[str, Any], location: Dict[str, Any]) -> List[Dict[str, str]]:
        value = tags.get(OWNER_TAG) if isinstance(tags, Mapping) else None
        if value is None:
            return []
        suggestion = suggested_owner(str(value), f"{OWNER_TAG}={value}")
        if suggestion is None:
            self.findings.append(
                {
                    "code": FINDING_OWNER_TAG_INVALID,
                    "severity": "warning",
                    **location,
                    "tag": f"{OWNER_TAG}={value}",
                    "message": "Owner tag does not name a team slug (lower-case letters, digits and '-').",
                }
            )
            return []
        return [suggestion]

    def _candidate(
        self,
        *,
        region: str,
        api_type: str,
        api_id: str,
        api_name: str,
        stage: str,
        deployment_id: str,
        invoke_url: str,
        tags: Mapping[str, Any],
        extra: Dict[str, Any],
    ) -> RefreshCandidate:
        location = {"region": region, "apiType": api_type, "apiId": api_id, "apiName": api_name, "stage": stage}
        deployment = {
            **location,
            "accountId": self._account(),
            "deploymentId": deployment_id,
            "invokeUrl": invoke_url,
            "tags": dict(sorted((str(k), str(v)) for k, v in (tags or {}).items())),
            **extra,
            "suggestedOwners": self._owners(tags or {}, location),
        }
        path = invoke_url.split(".amazonaws.com", 1)[-1] if ".amazonaws.com" in invoke_url else ""
        return RefreshCandidate(
            remote_id=f"{region}/{api_type}/{api_id}/{stage}",
            name=f"{api_name} ({stage})",
            revision=deployment_id,
            environment=stage,
            hosts=(invoke_url,),
            base_path=path or None,
            raw={"region": region, "apiType": api_type, "apiId": api_id, "stage": stage},
            deployment=deployment,
        )

    def _stage_missing(self, location: Dict[str, Any]) -> None:
        self.findings.append(
            {
                "code": FINDING_STAGE_NOT_DEPLOYED,
                "severity": "warning",
                **location,
                "message": "The stage has no deployment, so there is nothing to export; deploy it to import it.",
            }
        )

    def _rest_candidates(self, region: str) -> List[RefreshCandidate]:
        client = self._client("apigateway", region)

        def rest_page(token: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            kwargs: Dict[str, Any] = {"limit": 500}
            if token:
                kwargs["position"] = token
            body = _call("apigateway:GET", _arn(region, "/restapis"), client.get_rest_apis, **kwargs)
            return list(body.get("items") or []), body.get("position")

        candidates: List[RefreshCandidate] = []
        for api in _pages(rest_page):
            api_id, name = str(api["id"]), str(api.get("name") or api["id"])
            stages = _call(
                "apigateway:GET", _arn(region, f"/restapis/{api_id}/stages"), client.get_stages, restApiId=api_id
            ).get("item") or []
            for stage in stages:
                stage_name = str(stage.get("stageName"))
                deployment_id = stage.get("deploymentId")
                location = {"region": region, "apiType": "rest", "apiId": api_id, "apiName": name, "stage": stage_name}
                if not deployment_id:
                    self._stage_missing(location)
                    continue
                candidates.append(
                    self._candidate(
                        region=region,
                        api_type="rest",
                        api_id=api_id,
                        api_name=name,
                        stage=stage_name,
                        deployment_id=str(deployment_id),
                        invoke_url=f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage_name}",
                        tags=api.get("tags") or {},
                        extra={"endpointTypes": list((api.get("endpointConfiguration") or {}).get("types") or [])},
                    )
                )
        return candidates

    def _http_candidates(self, region: str) -> List[RefreshCandidate]:
        client = self._client("apigatewayv2", region)

        def api_page(token: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            kwargs: Dict[str, Any] = {"MaxResults": "500"}
            if token:
                kwargs["NextToken"] = token
            body = _call("apigateway:GET", _arn(region, "/apis"), client.get_apis, **kwargs)
            return list(body.get("Items") or []), body.get("NextToken")

        candidates: List[RefreshCandidate] = []
        for api in _pages(api_page):
            api_id, name = str(api["ApiId"]), str(api.get("Name") or api["ApiId"])
            if str(api.get("ProtocolType") or "").upper() != "HTTP":
                self.findings.append(
                    {
                        "code": FINDING_WEBSOCKET_SKIPPED,
                        "severity": "info",
                        "region": region,
                        "apiId": api_id,
                        "apiName": name,
                        "message": "WebSocket APIs cannot be exported by API Gateway and are not imported.",
                    }
                )
                continue

            def stage_page(token: Optional[str], api_id: str = api_id) -> Tuple[List[Dict[str, Any]], Optional[str]]:
                kwargs: Dict[str, Any] = {"ApiId": api_id}
                if token:
                    kwargs["NextToken"] = token
                body = _call("apigateway:GET", _arn(region, f"/apis/{api_id}/stages"), client.get_stages, **kwargs)
                return list(body.get("Items") or []), body.get("NextToken")

            endpoint = str(api.get("ApiEndpoint") or f"https://{api_id}.execute-api.{region}.amazonaws.com")
            for stage in _pages(stage_page):
                stage_name = str(stage.get("StageName"))
                deployment_id = stage.get("DeploymentId")
                location = {"region": region, "apiType": "http", "apiId": api_id, "apiName": name, "stage": stage_name}
                if not deployment_id:
                    self._stage_missing(location)
                    continue
                invoke = endpoint if stage_name == "$default" else f"{endpoint}/{stage_name}"
                candidates.append(
                    self._candidate(
                        region=region,
                        api_type="http",
                        api_id=api_id,
                        api_name=name,
                        stage=stage_name,
                        deployment_id=str(deployment_id),
                        invoke_url=invoke,
                        tags=api.get("Tags") or {},
                        extra={"autoDeploy": bool(stage.get("AutoDeploy", False))},
                    )
                )
        return candidates

    def list_candidates(self) -> List[RefreshCandidate]:
        """Assume the role and list every deployed stage of every REST and HTTP API, per region."""
        self.findings = []
        candidates: List[RefreshCandidate] = []
        for region in self.scope.get("regions") or []:
            found = self._rest_candidates(region) + self._http_candidates(region)
            if not found:
                self.findings.append(
                    {
                        "code": FINDING_REGION_EMPTY,
                        "severity": "info",
                        "region": region,
                        "message": "No REST or HTTP API with a deployed stage in this region.",
                    }
                )
            candidates.extend(found)
        return candidates

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """Export one stage with its API Gateway extensions (``GetExport`` / ``ExportApi``)."""
        raw = candidate.raw
        region, api_id, stage = str(raw["region"]), str(raw["apiId"]), str(raw["stage"])
        if raw.get("apiType") == "rest":
            client = self._client("apigateway", region)
            response = _call(
                "apigateway:GET",
                _arn(region, f"/restapis/{api_id}/stages/{stage}/exports/oas30"),
                client.get_export,
                restApiId=api_id,
                stageName=stage,
                exportType="oas30",
                parameters={"extensions": "apigateway"},
                accepts="application/json",
            )
        else:
            client = self._client("apigatewayv2", region)
            response = _call(
                "apigateway:GET",
                _arn(region, f"/apis/{api_id}/exports/OAS30"),
                client.export_api,
                ApiId=api_id,
                Specification="OAS30",
                OutputType="JSON",
                IncludeExtensions=True,
                StageName=stage,
            )
        body = response.get("body")
        content = body.read() if hasattr(body, "read") else bytes(body or b"")
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{candidate.name or api_id}").strip("-") or "api"
        return FetchedDocument(
            content=content,
            filename=f"{slug}.json",
            import_kind=KIND,
            revision=candidate.revision,
            source_uri=f"https://{region}.console.aws.amazon.com/apigateway/main/apis?region={region}",
        )

    def explain_unchanged(self, candidate: RefreshCandidate) -> str:
        """Why a stage was not re-imported: its deployment has not changed."""
        return (
            f"Stage {candidate.environment} of {candidate.deployment.get('apiName')}: deploymentId "
            f"{candidate.revision} is unchanged since the last import, so it was not re-imported."
        )

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, roleArn, regions}`` (no credentials: there are none)."""
        return {
            **super().describe(),
            "roleArn": self.scope.get("roleArn"),
            "regions": list(self.scope.get("regions") or []),
        }


register_connector_source(
    KIND,
    AwsApiGatewaySource,
    scope_validator=validate_aws_scope,
    connection_check=check_aws_connection,
    accepts_credentials=False,
)
