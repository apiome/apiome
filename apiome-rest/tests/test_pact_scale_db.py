"""The PFX-6.6 (#6958) scale rewrites, proved equal to the statements they replace — live Postgres.

PFX-6.6 rewrote four reads so their cost follows the number of pacticipants rather than the length
of their history (``scripts/bench_pact_matrix.py`` measures them at 100,000 versions):

* the matrix's **integrations** (:data:`app.pact_matrix_store._INTEGRATIONS`, a loose index scan);
* the matrix's **rows** (:func:`app.pact_matrix_store._recent_publications`, ordered branches);
* each consumer's **newest pact** for a provider (:func:`app.pact_publication_store.list_latest_pact_candidates`);
* each pact's **newest result** (:func:`app.verification_result_store.latest_results_by_pact`).

Each is checked here against the SQL it replaced — kept below as the oracle — on a workspace built
to hit the edge cases: a consumer whose newest version is deleted, a pair whose only version is
deleted (it is no integration), a pacticipant with no partners, a pact a provider version that
was deleted verified, a second workspace sharing nothing, and small limits so ordering decides
which rows come back.

Runs inside one always-rolled-back transaction. Skipped when no database is reachable or V452 is
not applied.
"""

from __future__ import annotations

import itertools
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Sequence, Tuple

import pytest

from app import pact_matrix_store as store
from app.pact_cleanup_store import PACTICIPANT_LABELS_ORDER, list_pacticipant_labels
from app.pact_publication_store import list_latest_pact_candidates, list_pact_candidates
from app.pact_selectors import latest_per_consumer
from app.pacticipant_store import get_pacticipant
from app.verification_result_store import latest_results_by_pact
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------------------------
# The oracle: the statements as they were before PFX-6.6
# ---------------------------------------------------------------------------------------------

_OLD_INTEGRATIONS = """
    SELECT i.required, c.id::text AS consumer_id, p.id::text AS provider_id
    FROM ({pairs}) i
    JOIN apiome.pacticipant c ON c.id = i.consumer_id AND c.tenant_id = %s::uuid AND c.deleted_at IS NULL
    JOIN apiome.pacticipant p ON p.id = i.provider_id AND p.tenant_id = %s::uuid AND p.deleted_at IS NULL
"""
_OLD_AS_CONSUMER = """
    SELECT DISTINCT p.consumer_id, p.provider_id, TRUE AS required
    FROM apiome.pact_publication p
    WHERE (p.consumer_id = ANY(%s::uuid[]) OR p.consumer_version_id = ANY(%s::uuid[]))
      AND EXISTS (SELECT 1 FROM apiome.pacticipant_version lv
                  WHERE lv.id = p.consumer_version_id AND lv.deleted_at IS NULL)
"""
_OLD_AS_PROVIDER = """
    SELECT DISTINCT pv.consumer_id, pv.provider_id, FALSE AS required
    FROM apiome.pact_version pv
    WHERE pv.provider_id = ANY(%s::uuid[]) AND pv.tenant_id = %s::uuid
      AND EXISTS (SELECT 1 FROM apiome.pact_publication lp
                  JOIN apiome.pacticipant_version lv ON lv.id = lp.consumer_version_id AND lv.deleted_at IS NULL
                  WHERE lp.pact_version_id = pv.id)
"""

_OLD_ROWS_BETWEEN = f"""
    WITH pubs AS (
        SELECT {store._PUBLICATION_COLUMNS}
        FROM apiome.pact_publication p
        WHERE (p.consumer_id = ANY($2::uuid[]) OR p.consumer_version_id = ANY($3::uuid[]))
          AND p.provider_id = ANY($4::uuid[])
          AND (p.consumer_id = ANY($5::uuid[]) OR p.provider_id = ANY($5::uuid[]))
          AND {store._LIVE_PUBLICATION}
        ORDER BY p.created_at DESC, p.id
        LIMIT $6::bigint
    )
    SELECT {store._ROW_COLUMNS}
    {store._row_from("pubs", "LEFT JOIN", store._ASKED_ABOUT, "$7")}
    ORDER BY last_action_at DESC, p.created_at DESC, r.seq DESC NULLS LAST
    LIMIT $6::bigint
"""
_OLD_ROWS_SINGLE = f"""
    WITH as_consumer AS (
        SELECT {store._PUBLICATION_COLUMNS}
        FROM apiome.pact_publication p
        WHERE (p.consumer_id = ANY($2::uuid[]) OR p.consumer_version_id = ANY($3::uuid[]))
          AND {store._LIVE_PUBLICATION}
        ORDER BY p.created_at DESC, p.id
        LIMIT $5::bigint
    ), as_provider AS (
        SELECT {store._PUBLICATION_COLUMNS}
        FROM apiome.pact_publication p
        WHERE p.provider_id = ANY($4::uuid[])
          AND {store._LIVE_PUBLICATION}
          AND EXISTS (SELECT 1 FROM apiome.verification_result r
                      WHERE r.pact_version_id = p.pact_version_id
                        AND (r.provider_id = ANY($2::uuid[]) OR r.provider_version_id = ANY($3::uuid[]))
                        AND {store._LIVE_RESULT})
        ORDER BY p.created_at DESC, p.id
        LIMIT $5::bigint
    )
    SELECT {store._ROW_NAMES}
    FROM (
        SELECT {store._ROW_COLUMNS}
        {store._row_from("as_consumer", "LEFT JOIN", "TRUE", "$6")}
        UNION ALL
        SELECT {store._ROW_COLUMNS}
        {store._row_from("as_provider", "JOIN", store._ASKED_ABOUT, "$6")}
    ) rows
    ORDER BY last_action_at DESC, pact_created_at DESC, verification_seq DESC NULLS LAST
    LIMIT $5::bigint
"""

