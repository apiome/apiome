"""Tests for the generated REST API reference pages (DOCS-1.11, #5628).

The first test is the **drift gate**: it renders the reference folder from the committed
``openapi.yaml`` in memory and compares it file by file with ``apiome-docs/docs/reference/rest/``.
Every REST change bumps and regenerates ``openapi.yaml``; one that does not also regenerate the pages
turns this suite red, so the published reference cannot fall behind the API.

The rest pin the renderer's behaviour on a tiny inline document: parameter tables, readable types
for ``$ref`` / ``anyOf`` / arrays / enums, cell escaping, untagged operations, titles and the hash
recorded for ``yarn docs:check``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

import pytest
import yaml

from app.rest_reference_doc import (
    HASH_FRONT_MATTER_KEY,
    OPENAPI_PATH,
    REGENERATE_COMMAND,
    REST_REFERENCE_DIR,
    UNTAGGED,
    collect_operations,
    render_rest_reference,
    tag_title,
    type_label,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "apiome-rest" / "scripts" / "generate_rest_reference_docs.py"


def _load_script() -> ModuleType:
    """Import the generator script as a module (it lives outside the package)."""
    spec = importlib.util.spec_from_file_location("generate_rest_reference_docs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ===========================================================================
# The drift gate
# ===========================================================================


def test_committed_pages_match_the_openapi_document() -> None:
    """The committed folder is exactly what the generator renders from openapi.yaml."""
    script = _load_script()
    problems = script.differences(REPO_ROOT / REST_REFERENCE_DIR, script.render())
    assert problems == [], (
        f"{REST_REFERENCE_DIR} is out of date ({', '.join(problems[:5])}"
        f"{', …' if len(problems) > 5 else ''}). Regenerate with: {REGENERATE_COMMAND}"
    )


def test_every_tag_of_the_document_has_a_page() -> None:
    """One page per tag, plus untagged.md, so no endpoint goes undocumented."""
    document = yaml.safe_load((REPO_ROOT / OPENAPI_PATH).read_bytes())
    tags = {tag for op in collect_operations(document) for tag in op.tags}
    folder = REPO_ROOT / REST_REFERENCE_DIR
    assert {f"{tag}.md" for tag in tags} <= {path.name for path in folder.iterdir()}


# ===========================================================================
# The renderer, on a tiny document
# ===========================================================================

TINY: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Tiny", "version": "9.8.7"},
    "paths": {
        "/v1/things/{thing_id}": {
            "get": {
                "tags": ["mcp-catalog"],
                "operationId": "get_thing",
                "summary": "Get a thing",
                "description": "Returns <one> thing.\n# not a heading",
                "parameters": [
                    {"name": "thing_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {
                        "name": "mode",
                        "in": "query",
                        "description": "a | b",
                        "schema": {"anyOf": [{"$ref": "#/components/schemas/Mode"}, {"type": "null"}]},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}},
                    }
                },
            }
        },
        "/v1/ping": {"get": {"operationId": "ping", "responses": {"204": {"description": "Pong"}}}},
    },
    "components": {
        "schemas": {
            "Thing": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "children": {"type": "array", "items": {"$ref": "#/components/schemas/Thing"}},
                },
            },
            "Mode": {"type": "string", "enum": ["a", "b"]},
        },
        "securitySchemes": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
    },
}

SOURCE = json.dumps(TINY).encode()


@pytest.fixture(scope="module")
def files() -> Dict[str, str]:
    """The folder rendered from the tiny document."""
    return render_rest_reference(TINY, SOURCE)


def test_one_page_per_tag_and_one_for_untagged_operations(files: Dict[str, str]) -> None:
    assert set(files) == {"_category_.json", "index.mdx", "mcp-catalog.md", f"{UNTAGGED}.md"}
    assert "`GET /v1/ping`" in files[f"{UNTAGGED}.md"]
    assert 'title: "Untagged"' in files[f"{UNTAGGED}.md"]


def test_index_records_the_document_hash_version_and_tags(files: Dict[str, str]) -> None:
    index = files["index.mdx"]
    assert f"{HASH_FRONT_MATTER_KEY}: {hashlib.sha256(SOURCE).hexdigest()}" in index
    assert "version **9.8.7**" in index
    assert "2 operations under 1 tags (and 1 untagged)" in index
    assert "| [MCP catalog](./mcp-catalog.md) | 1 |" in index
    assert "| `ApiKey` | apiKey | `X-API-Key` header |" in index


def test_operation_section_has_anchor_parameters_and_responses(files: Dict[str, str]) -> None:
    page = files["mcp-catalog.md"]
    assert "## `GET /v1/things/{thing_id}` {#get-thing}" in page
    assert "| `thing_id` | path | string | yes | — |" in page
    # The anyOf-with-null reads as "X or null", links the schema on the page, and the pipe is escaped.
    assert "| `mode` | query | [`Mode`](#schema-mode) or null | no | a \\| b |" in page
    assert "| 200 | OK | `application/json` [`Thing`](#schema-thing) |" in page


def test_prose_is_escaped_for_commonmark(files: Dict[str, str]) -> None:
    page = files["mcp-catalog.md"]
    assert "Returns &lt;one&gt; thing." in page
    assert "\n\\# not a heading" in page


def test_schemas_used_lists_direct_references_with_their_properties(files: Dict[str, str]) -> None:
    page = files["mcp-catalog.md"]
    assert "### `Thing` {#schema-thing}" in page
    assert "| `id` | string (uuid) | yes | — |" in page
    assert "| `children` | array of [`Thing`](#schema-thing) | no | — |" in page
    assert "### `Mode` {#schema-mode}" in page
    assert 'Type: enum `"a"`, `"b"`' in page


def test_front_matter_description_is_short(files: Dict[str, str]) -> None:
    for name, text in files.items():
        if not name.endswith(("md", "mdx")):
            continue
        line = next(line for line in text.splitlines() if line.startswith("description:"))
        assert len(json.loads(line.split(":", 1)[1]).split()) <= 14, name


@pytest.mark.parametrize(
    ("tag", "title"),
    [
        ("mcp-catalog", "MCP catalog"),
        ("sdk-git-delivery", "SDK git delivery"),
        ("openapi-change-report", "OpenAPI change report"),
        ("api-keys", "API keys"),
        ("versions", "Versions"),
    ],
)
def test_tag_titles_keep_acronyms(tag: str, title: str) -> None:
    assert tag_title(tag) == title


@pytest.mark.parametrize(
    ("schema", "label"),
    [
        ({"type": ["string", "null"]}, "string or null"),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, "map of integer"),
        ({"enum": list("abcdefgh")}, 'enum `"a"`, `"b"`, `"c"`, `"d"`, `"e"`, `"f"`, …'),
        ({"allOf": [{"$ref": "#/components/schemas/A"}]}, "`A`"),
        ({}, "any"),
    ],
)
def test_type_labels(schema: Dict[str, Any], label: str) -> None:
    assert type_label(schema) == label


def test_check_reports_stale_missing_and_extra_files(tmp_path: Path) -> None:
    script = _load_script()
    (tmp_path / "a.md").write_text("old", encoding="utf-8")
    (tmp_path / "gone.md").write_text("x", encoding="utf-8")
    problems = script.differences(tmp_path, {"a.md": "new", "b.md": "x"})
    assert problems == ["stale: a.md", "missing: b.md", "extra: gone.md"]
