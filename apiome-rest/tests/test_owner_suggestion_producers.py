"""Owner suggestions from CODEOWNERS and from the imported document — CDG-2.2 (#5961).

* :func:`app.repository_file_scan.apply_codeowners` reads the branch's CODEOWNERS file where GitHub
  looks for it and stores each spec file's owners; apiome-db V285's trigger turns ``@org/<team>``
  owners into suggestions on the linked project (pinned in ``test_entity_owners_migration``).
* :func:`app.import_source_pipeline._record_spec_owner_suggestions` records ``x-apiome-owner`` /
  ``info.contact`` as ``spec_extension`` suggestions on the imported row, never failing the import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import patch

from app import import_source_pipeline
from app.repository_file_scan import apply_codeowners


class _ScanDb:
    """The three accessors :func:`apply_codeowners` uses."""

    def __init__(self, codeowners_path: Optional[str], files: List[Dict[str, Any]]) -> None:
        self.codeowners_path = codeowners_path
        self.files = files
        self.updates: List[Tuple[str, List[str]]] = []

    def find_tenant_repository_codeowners_path(self, repository_id: str, branch: str) -> Optional[str]:
        return self.codeowners_path

    def list_codeowner_candidate_files(self, repository_id: str, branch: str) -> List[Dict[str, Any]]:
        return self.files

    def set_tenant_repository_file_codeowners(
        self, repository_id: str, branch: str, updates: Sequence[Tuple[str, List[str]]]
    ) -> int:
        self.updates = list(updates)
        return len(self.updates)


_FILE = "* @acme/platform\n/api/payments/ @acme/payments @alice\n"


def _fetch(text: str, seen: List[str]):
    def fetch(owner, repo, path, ref, token, *, max_bytes):
        seen.append(path)
        return text, False

    return fetch


def test_each_spec_file_gets_its_owners_and_only_changes_are_written() -> None:
    db = _ScanDb(
        ".github/CODEOWNERS",
        [
            {"path": "api/payments/openapi.yaml", "codeowners": []},
            {"path": "api/orders/openapi.yaml", "codeowners": ["@acme/platform"]},
        ],
    )
    seen: List[str] = []
    changed = apply_codeowners(db, "r", "main", "acme", "api", None, fetch_text=_fetch(_FILE, seen))
    assert seen == [".github/CODEOWNERS"]
    assert changed == 1
    assert db.updates == [("api/payments/openapi.yaml", ["@acme/payments", "@alice"])]


def test_without_a_codeowners_file_owners_are_cleared() -> None:
    db = _ScanDb(None, [{"path": "api/openapi.yaml", "codeowners": ["@acme/platform"]}])
    seen: List[str] = []
    apply_codeowners(db, "r", "main", "acme", "api", None, fetch_text=_fetch(_FILE, seen))
    assert seen == []
    assert db.updates == [("api/openapi.yaml", [])]


def test_a_github_failure_never_fails_the_scan() -> None:
    db = _ScanDb("CODEOWNERS", [{"path": "a.yaml", "codeowners": []}])

    def broken(*args, **kwargs):
        raise ValueError("GitHub returned 403")

    assert apply_codeowners(db, "r", "main", "acme", "api", None, fetch_text=broken) == 0
    assert db.updates == []


def test_github_precedence_is_the_database_lookup_order() -> None:
    from app.database import Database

    assert Database.CODEOWNERS_PATHS == (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


# ---------------------------------------------------------------------------------------------
# document suggestions in the import pipeline
# ---------------------------------------------------------------------------------------------


def test_the_import_records_the_documents_owner_as_a_spec_extension_suggestion() -> None:
    calls: List[Tuple[Any, ...]] = []
    with patch(
        "app.entity_owner_store.record_suggestions",
        side_effect=lambda *a: calls.append(a) or [],
    ):
        import_source_pipeline._record_spec_owner_suggestions(
            "t-1", "p-1", False, {"x-apiome-owner": "payments", "info": {"title": "x"}}
        )
    assert calls == [
        ("t-1", "catalog_item", "p-1", "spec_extension",
         [{"team": "payments", "sourceRef": "x-apiome-owner: payments"}])
    ]


def test_a_publishable_import_suggests_on_the_project() -> None:
    calls: List[Tuple[Any, ...]] = []
    with patch(
        "app.entity_owner_store.record_suggestions",
        side_effect=lambda *a: calls.append(a) or [],
    ):
        import_source_pipeline._record_spec_owner_suggestions("t-1", "p-1", True, {})
    assert calls[0][1] == "project" and calls[0][4] == []


def test_a_suggestion_failure_never_fails_the_import() -> None:
    with patch("app.entity_owner_store.record_suggestions", side_effect=RuntimeError("down")):
        import_source_pipeline._record_spec_owner_suggestions("t-1", "p-1", True, {})
