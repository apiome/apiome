"""GraphQL mock transport on the hosted HTTP listener (#5729, XPC-1.1).

A published GraphQL version with its mock on answers at ``/{tenant}/{project}/{version}/graphql``,
beside its REST-style routes on the same listener:

* ``GET`` with no ``query`` parameter serves the GraphiQL landing page, which introspects the
  schema through the same URL;
* ``GET`` with ``?query=…`` (and optional ``variables`` / ``operationName``) runs a query;
* ``POST`` with a JSON body ``{"query", "variables", "operationName"}`` runs any operation.

One request goes through these steps in order. A step that fails answers with a GraphQL
``errors[]`` document (HTTP 200), never a bare 5xx:

1. parse and validate the document (``graphql-core`` handles fragments, variables, aliases,
   ``@include`` / ``@skip`` and introspection, and reports unknown fields);
2. refuse subscriptions with ``extensions.code = "UNSUPPORTED_ON_THIS_DEPLOYMENT"`` (they need the
   WebSocket transport, XPC-2.6) and mutations over ``GET`` (HTTP 405);
3. enforce ``mock_settings.graphql.maxDepth`` / ``maxComplexity`` (``MAX_DEPTH_EXCEEDED`` /
   ``MAX_COMPLEXITY_EXCEEDED``);
4. pick the scenario (``X-Mock-Scenario`` header, else the stored active scenario);
5. apply chaos per root field (``Query.user``): the delay is the largest any selected root field
   draws, and an injected error nulls that root field with a ``MOCK_CHAOS_INJECTED`` error entry.
   The ``X-Mock-Chaos`` and ``X-Mock-Chaos-Delay-Ms`` headers report it as on the REST path;
6. render scenario overrides for the root fields they cover: a 2xx/3xx canned body becomes the
   field's value and a 4xx/5xx becomes a ``MOCK_SCENARIO_ERROR`` entry;
7. execute, resolving every other field through :mod:`apiome_mock.graphql_resolver`.

:func:`serve_graphql` is the framework-free core shared by the hosted route and the internal
sandbox endpoint. :func:`handle_graphql_request` is the hosted wrapper: it resolves the version,
enforces rate and quota limits, and records usage exactly as a REST call does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape
from typing import Any, Mapping

import structlog
from app.canonical_model import ApiParadigm
from app.mock_match import MatchContext
from app.mock_template import TemplateLimitError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from graphql import (
    DocumentNode,
    ExecutionResult,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLError,
    GraphQLSchema,
    GraphQLSyntaxError,
    InlineFragmentNode,
    OperationDefinitionNode,
    OperationType,
    SelectionSetNode,
    execute,
    get_operation_ast,
    parse,
    validate,
)
from psycopg_pool import AsyncConnectionPool
from starlette.requests import Request

from apiome_mock.api_key import ValidatedApiKey
from apiome_mock.canonical_compiler import GraphQlRoute, compile_canonical_spec
from apiome_mock.canonical_loader import load_canonical_spec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.chaos import (
    CHAOS_DELAY_HEADER,
    CHAOS_HEADER,
    ChaosDelayGuard,
    apply_chaos_delay,
    compute_delay_ms,
    effective_knobs,
    should_inject_error,
)
from apiome_mock.graphql_resolver import GraphQlValueResolver, RootOverride
from apiome_mock.graphql_schema import measure_operation
from apiome_mock.guard import enforce_mock_limits, record_mock_request, resolve_limits_for_tenant
from apiome_mock.scenarios import (
    MOCK_SCENARIO_HEADER,
    Scenario,
    render_canned_response,
    select_scenario_responses,
)
from apiome_mock.schema_synthesizer import parse_mock_seed
from apiome_mock.settings import Settings, get_settings
from apiome_mock.spec_loader import _fetch_access_row

_log = structlog.get_logger(__name__)

__all__ = [
    "CODE_CHAOS_INJECTED",
    "CODE_MAX_COMPLEXITY",
    "CODE_MAX_DEPTH",
    "CODE_SCENARIO_ERROR",
    "CODE_UNKNOWN_SCENARIO",
    "CODE_UNSUPPORTED",
    "GRAPHQL_OPERATION_SUPPORT",
    "GRAPHQL_PATH_SEGMENT",
    "GraphQlHttpRequest",
    "GraphQlHttpResult",
    "graphiql_page",
    "graphql_http_request",
    "handle_graphql_request",
    "is_graphql_source_format",
    "serve_graphql",
]

GRAPHQL_PATH_SEGMENT = "graphql"
"""Path segment the GraphQL route is mounted at, under ``/{tenant}/{project}/{version}``."""

CODE_UNSUPPORTED = "UNSUPPORTED_ON_THIS_DEPLOYMENT"
"""``extensions.code`` for an operation type this deployment does not execute (subscriptions)."""

CODE_MAX_DEPTH = "MAX_DEPTH_EXCEEDED"
"""``extensions.code`` when an operation nests deeper than ``maxDepth``."""

CODE_MAX_COMPLEXITY = "MAX_COMPLEXITY_EXCEEDED"
"""``extensions.code`` when an operation scores above ``maxComplexity``."""

CODE_CHAOS_INJECTED = "MOCK_CHAOS_INJECTED"
"""``extensions.code`` on a root field chaos turned into an error."""

CODE_SCENARIO_ERROR = "MOCK_SCENARIO_ERROR"
"""``extensions.code`` on a root field a scenario answered with a 4xx/5xx status."""

CODE_UNKNOWN_SCENARIO = "UNKNOWN_SCENARIO"
"""``extensions.code`` when ``X-Mock-Scenario`` names a scenario the version does not define."""

CODE_BAD_REQUEST = "BAD_REQUEST"
"""``extensions.code`` for a request the transport cannot read (no query, bad JSON)."""

GRAPHQL_OPERATION_SUPPORT: Mapping[str, str] = {
    "query": "supported",
    "mutation": "supported",
    "subscription": "unsupported",
}
"""What this deployment executes, per GraphQL operation type, for the capabilities report (XPC-5.5)."""

_GRAPHIQL_VERSION = "3.7.1"
_REACT_VERSION = "18.3.1"


@dataclass(frozen=True)
class GraphQlHttpRequest:
    """One GraphQL-over-HTTP request, independent of the web framework.

    Attributes:
        method: Upper-case HTTP method (``GET`` or ``POST``).
        headers: Request headers with lower-cased names.
        query: Query parameters, each with every supplied value in order.
        body: The parsed JSON body (``POST``), or ``None``.
        body_present: Whether the raw body was non-empty.
        body_invalid: Whether a non-empty body failed to parse as JSON.
    """

    method: str
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    body: Any = None
    body_present: bool = False
    body_invalid: bool = False

    def query_value(self, name: str) -> str | None:
        """Return the first value of one query parameter, or ``None``."""
        values = self.query.get(name)
        return values[0] if values else None


@dataclass
class GraphQlHttpResult:
    """What the GraphQL mock answered.

    Attributes:
        status: HTTP status (200 for every GraphQL-level outcome).
        body: The GraphQL response document (``data`` and/or ``errors``).
        headers: Response headers to set (scenario and chaos reporting).
        operation: The executed operation type (``query``/``mutation``/``subscription``), if any.
        scenario: The scenario in effect, if any.
    """

    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    operation: str | None = None
    scenario: str | None = None


def _error(message: str, code: str, **extensions: Any) -> dict[str, Any]:
    """Build one GraphQL error entry carrying ``extensions.code``."""
    return {"message": message, "extensions": {"code": code, **extensions}}


def _errors_result(status: int, *errors: dict[str, Any], operation: str | None = None) -> GraphQlHttpResult:
    """Build a result whose document holds only ``errors``."""
    return GraphQlHttpResult(status=status, body={"errors": list(errors)}, operation=operation)


def is_graphql_source_format(source_format: Any) -> bool:
    """Whether a version's ``source_format`` is GraphQL SDL (federated variants included)."""
    return isinstance(source_format, str) and source_format.strip().lower().startswith("graphql")