_OLD_LATEST_RESULTS = """
    SELECT DISTINCT ON (r2.pact_version_id) r2.id::text AS id
    FROM apiome.verification_result r2
    JOIN apiome.pact_version pv2 ON pv2.id = r2.pact_version_id
    JOIN apiome.pacticipant_version v2 ON v2.id = r2.provider_version_id AND v2.deleted_at IS NULL
    WHERE r2.tenant_id = %s::uuid AND r2.provider_id = %s::uuid
      AND (pv2.consumer_id::text || ':' || pv2.sha) = ANY(%s)
    ORDER BY r2.pact_version_id, r2.seq DESC
"""


def _run(db: Any, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Run a ``$n`` statement directly (no PREPARE), as the oracle."""
    text = re.sub(r"\$(\d+)", lambda match: f"%(p{match.group(1)})s", sql)
    return [dict(row) for row in db.execute_query(text, {f"p{i + 1}": v for i, v in enumerate(params)}) or []]


# ---------------------------------------------------------------------------------------------
# The workspace
# ---------------------------------------------------------------------------------------------


class _Seed:
    """Inserts pacticipants, versions, pacts and results with distinct timestamps."""

    def __init__(self, cursor: Any, tenant: str) -> None:
        self.cursor = cursor
        self.tenant = tenant
        self.clock = itertools.count(1)
        self.ids: Dict[str, str] = {}
        self.versions: Dict[Tuple[str, str], str] = {}

    def _at(self) -> datetime:
        return _START + timedelta(minutes=next(self.clock))

    def app(self, slug: str) -> str:
        self.cursor.execute(
            "INSERT INTO apiome.pacticipant (tenant_id, slug, name, main_branch) "
            "VALUES (%s::uuid, %s, %s, 'main') RETURNING id::text AS id",
            (self.tenant, slug, slug.replace("-", " ").title()),
        )
        self.ids[slug] = self.cursor.fetchone()["id"]
        return self.ids[slug]

    def version(self, slug: str, number: str) -> str:
        self.cursor.execute(
            "INSERT INTO apiome.pacticipant_version (pacticipant_id, number, created_at) "
            "VALUES (%s::uuid, %s, %s) RETURNING id::text AS id",
            (self.ids[slug], number, self._at()),
        )
        self.versions[(slug, number)] = self.cursor.fetchone()["id"]
        return self.versions[(slug, number)]

    def pact(self, consumer: str, number: str, provider: str) -> str:
        """``consumer`` at ``number`` publishes a pact for ``provider``; returns its pact version id."""
        at = self._at()
        self.cursor.execute(
            """
            INSERT INTO apiome.pact_version (tenant_id, consumer_id, provider_id, sha, content, interaction_count)
            VALUES (%s::uuid, %s::uuid, %s::uuid, encode(sha256(%s::bytea), 'hex'), '{}'::jsonb, 1)
            RETURNING id::text AS id
            """,
            (self.tenant, self.ids[consumer], self.ids[provider], f"{consumer}:{number}:{provider}".encode()),
        )
        pact = self.cursor.fetchone()["id"]
        self.cursor.execute(
            "INSERT INTO apiome.pact_publication (consumer_id, provider_id, consumer_version_id, pact_version_id, "
            "created_at) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
            (self.ids[consumer], self.ids[provider], self.versions[(consumer, number)], pact, at),
        )
        return pact

    def result(self, pact: str, consumer: str, provider: str, number: str, verification: int, ok: bool) -> None:
        self.cursor.execute(
            """
            INSERT INTO apiome.verification_result
                (tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number, success, created_at)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s)
            """,
            (
                self.tenant,
                self.ids[consumer],
                self.ids[provider],
                pact,
                self.versions[(provider, number)],
                verification,
                ok,
                self._at(),
            ),
        )

    def delete_version(self, slug: str, number: str) -> None:
        self.cursor.execute(
            "UPDATE apiome.pacticipant_version SET deleted_at = %s, delete_cause = 'version' WHERE id = %s::uuid",
            (self._at(), self.versions[(slug, number)]),
        )


@pytest.fixture
def workspace(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Three consumers, two providers and a loner in one workspace; one pair in another.

    * ``billing`` publishes for ``ledger`` and ``audit`` at 1, 2 and 3 — and 3 is deleted;
    * ``mobile`` publishes for ``ledger`` at 1 to 4;
    * ``legacy`` publishes for ``audit`` at 1 only, and 1 is deleted: no integration is left;
    * ``ledger`` 1 and 2 verify; ``ledger`` 1 is deleted, so its results do not count;
    * ``loner`` has no pact at all;
    * the other workspace's ``billing`` publishes for its ``ledger``.
    """
    cursor = stack["cursor"]
    cursor.execute("SELECT to_regclass('apiome.idx_pact_publication_consumer_recent') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V452 not applied")
    seed = _Seed(cursor, stack["seed"]["tenant"])
    for slug in ("billing", "mobile", "legacy", "ledger", "audit", "loner"):
        seed.app(slug)
    for number in ("1", "2"):
        seed.version("ledger", number)
    seed.version("audit", "1")
    pacts: Dict[Tuple[str, str, str], str] = {}
    for number in ("1", "2", "3"):
        seed.version("billing", number)
        for provider in ("ledger", "audit"):
            pacts[("billing", number, provider)] = seed.pact("billing", number, provider)
    for number in ("1", "2", "3", "4"):
        seed.version("mobile", number)
        pacts[("mobile", number, "ledger")] = seed.pact("mobile", number, "ledger")
    seed.version("legacy", "1")
    pacts[("legacy", "1", "audit")] = seed.pact("legacy", "1", "audit")
    for (consumer, number, provider), pact in pacts.items():
        if provider == "ledger":
            seed.result(pact, consumer, provider, "1", 1, True)
            seed.result(pact, consumer, provider, "2", 2, number != "2")
        else:
            seed.result(pact, consumer, provider, "1", 1, number == "1")
    seed.delete_version("billing", "3")
    seed.delete_version("legacy", "1")
    seed.delete_version("ledger", "1")

    other = _Seed(cursor, stack["other"]["tenant"])
    for slug in ("billing", "ledger"):
        other.app(slug)
    other.version("ledger", "1")
    other.version("billing", "1")
    other.result(other.pact("billing", "1", "ledger"), "billing", "ledger", "1", 1, True)
    for table in ("pacticipant", "pacticipant_version", "pact_version", "pact_publication", "verification_result"):
        cursor.execute(f"ANALYZE apiome.{table}")
    yield {**stack, "ids": seed.ids, "versions": seed.versions, "pacts": pacts, "other_ids": other.ids}


