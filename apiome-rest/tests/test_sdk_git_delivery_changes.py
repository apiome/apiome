"""What a git delivery writes — SDK-4.2 (#4496).

Pure tests for :mod:`app.sdk_git_delivery_changes`: that a file's git blob id is computed exactly
as git computes it, that the SDK-4.1 layout lands under the target directory with a deterministic
manifest beside it, and — the rule that protects a tenant's repository — that a delivery only ever
removes files a *previous delivery* generated.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest
from test_sdk_distribution import _build

from app.sdk_git_delivery_changes import (
    CHANGE_ADDED,
    CHANGE_DELETED,
    CHANGE_MODIFIED,
    DELIVERY_MANIFEST_SCHEMA_VERSION,
    MANIFEST_RELATIVE_PATH,
    ChangeSet,
    DeliveryFile,
    ExistingEntry,
    build_manifest,
    delivery_files,
    git_blob_sha,
    join_repo_path,
    manifest_paths,
    plan_changes,
)


# --------------------------------------------------------------------------------------------
# Blob ids
# --------------------------------------------------------------------------------------------
def test_the_blob_id_of_an_empty_file_is_gits():
    assert git_blob_sha("") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_the_blob_id_counts_utf8_bytes_not_characters():
    text = "héllo — wörld\n"
    data = text.encode("utf-8")
    expected = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    assert git_blob_sha(text) == expected


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_blob_id_matches_git_hash_object(tmp_path):
    text = '{"openapi": "3.1.0"}\nsnippet ✓\n'
    path = tmp_path / "file.json"
    path.write_bytes(text.encode("utf-8"))
    expected = subprocess.run(
        ["git", "hash-object", str(path)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert git_blob_sha(text) == expected


# --------------------------------------------------------------------------------------------
# Placement and the manifest
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "target, relative, expected",
    [
        ("", "package.json", "package.json"),
        ("sdks/ts", "package.json", "sdks/ts/package.json"),
        ("sdks/ts", "/snippets/a.ts", "sdks/ts/snippets/a.ts"),
    ],
)
def test_join_repo_path(target, relative, expected):
    assert join_repo_path(target, relative) == expected


def test_delivery_files_place_the_layout_and_its_manifest_under_the_target():
    distribution = _build("npm")

    files = delivery_files(distribution, "sdks/ts")

    paths = [item.path for item in files]
    assert paths == sorted(paths)
    assert all(path.startswith("sdks/ts/") for path in paths)
    assert f"sdks/ts/{MANIFEST_RELATIVE_PATH}" in paths
    assert len(files) == len(distribution.files) + 1
    # The archive's `package/` root is a tarball convention, not part of the committed layout.
    assert "sdks/ts/package.json" in paths and not any("/package/" in path for path in paths)


def test_the_manifest_names_every_generated_file_and_nothing_that_changes_per_run():
    distribution = _build("npm")

    first = build_manifest(distribution)
    second = build_manifest(_build("npm"))

    assert first == second, "identical inputs must yield an identical manifest"
    document = json.loads(first)
    assert document["schemaVersion"] == DELIVERY_MANIFEST_SCHEMA_VERSION
    assert document["packageVersion"] == "1.4.3"
    assert document["provenance"] == distribution.provenance
    assert [entry["path"] for entry in document["files"]] == [item.path for item in distribution.files]
    assert not {"at", "generatedAt", "timestamp", "runId"} & set(document)


def test_manifest_paths_reads_back_what_build_manifest_wrote():
    distribution = _build("pypi")
    paths = manifest_paths(build_manifest(distribution), "python")
    assert paths == {f"python/{item.path}" for item in distribution.files}


@pytest.mark.parametrize(
    "text",
    [None, "", "not json", "[]", '{"files": "nope"}', '{"files": [1, null, {"path": 3}]}'],
)
def test_a_malformed_manifest_yields_no_paths_rather_than_an_error(text):
    assert manifest_paths(text, "sdks/ts") == set()


def test_a_manifest_cannot_name_a_file_outside_the_target_directory():
    text = json.dumps(
        {
            "files": [
                {"path": "../../README.md"},
                {"path": "/etc/passwd"},
                {"path": ".git/config"},
                {"path": "snippets\\evil.ts"},
                {"path": "./ok/../escape"},
                {"path": "snippets/kept.ts"},
            ]
        }
    )
    assert manifest_paths(text, "sdks/ts") == {"sdks/ts/snippets/kept.ts"}


def test_an_oversized_manifest_is_ignored():
    text = json.dumps({"files": [{"path": "a" * 10}] * 60_000})
    assert manifest_paths(text, "") == set()


# --------------------------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------------------------
def _file(path: str, text: str = "x\n") -> DeliveryFile:
    return DeliveryFile(path, text, "module")


def _blob(path: str, text: str = "x\n") -> ExistingEntry:
    return ExistingEntry(path=path, sha=git_blob_sha(text))


def test_a_file_the_base_lacks_is_added_and_an_identical_one_is_unchanged():
    changes = plan_changes(
        [_file("sdk/a.ts"), _file("sdk/b.ts", "same\n")],
        {"sdk/b.ts": _blob("sdk/b.ts", "same\n")},
    )
    assert [item.path for item in changes.added] == ["sdk/a.ts"]
    assert changes.unchanged == ["sdk/b.ts"]
    assert changes.modified == [] and changes.deleted == []
    assert changes.has_changes


def test_a_file_with_different_content_or_a_different_type_is_modified():
    changes = plan_changes(
        [_file("sdk/a.ts", "new\n"), _file("sdk/dir")],
        {
            "sdk/a.ts": _blob("sdk/a.ts", "old\n"),
            "sdk/dir": ExistingEntry(path="sdk/dir", sha=git_blob_sha("x\n"), type="tree"),
        },
    )
    assert [item.path for item in changes.modified] == ["sdk/a.ts", "sdk/dir"]


def test_only_files_the_previous_manifest_named_are_removed():
    existing = {
        "sdk/gone.ts": _blob("sdk/gone.ts"),
        "sdk/LICENSE": _blob("sdk/LICENSE"),
        "sdk/kept.ts": _blob("sdk/kept.ts"),
    }
    changes = plan_changes(
        [_file("sdk/kept.ts")],
        existing,
        previous_manifest={"sdk/gone.ts", "sdk/kept.ts", "sdk/already-deleted.ts"},
    )
    # LICENSE was never generated; kept.ts is still generated; already-deleted.ts is not there.
    assert changes.deleted == ["sdk/gone.ts"]


def test_a_previously_generated_path_that_is_now_a_directory_is_not_removed():
    changes = plan_changes(
        [], {"sdk/x": ExistingEntry(path="sdk/x", sha="abc", type="tree")}, previous_manifest={"sdk/x"}
    )
    assert changes.deleted == []


def test_nothing_differing_means_no_changes():
    changes = plan_changes([_file("a")], {"a": _blob("a")})
    assert not changes.has_changes


def test_the_overview_counts_exactly_and_caps_the_list():
    changes = ChangeSet(
        added=[_file(f"a{i}") for i in range(3)],
        modified=[_file("m")],
        deleted=["d"],
        unchanged=["u1", "u2"],
    )
    overview = changes.overview(max_files=2)
    assert overview[CHANGE_ADDED] == 3
    assert overview[CHANGE_MODIFIED] == 1
    assert overview[CHANGE_DELETED] == 1
    assert overview["unchanged"] == 2
    assert len(overview["files"]) == 2 and overview["truncated"] is True
    assert overview["files"][0] == {"path": "a0", "change": CHANGE_ADDED}


def test_written_lists_added_and_modified_in_path_order():
    changes = ChangeSet(added=[_file("z")], modified=[_file("a")])
    assert [item.path for item in changes.written] == ["a", "z"]
