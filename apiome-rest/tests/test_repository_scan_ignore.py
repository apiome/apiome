"""Include / exclude rules for the repository scanner (REPO-2.2, #2763).

Covers the acceptance criteria:

1. The default ignore list is published (and the UI copy in
   ``apiome-ui/lib/repositories/scanner/defaults.ts`` stays equal to it).
2. The manifest's ``ignore:`` array merges over the defaults.
3. The walker reports ``files_skipped_by_ignore`` per scan.
4. Precedence: an explicit ``specs:`` entry always wins over ``ignore:`` patterns.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

import app.repository_file_scan as file_scan
from app.repository_file_scan import ScanPass, scan_repository_branch_into_index, walk_github_tree_in_chunks
from app.repository_scan_budget import WALK_MODE_RECURSIVE, ScanBudget, ScanCursor
from app.repository_scan_ignore import (
    DEFAULT_SCAN_IGNORE_PATTERNS,
    MAX_MANIFEST_PATTERNS,
    SCAN_MANIFEST_PATH,
    ScanIgnoreRules,
    load_scan_ignore_rules,
    merge_ignore_patterns,
    parse_scan_manifest,
)

_UI_DEFAULTS = Path(__file__).resolve().parents[2] / "apiome-ui/lib/repositories/scanner/defaults.ts"


# --- AC1: the published default list ------------------------------------------------------


def test_defaults_cover_the_usual_noise_trees() -> None:
    for name in (".git", "node_modules", "vendor", "dist", "build", "coverage", "__pycache__"):
        assert f"**/{name}/**" in DEFAULT_SCAN_IGNORE_PATTERNS


def test_the_ui_publishes_the_same_default_list() -> None:
    source = _UI_DEFAULTS.read_text(encoding="utf-8")
    block = re.search(r"DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS\s*=\s*\[(.*?)\]", source, re.S)
    assert block, "defaults.ts must export DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS"
    assert tuple(re.findall(r"[\"']([^\"']+)[\"']", block.group(1))) == DEFAULT_SCAN_IGNORE_PATTERNS


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/left-pad/index.js",
        "web/node_modules/a/b/openapi.yaml",
        ".git/HEAD",
        "services/orders/vendor/github.com/x/spec.json",
        "dist/openapi.json",
        "pkg/build/out.yaml",
        "coverage/lcov.info",
        "src/app/__pycache__/m.cpython-312.pyc",
    ],
)
def test_defaults_ignore_files_at_any_depth(path: str) -> None:
    assert ScanIgnoreRules().ignores_file(path)


@pytest.mark.parametrize(
    "path",
    ["openapi.yaml", "builder/openapi.yaml", "src/distance.yaml", "docs/build.md", "vendored/spec.yaml"],
)
def test_defaults_leave_lookalike_names_alone(path: str) -> None:
    """Patterns match whole path segments, never a substring of one."""
    assert not ScanIgnoreRules().ignores_file(path)


# --- AC2: manifest ignore merges over the defaults ----------------------------------------


def test_manifest_ignore_is_added_to_the_defaults() -> None:
    rules = parse_scan_manifest('version: 1\nignore:\n  - "**/testdata/**"\n  - "legacy/*.yaml"\n')
    assert rules.ignore_patterns[: len(DEFAULT_SCAN_IGNORE_PATTERNS)] == DEFAULT_SCAN_IGNORE_PATTERNS
    assert rules.ignore_patterns[len(DEFAULT_SCAN_IGNORE_PATTERNS) :] == ("**/testdata/**", "legacy/*.yaml")
    assert rules.ignores_file("api/testdata/bad.yaml")
    assert rules.ignores_file("legacy/old.yaml")
    assert not rules.ignores_file("legacy/v1/old.yaml")  # ``*`` stays inside one segment
    # The defaults still apply.
    assert rules.ignores_file("node_modules/x.json")


def test_merge_drops_duplicates_of_the_defaults() -> None:
    merged = merge_ignore_patterns(["**/dist/**", "extra/**"])
    assert merged == DEFAULT_SCAN_IGNORE_PATTERNS + ("extra/**",)


def test_manifest_patterns_are_cleaned() -> None:
    rules = parse_scan_manifest('ignore:\n  - "  /tmp/**  "\n  - 42\n  - ""\n  - "tmp/**"\n')
    assert rules.ignore_patterns[len(DEFAULT_SCAN_IGNORE_PATTERNS) :] == ("tmp/**",)


def test_manifest_pattern_count_is_capped() -> None:
    text = "ignore:\n" + "".join(f'  - "p{i}/**"\n' for i in range(MAX_MANIFEST_PATTERNS + 50))
    rules = parse_scan_manifest(text)
    assert len(rules.ignore_patterns) == len(DEFAULT_SCAN_IGNORE_PATTERNS) + MAX_MANIFEST_PATTERNS


@pytest.mark.parametrize("text", ["ignore: [unclosed", "- a\n- b\n", "ignore: '**/x/**'\n", ""])
def test_an_unusable_manifest_falls_back_to_the_defaults(text: str) -> None:
    rules = parse_scan_manifest(text)
    assert rules.ignore_patterns == DEFAULT_SCAN_IGNORE_PATTERNS
    assert rules.spec_patterns == ()


# --- AC4: explicit specs always win -------------------------------------------------------


def test_an_explicit_spec_wins_over_a_default_ignore() -> None:
    rules = parse_scan_manifest("specs:\n  - path: dist/openapi.yaml\n    project: orders\n")
    assert not rules.ignores_file("dist/openapi.yaml")
    assert rules.ignores_file("dist/other.yaml")


def test_an_explicit_spec_wins_over_a_manifest_ignore() -> None:
    rules = parse_scan_manifest('ignore:\n  - "contracts/**"\nspecs:\n  - contracts/public/*.yaml\n')
    assert not rules.ignores_file("contracts/public/orders.yaml")
    assert rules.ignores_file("contracts/internal/orders.yaml")
    assert rules.is_explicit_spec("contracts/public/orders.yaml")


def test_a_spec_glob_with_double_star_wins_everywhere_it_matches() -> None:
    rules = parse_scan_manifest('specs:\n  - "**/vendor/**/openapi.yaml"\n')
    assert not rules.ignores_file("svc/vendor/acme/openapi.yaml")
    assert rules.ignores_file("svc/vendor/acme/readme.md")


# --- directory pruning (sparse walks) -----------------------------------------------------


def test_an_ignored_directory_is_pruned() -> None:
    rules = ScanIgnoreRules()
    assert rules.prunes_directory("node_modules")
    assert rules.prunes_directory("web/node_modules")
    assert rules.prunes_directory("web/node_modules/left-pad")
    assert not rules.prunes_directory("web")
    assert not rules.prunes_directory("")


def test_a_directory_a_spec_reaches_into_is_never_pruned() -> None:
    rules = parse_scan_manifest("specs:\n  - path: web/build/openapi.yaml\n")
    assert not rules.prunes_directory("web/build")
    assert rules.prunes_directory("api/build")


def test_a_wildcard_spec_keeps_matching_directories_listed() -> None:
    rules = parse_scan_manifest('specs:\n  - "**/openapi.yaml"\n')
    assert not rules.prunes_directory("node_modules")


def test_a_single_level_pattern_never_prunes() -> None:
    """``legacy/*`` covers files directly in ``legacy`` but not ``legacy/sub``, so the
    directory has to be listed."""
    rules = parse_scan_manifest('ignore:\n  - "legacy/*"\n')
    assert rules.ignores_file("legacy/a.yaml")
    assert not rules.prunes_directory("legacy")


# --- reading the manifest -----------------------------------------------------------------


def test_load_reads_the_manifest_at_the_given_ref() -> None:
    calls: List[Any] = []

    def fetch(owner, repo, path, ref, token, *, max_bytes):
        calls.append((owner, repo, path, ref, token))
        return 'ignore:\n  - "fixtures/**"\n', False

    rules = load_scan_ignore_rules(fetch, "acme", "mono", "tip-sha", "tok")
    assert calls == [("acme", "mono", SCAN_MANIFEST_PATH, "tip-sha", "tok")]
    assert rules.ignores_file("fixtures/a.yaml")


@pytest.mark.parametrize(
    "error",
    [
        ValueError("GitHub file not found (path or ref may be stale)"),
        ValueError("GitHub returned 403 (private repo needs a linked account token or rate limit)"),
        RuntimeError("connection reset"),
    ],
)
def test_a_missing_or_unreadable_manifest_means_the_defaults(error: Exception) -> None:
    def fetch(*_a, **_k):
        raise error

    assert load_scan_ignore_rules(fetch, "acme", "mono", "main", None) == ScanIgnoreRules()


def test_an_oversized_manifest_means_the_defaults() -> None:
    rules = load_scan_ignore_rules(lambda *a, **k: ('ignore: ["x/**"]', True), "acme", "mono", "main", None)
    assert rules == ScanIgnoreRules()


# --- AC3: the walker skips and counts -----------------------------------------------------


def _response(payload: Dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def _branch_payload() -> Dict[str, Any]:
    return {
        "commit": {
            "sha": "tip-sha",
            "commit": {"committer": {"date": "2026-06-20T10:00:00Z"}, "tree": {"sha": "root-tree"}},
        }
    }


class _FakeClient:
    """An ``httpx.Client`` stand-in answering requests in order."""

    def __init__(self, responses: List[Any]):
        self._responses = list(responses)
        self.urls: List[str] = []

    def get(self, url: str, headers: Optional[Dict[str, str]] = None) -> Any:
        self.urls.append(url)
        if not self._responses:
            raise AssertionError(f"unexpected request: {url}")
        return self._responses.pop(0)

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def _blob(path: str) -> Dict[str, Any]:
    return {"type": "blob", "path": path, "size": 10, "sha": f"sha-{path}"}


_MIXED_TREE = [
    _blob("openapi.yaml"),
    _blob("node_modules/a/package.json"),
    _blob("web/node_modules/b/openapi.yaml"),
    _blob("services/orders/openapi.yaml"),
    _blob("dist/openapi.json"),
    _blob("services/orders/dist/bundle.yaml"),
]


def test_recursive_walk_skips_and_counts_ignored_files() -> None:
    client = _FakeClient([_response(_branch_payload()), _response({"truncated": False, "tree": _MIXED_TREE})])
    emitted: List[str] = []

    with patch("app.repository_file_scan.httpx.Client", return_value=client):
        outcome = walk_github_tree_in_chunks(
            "acme",
            "mono",
            "main",
            None,
            on_chunk=lambda c: emitted.extend(e["path"] for e in c),
            ignore=parse_scan_manifest("specs:\n  - dist/openapi.json\n"),
        )

    assert outcome.completed
    assert emitted == ["openapi.yaml", "services/orders/openapi.yaml", "dist/openapi.json"]
    assert outcome.files_skipped_by_ignore == 3
    assert outcome.directories_skipped_by_ignore == 0


def test_without_rules_the_walker_indexes_everything() -> None:
    client = _FakeClient([_response(_branch_payload()), _response({"truncated": False, "tree": _MIXED_TREE})])
    emitted: List[str] = []
    with patch("app.repository_file_scan.httpx.Client", return_value=client):
        outcome = walk_github_tree_in_chunks(
            "acme", "mono", "main", None, on_chunk=lambda c: emitted.extend(e["path"] for e in c)
        )
    assert len(emitted) == len(_MIXED_TREE)
    assert outcome.files_skipped_by_ignore == 0


def test_a_resumed_recursive_walk_counts_skipped_blobs_in_its_offset() -> None:
    """Ignored blobs are part of the resume position; otherwise the resumed pass would
    re-emit or lose files."""
    tree = [_blob(f"f{i}.yaml") if i % 2 else _blob(f"node_modules/m{i}.js") for i in range(8)]
    # A pass already emitted f1, f3 and skipped m0, m2, m4 — five blobs consumed.
    cursor = ScanCursor(
        tree_sha="root-tree",
        mode=WALK_MODE_RECURSIVE,
        emitted=2,
        tip_commit_sha="tip-sha",
        files_skipped_by_ignore=3,
    )
    client = _FakeClient([_response({"truncated": False, "tree": tree})])
    emitted: List[str] = []

    with patch("app.repository_file_scan.httpx.Client", return_value=client):
        outcome = walk_github_tree_in_chunks(
            "acme",
            "mono",
            "main",
            None,
            on_chunk=lambda c: emitted.extend(e["path"] for e in c),
            cursor=cursor,
            ignore=ScanIgnoreRules(),
        )

    assert emitted == ["f5.yaml", "f7.yaml"]
    assert outcome.files_skipped_by_ignore == 4  # m0, m2, m4 earlier plus m6 now


def test_a_paused_recursive_walk_carries_its_counts_in_the_cursor() -> None:
    tree = [_blob("node_modules/x.js")] + [_blob(f"f{i}.yaml") for i in range(3)]
    client = _FakeClient([_response(_branch_payload()), _response({"truncated": False, "tree": tree})])
    exhausted = MagicMock(spec=ScanBudget)
    exhausted.exhausted.return_value = True

    with patch("app.repository_file_scan.httpx.Client", return_value=client):
        outcome = walk_github_tree_in_chunks(
            "acme",
            "mono",
            "main",
            None,
            on_chunk=lambda c: None,
            budget=exhausted,
            chunk_size=1,
            ignore=ScanIgnoreRules(),
        )

    assert not outcome.completed
    assert outcome.cursor is not None
    assert outcome.cursor.emitted == 1
    assert outcome.cursor.files_skipped_by_ignore == 1
    restored = ScanCursor.from_json(outcome.cursor.to_json())
    assert restored is not None and restored.files_skipped_by_ignore == 1


def test_sparse_walk_never_lists_an_ignored_directory() -> None:
    client = _FakeClient(
        [
            _response(_branch_payload()),
            _response({"truncated": True, "tree": []}),  # recursive call: too big
            _response(
                {
                    "tree": [
                        {"type": "blob", "path": "openapi.yaml", "sha": "a", "size": 1},
                        {"type": "tree", "path": "node_modules", "sha": "nm"},
                        {"type": "tree", "path": "services", "sha": "svc"},
                    ]
                }
            ),
            _response(
                {
                    "tree": [
                        {"type": "blob", "path": "orders.yaml", "sha": "b", "size": 1},
                        {"type": "blob", "path": "orders.pyc", "sha": "c", "size": 1},
                    ]
                }
            ),
        ]
    )
    emitted: List[str] = []

    with patch("app.repository_file_scan.httpx.Client", return_value=client):
        outcome = walk_github_tree_in_chunks(
            "acme",
            "mono",
            "main",
            None,
            on_chunk=lambda c: emitted.extend(e["path"] for e in c),
            ignore=parse_scan_manifest('ignore:\n  - "**/*.pyc"\n'),
        )

    assert outcome.completed
    assert emitted == ["openapi.yaml", "services/orders.yaml"]
    assert not any("/trees/nm" in url for url in client.urls)
    assert outcome.directories_skipped_by_ignore == 1
    assert outcome.files_skipped_by_ignore == 1