# ---------------------------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------------------------


def _old_integrations(db: Any, tenant: str, name_only: str, versions: str, all_ids: str, involving: bool) -> set:
    if involving:
        pairs = f"{_OLD_AS_CONSUMER} UNION ALL {_OLD_AS_PROVIDER}"
        params: Tuple[Any, ...] = (name_only, versions, all_ids, tenant)
    else:
        pairs = f"{_OLD_AS_CONSUMER} AND p.provider_id = ANY(%s::uuid[])"
        params = (name_only, versions, all_ids)
    rows = db.execute_query(_OLD_INTEGRATIONS.format(pairs=pairs), params + (tenant, tenant)) or []
    return {(row["consumer_id"], row["provider_id"], bool(row["required"])) for row in rows}


def _new_integrations(db: Any, tenant: str, name_only: str, versions: str, all_ids: str, involving: bool) -> set:
    rows = _run(db, store._INTEGRATIONS, (tenant, name_only, versions, all_ids, involving))
    return {(row["consumer_id"], row["provider_id"], bool(row["required"])) for row in rows}


def _ids(workspace: Dict[str, Any], *slugs: str) -> str:
    return store._array([workspace["ids"][slug] for slug in slugs])


def _version_ids(workspace: Dict[str, Any], *keys: Tuple[str, str]) -> str:
    return store._array([workspace["versions"][key] for key in keys])


