"""Similar servers ranked in the database, finished in Python (DBP-1.17, #7200).

The database now does the set arithmetic and returns the nearest few peers; these tests pin that
the Python that finishes the job agrees with the functions that used to do all of it.
"""

from __future__ import annotations

import random

from app.mcp_insight_aggregation import (
    capability_name_set,
    compute_capability_overlap,
    embedding_neighbors_from_rows,
    overlap_neighbors_from_rows,
    rank_embedding_neighbors,
)


def _rows_as_sql_would(target_names, peers):
    """What ``Database.get_mcp_similar_servers`` returns for these peers: counts, not name lists."""
    target = capability_name_set(target_names)
    rows = []
    for peer in peers:
        names = capability_name_set(peer["capability_names"])
        shared = sorted(target & names)
        if shared:
            rows.append(
                {
                    "endpoint_id": peer["endpoint_id"],
                    "name": peer["name"],
                    "slug": peer.get("slug"),
                    "category": peer.get("category"),
                    "shared_count": len(shared),
                    "candidate_capability_count": len(names),
                    "shared_capabilities": shared,
                }
            )
    return len(target), rows


def _peer(n, names):
    return {
        "endpoint_id": f"ep-{n}",
        "name": f"Server {n}",
        "slug": f"server-{n}",
        "category": "x",
        "capability_names": names,
    }


def test_overlap_from_rows_matches_the_in_python_ranking_on_many_random_catalogs():
    rng = random.Random(7200)
    vocabulary = [f"tool_{i}" for i in range(40)]
    for _ in range(200):
        target = rng.sample(vocabulary, rng.randint(0, 12))
        peers = [_peer(n, rng.sample(vocabulary, rng.randint(0, 15))) for n in range(rng.randint(0, 25))]
        limit = rng.randint(0, 12)
        expected = compute_capability_overlap(target, peers, limit=limit)
        count, rows = _rows_as_sql_would(target, peers)
        rng.shuffle(rows)  # the final order must not depend on the order the database returned
        assert overlap_neighbors_from_rows(count, rows, limit=limit) == expected


def test_overlap_from_rows_folds_names_as_the_set_does():
    target = ["  Get_Weather ", "get_weather", "List", ""]
    peers = [_peer(1, ["GET_WEATHER", "list ", "other"])]
    count, rows = _rows_as_sql_would(target, peers)
    assert count == 2
    assert overlap_neighbors_from_rows(count, rows) == compute_capability_overlap(target, peers)


def test_overlap_from_rows_is_empty_for_a_target_with_no_capabilities():
    row = {
        "endpoint_id": "p",
        "name": "P",
        "shared_count": 0,
        "candidate_capability_count": 3,
        "shared_capabilities": [],
    }
    assert overlap_neighbors_from_rows(0, [row]) == []
    # A peer that shares nothing is not similar, whatever the database sent.
    assert overlap_neighbors_from_rows(4, [row]) == []


def test_overlap_from_rows_orders_by_rounded_similarity_then_shared_names_then_name():
    def row(name, shared, candidate):
        return {
            "endpoint_id": name,
            "name": name,
            "shared_count": shared,
            "candidate_capability_count": candidate,
            "shared_capabilities": [f"n{i}" for i in range(shared)],
        }

    # target 4 names. a: 2/(4+2-2)=0.5; b: 3/(4+5-3)=0.5 with more shared; c and d tie on everything but name.
    ranked = overlap_neighbors_from_rows(4, [row("d", 1, 1), row("a", 2, 2), row("c", 1, 1), row("b", 3, 5)])
    assert [n.endpoint_id for n in ranked] == ["b", "a", "c", "d"]
    assert [n.similarity for n in ranked] == [0.5, 0.5, 0.25, 0.25]
    assert overlap_neighbors_from_rows(4, [row("a", 2, 2), row("b", 3, 5)], limit=1)[0].endpoint_id == "b"


def test_embedding_rows_are_floored_rounded_and_ordered_as_the_python_ranking_does():
    target = [1.0, 0.0, 0.0]
    peers = [
        {"endpoint_id": "near", "name": "Near", "embedding": [0.99, 0.14, 0.0]},
        {"endpoint_id": "mid", "name": "Mid", "embedding": [0.6, 0.8, 0.0]},
        {"endpoint_id": "opposite", "name": "Opposite", "embedding": [-1.0, 0.0, 0.0]},
        {"endpoint_id": "zero", "name": "Zero", "embedding": [0.0, 0.0, 0.0]},
    ]
    expected = rank_embedding_neighbors(target, peers, limit=10)
    # The database returns the cosine similarity (NaN / NULL for a zero vector), nearest first.
    rows = [
        {"endpoint_id": "near", "name": "Near", "similarity": 0.99 / (0.99**2 + 0.14**2) ** 0.5},
        {"endpoint_id": "mid", "name": "Mid", "similarity": 0.6},
        {"endpoint_id": "opposite", "name": "Opposite", "similarity": -1.0},
        {"endpoint_id": "zero", "name": "Zero", "similarity": float("nan")},
        {"endpoint_id": "null", "name": "Null", "similarity": None},
    ]
    assert embedding_neighbors_from_rows(rows, limit=10) == expected
    assert [n.endpoint_id for n in expected] == ["near", "mid"]


def test_embedding_rows_respect_the_limit_and_a_higher_floor():
    rows = [{"endpoint_id": str(i), "name": f"S{i}", "similarity": 1 - i / 10} for i in range(8)]
    assert [n.endpoint_id for n in embedding_neighbors_from_rows(rows, limit=3)] == ["0", "1", "2"]
    assert [n.endpoint_id for n in embedding_neighbors_from_rows(rows, min_similarity=0.75)] == ["0", "1", "2"]
    assert embedding_neighbors_from_rows([], limit=5) == []


def test_embedding_ties_break_by_name():
    rows = [
        {"endpoint_id": "b", "name": "beta", "similarity": 0.50001},
        {"endpoint_id": "a", "name": "Alpha", "similarity": 0.50004},
    ]
    # Both round to 0.5, so the name decides, case-insensitively.
    assert [n.endpoint_id for n in embedding_neighbors_from_rows(rows)] == ["a", "b"]