def _request_parameters(request: GraphQlHttpRequest) -> tuple[str | None, Any, str | None] | GraphQlHttpResult:
    """Read ``query`` / ``variables`` / ``operationName`` from the body (POST) or query string (GET).

    Args:
        request: The request.

    Returns:
        ``(query, variables, operation_name)``, or a 400 result when the request is unreadable.
    """
    if request.method == "POST":
        if request.body_invalid:
            return _errors_result(400, _error("The request body is not valid JSON.", CODE_BAD_REQUEST))
        body = request.body if isinstance(request.body, Mapping) else {}
        query, variables, operation_name = body.get("query"), body.get("variables"), body.get("operationName")
    else:
        query = request.query_value("query")
        operation_name = request.query_value("operationName")
        raw_variables = request.query_value("variables")
        variables = None
        if raw_variables:
            try:
                variables = json.loads(raw_variables)
            except json.JSONDecodeError:
                return _errors_result(400, _error("The 'variables' parameter is not valid JSON.", CODE_BAD_REQUEST))
    if not isinstance(query, str) or not query.strip():
        return _errors_result(400, _error("Provide a GraphQL document in 'query'.", CODE_BAD_REQUEST))
    if variables is not None and not isinstance(variables, Mapping):
        return _errors_result(400, _error("'variables' must be a JSON object.", CODE_BAD_REQUEST))
    if operation_name is not None and not isinstance(operation_name, str):
        return _errors_result(400, _error("'operationName' must be a string.", CODE_BAD_REQUEST))
    return query, variables, operation_name