@pytest.mark.parametrize(
    ("named", "versions", "involving"),
    [
        (("ledger",), (), True),
        (("billing",), (), True),
        (("audit",), (), True),
        (("legacy",), (), True),
        (("loner",), (), True),
        (("billing", "ledger"), (), False),
        (("mobile", "audit"), (), False),
        ((), (("billing", "2"),), True),
        ((), (("billing", "3"),), True),
        (("ledger",), (("mobile", "4"),), True),
        ((), (("mobile", "1"), ("billing", "1")), False),
    ],
)
def test_the_integrations_are_the_ones_the_old_statement_found(
    workspace: Dict[str, Any], named: Tuple[str, ...], versions: Tuple[Tuple[str, str], ...], involving: bool
) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    name_only = _ids(workspace, *named)
    version_ids = _version_ids(workspace, *versions)
    all_ids = store._array(
        [workspace["ids"][slug] for slug in named] + [workspace["ids"][slug] for slug, _ in versions]
    )
    expected = _old_integrations(db, tenant, name_only, version_ids, all_ids, involving)
    assert _new_integrations(db, tenant, name_only, version_ids, all_ids, involving) == expected


def test_a_pair_left_only_with_deleted_versions_is_no_integration(workspace: Dict[str, Any]) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    found = _new_integrations(db, tenant, _ids(workspace, "audit"), "{}", _ids(workspace, "audit"), True)
    consumers = {consumer for consumer, _provider, _required in found}
    assert workspace["ids"]["billing"] in consumers and workspace["ids"]["legacy"] not in consumers


def test_the_integrations_never_reach_another_workspace(workspace: Dict[str, Any]) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    theirs = workspace["other_ids"]
    # Their pacticipants named in our workspace's query find nothing of theirs.
    assert (
        _new_integrations(db, tenant, store._array(theirs.values()), "{}", store._array(theirs.values()), True) == set()
    )
    # And ours never pick up theirs, though the index walk passes their rows.
    ours = _new_integrations(db, tenant, _ids(workspace, "ledger"), "{}", _ids(workspace, "ledger"), True)
    assert not {pid for pair in ours for pid in pair[:2]} & set(theirs.values())


def test_the_integrations_run_as_a_named_statement(workspace: Dict[str, Any]) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    ledger = get_pacticipant(db, tenant, "ledger")
    selector = store.ResolvedSelector(pacticipant_id=ledger.id, pacticipant_name=ledger.name, kind=store.SPECIFIED)
    integrations, pacticipants = store._find_integrations(db, tenant, [selector], True)
    assert {(i.consumer_name, i.provider_name, i.required) for i in integrations} == {
        ("Billing", "Ledger", False),
        ("Mobile", "Ledger", False),
    }
    assert set(pacticipants) == {workspace["ids"][slug] for slug in ("billing", "mobile", "ledger")}
    rows = db.execute_query("SELECT name FROM pg_prepared_statements WHERE name = 'pfx_matrix_integrations'")
    assert rows, "the integrations statement is prepared on the connection"


# ---------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------


def _row_keys(rows: Sequence[Dict[str, Any]]) -> List[Tuple[Any, ...]]:
    return [
        (r["consumer_version_id"], r["provider_id"], r["provider_version_id"], r["verification_number"]) for r in rows
    ]


@pytest.mark.parametrize("limit", [1, 2, 3, 5, 100])
@pytest.mark.parametrize("latest", [False, True])
@pytest.mark.parametrize(
    ("named", "versions"),
    [(("ledger",), ()), (("billing",), ()), (("mobile",), ()), ((), (("mobile", "3"),)), ((), (("billing", "3"),))],
)
def test_the_rows_of_one_selector_are_the_old_statements(
    workspace: Dict[str, Any], named: Tuple[str, ...], versions: Tuple[Tuple[str, str], ...], limit: int, latest: bool
) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    params = (
        tenant,
        _ids(workspace, *named),
        _version_ids(workspace, *versions),
        store._array([workspace["ids"][s] for s in named] + [workspace["ids"][s] for s, _ in versions]),
        limit,
        latest,
    )
    assert _row_keys(_run(db, store._ROWS_SINGLE, params)) == _row_keys(_run(db, _OLD_ROWS_SINGLE, params))


