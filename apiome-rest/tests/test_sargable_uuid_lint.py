"""Fail on ``<uuid column>::text =`` / ``::text COLLATE`` predicates in SQL strings (DBP-1.10, #7193).

Casting a uuid column to text hides it from its index, so PostgreSQL scans the table. Cast the
*parameter* instead (``id = %s::uuid`` / ``id = ANY(%s::uuid[])``).

The allowlist holds the places that remain by design, with the count of occurrences per file:
"slug or id" lookups where the parameter may be a slug (it cannot be cast to uuid), and the
keyset-paged migration walks, which page on the text order of the id. A new file, or a higher
count, fails the test; lowering a count is always fine.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DB = ROOT.parent / "apiome-ui" / "lib" / "db"

#: ``id::text =``, ``tenant_id::text IN``, ``v.id::text COLLATE`` (but not ``::text[]`` or ``::text IS``).
PATTERN = re.compile(r"\b[a-z_]*\bid::text\s*(?:=|IN\b|COLLATE\b)", re.IGNORECASE)

ALLOWED = {
    "src/app/api_plan_store.py": 2,
    "src/app/blast_radius.py": 1,
    "src/app/catalog_agent_store.py": 2,
    "src/app/catalog_entity_store.py": 2,
    "src/app/catalog_migration_store.py": 1,
    "src/app/document_migration.py": 13,
    "src/app/document_store_move.py": 4,
    "src/app/gateway_config_store.py": 1,
    "src/app/owner_routing.py": 1,
    "../apiome-ui/lib/db/comment-anchor-labels.ts": 2,
}


def _counts() -> dict:
    found = {}
    files = list((ROOT / "src").rglob("*.py"))
    if UI_DB.is_dir():
        files += list(UI_DB.glob("*.ts"))
    for path in files:
        n = len(PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
        if n:
            found[os.path.relpath(path, ROOT)] = n
    return found


def test_no_new_text_cast_on_uuid_columns() -> None:
    over = {f: n for f, n in _counts().items() if n > ALLOWED.get(f, 0)}
    assert not over, (
        "uuid column cast to text in a predicate (index unusable); cast the parameter to "
        f"uuid instead, or justify an allowlist entry: {over}"
    )
