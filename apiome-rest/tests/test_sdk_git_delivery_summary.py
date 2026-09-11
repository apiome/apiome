"""The words a git delivery writes — SDK-4.2 (#4496).

Pure tests for :mod:`app.sdk_git_delivery_summary`: the pull request body carries the spec version,
the generator version, a changed-files overview and the provenance (the acceptance criterion); it
is deterministic (which is what makes an unchanged re-run write nothing); it stays inside GitHub's
size limit; and an unusual label cannot break its Markdown.
"""

from __future__ import annotations

from dataclasses import replace

from app.sdk_git_delivery_summary import (
    PULL_REQUEST_MARKER,
    DeliverySummary,
    commit_message,
    pull_request_body,
    pull_request_title,
)

_REVISION = "33333333-3333-4333-8333-333333333333"

_SUMMARY = DeliverySummary(
    project_slug="widgets",
    api_title="Widgets API",
    version_line="1.4.2",
    version_record_id=_REVISION,
    ecosystem="npm",
    package_name="@acme/widgets-sdk",
    package_version="1.4.3",
    repository_full_name="acme/widgets-sdk",
    base_branch="main",
    branch_name="apiome/sdk-regen-1.4.2-widgets-npm",
    target_path="sdks/ts",
    apiome_version="1.184.0",
    renderer="app.snippet_render/sdk.client-kit.v1",
    changes={
        "added": 2,
        "modified": 1,
        "removed": 1,
        "unchanged": 7,
        "files": [
            {"path": "sdks/ts/index.js", "change": "modified"},
            {"path": "sdks/ts/snippets/a.ts", "change": "added"},
            {"path": "sdks/ts/snippets/b.ts", "change": "added"},
            {"path": "sdks/ts/snippets/old.ts", "change": "removed"},
        ],
        "truncated": False,
    },
    provenance={
        "schemaVersion": "sdk.distribution.v1",
        "versionRecordId": _REVISION,
        "packageVersion": "1.4.3",
        "settingsFingerprint": None,
    },
)


def test_the_title_names_the_package_and_the_api_version():
    assert pull_request_title(_SUMMARY) == "Apiome SDK: @acme/widgets-sdk 1.4.3 (widgets 1.4.2)"


def test_a_revision_without_a_version_line_is_titled_by_its_id():
    assert _REVISION in pull_request_title(replace(_SUMMARY, version_line=None))


def test_the_body_carries_every_part_the_ticket_asks_for():
    body = pull_request_body(_SUMMARY)

    assert body.startswith(PULL_REQUEST_MARKER)
    # Spec version, with the exact revision.
    assert "| Spec version | `1.4.2` (revision `33333333-3333-4333-8333-333333333333`) |" in body
    # Generator version.
    assert "Apiome `1.184.0` · `app.snippet_render/sdk.client-kit.v1`" in body
    # Changed-files overview.
    assert "**2 added · 1 modified · 1 removed** · 7 unchanged" in body
    assert "| removed | `sdks/ts/snippets/old.ts` |" in body
    # Provenance, without empty values or the schema tag already implied.
    assert "| `versionRecordId` | `33333333-3333-4333-8333-333333333333` |" in body
    assert "settingsFingerprint" not in body
    assert "schemaVersion" not in body
    # And the warning that the branch is Apiome's.
    assert "force-updates it" in body


def test_the_body_is_deterministic():
    assert pull_request_body(_SUMMARY) == pull_request_body(replace(_SUMMARY))


def test_a_long_change_list_is_summarised_to_fit_with_exact_counts():
    files = [{"path": f"sdks/ts/snippets/{'x' * 200}-{i}.ts", "change": "added"} for i in range(400)]
    summary = replace(
        _SUMMARY,
        changes={"added": 900, "modified": 0, "removed": 0, "unchanged": 0, "files": files},
    )

    body = pull_request_body(summary, max_chars=20_000)

    assert len(body) <= 20_000
    assert "**900 added · 0 modified · 0 removed**" in body
    assert "more changed files._" in body


def test_a_body_that_cannot_fit_is_cut_rather_than_rejected_by_github():
    summary = replace(_SUMMARY, provenance={f"k{i}": "v" * 500 for i in range(50)})
    body = pull_request_body(summary, max_chars=5_000)
    assert len(body) <= 5_000
    assert body.endswith("…\n")


def test_a_hostile_label_cannot_break_out_of_its_table_cell():
    summary = replace(_SUMMARY, version_line="1.0 | `evil`\n| injected |")
    body = pull_request_body(summary)
    spec_row = next(line for line in body.splitlines() if line.startswith("| Spec version |"))
    assert "\\|" in spec_row and "`evil`" not in spec_row
    assert "\n| injected |" not in body


def test_a_multi_line_api_title_stays_on_one_line():
    body = pull_request_body(replace(_SUMMARY, api_title="Widgets\n\n# Injected heading\n**x**"))
    assert "\n# Injected heading" not in body
    assert "**Widgets # Injected heading \\*\\*x\\*\\***" in body


def test_the_commit_message_carries_provenance_trailers():
    message = commit_message(_SUMMARY)
    subject, blank, *_ = message.splitlines()
    assert subject == "Regenerate @acme/widgets-sdk 1.4.3 from widgets 1.4.2"
    assert blank == ""
    assert f"Apiome-Revision: {_REVISION}" in message
    assert "Apiome-Version-Line: 1.4.2" in message
    assert "Apiome-Package: npm @acme/widgets-sdk@1.4.3" in message
    assert "Apiome-Generator: apiome 1.184.0" in message


def test_the_repository_root_is_named_as_such():
    assert "`(repository root)`" in pull_request_body(replace(_SUMMARY, target_path=""))