def _root_field_names(
    selection_set: SelectionSetNode,
    fragments: Mapping[str, FragmentDefinitionNode],
    visiting: frozenset[str] = frozenset(),
) -> list[str]:
    """List the root field names an operation selects, fragments expanded, in order, deduplicated.

    Args:
        selection_set: The operation's selection set.
        fragments: The document's fragments by name.
        visiting: Fragment names already being expanded (cycle guard).

    Returns:
        The selected root field names (introspection fields excluded).
    """
    names: list[str] = []
    for selection in selection_set.selections:
        found: list[str] = []
        if isinstance(selection, FieldNode):
            found = [selection.name.value]
        elif isinstance(selection, InlineFragmentNode):
            found = _root_field_names(selection.selection_set, fragments, visiting)
        elif isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            fragment = fragments.get(name)
            if fragment is not None and name not in visiting:
                found = _root_field_names(fragment.selection_set, fragments, visiting | {name})
        names.extend(item for item in found if not item.startswith("__") and item not in names)
    return names


def _select_scenario(route: GraphQlRoute, request: GraphQlHttpRequest) -> Scenario | None | GraphQlHttpResult:
    """Pick the scenario for a request: the header first, then the stored active scenario.

    Args:
        route: The compiled GraphQL route.
        request: The request.

    Returns:
        The scenario, ``None`` when none applies, or an ``UNKNOWN_SCENARIO`` result when the header
        names a scenario the version does not define.
    """
    named = (request.headers.get(MOCK_SCENARIO_HEADER.lower()) or "").strip()
    if named:
        scenario = route.scenarios.get(named)
        if scenario is None:
            return _errors_result(
                200,
                _error(
                    f"No scenario named '{named}' is defined for this version.",
                    CODE_UNKNOWN_SCENARIO,
                    available=sorted(route.scenarios),
                ),
            )
        return scenario
    if route.active_scenario:
        return route.scenarios.get(route.active_scenario)
    return None