@pytest.mark.parametrize("limit", [1, 2, 4, 100])
@pytest.mark.parametrize(
    ("named", "versions", "specified"),
    [
        (("billing", "ledger"), (), ("billing", "ledger")),
        (("mobile", "ledger"), (), ("mobile",)),
        (("billing",), (("ledger", "2"),), ("billing", "ledger")),
        ((), (("mobile", "4"), ("ledger", "2")), ("mobile", "ledger")),
        (("billing", "mobile", "ledger", "audit"), (), ("ledger",)),
    ],
)
def test_the_rows_between_selectors_are_the_old_statements(
    workspace: Dict[str, Any],
    named: Tuple[str, ...],
    versions: Tuple[Tuple[str, str], ...],
    specified: Tuple[str, ...],
    limit: int,
) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    params = (
        tenant,
        _ids(workspace, *named),
        _version_ids(workspace, *versions),
        store._array([workspace["ids"][s] for s in named] + [workspace["ids"][s] for s, _ in versions]),
        _ids(workspace, *specified),
        limit,
        True,
    )
    assert _row_keys(_run(db, store._ROWS_BETWEEN, params)) == _row_keys(_run(db, _OLD_ROWS_BETWEEN, params))


# ---------------------------------------------------------------------------------------------
# Newest pacts and results
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["ledger", "audit", "loner"])
def test_each_consumers_newest_pact_is_the_one_every_publication_gives(
    workspace: Dict[str, Any], provider: str
) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    record, every = list_pact_candidates(db, tenant, provider)
    _, newest = list_latest_pact_candidates(db, tenant, provider)
    expected = sorted(latest_per_consumer(every, lambda _c: True), key=lambda c: c.version_seq)
    assert newest == expected
    if provider == "ledger":
        # billing 3 is deleted: its newest live pact for the ledger is 2.
        assert {c.consumer_slug: c.version_number for c in newest} == {"billing": "2", "mobile": "4"}


def test_each_pacts_newest_result_is_the_one_the_old_statement_found(workspace: Dict[str, Any]) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    ledger = get_pacticipant(db, tenant, "ledger")
    _, every = list_pact_candidates(db, tenant, "ledger")
    pairs = [(c.consumer_id, c.sha) for c in every]
    found = latest_results_by_pact(db, tenant, ledger, pairs)
    keys = sorted({f"{consumer_id}:{sha}" for consumer_id, sha in pairs})
    old = {row["id"] for row in db.execute_query(_OLD_LATEST_RESULTS, (tenant, ledger.id, keys)) or []}
    assert {record.id for record in found.values()} == old
    # ledger 1 is deleted, so each pact's newest result is ledger 2's.
    assert {record.provider_version for record in found.values()} == {"2"}


def test_results_of_another_workspace_are_never_found(workspace: Dict[str, Any]) -> None:
    db, tenant = workspace["db"], workspace["seed"]["tenant"]
    other_tenant = workspace["other"]["tenant"]
    ledger = get_pacticipant(db, tenant, "ledger")
    _, theirs = list_pact_candidates(db, other_tenant, "ledger")
    assert latest_results_by_pact(db, tenant, ledger, [(c.consumer_id, c.sha) for c in theirs]) == {}


# ---------------------------------------------------------------------------------------------
# A pacticipant's labels, a page at a time
# ---------------------------------------------------------------------------------------------


def test_a_pacticipants_labels_page_by_name_and_stay_its_own(workspace: Dict[str, Any]) -> None:
    db, cursor, tenant = workspace["db"], workspace["cursor"], workspace["seed"]["tenant"]
    names = [f"team-{index:02d}" for index in range(7)]
    for name in names:
        cursor.execute(
            "INSERT INTO apiome.pacticipant_label (tenant_id, pacticipant_id, name) VALUES (%s::uuid, %s::uuid, %s)",
            (tenant, workspace["ids"]["billing"], name),
        )
    # Another pacticipant's label sorts between them and must never appear.
    cursor.execute(
        "INSERT INTO apiome.pacticipant_label (tenant_id, pacticipant_id, name) VALUES (%s::uuid, %s::uuid, %s)",
        (tenant, workspace["ids"]["mobile"], "team-03a"),
    )
    billing = get_pacticipant(db, tenant, "billing")
    seen: List[str] = []
    after = None
    while True:
        rows = list_pacticipant_labels(db, billing, limit=3 + 1, cursor=after)
        page = PACTICIPANT_LABELS_ORDER.page(rows, 3)
        seen += [label.name for label in page.items]
        if not page.has_more:
            break
        after = PACTICIPANT_LABELS_ORDER.parse(page.next_cursor)
    assert seen == names
    # Without a limit (the HAL documents and the purge) every label is read.
    assert [label.name for label in list_pacticipant_labels(db, billing)] == names
