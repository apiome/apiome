"""Multi-item batch export jobs — E1-3 (#6219).

Pins the ``items`` source shape of a batch export job (several artifacts, each at a version or its
latest, × one or more targets → one archive):

* the request shape — ``items`` instead of ``artifact``, never mixed with a version selection,
  distinct non-blank entries, and at most 100 item × target pairs;
* the folder seam — :func:`~app.export_batch.item_directory`;
* the pipeline — each item lands under ``<item>/<target>/``, the manifest names each item's
  artifact, and a failing item does not sink the batch.

The DB-backed loaders are faked; the emitters run the real registry/SPI.
"""

from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.export_batch import LATEST_VERSION, item_directory
from app.export_job_engine import MAX_BATCH_ITEMS, ExportJobStartRequest, resolve_export_download
from app.export_source import ExportSourceError
from tests.test_export_batch import TENANT_SLUG, _run, _version

#: Fake catalog: artifact id → {version reference (None = latest) → source}.
_ARTIFACTS = {
    "art-orders": {None: _version("2.0.0", "rev-o2"), "1.0.0": _version("1.0.0", "rev-o1")},
    "art-pets": {None: _version("3.1.0", "rev-p3")},
}
_NAMES = {"art-orders": {"slug": "orders-api"}, "art-pets": {"name": "Pets API"}}


def _load(_tenant_id, artifact, ref):
    """Fake :func:`load_export_source` over :data:`_ARTIFACTS`."""
    try:
        return _ARTIFACTS[artifact][ref]
    except KeyError:
        raise ExportSourceError(f"Artifact {artifact!r} was not found.") from None


def _items_request(*items, targets=("openapi",), **kwargs) -> ExportJobStartRequest:
    return ExportJobStartRequest(items=list(items), targets=[{"target": t} for t in targets], **kwargs)


async def _run_items(request):
    with patch("app.database.db.get_project_by_id", side_effect=lambda pid, _t: _NAMES.get(pid)):
        return await _run(request, load=_load)


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
def test_items_is_a_batch_labelled_by_its_count():
    request = _items_request({"artifact": " art-orders "}, {"artifact": "art-pets", "version": "1.0.0"})
    assert request.is_batch and request.artifact is None
    assert [(i.artifact, i.version) for i in request.items] == [("art-orders", None), ("art-pets", "1.0.0")]
    assert request.artifact_label == "2 items"


@pytest.mark.parametrize(
    "payload",
    [
        {"target": "openapi"},  # neither artifact nor items
        {"artifact": "a", "items": [{"artifact": "b"}], "target": "openapi"},
        {"items": [{"artifact": "b"}], "version": "1.0.0", "target": "openapi"},
        {"items": [{"artifact": "b"}], "versions": ["1.0.0"], "target": "openapi"},
        {"items": [{"artifact": "b"}], "all_versions": True, "target": "openapi"},
        {"items": [], "target": "openapi"},
        {"items": [{"artifact": "  "}], "target": "openapi"},
        {"items": [{"artifact": "b"}, {"artifact": "b "}], "target": "openapi"},
        {"items": [{"artifact": "b", "extra": 1}], "target": "openapi"},
    ],
)
def test_request_rejects_inconsistent_item_shapes(payload):
    with pytest.raises(ValidationError):
        ExportJobStartRequest(**payload)


def test_the_same_artifact_at_two_versions_is_two_items():
    request = _items_request({"artifact": "a"}, {"artifact": "a", "version": "1.0.0"})
    assert len(request.items) == 2


def test_request_caps_item_target_pairs():
    half = MAX_BATCH_ITEMS // 2
    _items_request(*[{"artifact": f"a{i}"} for i in range(half)], targets=("openapi", "graphql"))
    with pytest.raises(ValidationError, match="at most 100 item × target pairs"):
        _items_request(*[{"artifact": f"a{i}"} for i in range(half + 1)], targets=("openapi", "graphql"))


# ---------------------------------------------------------------------------
# Folder seam
# ---------------------------------------------------------------------------
def test_item_directory_names_by_item_and_version_and_stays_unique():
    taken: set = set()
    source = _version("1.0.0", "rev-1")
    assert item_directory("orders-api", source, versioned=False, taken=taken) == "orders-api"
    assert item_directory("orders-api", source, versioned=True, taken=taken) == "orders-api-1.0.0"
    assert item_directory("orders-api", source, versioned=False, taken=taken) == "orders-api-2"
    assert item_directory("../etc", source, versioned=False, taken=taken).find("/") == -1


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
async def test_several_items_export_to_one_archive_with_a_folder_per_item():
    job_id, status = await _run_items(
        _items_request(
            {"artifact": "art-orders"},
            {"artifact": "art-orders", "version": "1.0.0"},
            {"artifact": "art-pets"},
            targets=("openapi", "graphql"),
        )
    )
    assert status["state"] == "completed", status["error"]
    result = status["result"]
    assert result["artifact"] == "3 items"
    batch = result["batch"]
    assert (batch["item_count"], batch["completed_count"], batch["failed_count"]) == (6, 6, 0)
    items = batch["items"]
    assert [(i["artifact"], i["version"]) for i in items[::2]] == [
        ("art-orders", LATEST_VERSION), ("art-orders", "1.0.0"), ("art-pets", LATEST_VERSION),
    ]
    assert [i["directory"].split("/")[0] for i in items[::2]] == ["orders-api", "orders-api-1.0.0", "Pets-API"]

    with zipfile.ZipFile(io.BytesIO(resolve_export_download(TENANT_SLUG, job_id).body)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["artifact"] == "3 items" and manifest["artifact_count"] == 2
    assert {i["artifact"] for i in manifest["items"]} == {"art-orders", "art-pets"}


async def test_an_unknown_item_fails_only_its_items():
    _job_id, status = await _run_items(_items_request({"artifact": "art-pets"}, {"artifact": "art-gone"}))
    assert status["state"] == "completed", status["error"]
    items = status["result"]["batch"]["items"]
    assert [(i["artifact"], i["state"]) for i in items] == [("art-pets", "completed"), ("art-gone", "failed")]


async def test_a_name_lookup_failure_falls_back_to_the_artifact_id():
    with patch("app.database.db.get_project_by_id", side_effect=RuntimeError("db down")):
        _job_id, status = await _run(_items_request({"artifact": "art-pets"}), load=_load)
    assert status["state"] == "completed", status["error"]
    assert status["result"]["batch"]["items"][0]["directory"].startswith("art-pets/")