def _scenario_error_message(body: Any, scenario: str, status: int) -> str:
    """Choose the message of a scenario error entry from a canned body (problem+json aware)."""
    if isinstance(body, Mapping):
        for key in ("detail", "message", "title"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return f"Scenario '{scenario}' answered with status {status}."


def _scenario_override(
    scenario: Scenario,
    coordinate: str,
    *,
    ctx: MatchContext,
    seed: int,
    fixtures: Mapping[str, Any],
) -> RootOverride | None:
    """Render what one scenario declares for one root field.

    Only the first response of a selection is served. Sequences need a session to count calls in,
    and GraphQL requests carry several root fields at once, so a sequence position would be
    ambiguous.

    Args:
        scenario: The scenario in effect.
        coordinate: The root field's schema coordinate (``Query.user``).
        ctx: The request's match context (rules read it; ``body`` is the GraphQL request).
        seed: The request seed (templates read it).
        fixtures: Fixture data templates may read.

    Returns:
        The override, or ``None`` when the scenario does not cover this field (it then resolves
        through the default layers).
    """
    override = scenario.override_for(coordinate)
    if override is None:
        return None
    selection = select_scenario_responses(override, ctx)
    if selection is None:
        if override.status is not None and override.status >= 400:
            return RootOverride(
                error=GraphQLError(
                    f"Scenario '{scenario.name}' answered with status {override.status}.",
                    extensions={"code": CODE_SCENARIO_ERROR, "status": override.status, "scenario": scenario.name},
                )
            )
        return None
    rule_index, responses = selection
    try:
        canned = render_canned_response(
            responses[0],
            ctx=ctx,
            seed=seed,
            fixtures=fixtures,
            scenario_name=scenario.name,
            operation_key=coordinate,
            rule_index=rule_index,
        )
    except TemplateLimitError as exc:
        return RootOverride(
            error=GraphQLError(
                f"Scenario '{scenario.name}' template for {coordinate} exceeded its render budget: {exc}",
                extensions={"code": CODE_SCENARIO_ERROR, "scenario": scenario.name},
            )
        )
    if canned.status >= 400:
        return RootOverride(
            error=GraphQLError(
                _scenario_error_message(canned.body, scenario.name, canned.status),
                extensions={"code": CODE_SCENARIO_ERROR, "status": canned.status, "scenario": scenario.name},
            )
        )
    if not canned.has_body:
        return None
    return RootOverride(value=canned.body)


def _parse_and_validate(
    schema: GraphQLSchema, query: str, operation_name: str | None
) -> tuple[DocumentNode, OperationDefinitionNode] | GraphQlHttpResult:
    """Parse and validate a document and pick the operation to run.

    Returns:
        ``(document, operation)``, or a result carrying the syntax / validation errors.
    """
    try:
        document = parse(query)
    except GraphQLSyntaxError as exc:
        return GraphQlHttpResult(status=200, body={"errors": [exc.formatted]})
    errors = validate(schema, document)
    if errors:
        return GraphQlHttpResult(status=200, body={"errors": [error.formatted for error in errors]})
    operation = get_operation_ast(document, operation_name)
    if operation is None:
        message = (
            f"Unknown operation named '{operation_name}'."
            if operation_name
            else "Provide 'operationName' when the document holds more than one operation."
        )
        return _errors_result(200, _error(message, CODE_BAD_REQUEST))
    return document, operation


async def serve_graphql(
    route: GraphQlRoute,
    request: GraphQlHttpRequest,
    *,
    tenant: str,
    delay_guard: ChaosDelayGuard | None = None,
) -> GraphQlHttpResult:
    """Answer one GraphQL request against a compiled route (the steps in the module docstring).

    Args:
        route: The version's compiled GraphQL route.
        request: The request.
        tenant: Tenant slug, for chaos-delay accounting.
        delay_guard: Per-tenant chaos delay guard (the module default when omitted).

    Returns:
        The response document, status and headers.
    """
    parameters = _request_parameters(request)
    if isinstance(parameters, GraphQlHttpResult):
        return parameters
    query, variables, operation_name = parameters
    assert query is not None

    parsed = _parse_and_validate(route.schema, query, operation_name)
    if isinstance(parsed, GraphQlHttpResult):
        return parsed
    document, operation = parsed
    kind = operation.operation.value

    if operation.operation is OperationType.SUBSCRIPTION:
        return _errors_result(
            200,
            _error(
                "Subscriptions are not executed on this deployment's HTTP mock yet. Use a query or a mutation.",
                CODE_UNSUPPORTED,
            ),
            operation=kind,
        )
    if operation.operation is OperationType.MUTATION and request.method == "GET":
        return _errors_result(405, _error("Mutations must be sent with POST.", CODE_BAD_REQUEST), operation=kind)

    fragments = {
        definition.name.value: definition
        for definition in document.definitions
        if isinstance(definition, FragmentDefinitionNode)
    }
    measure = measure_operation(route.schema, operation, fragments, list_length=route.settings.list_length)
    if measure.depth > route.settings.max_depth:
        return _errors_result(
            200,
            _error(
                f"The operation is {measure.depth} levels deep; this mock allows {route.settings.max_depth}.",
                CODE_MAX_DEPTH,
                depth=measure.depth,
                maxDepth=route.settings.max_depth,
            ),
            operation=kind,
        )
    if measure.complexity > route.settings.max_complexity:
        return _errors_result(
            200,
            _error(
                f"The operation's complexity is {measure.complexity}; "
                f"this mock allows {route.settings.max_complexity}.",
                CODE_MAX_COMPLEXITY,
                complexity=measure.complexity,
                maxComplexity=route.settings.max_complexity,
            ),
            operation=kind,
        )

    selected = _select_scenario(route, request)
    if isinstance(selected, GraphQlHttpResult):
        selected.operation = kind
        return selected
    scenario = selected

    root = route.schema.get_root_type(operation.operation)
    assert root is not None
    coordinates = [f"{root.name}.{name}" for name in _root_field_names(operation.selection_set, fragments)]

    chaos_config = scenario.chaos if scenario is not None and scenario.chaos is not None else route.chaos
    knobs = {coordinate: effective_knobs(chaos_config, coordinate) for coordinate in coordinates}
    delay_ms = max((compute_delay_ms(entry) for entry in knobs.values()), default=0)
    applied_delay_ms = await apply_chaos_delay(delay_ms, tenant=tenant, guard=delay_guard)

    seed = parse_mock_seed(request.query_value("__seed"))
    overrides: dict[str, RootOverride] = {}
    injected = False
    ctx = MatchContext(
        method=request.method,
        path_params={},
        query=dict(request.query),
        headers=dict(request.headers),
        body=request.body,
        body_present=request.body_present,
    )
    for coordinate in coordinates:
        if should_inject_error(knobs[coordinate]):
            injected = True
            overrides[coordinate] = RootOverride(
                error=GraphQLError(
                    f"Chaos injected an error into {coordinate}.",
                    extensions={"code": CODE_CHAOS_INJECTED},
                )
            )
            continue
        if scenario is not None:
            scenario_override = _scenario_override(scenario, coordinate, ctx=ctx, seed=seed, fixtures=route.fixtures)
            if scenario_override is not None:
                overrides[coordinate] = scenario_override

    resolver = GraphQlValueResolver(
        schema=route.schema,
        examples=route.examples,
        fixtures=route.fixtures,
        seed=seed,
        list_length=route.settings.list_length,
        root_overrides=overrides,
    )
    outcome = execute(
        route.schema,
        document,
        variable_values=dict(variables) if variables else None,
        operation_name=operation_name,
        field_resolver=resolver.resolve_field,
        type_resolver=resolver.resolve_type,
    )
    if not isinstance(outcome, ExecutionResult):
        # Every resolver is synchronous, so execution never returns an awaitable.
        raise TypeError("GraphQL mock execution unexpectedly returned an awaitable")
    body: dict[str, Any] = dict(outcome.formatted)

    headers: dict[str, str] = {}
    if injected:
        headers[CHAOS_HEADER] = "error"
    if applied_delay_ms > 0:
        headers[CHAOS_DELAY_HEADER] = str(applied_delay_ms)
    if scenario is not None:
        headers[MOCK_SCENARIO_HEADER] = scenario.name
    return GraphQlHttpResult(
        status=200,
        body=body,
        headers=headers,
        operation=kind,
        scenario=scenario.name if scenario is not None else None,
    )


def graphiql_page(endpoint: str, *, title: str) -> str:
    """Render the GraphiQL landing page for one GraphQL mock.

    Args:
        endpoint: The URL GraphiQL sends operations (and its introspection query) to.
        title: The page title (the API's coordinates).

    Returns:
        A self-contained HTML document loading pinned GraphiQL and React builds from unpkg.
    """
    safe_title = escape(title)
    # ``<`` is escaped so no value can close the inline <script> it is written into.
    endpoint_json = json.dumps(endpoint).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} · GraphQL mock</title>
