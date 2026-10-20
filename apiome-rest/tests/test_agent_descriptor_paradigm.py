"""The agent-descriptor paradigm of the canonical model — MFI-18.4 (#3977).

``CanonicalApi.agents`` makes agents first-class: one :class:`AgentDescriptor` per agent
(identity, provider, version, capability flags, typed security schemes) with
:class:`AgentSkill` entries keyed by skill id. These tests pin the acceptance criteria:

* A2A and ACP cards round-trip **losslessly** through the model (JSON) and through persistence
  (the tree codec, and the SQL the codec feeds);
* **skill-level diffs** are stable across versions — keyed by skill id, invariant to order;
* **fidelity**: skills, capabilities and auth survive the normalizer pipeline;
* the field is **additive**: a model with no agents serializes exactly as before, so no other
  format's fingerprint moves.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.agent_descriptor_schemes import agent_security_schemes
from app.canonical_model import (
    AgentDescriptor,
    AgentSkill,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
)
from app.canonical_persistence import (
    dump_canonical_tree,
    load_canonical_api,
    load_canonical_tree,
    persist_canonical_api,
)
from app.import_source import (
    DiffChangeKind,
    canonical_diff,
    canonical_fingerprint,
    get_import_source,
    load_builtin_import_sources,
)
from app.normalizer import normalize_ordering

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples"

_A2A_FIXTURES = sorted(p.name for p in (_EXAMPLES / "a2a").glob("*.json"))
_ACP_FIXTURES = sorted(p.name for p in (_EXAMPLES / "acp").glob("*.json"))


def _import(fmt: str, name: str) -> CanonicalApi:
    adapter = get_import_source(fmt)
    text = (_EXAMPLES / fmt / name).read_text(encoding="utf-8")
    return adapter.normalize(adapter.parse(text, source_label=name))


def _card(name: str) -> Dict[str, Any]:
    return json.loads((_EXAMPLES / "a2a" / name).read_text(encoding="utf-8"))


def _a2a(card: Dict[str, Any]) -> CanonicalApi:
    adapter = get_import_source("a2a")
    return adapter.normalize(adapter.parse(json.dumps(card)))


# ---------------------------------------------------------------------------
# The descriptor A2A and ACP produce
# ---------------------------------------------------------------------------


def test_an_a2a_card_is_one_descriptor_with_identity_capabilities_and_auth() -> None:
    model = _import("a2a", "02-typical-travel-concierge.json")
    card = _card("02-typical-travel-concierge.json")
    (agent,) = model.agents
    assert agent.protocol == "a2a"
    assert agent.name == card["name"] and agent.version == card["version"]
    assert agent.url == card["url"]
    assert agent.provider is not None
    assert agent.provider.organization == card["provider"]["organization"]
    assert agent.capabilities == card["capabilities"]
    assert agent.default_input_modes == card["defaultInputModes"]
    assert {s.name for s in agent.security_schemes} == set(card.get("securitySchemes", {}))
    assert agent.service_ref == model.services[0].key


def test_each_a2a_skill_is_first_class_and_points_at_its_operation() -> None:
    model = _import("a2a", "02-typical-travel-concierge.json")
    card = _card("02-typical-travel-concierge.json")
    (agent,) = model.agents
    assert sorted(s.id for s in agent.skills) == sorted(s["id"] for s in card["skills"])
    operations = {op.key for op in model.operations()}
    for skill in agent.skills:
        assert skill.key == f"{agent.key}.{skill.id}"
        assert skill.operation_ref in operations
    source = {s["id"]: s for s in card["skills"]}
    for skill in agent.skills:
        assert skill.tags == source[skill.id].get("tags", [])
        assert skill.input_modes == source[skill.id].get("inputModes", [])


def test_an_acp_listing_is_one_descriptor_per_agent() -> None:
    model = _import("acp", "03-composition-agent-list.json")
    listing = json.loads((_EXAMPLES / "acp/03-composition-agent-list.json").read_text())
    assert sorted(a.name for a in model.agents) == sorted(a["name"] for a in listing["agents"])
    for agent in model.agents:
        assert agent.protocol == "acp"
        assert agent.service_ref == agent.key
        source = next(a for a in listing["agents"] if a["name"] == agent.name)
        assert [s.id for s in agent.skills] == sorted(
            c["name"] for c in source["metadata"].get("capabilities", [])
        )
        assert agent.default_input_modes == source.get("input_content_types", ["*/*"])


def test_repeated_skill_ids_keep_both_and_mark_the_repeat() -> None:
    model = _import("a2a", "04-stress-edge-cases.json")
    repeats = [s for s in model.agents[0].skills if s.extras.get("duplicate_of")]
    assert repeats and all(s.key.endswith("~2") for s in repeats)
    assert len({s.key for s in model.agents[0].skills}) == len(model.agents[0].skills)


# ---------------------------------------------------------------------------
# Lossless round trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "name"),
    [("a2a", n) for n in _A2A_FIXTURES] + [("acp", n) for n in _ACP_FIXTURES],
)
def test_agent_models_round_trip_through_json_and_the_persistence_codec(
    fmt: str, name: str
) -> None:
    model = _import(fmt, name)
    assert model.agents, "every A2A / ACP model carries descriptors"
    assert CanonicalApi.model_validate(json.loads(model.model_dump_json())) == model
    tree = json.loads(json.dumps(dump_canonical_tree(model)))  # JSONB-shaped
    assert load_canonical_tree(tree) == model
    assert canonical_fingerprint(load_canonical_tree(tree)) == canonical_fingerprint(model)


def test_a_model_without_agents_serializes_exactly_as_before() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="x"))
    assert "agents" not in api.model_dump()
    assert '"agents"' not in api.model_dump_json()
    assert dump_canonical_tree(api)["agents"] == []
    assert CanonicalApi.model_validate(api.model_dump()).agents == []


def test_a_tree_from_before_agents_existed_loads() -> None:
    model = _import("a2a", "01-minimal-echo-agent.json")
    tree = dump_canonical_tree(model)
    del tree["agents"]  # a pre-MFI-18.4 tree
    assert load_canonical_tree(tree).agents == []


# ---------------------------------------------------------------------------
# Skill-level diffs
# ---------------------------------------------------------------------------


def test_a_skill_delta_is_reported_on_the_skill_entity() -> None:
    before = _card("02-typical-travel-concierge.json")
    after = json.loads(json.dumps(before))
    removed = after["skills"].pop(0)
    after["skills"][0]["description"] = "Edited."
    after["skills"].append({"id": "track-bags", "name": "Track bags", "tags": ["baggage"]})
    diff = canonical_diff(_a2a(before), _a2a(after))
    skills = {(e.key.split(".", 1)[1], e.change) for e in diff.entries if e.entity == "skill"}
    assert skills == {
        (removed["id"], DiffChangeKind.REMOVED),
        (after["skills"][0]["id"], DiffChangeKind.CHANGED),
        ("track-bags", DiffChangeKind.ADDED),
    }


def test_skill_diffs_are_stable_under_reordering_and_renaming() -> None:
    card = _card("02-typical-travel-concierge.json")
    shuffled = json.loads(json.dumps(card))
    shuffled["skills"].reverse()
    assert canonical_diff(_a2a(card), _a2a(shuffled)).is_empty
    renamed = json.loads(json.dumps(card))
    renamed["skills"][0]["name"] = "A new display name"
    entries = [(e.entity, e.change) for e in canonical_diff(_a2a(card), _a2a(renamed)).entries]
    # Same id, new name: one changed skill, never a remove + add.
    assert ("skill", DiffChangeKind.CHANGED) in entries
    assert not any(c in (DiffChangeKind.ADDED, DiffChangeKind.REMOVED) for _, c in entries)


def test_a_capability_flag_or_auth_change_is_a_changed_agent() -> None:
    card = _card("01-minimal-echo-agent.json")
    streaming = json.loads(json.dumps(card))
    streaming.setdefault("capabilities", {})["pushNotifications"] = True
    entities = {e.entity for e in canonical_diff(_a2a(card), _a2a(streaming)).entries}
    assert "agent" in entities
    secured = json.loads(json.dumps(card))
    secured["securitySchemes"] = {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}}
    changes = canonical_diff(_a2a(card), _a2a(secured)).entries
    assert ("agent", DiffChangeKind.CHANGED) in {(e.entity, e.change) for e in changes}
    assert not [e for e in changes if e.entity == "skill"]


def test_ordering_normalization_sorts_agents_skills_and_schemes() -> None:
    agent = AgentDescriptor(
        key="b",
        name="b",
        protocol="a2a",
        security_schemes=agent_security_schemes({"z": {"type": "http"}, "a": {"type": "apiKey"}}),
        skills=[
            AgentSkill(key="b.y", id="y", name="y"),
            AgentSkill(key="b.x", id="x", name="x"),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.AGENT,
        format="a2a",
        identity=ApiIdentity(name="n"),
        agents=[agent, AgentDescriptor(key="a", name="a", protocol="acp")],
    )
    ordered = normalize_ordering(api)
    assert [a.key for a in ordered.agents] == ["a", "b"]
    assert [s.key for s in ordered.agents[1].skills] == ["b.x", "b.y"]
    assert [s.name for s in ordered.agents[1].security_schemes] == ["a", "z"]
    assert normalize_ordering(ordered) == ordered


# ---------------------------------------------------------------------------
# Fidelity: skills, capabilities and auth survive
# ---------------------------------------------------------------------------


def test_security_schemes_are_typed_and_lossless() -> None:
    schemes = agent_security_schemes(
        {
            "oauth": {
                "type": "oauth2",
                "flows": {"clientCredentials": {"tokenUrl": "https://x/token", "scopes": {}}},
                "description": "OAuth",
            },
            "key": {"type": "apiKey", "in": "query", "name": "k", "x-vendor": 1},
            "bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "oidc": {"type": "openIdConnect", "openIdConnectUrl": "https://x/.well-known"},
            "broken": "not an object",
        }
    )
    by_name = {s.name: s for s in schemes}
    assert [s.name for s in schemes] == ["bearer", "broken", "key", "oauth", "oidc"]
    assert by_name["key"].location == "query" and by_name["key"].parameter_name == "k"
    assert by_name["key"].extras == {"x-vendor": 1}
    assert by_name["bearer"].scheme == "bearer" and by_name["bearer"].bearer_format == "JWT"
    assert by_name["oauth"].flows == {"clientCredentials": {"tokenUrl": "https://x/token", "scopes": {}}}
    assert by_name["oidc"].openid_connect_url == "https://x/.well-known"
    assert by_name["broken"].type == "unknown"


@pytest.mark.parametrize("name", _A2A_FIXTURES)
def test_every_card_skill_capability_and_scheme_survives(name: str) -> None:
    card = _card(name)
    (agent,) = _import("a2a", name).agents
    assert agent.capabilities == card.get("capabilities", {})
    assert sorted(s.name for s in agent.security_schemes) == sorted(card.get("securitySchemes", {}))
    assert len(agent.skills) == len(card["skills"])
    for skill, source in zip(sorted(agent.skills, key=lambda s: s.key), sorted(
        card["skills"], key=lambda s: f"{agent.key}.{s['id']}"
    )):
        assert skill.id == str(source["id"])  # the parser reads a numeric id as text
        if "security" in source:
            assert skill.security is not None


# ---------------------------------------------------------------------------
# The SQL persistence path
# ---------------------------------------------------------------------------


class _RecordingDb:
    """A fake DB that stores inserted rows per table and serves them back to SELECTs.

    It understands exactly the statement shapes :mod:`app.canonical_persistence` issues —
    ``INSERT INTO apiome.<table> (cols) … RETURNING id``, ``UPDATE … SET deleted_at``, and
    ``SELECT * FROM apiome.<table> WHERE <parent>_id = %s`` — which is enough to prove the agent
    rows are written and read back through the real SQL code path.
    """

    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        self._next = 0

    def connect(self) -> "_RecordingDb":
        return self

    def cursor(self) -> "_RecordingDb":
        return self

    def __enter__(self) -> "_RecordingDb":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def execute(self, query: str, params: Any = ()) -> None:
        q = " ".join(query.split())
        self._result: List[Dict[str, Any]] = []
        insert = re.match(r"INSERT INTO apiome\.(\w+) \(([^)]*)\)", q)
        if insert:
            table, cols = insert.group(1), [c.strip() for c in insert.group(2).split(",")]
            row: Dict[str, Any] = {}
            for col, value in zip(cols, params):
                is_json = col in self._JSON_COLUMNS and isinstance(value, str)
                row[col] = json.loads(value) if is_json else value
            self._next += 1
            row["id"] = f"00000000-0000-0000-0000-{self._next:012d}"
            row["deleted_at"] = None
            self.tables.setdefault(table, []).append(row)
            self._result = [{"id": row["id"]}]
            return
        select = re.match(r"SELECT \* FROM apiome\.(\w+) WHERE (\w+) = %s::uuid", q)
        if select:
            table, column = select.group(1), select.group(2)
            rows = [
                r for r in self.tables.get(table, [])
                if str(r.get(column)) == str(params[0]) and r.get("deleted_at") is None
            ]
            self._result = sorted(rows, key=lambda r: (r.get("ordinal") or 0, r.get("key") or ""))
            return
        # UPDATE … soft-delete statements and the live-artifact SELECT id: nothing live yet.
        self._result = []

    _JSON_COLUMNS = {
        "provider", "capabilities", "default_input_modes", "default_output_modes",
        "security_schemes", "security", "extras", "tags", "examples", "input_modes",
        "output_modes", "servers", "raw", "parameters", "payload", "payload_schema", "headers",
        "content_types", "bindings", "enum_values", "union_members", "aliased", "key_type",
        "value_type", "constraints", "type_ref", "default_value",
    }

    def fetchone(self) -> Any:
        return self._result[0] if self._result else None

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self._result)


@pytest.mark.parametrize(
    ("fmt", "name"),
    [("a2a", "02-typical-travel-concierge.json"), ("acp", "03-composition-agent-list.json")],
)
def test_agents_persist_to_their_tables_and_reload_losslessly(fmt: str, name: str) -> None:
    model = _import(fmt, name)
    db = _RecordingDb()
    persist_canonical_api(
        db, tenant_id="t", creator_id="u", version_id="v", model=model
    )
    assert len(db.tables["api_agent_descriptors"]) == len(model.agents)
    assert len(db.tables["api_agent_skills"]) == sum(len(a.skills) for a in model.agents)
    skill_row = db.tables["api_agent_skills"][0]
    assert skill_row["agent_id"] == db.tables["api_agent_descriptors"][0]["id"]
    reloaded = load_canonical_api(db, tenant_id="t", version_id="v")
    assert reloaded is not None
    assert reloaded.agents == model.agents


def test_a_model_without_agents_writes_no_agent_rows() -> None:
    model = _import("agents-manifest", "02-typical-northwind-agents.json")
    assert model.agents == []
    db = _RecordingDb()
    persist_canonical_api(db, tenant_id="t", creator_id="u", version_id="v", model=model)
    assert "api_agent_descriptors" not in db.tables
    assert "api_agent_skills" not in db.tables


_V306 = (
    Path(__file__).resolve().parents[2]
    / "apiome-db/scripts/V306__canonical_agent_descriptors_3977.sql"
)


def test_the_artifact_paradigm_check_admits_every_paradigm() -> None:
    """V135 predated the agent paradigm, so no agent model could persist; V306 widens the check.
    Pinning it to the enum stops the next paradigm from drifting the same way."""
    sql = _V306.read_text(encoding="utf-8")
    match = re.search(r"api_artifacts_paradigm_check\s+CHECK \(paradigm IN \(([^)]*)\)\)", sql)
    assert match, "V306 must re-create api_artifacts_paradigm_check"
    allowed = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert allowed == {p.value for p in ApiParadigm}
