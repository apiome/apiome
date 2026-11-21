"""``apiome versions original`` (COA-5.7, #7083).

The helpers (:mod:`apiome_cli.version_original`) and the command against a mocked REST API: the
bytes are written as served once their SHA-256 matches ``X-Apiome-Content-Sha256``; a mismatch
writes nothing and exits 6; ``-o <dir>`` uses the offered file name; ``--part`` addresses one file
of a set; ``original-not-stored`` and ``original-withheld`` read as a sentence and exit 1.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_CHECKSUM_MISMATCH, EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app
from apiome_cli.version_original import (
    digest_problem,
    download_name,
    error_message,
    original_suffix,
    target_path,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V21 = "22222222-2222-4222-8222-222222222222"
_ORIGINAL = f"{_HOST}/versions/acme/{_PROJECT}/{_V21}/original"
_DOC = b"openapi: 3.1.0\ninfo:\n  title: Payments\npaths: {}\n"


def _resolve(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme/{_PROJECT}/by-version/2.1.0", json={"id": _V21}, is_optional=True
    )


def _serve(httpx_mock, *, url: str = _ORIGINAL, body: bytes = _DOC, sha: str | None = None) -> None:
    httpx_mock.add_response(
        url=url,
        content=body,
        headers={
            "Content-Type": "application/yaml",
            "Content-Disposition": 'attachment; filename="payments.yaml"',
            "X-Apiome-Content-Sha256": sha or hashlib.sha256(body).hexdigest(),
            "ETag": f'"{hashlib.sha256(body).hexdigest()}"',
        },
    )


class TestHelpers:
    def test_suffix(self):
        assert original_suffix(None) == "/original"
        assert original_suffix("/api/schemas/pet v2.json") == "/original/api/schemas/pet%20v2.json"

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ('attachment; filename="pets.yaml"', "pets.yaml"),
            ("attachment; filename=\"_ API.yaml\"; filename*=UTF-8''%E6%B3%A8%E6%96%87%20API.yaml", "注文 API.yaml"),
            ('attachment; filename="../../etc/passwd"', "passwd"),
            ('attachment; filename=".."', "original"),
            (None, "original"),
        ],
    )
    def test_download_name(self, header, expected):
        assert download_name(header) == expected

    def test_target_path(self, tmp_path: Path):
        assert target_path(tmp_path, "a.yaml") == tmp_path / "a.yaml"
        assert target_path(tmp_path / "b.yaml", "a.yaml") == tmp_path / "b.yaml"

    def test_digest_problem(self):
        good = hashlib.sha256(b"x").hexdigest()
        assert digest_problem(b"x", good) is None
        assert digest_problem(b"x", None) is None
        assert "does not match" in digest_problem(b"y", good)

    def test_error_message(self):
        assert error_message(404, {"code": "original-not-stored", "message": "Nothing."}, "2.1.0") == (
            "No original is stored for 2.1.0. Nothing."
        )
        assert "withheld at import (secrets-detected)" in error_message(
            410, {"code": "original-withheld", "reason": "secrets-detected"}, "2.1.0"
        )
        assert error_message(404, "Version not found", "2.1.0") is None


class TestCommand:
    def test_writes_to_stdout_by_default(self, httpx_mock):
        _resolve(httpx_mock)
        _serve(httpx_mock)

        result = runner.invoke(app, ["versions", "original", "payments-api", "2.1.0"], env=_ENV)

        assert result.exit_code == EXIT_SUCCESS, result.output
        assert result.stdout_bytes == _DOC

    def test_writes_under_the_offered_name_in_a_directory(self, httpx_mock, tmp_path: Path):
        _resolve(httpx_mock)
        _serve(httpx_mock)

        result = runner.invoke(
            app, ["--json", "versions", "original", "payments-api", "v2.1.0", "-o", str(tmp_path)], env=_ENV
        )

        assert result.exit_code == EXIT_SUCCESS, result.output
        written = tmp_path / "payments.yaml"
        assert written.read_bytes() == _DOC
        record = json.loads(result.stdout)
        assert record == {
            "file": str(written),
            "filename": "payments.yaml",
            "sha256": hashlib.sha256(_DOC).hexdigest(),
            "sizeBytes": len(_DOC),
            "mediaType": "application/yaml",
        }

    def test_a_digest_mismatch_writes_nothing(self, httpx_mock, tmp_path: Path):
        _resolve(httpx_mock)
        _serve(httpx_mock, sha="0" * 64)
        target = tmp_path / "out.yaml"

        result = runner.invoke(
            app, ["versions", "original", "payments-api", "2.1.0", "-o", str(target)], env=_ENV
        )

        assert result.exit_code == EXIT_CHECKSUM_MISMATCH
        assert "does not match" in result.stderr
        assert not target.exists()

    def test_part_downloads_one_file_of_a_set(self, httpx_mock, tmp_path: Path):
        _resolve(httpx_mock)
        _serve(httpx_mock, url=f"{_ORIGINAL}/api/schemas/pet.json", body=b'{"type": "object"}')
        target = tmp_path / "pet.json"

        result = runner.invoke(
            app,
            ["versions", "original", "payments-api", "2.1.0", "--part", "api/schemas/pet.json", "-o", str(target)],
            env=_ENV,
        )

        assert result.exit_code == EXIT_SUCCESS, result.output
        assert target.read_bytes() == b'{"type": "object"}'

    @pytest.mark.parametrize(
        ("status", "detail", "needle"),
        [
            (404, {"code": "original-not-stored", "message": "The revision has no stored original."}, "No original is stored"),
            (410, {"code": "original-withheld", "reason": "secrets-detected"}, "withheld at import"),
        ],
    )
    def test_missing_and_withheld(self, httpx_mock, status, detail, needle):
        _resolve(httpx_mock)
        httpx_mock.add_response(url=_ORIGINAL, status_code=status, json={"detail": detail})

        result = runner.invoke(app, ["versions", "original", "payments-api", "2.1.0"], env=_ENV)

        assert result.exit_code == EXIT_ERROR
        assert needle in result.stderr
