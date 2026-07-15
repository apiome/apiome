"""Unit tests for the lint gate attestation signer/verifier (CLX-4.2, #4860)."""

import base64
import json
from datetime import datetime, timezone

from app.lint_attestation import (
    PAYLOAD_TYPE,
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    _pae,
    attestation_envelope,
    build_attestation_statement,
    verify_attestation_envelope,
)

GATE = {
    "subjectType": "catalog_revision",
    "subjectId": "v1",
    "projectId": "p1",
    "baselineSubjectId": None,
    "newOnly": True,
    "policy": {"policyVersionId": "pv1", "contentFingerprint": "packfp"},
    "evaluation": {"evaluationId": "e1", "passed": True, "gateResults": {}},
    "gate": {"passed": True, "newOnly": True, "gateResults": {}},
    "counts": {"total": 0},
    "scanners": [
        {"scannerId": "apiome.lint", "reportFingerprint": "rf1", "inputFingerprint": "if1"},
        {"scannerId": "spectral", "reportFingerprint": "rf2", "inputFingerprint": "if2"},
    ],
}

FIXED_TS = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def test_statement_shape_and_determinism():
    a = build_attestation_statement(GATE, generated_at=FIXED_TS)
    b = build_attestation_statement(GATE, generated_at=FIXED_TS)
    assert a == b
    assert a["_type"] == STATEMENT_TYPE
    assert a["predicateType"] == PREDICATE_TYPE
    assert a["subject"] == [
        {"name": "apiome.lint", "digest": {"apiome-report-fingerprint": "rf1"}},
        {"name": "spectral", "digest": {"apiome-report-fingerprint": "rf2"}},
    ]
    predicate = a["predicate"]
    assert predicate["policy"]["contentFingerprint"] == "packfp"
    assert predicate["gate"]["passed"] is True
    assert predicate["generatedAt"] == FIXED_TS.isoformat()


def test_pae_encoding():
    pae = _pae("application/vnd.in-toto+json", b"hello")
    assert pae == b"DSSEv1 28 application/vnd.in-toto+json 5 hello"


def test_sign_verify_roundtrip_and_wrong_key():
    statement = build_attestation_statement(GATE, generated_at=FIXED_TS)
    envelope = attestation_envelope(statement, secret="shared")
    assert envelope["payloadType"] == PAYLOAD_TYPE
    assert envelope["signatures"][0]["keyid"] == "apiome-lint-hmac-v1"
    assert verify_attestation_envelope(envelope, "shared") is True
    assert verify_attestation_envelope(envelope, "other") is False
    # The payload decodes back to the exact statement.
    decoded = json.loads(base64.b64decode(envelope["payload"]))
    assert decoded == statement


def test_unsigned_envelope_when_no_secret():
    statement = build_attestation_statement(GATE, generated_at=FIXED_TS)
    envelope = attestation_envelope(statement, secret=None)
    assert envelope["signatures"] == []
    assert verify_attestation_envelope(envelope, "anything") is False


def test_verify_tolerates_malformed_envelopes():
    assert verify_attestation_envelope({}, "s") is False
    assert verify_attestation_envelope({"payloadType": PAYLOAD_TYPE, "payload": "!!"}, "s") is False
    assert (
        verify_attestation_envelope(
            {"payloadType": "wrong", "payload": "", "signatures": []}, "s"
        )
        is False
    )


def test_cli_verifier_is_lockstep():
    """The apiome-cli mirror must verify envelopes this module signs."""
    import importlib.util
    import pathlib

    cli_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apiome-cli"
        / "src"
        / "apiome_cli"
        / "attestation.py"
    )
    spec = importlib.util.spec_from_file_location("cli_attestation", cli_path)
    cli_attestation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_attestation)

    statement = build_attestation_statement(GATE, generated_at=FIXED_TS)
    envelope = attestation_envelope(statement, secret="shared")
    assert cli_attestation.verify_attestation_envelope(envelope, "shared") is True
    assert cli_attestation.verify_attestation_envelope(envelope, "wrong") is False
