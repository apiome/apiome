"""``apiome usage upload`` — RDG-1.4 (#5762).

The server is mocked: ``POST …/usage/sources/har`` answers the source, ``POST …/usage/ingest``
answers a ledger row per batch. These tests pin what the command owns: a broken file or a ``.http``
file exits ``2`` before anything is sent, the batches are gzip JSON naming the source and carrying
no credential, query value or body, one batch per 5,000 entries, the server's scrub summary is
printed, ``--sample-bodies`` is refused against a closed body window, and a ``401`` exits ``2``
like ``apiome diff``.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "usage-har"
PETSTORE = FIXTURES / "petstore.har"
BASE = "http://localhost:8000/v1/tenants/acme-corp/usage"
SOURCE_URL = f"{BASE}/sources/har"
INGEST_URL = f"{BASE}/ingest"
SOURCE_ID = "6f1c9a52-4a5e-4c1b-9d0e-1f2a3b4c5d6e"

SECRETS = (
    "abcDEF1234567890ghiJKL",
    "s3cr3tSessionValue42",
    "ak_live_9f8e7d6c5b4a39281706f5e4d3c2b1a0",
    "c2VjcmV0",
    "alice@example.com",
)


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _source(**overrides: Any) -> dict[str, Any]:
    body = {
        "sourceId": SOURCE_ID,
        "projectId": "22222222-2222-2222-2222-222222222222",
        "kind": "har",
        "environment": "staging",
        "samplingRate": 1.0,
        "fieldCapture": True,
        "bodySamplesOpen": False,
        "created": True,
    }
    body.update(overrides)
    return body


def _ledger(received: int, **overrides: Any) -> dict[str, Any]:
    body = {
        "batchId": "b-1",
        "sourceId": SOURCE_ID,
        "receivedAt": "2026-11-16T12:00:00Z",
        "received": received,
        "accepted": received - 1,
        "attributed": 0,
        "sampledOut": 0,
        "unmatched": 1,
        "rejected": 0,
        "scrubFindings": 2,
        "basis": "complete",
        "samplingRate": 1.0,
        "samples": {"stored": 0, "dropped": 0},
        "rejections": [],
        "rejectionsTruncated": False,
    }
    body.update(overrides)
    return body


def _batches(httpx_mock) -> list[dict[str, Any]]:
    """The ingest batches the command sent, decompressed."""
    sent = []
    for request in httpx_mock.get_requests():
        if str(request.url) == INGEST_URL:
            assert request.headers["content-encoding"] == "gzip"
            assert request.headers["x-apiome-usage-source"] == SOURCE_ID
            sent.append(json.loads(gzip.decompress(request.content)))
    return sent


def _upload(*args: str):
    return runner.invoke(
        app,
        [
            "usage",
            "upload",
            str(PETSTORE),
            "--project",
            "pets",
            "--environment",
            "staging",
            *args,
        ],
    )


def test_an_upload_posts_one_batch_and_prints_the_scrub_summary(httpx_mock) -> None:
    httpx_mock.add_response(url=SOURCE_URL, method="POST", json=_source())
    httpx_mock.add_response(url=INGEST_URL, method="POST", json=_ledger(5))
    result = _upload()
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = result.stdout
    assert "Uploaded petstore.har: 8 entries in 1 batch(es)" in out
    assert f"Source {SOURCE_ID} (har · staging, created)" in out
    assert "Received 5 · accepted 4 · unmatched 1 · sampled out 0 · rejected 0" in out
    assert "Scrub findings: 2" in out
    assert (
        "Skipped on this machine: 3 (invalid-entry 1, no-response 1, unsupported-url 1)"
        in out
    )

    resolve = json.loads(httpx_mock.get_requests()[0].content)
    assert resolve == {"project": "pets", "environment": "staging"}
    (batch,) = _batches(httpx_mock)
    assert batch["source_id"] == SOURCE_ID and len(batch["events"]) == 5


def test_no_credential_query_value_or_body_leaves_the_machine(httpx_mock) -> None:
    httpx_mock.add_response(url=SOURCE_URL, method="POST", json=_source())
    httpx_mock.add_response(url=INGEST_URL, method="POST", json=_ledger(5))
    assert _upload().exit_code == EXIT_SUCCESS
    sent = json.dumps(_batches(httpx_mock))
    for secret in SECRETS:
        assert secret not in sent
    assert '"sample"' not in sent and '"headers"' not in sent


def test_json_prints_the_summed_report(httpx_mock) -> None:
    httpx_mock.add_response(url=SOURCE_URL, method="POST", json=_source(created=False))
    httpx_mock.add_response(
        url=INGEST_URL,
        method="POST",
        json=_ledger(
            5,
            rejected=1,
            accepted=3,
            rejections=[{"index": 4, "reason": "invalid-event"}],
        ),
    )
    result = runner.invoke(
        app,
        [
            "--json",
            "usage",
            "upload",
            str(PETSTORE),
            "--project",
            "pets",
            "--environment",
            "staging",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    report = json.loads(result.stdout)
    assert report["entries"] == 8 and report["batches"] == ["b-1"]
    assert report["totals"]["received"] == 5 and report["totals"]["rejected"] == 1
    assert report["skipped"] == {
        "invalid-entry": 1,
        "no-response": 1,
        "unsupported-url": 1,
    }
    assert report["rejections"] == {"invalid-event": 1}
    assert report["source"]["sourceId"] == SOURCE_ID


def test_a_large_archive_is_ledgered_as_one_batch_per_5000_entries(
    httpx_mock, tmp_path: Path
) -> None:
    har = json.loads(PETSTORE.read_text())
    template = har["log"]["entries"][3]  # the DELETE: no body, smallest event
    har["log"]["entries"] = [template] * 10_001
    big = tmp_path / "big.har"
    big.write_text(json.dumps(har))
    httpx_mock.add_response(url=SOURCE_URL, method="POST", json=_source())
    for size in (5000, 5000, 1):
        httpx_mock.add_response(url=INGEST_URL, method="POST", json=_ledger(size))
    result = runner.invoke(
        app,
        ["usage", "upload", str(big), "--project", "pets", "--environment", "staging"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert [len(b["events"]) for b in _batches(httpx_mock)] == [5000, 5000, 1]
    assert "10,001 entries in 3 batch(es)" in result.stdout


def test_a_named_source_is_sent_for_checking(httpx_mock) -> None:
    httpx_mock.add_response(url=SOURCE_URL, method="POST", json=_source(created=False))
    httpx_mock.add_response(url=INGEST_URL, method="POST", json=_ledger(5))
    assert _upload("--source", SOURCE_ID).exit_code == EXIT_SUCCESS
    resolve = json.loads(httpx_mock.get_requests()[0].content)
    assert resolve["sourceId"] == SOURCE_ID


def test_sample_bodies_against_a_closed_window_sends_nothing(httpx_mock) -> None:
    httpx_mock.add_response(
        url=SOURCE_URL, method="POST", json=_source(bodySamplesOpen=False)
    )
    result = _upload("--sample-bodies")
    assert result.exit_code == EXIT_USAGE
    assert "does not accept body samples" in result.stderr
    assert _batches(httpx_mock) == []


def test_sample_bodies_against_an_open_window_attaches_samples(httpx_mock) -> None:
    httpx_mock.add_response(
        url=SOURCE_URL, method="POST", json=_source(bodySamplesOpen=True)
    )
    httpx_mock.add_response(
        url=INGEST_URL,
        method="POST",
        json=_ledger(5, samples={"stored": 3, "dropped": 2}),
    )
    result = _upload("--sample-bodies")
    assert result.exit_code == EXIT_SUCCESS, result.output
    (batch,) = _batches(httpx_mock)
    assert sum(1 for e in batch["events"] if "sample" in e) == 5
    assert "Body samples: 3 stored, 2 dropped by the re-scan" in result.stdout


@pytest.mark.parametrize("name", ["truncated.har", "not-a-har.har"])
def test_a_parse_error_exits_2_before_anything_is_sent(httpx_mock, name: str) -> None:
    result = runner.invoke(
        app,
        [
            "usage",
            "upload",
            str(FIXTURES / name),
            "--project",
            "pets",
            "--environment",
            "staging",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert name in result.stderr
    assert httpx_mock.get_requests() == []


def test_an_http_request_file_is_refused_with_exit_2(httpx_mock) -> None:
    result = runner.invoke(
        app,
        [
            "usage",
            "upload",
            str(FIXTURES / "requests.http"),
            "--project",
            "pets",
            "--environment",
            "staging",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "record requests without responses" in result.stderr
    assert httpx_mock.get_requests() == []


def test_a_missing_file_exits_2(httpx_mock, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "usage",
            "upload",
            str(tmp_path / "nope.har"),
            "--project",
            "pets",
            "--environment",
            "staging",
        ],
    )
    assert result.exit_code == EXIT_USAGE and "no such file" in result.stderr


def test_an_auth_error_exits_2(httpx_mock) -> None:
    httpx_mock.add_response(
        url=SOURCE_URL,
        method="POST",
        status_code=401,
        json={"detail": "Invalid API key"},
    )
    assert _upload().exit_code == EXIT_USAGE


def test_a_refused_batch_exits_2(httpx_mock) -> None:
    httpx_mock.add_response(url=SOURCE_URL, method="POST", json=_source())
    httpx_mock.add_response(
        url=INGEST_URL,
        method="POST",
        status_code=429,
        json={
            "detail": {"code": "usage-quota-exceeded", "message": "over today's cap"}
        },
    )
    assert _upload().exit_code == EXIT_USAGE


def test_a_server_error_exits_1(httpx_mock) -> None:
    httpx_mock.add_response(
        url=SOURCE_URL, method="POST", status_code=500, json={"detail": "boom"}
    )
    assert _upload().exit_code == EXIT_ERROR


def test_a_tenant_is_required(httpx_mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APIOME_TENANT_ID")
    result = _upload()
    assert result.exit_code == EXIT_USAGE and "tenant scope required" in result.stderr
