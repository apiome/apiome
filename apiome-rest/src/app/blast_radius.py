"""The blast-radius query — CDG-3.3 (#5968).

"What consumes this operation, and what evidence do we lose if it changes?" — answered over the
catalog graph (:mod:`app.catalog_graph`, apiome-db V288) and the evidence tables.

**Affected entities.** A change to an entity (optionally narrowed to JSON ``pointers`` into it)
affects whatever depends on it, along *inbound* edges of the dependency kinds — ``consumes``,
``depends_on`` and ``runtime_calls`` (:data:`DEPENDENCY_EDGES`). Structural edges (``served_by``,
``deployed_on``, ``built_from``, ``identity_of``, ``converted_from``) are not dependents.

* **Direct** (depth 1): for a project or catalog item, the ``consumes`` layer is the **CTG-4.2
  intersection** — :meth:`Database.find_consumer_contracts_by_pointers` as the candidate set, kept
  only where :func:`app.consumer_impact.pointers_overlap` holds segment-wise, and every current
  contract for a document-wide change (``/security``, ``/servers``, …) — so this and the
  per-consumer impact analysis never disagree. Every other inbound dependency edge counts when it
  has no pointer (it depends on the whole entity) or its pointer overlaps a changed one.
* **Transitive** (depth 2..``depth``): anything with an inbound dependency edge into an affected
  entity, whatever its pointer (a change reaches a dependent of a dependent whole).

Stale edges are skipped. Traversal is breadth-first, one indexed query per level, at most
:data:`MAX_DEPTH` levels and :data:`MAX_NODES` entities; past that ``truncated`` is true. Each
entity carries its edge ``path`` from the changed entity, its provenance and its owner team.

**Invalidated evidence** (for a project or catalog item, in one version — the request's, else the
latest published, else the latest revision):

=========================  ====================================================================
``verification_runs``      the latest provider verification run per target for the version that
                           exercised an affected operation (CTG-4.3)
``consumer_contracts``     current contract revisions whose ``surface_pointers`` overlap
``deploy_gate_evaluations``  deploy-gate / publish evaluations that cited one of those runs
``sdk_regen_targets``      the project's active SDK regeneration subscriptions (V258), when the
                           change reaches any dependent or other evidence (SDKs are project-wide)
``agent_toolset_tools``    the version's agent-toolset tools for an affected operation (AGX-1.2)
``mock_fixture_packs``     the version's fixture packs whose collection path is a prefix of an
                           affected operation's path, and scenarios keyed by an affected operation
``sunset_consumers``       current contracts pinned to a deprecated or sunset version of the
                           project whose pointers overlap
=========================  ====================================================================

Operations are matched by method and **template shape**: ``GET /pets/{id}`` matches a run's
``GET /pets/{petId}``. A schema pointer (``/components/schemas/Pet``) affects every operation of the
version's document that reaches it through ``$ref``s. ``evidence_checked`` is true whenever the
evidence was looked for — empty sections are an answer, not an absence.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .catalog_graph import PROVENANCES
from .consumer_impact import DOCUMENT_WIDE_PREFIXES, pointer_covers, pointers_overlap
from .declared_dependencies import DependencyValidationError

__all__ = [
    "DEFAULT_DEPTH",
    "DEPENDENCY_EDGES",
    "MAX_DEPTH",
    "MAX_NODES",
    "BlastRadiusRequest",
    "affected_operations",
    "blast_radius",
    "operation_key_from_pointer",
    "shape_pointer",
    "template_shape",
]

_logger = logging.getLogger(__name__)

#: Inbound edges of these kinds make their source a dependent of their target.
DEPENDENCY_EDGES: Tuple[str, ...] = ("consumes", "depends_on", "runtime_calls")

DEFAULT_DEPTH = 3
MAX_DEPTH = 5
MAX_NODES = 2_000

#: At most this many rows per evidence section.
_EVIDENCE_LIMIT = 500

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
_PROJECT_KINDS = ("project", "catalog_item")
_PARAM = re.compile(r"\{[^}/]*\}")


@dataclass(frozen=True)
class BlastRadiusRequest:
    """One blast-radius question.

    Attributes:
        kind: The changed entity's kind.
        entity: Its id, or a project/catalog-item slug.
        pointers: JSON pointers into it that change; empty means the whole entity.
        depth: Levels to walk, 1..:data:`MAX_DEPTH`.
        provenances: Edge provenances to follow.
        version: A version label or id for the evidence; ``None`` for the default.
    """

    kind: str
    entity: str
    pointers: Tuple[str, ...] = ()
    depth: int = DEFAULT_DEPTH
    provenances: Tuple[str, ...] = PROVENANCES
    version: Optional[str] = None


# ---------------------------------------------------------------------------------------------
# Pointers and operations
# ---------------------------------------------------------------------------------------------


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _segments(pointer: str) -> List[str]:
    return [_unescape(part) for part in pointer.split("/")[1:]] if pointer.startswith("/") else []


def template_shape(path: str) -> str:
    """A path template with its parameter names erased: ``/pets/{petId}`` → ``/pets/{}``."""
    return _PARAM.sub("{}", path or "")


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def shape_pointer(pointer: str) -> str:
    """A pointer with its ``/paths`` template's parameter names erased, for comparison.

    ``/paths/~1pets~1{petId}/get`` and ``/paths/~1pets~1{id}/get`` both become
    ``/paths/~1pets~1{}/get``; any other pointer is returned unchanged.
    """
    if not pointer.startswith("/paths/"):
        return pointer
    head, _, rest = pointer[len("/paths/"):].partition("/")
    shaped = "/paths/" + _escape(template_shape(_unescape(head)))
    return f"{shaped}/{rest}" if rest else shaped


def operation_key_from_pointer(pointer: str) -> Optional[Tuple[Optional[str], str]]:
    """The operation a ``/paths/…`` pointer is at or under, as ``(METHOD | None, path)``.

    ``/paths/~1pets~1{id}/get/responses/200`` → ``("GET", "/pets/{id}")``; ``/paths/~1pets~1{id}``
    (the whole path item) → ``(None, "/pets/{id}")``. Anything outside ``/paths`` → ``None``.
    """
    parts = _segments(pointer)
    if len(parts) < 2 or parts[0] != "paths":
        return None
    method = parts[2].lower() if len(parts) > 2 and parts[2].lower() in _HTTP_METHODS else None
    return (method.upper() if method else None, parts[1])


def _refs_in(node: Any, found: Set[str]) -> None:
    """Every local ``$ref`` target pointer under ``node``."""
    if isinstance(node, Mapping):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            found.add(ref[1:])
        for value in node.values():
            _refs_in(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs_in(value, found)


def _resolve(document: Mapping[str, Any], pointer: str) -> Any:
    node: Any = document
    for part in _segments(pointer):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        else:
            return None
    return node


def _reachable_refs(document: Mapping[str, Any], node: Any) -> Set[str]:
    """Every ``$ref`` target reachable from ``node``, following refs through the document."""
    seen: Set[str] = set()
    queue: deque = deque()
    first: Set[str] = set()
    _refs_in(node, first)
    queue.extend(first)
    while queue:
        target = queue.popleft()
        if target in seen:
            continue
        seen.add(target)
        nested: Set[str] = set()
        _refs_in(_resolve(document, target), nested)
        queue.extend(nested - seen)
    return seen


def affected_operations(
    pointers: Sequence[str], document: Optional[Mapping[str, Any]]
) -> Tuple[Optional[List[Tuple[Optional[str], str]]], List[str]]:
    """The operations a set of changed pointers reaches.

    Args:
        pointers: The changed pointers; empty means the whole entity.
        document: The version's OpenAPI document, used for pointers outside ``/paths`` (schemas,
            shared parameters, …); ``None`` when unavailable.

    Returns:
        ``(operations, warnings)`` — ``operations`` is ``None`` for "every operation" (no pointers,
        or a document-wide change), else ``[(METHOD | None, path)]``.
    """
    if not pointers:
        return None, []
    warnings: List[str] = []
    operations: List[Tuple[Optional[str], str]] = []
    component_pointers: List[str] = []
    for pointer in pointers:
        if pointer in ("", "/") or any(pointer_covers(prefix, pointer) for prefix in DOCUMENT_WIDE_PREFIXES):
            return None, []
        key = operation_key_from_pointer(pointer)
        if key is not None:
            operations.append(key)
        else:
            component_pointers.append(pointer)
    if component_pointers:
        if not isinstance(document, Mapping):
            warnings.append("the version's document is unavailable, so schema pointers reach no operations")
        else:
            paths = document.get("paths") if isinstance(document.get("paths"), Mapping) else {}
            for path, item in paths.items():
                if not isinstance(item, Mapping):
                    continue
                shared = [item.get("parameters")]
                for method, op in item.items():
                    if str(method).lower() not in _HTTP_METHODS or not isinstance(op, Mapping):
                        continue
                    refs = _reachable_refs(document, [op, shared])
                    if any(pointers_overlap(ref, changed) for ref in refs for changed in component_pointers):
                        operations.append((str(method).upper(), str(path)))
    unique = sorted(set(operations), key=lambda op: (op[1], op[0] or ""))
    return unique, warnings


def _matches(operations: Optional[List[Tuple[Optional[str], str]]], method: str, path: str) -> bool:
    """Whether an operation ``method path`` is one of ``operations`` (``None`` = all)."""
    if operations is None:
        return True
    shape = template_shape(path)
    return any(
        template_shape(op_path) == shape and (op_method is None or op_method == (method or "").upper())
        for op_method, op_path in operations
    )


def _parse_key(key: str) -> Tuple[str, str]:
    """``"GET /pets/{id}"`` → ``("GET", "/pets/{id}")``."""
    method, _, path = str(key or "").strip().partition(" ")
    return method.upper(), path.strip()


def _overlaps_any(declared: Iterable[str], changed: Sequence[str]) -> List[str]:
    """The changed pointers that meet any declared pointer (segment-wise); all of them when the
    change is the whole entity or document-wide."""
    declared = list(declared or [])
    if not changed:
        return []
    hits = []
    for pointer in changed:
        if pointer in ("", "/") or any(pointer_covers(prefix, pointer) for prefix in DOCUMENT_WIDE_PREFIXES):
            hits.append(pointer)
        elif any(pointers_overlap(shape_pointer(pointer), shape_pointer(item)) for item in declared):
            hits.append(pointer)
    return hits


# ---------------------------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------------------------


@dataclass
class _Node:
    kind: str
    id: str
    depth: int
    edge_kind: str
    provenance: str
    pointers: List[str] = field(default_factory=list)
    path: List[Dict[str, Any]] = field(default_factory=list)


def _edge_step(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "from_kind": row["from_kind"], "from_id": str(row["from_id"]),
        "to_kind": row["to_kind"], "to_id": str(row["to_id"]),
        "edge_kind": row["edge_kind"], "provenance": row["provenance"], "pointer": row.get("pointer"),
    }


def _concrete_pointers(db: Any, tenant_id: str, project_id: str, pointers: Sequence[str]) -> List[str]:
    """Rewrite ``/paths`` pointers onto the templates the project's contracts actually use.

    ``/paths/~1pets~1{id}/get`` becomes ``/paths/~1pets~1{petId}/get`` when the contracts declare
    ``/pets/{petId}``, so the CTG-4.2 string intersection finds them. Other pointers, and paths no
    contract declares, are kept as given.
    """
    if not any(p.startswith("/paths/") for p in pointers):
        return list(pointers)
    rows = db.execute_query(
        """
        SELECT DISTINCT split_part(substr(p, 8), '/', 1) AS token
        FROM apiome.consumer_contract cc, unnest(cc.surface_pointers) AS p
        WHERE cc.project_id = %s::uuid AND cc.tenant_id = %s::uuid AND cc.is_current AND p LIKE '/paths/%%'
        """,
        (project_id, tenant_id),
    )
    by_shape: Dict[str, List[str]] = {}
    for row in rows:
        token = str(row["token"])
        by_shape.setdefault(template_shape(_unescape(token)), []).append(token)
    out: List[str] = []
    for pointer in pointers:
        if not pointer.startswith("/paths/"):
            out.append(pointer)
            continue
        head, _, rest = pointer[len("/paths/"):].partition("/")
        tokens = by_shape.get(template_shape(_unescape(head))) or [head]
        out.extend(f"/paths/{token}/{rest}" if rest else f"/paths/{token}" for token in sorted(tokens))
    return list(dict.fromkeys(out))


def _current_contracts(db: Any, tenant_id: str, project_id: str, pointers: Sequence[str]) -> List[Dict[str, Any]]:
    """The CTG-4.2 consumes layer: current contracts whose surface meets the change."""
    whole = not pointers or bool(_overlaps_any([], pointers))
    if whole:
        rows = db.execute_query(
            """
            SELECT cc.id::text AS id, cc.consumer_id::text AS consumer_id, cc.revision,
                   cc.version_id::text AS version_id, cc.version_label, cc.surface_pointers
            FROM apiome.consumer_contract cc
            JOIN apiome.consumer c ON c.id = cc.consumer_id
            WHERE cc.project_id = %s::uuid AND cc.tenant_id = %s::uuid AND cc.is_current
              AND c.deleted_at IS NULL
            ORDER BY c.slug
            """,
            (project_id, tenant_id),
        )
        return [{**dict(row), "matched": list(pointers)} for row in rows]
    kept = []
    concrete = _concrete_pointers(db, tenant_id, project_id, pointers)
    for row in db.find_consumer_contracts_by_pointers(project_id, tenant_id, concrete):
        hits = _overlaps_any(row.get("surface_pointers") or [], pointers)
        if hits:
            kept.append({**dict(row), "matched": hits})
    return kept


def _inbound(
    db: Any, tenant_id: str, ids: Sequence[str], provenances: Sequence[str], *, skip_derived_consumes: bool
) -> List[Dict[str, Any]]:
    """Current inbound dependency edges into ``ids``."""
    extra = " AND NOT (edge_kind = 'consumes' AND provenance = 'derived')" if skip_derived_consumes else ""
    return db.execute_query(
        f"""
        SELECT from_kind, from_id::text AS from_id, to_kind, to_id::text AS to_id, edge_kind,
               provenance, pointer
        FROM apiome.catalog_edges
        WHERE tenant_id = %s::uuid AND to_id = ANY(%s::uuid[]) AND edge_kind = ANY(%s::text[])
          AND provenance = ANY(%s::text[]) AND stale_since IS NULL{extra}
        ORDER BY to_id, edge_kind, from_kind, from_id, pointer NULLS FIRST
        """,
        (tenant_id, list(ids), list(DEPENDENCY_EDGES), list(provenances)),
    )


def _traverse(
    db: Any, tenant_id: str, root: Tuple[str, str], request: BlastRadiusRequest, contracts: List[Dict[str, Any]]
) -> Tuple[Dict[str, _Node], bool, int]:
    """Breadth-first walk of inbound dependency edges (module docstring).

    Returns:
        ``(nodes, truncated, total_found)`` — ``total_found`` also counts the entities seen past the
        node cap or one level past the depth bound, so it is a lower bound when truncated.
    """
    root_kind, root_id = root
    nodes: Dict[str, _Node] = {}
    beyond: Set[str] = set()
    truncated = False

    def add(node: _Node) -> bool:
        nonlocal truncated
        if node.id == root_id or node.id in nodes:
            existing = nodes.get(node.id)
            if existing and existing.depth == node.depth:
                existing.pointers = sorted(set(existing.pointers) | set(node.pointers))
            return False
        if len(nodes) >= MAX_NODES:
            truncated = True
            beyond.add(node.id)
            return False
        nodes[node.id] = node
        return True

    if root_kind in _PROJECT_KINDS and "derived" in request.provenances:
        for row in contracts:
            add(_Node(
                "consumer", row["consumer_id"], 1, "consumes", "derived", list(row.get("matched") or []),
                [{"from_kind": "consumer", "from_id": row["consumer_id"], "to_kind": root_kind, "to_id": root_id,
                  "edge_kind": "consumes", "provenance": "derived", "pointer": None,
                  "source_ref": f"consumer_contract:{row['id']}"}],
            ))
    for row in _inbound(db, tenant_id, [root_id], request.provenances,
                        skip_derived_consumes=root_kind in _PROJECT_KINDS):
        pointer = row.get("pointer")
        if request.pointers and pointer and not _overlaps_any([pointer], request.pointers):
            continue
        add(_Node(row["from_kind"], row["from_id"], 1, row["edge_kind"], row["provenance"],
                  [pointer] if pointer else [], [_edge_step(row)]))

    frontier = [node.id for node in nodes.values()]
    for depth in range(2, request.depth + 1):
        if not frontier or truncated:
            break
        parents = {node_id: nodes[node_id] for node_id in frontier}
        frontier = []
        for row in _inbound(db, tenant_id, list(parents), request.provenances, skip_derived_consumes=False):
            parent = parents.get(str(row["to_id"]))
            if parent is None:
                continue
            node = _Node(row["from_kind"], row["from_id"], depth, row["edge_kind"], row["provenance"],
                         [row["pointer"]] if row.get("pointer") else [], [*parent.path, _edge_step(row)])
            if add(node):
                frontier.append(node.id)
    if frontier and not truncated:
        # The depth bound cut the walk short only if the next level has new entities: one probe.
        probe = _inbound(db, tenant_id, frontier[:MAX_NODES], request.provenances, skip_derived_consumes=False)
        unseen = {str(row["from_id"]) for row in probe} - set(nodes) - {root_id}
        truncated = bool(unseen)
        beyond |= unseen
    return nodes, truncated, len(nodes) + len(beyond)


# ---------------------------------------------------------------------------------------------
# Names and owners
# ---------------------------------------------------------------------------------------------

def _labels(db: Any, tenant_id: str, refs: Sequence[Tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
    """``{id: {name, slug}}`` (:func:`app.graph_nodes.label_nodes`)."""
    from .graph_nodes import label_nodes

    return label_nodes(db, tenant_id, refs)


def _owners(db: Any, tenant_id: str, refs: Sequence[Tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
    """``{id: owner}`` (:func:`app.graph_nodes.node_owners`)."""
    from .graph_nodes import node_owners

    return node_owners(db, tenant_id, [entity_id for _kind, entity_id in refs])


# ---------------------------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------------------------


def _resolve_version(db: Any, tenant_id: str, project_id: str, version: Optional[str]) -> Optional[Dict[str, Any]]:
    """The evidence version: the requested one (label or id), else latest published, else latest."""
    if version:
        rows = db.execute_query(
            """
            SELECT v.id::text AS id, v.version_id AS label, v.published, v.mock_settings
            FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
            WHERE v.project_id = %s::uuid AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
              AND (v.version_id = %s OR v.id::text = %s)
            ORDER BY v.created_at DESC LIMIT 1
            """,
            (project_id, tenant_id, version, version),
        )
        if not rows:
            raise DependencyValidationError("graph-entity-not-found", f"no version '{version}' of this project")
        return dict(rows[0])
    rows = db.execute_query(
        """
        SELECT v.id::text AS id, v.version_id AS label, v.published, v.mock_settings
        FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.project_id = %s::uuid AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
        ORDER BY v.published DESC, COALESCE(v.published_at, v.created_at) DESC, v.created_at DESC
        LIMIT 1
        """,
        (project_id, tenant_id),
    )
    return dict(rows[0]) if rows else None


def _version_document(db: Any, tenant_id: str, version: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The version's OpenAPI document: its frozen snapshot, else a render; ``None`` on failure."""
    try:
        snapshot = db.get_spec_snapshot(version["id"], with_content=True)
        content = (snapshot or {}).get("content")
        if isinstance(content, Mapping):
            return dict(content)
        if isinstance(content, str):
            import json

            return json.loads(content)
        from .compatibility_engine import openapi_for_revision

        row = db.get_version_by_id(version["id"], tenant_id)
        tenant = db.execute_query("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (tenant_id,))
        return openapi_for_revision(row, tenant[0]["slug"], tenant_id) if row and tenant else None
    except Exception as exc:  # noqa: BLE001 - schema → operation mapping is best-effort
        _logger.info("blast radius: no document for version %s (%s)", version.get("id"), type(exc).__name__)
        return None


def _verification_runs(
    db: Any, tenant_id: str, version_id: str, operations: Optional[List[Tuple[Optional[str], str]]]
) -> List[Dict[str, Any]]:
    """The latest run per target for the version that exercised an affected operation."""
    rows = db.execute_query(
        """
        WITH latest AS (
            SELECT DISTINCT ON (COALESCE(r.target_id::text, r.target_slug))
                   r.id, r.target_slug, r.target_environment, r.outcome, r.finished_at
            FROM apiome.verification_run r
            WHERE r.tenant_id = %s::uuid AND r.source->>'revision_id' = %s
            ORDER BY COALESCE(r.target_id::text, r.target_slug), r.finished_at DESC, r.id
        )
        SELECT l.id::text AS run_id, l.target_slug, l.target_environment, l.outcome, l.finished_at,
               array_agg(o.operation_key ORDER BY o.sequence) AS operation_keys,
               array_agg(o.http_method ORDER BY o.sequence) AS methods,
               array_agg(o.http_path ORDER BY o.sequence) AS paths
        FROM latest l
        JOIN apiome.verification_run_operation o ON o.run_id = l.id AND o.tenant_id = %s::uuid
        GROUP BY l.id, l.target_slug, l.target_environment, l.outcome, l.finished_at
        ORDER BY l.finished_at DESC, l.id
        """,
        (tenant_id, version_id, tenant_id),
    )
    runs = []
    for row in rows:
        hits = sorted({
            key for key, method, path in zip(row["operation_keys"], row["methods"], row["paths"])
            if _matches(operations, method, path)
        })
        if hits:
            finished = row.get("finished_at")
            runs.append({
                "run_id": row["run_id"], "target": row.get("target_slug"),
                "environment": row.get("target_environment"), "outcome": row.get("outcome"),
                "finished_at": finished.isoformat() if hasattr(finished, "isoformat") else finished,
                "operations": hits,
            })
    return runs[:_EVIDENCE_LIMIT]


def _gate_evaluations(db: Any, tenant_id: str, run_ids: Sequence[str]) -> List[Dict[str, Any]]:
    if not run_ids:
        return []
    rows = db.execute_query(
        """
        SELECT id::text AS id, purpose, passed, enforcement, version_record_id::text AS version_id,
               evaluated_at, ARRAY(SELECT unnest(evidence_run_ids)::text INTERSECT
                                   SELECT unnest(%s::text[])) AS cited_runs
        FROM apiome.verification_policy_evaluations
        WHERE tenant_id = %s::uuid AND evidence_run_ids && %s::uuid[]
        ORDER BY evaluated_at DESC
        LIMIT %s
        """,
        (list(run_ids), tenant_id, list(run_ids), _EVIDENCE_LIMIT),
    )
    out = []
    for row in rows:
        item = dict(row)
        evaluated = item.get("evaluated_at")
        item["evaluated_at"] = evaluated.isoformat() if hasattr(evaluated, "isoformat") else evaluated
        item["cited_runs"] = sorted(item.get("cited_runs") or [])
        out.append(item)
    return out


def _sdk_targets(db: Any, tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    rows = db.execute_query(
        """
        SELECT id::text AS id, ecosystem, delivery_mode
        FROM apiome.sdk_regen_subscriptions
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND active
        ORDER BY ecosystem
        """,
        (tenant_id, project_id),
    )
    return [dict(row) for row in rows]


def _toolset_tools(
    db: Any, tenant_id: str, version_id: str, operations: Optional[List[Tuple[Optional[str], str]]]
) -> List[Dict[str, Any]]:
    rows = db.execute_query(
        """
        SELECT t.id::text AS id, t.toolset_id::text AS toolset_id, t.operation_key, t.tool_name,
               t.enabled, t.write_op
        FROM apiome.agent_toolset_tools t
        JOIN apiome.agent_toolsets s ON s.id = t.toolset_id
        WHERE s.tenant_id = %s::uuid AND s.version_id = %s::uuid
        ORDER BY t.operation_key
        """,
        (tenant_id, version_id),
    )
    return [dict(row) for row in rows if _matches(operations, *_parse_key(row["operation_key"]))][:_EVIDENCE_LIMIT]


def _path_prefix(prefix: str, path: str) -> bool:
    """Segment-wise: ``/pets`` is a prefix of ``/pets/{id}`` but not of ``/petsitters``."""
    a = [part for part in template_shape(prefix).split("/") if part]
    b = [part for part in template_shape(path).split("/") if part]
    return b[: len(a)] == a


def _mock_evidence(
    mock_settings: Any, operations: Optional[List[Tuple[Optional[str], str]]]
) -> List[Dict[str, Any]]:
    """Fixture packs and scenarios of the version that touch an affected operation."""
    settings = mock_settings if isinstance(mock_settings, Mapping) else {}
    found: List[Dict[str, Any]] = []
    packs = settings.get("fixturePacks") if isinstance(settings.get("fixturePacks"), Mapping) else {}
    for name, pack in sorted(packs.items()):
        collections = pack.get("collections") if isinstance(pack, Mapping) else None
        paths = sorted(collections) if isinstance(collections, Mapping) else []
        hits = [
            path for path in paths
            if operations is None or any(_path_prefix(path, op_path) for _m, op_path in operations)
        ]
        if hits:
            found.append({"kind": "fixture_pack", "name": str(name), "collections": hits})
    scenarios = settings.get("scenarios") if isinstance(settings.get("scenarios"), Mapping) else {}
    for name, scenario in sorted(scenarios.items()):
        ops = scenario.get("operations") if isinstance(scenario, Mapping) else None
        keys = sorted(ops) if isinstance(ops, Mapping) else []
        hits = [key for key in keys if key == "*" or _matches(operations, *_parse_key(key))]
        if hits:
            found.append({"kind": "scenario", "name": str(name), "operations": hits})
    return found


def _sunset_consumers(
    db: Any, tenant_id: str, project_id: str, pointers: Sequence[str]
) -> List[Dict[str, Any]]:
    rows = db.execute_query(
        """
        SELECT cc.id::text AS contract_id, cc.consumer_id::text AS consumer_id, c.slug AS consumer_slug,
               c.name AS consumer_name, cc.revision, v.id::text AS version_id, v.version_id AS version_label,
               COALESCE(v.metadata->>'sunsetDate', v.metadata->>'sunset_date') AS sunset_date,
               cc.surface_pointers
        FROM apiome.consumer_contract cc
        JOIN apiome.consumer c ON c.id = cc.consumer_id AND c.deleted_at IS NULL
        JOIN apiome.versions v ON v.id = cc.version_id AND v.deleted_at IS NULL AND v.published
        WHERE cc.tenant_id = %s::uuid AND cc.project_id = %s::uuid AND cc.is_current
          AND (
            COALESCE(v.metadata->>'deprecated', '') IN ('true', '1', 'True', 'yes')
            OR (v.metadata @> '{"deprecated": true}'::jsonb)
            OR NULLIF(trim(COALESCE(v.metadata->>'sunsetDate', v.metadata->>'sunset_date', '')), '') IS NOT NULL
          )
        ORDER BY c.slug
        LIMIT %s
        """,
        (tenant_id, project_id, _EVIDENCE_LIMIT),
    )
    out = []
    for row in rows:
        if pointers and not _overlaps_any(row.get("surface_pointers") or [], pointers):
            continue
        item = {k: v for k, v in dict(row).items() if k != "surface_pointers"}
        out.append(item)
    return out


def _empty_evidence() -> Dict[str, List[Any]]:
    return {
        "verification_runs": [], "consumer_contracts": [], "deploy_gate_evaluations": [],
        "sdk_regen_targets": [], "agent_toolset_tools": [], "mock_fixture_packs": [], "sunset_consumers": [],
    }


# ---------------------------------------------------------------------------------------------
# The query
# ---------------------------------------------------------------------------------------------


def _validate(request: BlastRadiusRequest) -> None:
    if not 1 <= int(request.depth) <= MAX_DEPTH:
        raise DependencyValidationError("graph-invalid", f"depth must be between 1 and {MAX_DEPTH}")
    bad = [p for p in request.provenances if p not in PROVENANCES]
    if bad or not request.provenances:
        raise DependencyValidationError("graph-invalid", f"provenance must be among {', '.join(PROVENANCES)}")
    for pointer in request.pointers:
        if pointer and not pointer.startswith("/"):
            raise DependencyValidationError("graph-invalid", f"pointer '{pointer}' must start with '/'")
    if len(request.pointers) > 200:
        raise DependencyValidationError("graph-invalid", "at most 200 pointers")


def blast_radius(db: Any, tenant_id: str, request: BlastRadiusRequest) -> Dict[str, Any]:
    """Answer one blast-radius question (module docstring).

    Args:
        db: Database handle.
        tenant_id: The tenant.
        request: The question.

    Returns:
        ``{entity, version, pointers, operations, depth, provenance, direct, transitive,
        invalidated_evidence, evidence_checked, truncated, node_count, total_found, warnings}``.

    Raises:
        DependencyValidationError: ``graph-invalid`` for a malformed request,
            ``graph-entity-not-found`` for an unknown entity or version.
    """
    from .declared_dependency_store import resolve_entity

    _validate(request)
    pointers = tuple(dict.fromkeys(p.strip() for p in request.pointers if p and p.strip()))
    request = BlastRadiusRequest(
        request.kind, request.entity, pointers, int(request.depth),
        tuple(dict.fromkeys(request.provenances)), request.version,
    )
    root_kind, root_id = db._guarded_tx(lambda cursor: resolve_entity(cursor, tenant_id, request.kind, request.entity))
    is_api = root_kind in _PROJECT_KINDS

    contracts = _current_contracts(db, tenant_id, root_id, pointers) if is_api else []
    nodes, truncated, total_found = _traverse(db, tenant_id, (root_kind, root_id), request, contracts)

    refs = [(node.kind, node.id) for node in nodes.values()] + [(root_kind, root_id)]
    labels = _labels(db, tenant_id, refs)
    owners = _owners(db, tenant_id, refs)

    def entity_out(node: _Node) -> Dict[str, Any]:
        label = labels.get(node.id, {})
        return {
            "kind": node.kind, "id": node.id, "name": label.get("name"), "slug": label.get("slug"),
            "depth": node.depth, "edge_kind": node.edge_kind, "provenance": node.provenance,
            "pointers": node.pointers, "path": node.path, "owner": owners.get(node.id),
        }

    ordered = sorted(nodes.values(), key=lambda n: (n.depth, n.kind, labels.get(n.id, {}).get("slug") or "", n.id))
    evidence = _empty_evidence()
    version_out = None
    operations: Optional[List[Tuple[Optional[str], str]]] = None
    warnings: List[str] = []
    if is_api:
        version = _resolve_version(db, tenant_id, root_id, request.version)
        document = None
        if version and any(operation_key_from_pointer(p) is None for p in pointers):
            document = _version_document(db, tenant_id, version)
        operations, warnings = affected_operations(pointers, document)
        evidence["consumer_contracts"] = [
            {"contract_id": row["id"], "consumer_id": row["consumer_id"], "revision": row["revision"],
             "version_label": row.get("version_label"), "matched_pointers": row.get("matched") or []}
            for row in contracts
        ][:_EVIDENCE_LIMIT]
        evidence["sunset_consumers"] = _sunset_consumers(db, tenant_id, root_id, pointers)
        if version:
            version_out = {
                "id": version["id"], "label": version.get("label"), "published": bool(version.get("published")),
            }
            reached = operations is None or bool(operations)
            if reached:
                evidence["verification_runs"] = _verification_runs(db, tenant_id, version["id"], operations)
                evidence["deploy_gate_evaluations"] = _gate_evaluations(
                    db, tenant_id, [run["run_id"] for run in evidence["verification_runs"]]
                )
                evidence["agent_toolset_tools"] = _toolset_tools(db, tenant_id, version["id"], operations)
                evidence["mock_fixture_packs"] = _mock_evidence(version.get("mock_settings"), operations)
                # SDKs are project-wide: they are invalidated when the change reaches anything else.
                if nodes or any(evidence[key] for key in evidence if key != "sdk_regen_targets"):
                    evidence["sdk_regen_targets"] = _sdk_targets(db, tenant_id, root_id)

    root_label = labels.get(root_id, {})
    return {
        "entity": {"kind": root_kind, "id": root_id, "name": root_label.get("name"), "slug": root_label.get("slug"),
                   "owner": owners.get(root_id)},
        "version": version_out,
        "pointers": list(pointers),
        "operations": None if operations is None else [
            f"{method} {path}" if method else path for method, path in operations
        ],
        "depth": request.depth,
        "provenance": list(request.provenances),
        "direct": [entity_out(node) for node in ordered if node.depth == 1],
        "transitive": [entity_out(node) for node in ordered if node.depth > 1],
        "invalidated_evidence": evidence,
        "evidence_checked": True,
        "truncated": truncated,
        "node_count": len(nodes),
        "total_found": total_found,
        "warnings": warnings,
    }