def test_a_cursor_stored_before_repo_2_2_resumes_with_zero_counts() -> None:
    restored = ScanCursor.from_json({"version": 1, "tree_sha": "t", "mode": "recursive", "emitted": 4})
    assert restored is not None
    assert restored.files_skipped_by_ignore == 0
    assert restored.directories_skipped_by_ignore == 0


# --- AC3: the scan reports the count -------------------------------------------------------


def _repo_row() -> Dict[str, Any]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "provider": "github",
        "visibility": "public",
        "repository_full_name": "acme/mono",
        "clone_url": "https://github.com/acme/mono.git",
    }


def _scan_db() -> MagicMock:
    db = MagicMock()
    db.get_tenant_repository_scan_budget_seconds.return_value = None
    db.count_tenant_repository_files.return_value = (2, 2)
    db.find_tenant_repository_codeowners_path.return_value = None
    db.list_codeowner_candidate_files.return_value = []
    return db


def test_the_scan_applies_the_manifest_and_reports_files_skipped(monkeypatch) -> None:
    seen: Dict[str, Any] = {}

    def fake_walk(owner, repo, branch, token, *, on_chunk, cursor, budget, chunk_size, ignore=None):
        seen["ignore"] = ignore
        on_chunk([{"path": "openapi.yaml", "detected_kind": "openapi", "size_bytes": 5}])
        return file_scan.WalkOutcome(True, None, [], files_skipped_by_ignore=7, directories_skipped_by_ignore=2)

    monkeypatch.setattr(file_scan, "_load_resume_state", lambda *a: None)
    monkeypatch.setattr(file_scan, "walk_github_tree_in_chunks", fake_walk)
    refs: List[str] = []

    def manifest(owner, repo, path, ref, token, *, max_bytes):
        refs.append(ref)
        return 'ignore:\n  - "examples/**"\n', False

    result = scan_repository_branch_into_index(_scan_db(), _repo_row(), "main", manifest_fetch=manifest)

    assert isinstance(result, ScanPass)
    assert result.completed
    assert result.files_skipped_by_ignore == 7
    assert result.directories_skipped_by_ignore == 2
    assert refs == ["main"]
    assert seen["ignore"].ignores_file("examples/a.yaml")
    assert seen["ignore"].ignores_file("node_modules/a.json")


def test_a_resumed_scan_reads_the_manifest_at_the_pinned_commit(monkeypatch) -> None:
    resume = file_scan.ResumeState(
        cursor=ScanCursor(tree_sha="root-tree", tip_commit_sha="pinned-sha", files_skipped_by_ignore=3),
        entries_indexed=10,
        importable_indexed=4,
    )
    monkeypatch.setattr(file_scan, "_load_resume_state", lambda *a: resume)
    monkeypatch.setattr(
        file_scan,
        "walk_github_tree_in_chunks",
        lambda *a, **k: file_scan.WalkOutcome(True, None, [], files_skipped_by_ignore=5),
    )
    refs: List[str] = []

    def manifest(owner, repo, path, ref, token, *, max_bytes):
        refs.append(ref)
        raise ValueError("GitHub file not found (path or ref may be stale)")

    result = scan_repository_branch_into_index(_scan_db(), _repo_row(), "main", manifest_fetch=manifest)

    assert refs == ["pinned-sha"]
    assert result.resumed
    assert result.files_skipped_by_ignore == 5