<link rel="stylesheet" href="https://unpkg.com/graphiql@{_GRAPHIQL_VERSION}/graphiql.min.css">
<style>html, body, #graphiql {{ height: 100%; margin: 0; }}</style>
</head>
<body>
<div id="graphiql">Loading GraphiQL…</div>
<script crossorigin src="https://unpkg.com/react@{_REACT_VERSION}/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@{_REACT_VERSION}/umd/react-dom.production.min.js"></script>
<script crossorigin src="https://unpkg.com/graphiql@{_GRAPHIQL_VERSION}/graphiql.min.js"></script>
<script>
  const fetcher = GraphiQL.createFetcher({{ url: {endpoint_json} }});
  ReactDOM.createRoot(document.getElementById("graphiql")).render(
    React.createElement(GraphiQL, {{ fetcher, defaultEditorToolsVisibility: true }})
  );
</script>
</body>
</html>
"""


async def graphql_http_request(request: Request) -> GraphQlHttpRequest:
    """Project a Starlette request onto :class:`GraphQlHttpRequest`."""
    query: dict[str, tuple[str, ...]] = {}
    for name, value in request.query_params.multi_items():
        query[name] = (*query.get(name, ()), value)
    headers = {name.lower(): value for name, value in request.headers.items()}
    body: Any = None
    body_present = False
    body_invalid = False
    if request.method.upper() == "POST":
        raw = await request.body()
        body_present = bool(raw)
        if body_present:
            try:
                body = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                body_invalid = True
    return GraphQlHttpRequest(
        method=request.method.upper(),
        headers=headers,
        query=query,
        body=body,
        body_present=body_present,
        body_invalid=body_invalid,
    )


async def _resolve_graphql_route(
    *,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None,
) -> GraphQlRoute | Response | None:
    """Find the compiled GraphQL route of a version.

    Returns:
        The route; ``None`` when the version is not a GraphQL version (or is not mockable), so the
        caller serves the request through the REST path instead; or an error response when the
        version is GraphQL but its schema cannot be built.
    """
    cached = cache.get(tenant, project, version)
    if cached is not None:
        return cached.graphql
    access_row = await _fetch_access_row(pool, tenant=tenant, project=project, version=version)
    if access_row is None or not is_graphql_source_format(access_row.get("source_format")):
        return None
    loaded = await load_canonical_spec(pool, tenant=tenant, project=project, version=version, api_key=api_key)
    if loaded is None or loaded.paradigm is not ApiParadigm.GRAPH:
        return None
    try:
        compiled = compile_canonical_spec(loaded)
    except ValueError as exc:
        _log.warning(
            "graphql_mock_schema_build_failed", tenant=tenant, project=project, version=version, error=str(exc)
        )
        return JSONResponse(
            {"errors": [_error("This version's GraphQL schema could not be built for mocking.", CODE_UNSUPPORTED)]},
            status_code=200,
        )
    cache.put(compiled)
    return compiled.graphql


async def handle_graphql_request(
    request: Request,
    *,
    tenant: str,
    project: str,
    version: str,
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    api_key: ValidatedApiKey | None,
    settings: Settings | None = None,
) -> Response | None:
    """Serve ``/{tenant}/{project}/{version}/graphql`` for a GraphQL version.

    Args:
        request: The incoming request.
        tenant: Tenant slug.
        project: Project slug.
        version: Version label.
        pool: Database pool.
        cache: Compiled canonical spec cache.
        api_key: The validated API key, if one was presented.
        settings: Runtime settings (resolved when omitted).

    Returns:
        The response, or ``None`` when the version is not a GraphQL version. The caller then
        serves the request through the REST path, so a REST API that has its own ``/graphql``
        operation keeps working.
    """
    cfg = settings or get_settings()
    resolved = await _resolve_graphql_route(
        pool=pool, cache=cache, tenant=tenant, project=project, version=version, api_key=api_key
    )
    if resolved is None:
        return None
    if isinstance(resolved, Response):
        return resolved

    blocked = await enforce_mock_limits(
        request, tenant=tenant, project=project, version=version, pool=pool, settings=cfg
    )
    if blocked is not None:
        return blocked

    graphql_request = await graphql_http_request(request)
    response: Response
    if graphql_request.method == "GET" and graphql_request.query_value("query") is None:
        response = HTMLResponse(
            graphiql_page(str(request.url.replace(query="")), title=f"{tenant}/{project}/{version}")
        )
    else:
        result = await serve_graphql(resolved, graphql_request, tenant=tenant)
        response = JSONResponse(result.body, status_code=result.status, headers=result.headers)
        _log.info(
            "graphql_mock_served",
            tenant=tenant,
            project=project,
            version=version,
            operation=result.operation,
            status=result.status,
            scenario=result.scenario,
        )

    limits = await resolve_limits_for_tenant(pool, tenant, settings=cfg)
    if limits is not None:
        record_mock_request(
            pool=pool,
            request=request,
            tenant=tenant,
            project=project,
            version=version,
            path=GRAPHQL_PATH_SEGMENT,
            status_code=response.status_code,
            tenant_id=limits.tenant_id,
            api_key_id=api_key.id if api_key is not None else None,
            settings=cfg,
        )
    return response
