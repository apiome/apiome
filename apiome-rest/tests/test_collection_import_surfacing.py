"""Source cards, detection and fixtures for the collection formats — MFI-32.6 (#4408).

The HAR (MFI-32.2), Insomnia (32.3) and Bruno (32.4) adapters surface the standard way: the UI's
source cards and the CLI's ``apiome import <format>`` verb are both built from
``GET /v1/import/sources``, so these tests pin what the registry advertises, and that
``POST /v1/import/detect`` routes every committed example of each format to its own adapter with
no ambiguity — in particular that a Bruno ``.bru`` request is no longer also claimed as an
``.http`` file (``get {`` opens a Bruno method block; it is not a request line).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.http_file_parser import is_http_file
from app.main import app

client = TestClient(app)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

#: The three collection formats this ticket surfaces, keyed by registry key.
_FORMATS = ("har", "insomnia", "bruno")


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "tenant_id": "t1",
        "user_id": "u1",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.clear()


def _sources() -> dict:
    """Return the registry descriptors keyed by ``key``."""
    response = client.get("/v1/import/sources")
    assert response.status_code == 200
    return {source["key"]: source for source in response.json()["sources"]}


def _positive_examples(fmt: str) -> List[Path]:
    """Every committed positive example of ``fmt`` — top-level files and set members, no negatives."""
    root = _EXAMPLES / fmt
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "README.md" and "negative" not in path.relative_to(root).parts
    ]
    assert files, f"no committed examples for {fmt}"
    return files


def _example_cases() -> List[Tuple[str, Path]]:
    """``(format, path)`` for every positive example of every surfaced format."""
    return [(fmt, path) for fmt in _FORMATS for path in _positive_examples(fmt)]


def _detect(path: Path) -> dict:
    """POST one example to ``/v1/import/detect`` — archives as bytes, everything else as text."""
    data = path.read_bytes()
    if path.suffix == ".zip":
        body = {"document_base64": base64.standard_b64encode(data).decode("ascii"), "filename": path.name}
    else:
        body = {"text": data.decode("utf-8"), "filename": path.name}
    response = client.post("/v1/import/detect", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Source cards (GET /v1/import/sources)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,label,icon",
    [
        # HAR's card uses Lucide's ``activity`` (captured traffic); Insomnia and Bruno marks are
        # trademarked, so their cards use the neutral ``send`` icon instead of a brand logo.
        ("har", "HAR (inferred)", "activity"),
        ("insomnia", "Insomnia collection", "send"),
        ("bruno", "Bruno collection", "send"),
    ],
)
def test_source_card_descriptor(key: str, label: str, icon: str) -> None:
    source = _sources()[key]
    assert source["label"] == label
    assert source["icon"] == icon
    assert source["paradigm"] == "rest"
    assert source["supports_live_discovery"] is False
    assert source["formats"] == [key]
    # File upload drives the card's panel; fileset is the archive / git intake.
    assert source["input_kinds"] == ["file", "url", "paste", "fileset"]


@pytest.mark.parametrize(
    "key,own_suffixes",
    [("har", {".har"}), ("insomnia", {".json", ".yaml", ".yml"}), ("bruno", {".bru", ".json"})],
)
def test_source_cards_accept_their_files_and_archives(key: str, own_suffixes: set) -> None:
    # A fileset adapter's accept list carries the archive suffixes too, so the card's file picker
    # takes a zipped Bruno folder, a zip of HAR sessions, or an Insomnia export with environments.
    suffixes = set(_sources()[key]["file_extensions"])
    assert own_suffixes <= suffixes
    assert {".zip", ".tar.gz"} <= suffixes


# ---------------------------------------------------------------------------
# Detection (POST /v1/import/detect) over the committed fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt,path",
    _example_cases(),
    ids=lambda value: value.relative_to(_EXAMPLES).as_posix() if isinstance(value, Path) else value,
)
def test_every_example_routes_to_its_own_adapter(fmt: str, path: Path) -> None:
    body = _detect(path)
    assert body["matched"] is True
    assert body["detected"]["source_key"] == fmt
    assert body["detected"]["importable"] is True
    assert body["ambiguous"] is False, body.get("ambiguous_candidates")


def test_bruno_archive_resolves_bruno_json_as_root() -> None:
    body = _detect(_EXAMPLES / "bruno" / "03-users-collection.zip")
    assert body["archive_root"].endswith("bruno.json")


# ---------------------------------------------------------------------------
# The .http sniffer no longer claims .bru files
# ---------------------------------------------------------------------------


def test_bru_method_block_is_not_an_http_request_line() -> None:
    bru = "meta {\n  name: Ping\n  type: http\n}\n\nget {\n  url: https://api.example.com/ping\n}\n"
    assert is_http_file(bru) is False


@pytest.mark.parametrize(
    "text",
    [
        "GET https://api.example.com/ping\n",
        "GET {{baseUrl}}/users/{{id}} HTTP/1.1\n",
        "post /orders\n",
    ],
)
def test_http_request_lines_still_sniff(text: str) -> None:
    assert is_http_file(text) is True


@pytest.mark.parametrize(
    "path",
    [path for path in sorted((_EXAMPLES / "http-file").glob("*.http"))],
    ids=lambda path: path.name,
)
def test_http_file_examples_still_route_to_http_file(path: Path) -> None:
    assert _detect(path)["detected"]["source_key"] == "http-file"
