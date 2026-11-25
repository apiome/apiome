"""Shared builders for the hosted Pact verifier tests — PFX-3.2 (#6932).

The fixtures under ``tests/fixtures/pact_verifier`` are pacts in the shapes pact-js, pact-jvm and
pact-go write. :class:`LedgerApi` is a fake provider that honours all three, and records every
request it is sent — "a mutating interaction was not sent" is only provable by looking at what
actually went out.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.contract_suite import ContractSuiteManifest
from app.contract_suite_pact import compile_pact_suite
from app.verification_target import (
    NETWORK_CLASS_PUBLIC,
    ResolvedTarget,
    TargetAuthReference,
    VerificationPolicy,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pact_verifier"

PACT_JS = "pact-js-v3.json"
PACT_JVM = "pact-jvm-v4.json"
PACT_GO = "pact-go-v2.json"


def load_pact(name: str) -> Dict[str, Any]:
    """Read one fixture pact."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def compile_fixture(name: str) -> ContractSuiteManifest:
    """Compile one fixture pact as the verifier does."""
    document = load_pact(name)
    return compile_pact_suite(document, consumer=document["consumer"]["name"], provider=document["provider"]["name"])


def target(*, allow_mutating: bool = False, **policy: Any) -> ResolvedTarget:
    """A resolved staging target."""
    return ResolvedTarget(
        target_id="22222222-2222-4222-8222-222222222222",
        slug="ledger-staging",
        name="Ledger staging",
        environment="staging",
        network_class=NETWORK_CLASS_PUBLIC,
        base_url="https://ledger.staging.example.test",
        policy=VerificationPolicy(allow_mutating_methods=allow_mutating, **policy),
        auth=TargetAuthReference(),
        resolved_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
    )


def _json(status: int, body: Any, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


class LedgerApi:
    """A fake Ledger API that satisfies the three fixture pacts.

    ``overrides`` maps ``"METHOD /path"`` to a handler replacing the conformant answer, which is
    how a test makes the provider drift.
    """

    def __init__(self, overrides: Optional[Dict[str, Callable[[httpx.Request], httpx.Response]]] = None) -> None:
        self.requests: List[httpx.Request] = []
        self.overrides = overrides or {}

    @property
    def sent(self) -> List[str]:
        """``METHOD /path`` of every request received, in order."""
        return [f"{request.method} {request.url.path}" for request in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        if key in self.overrides:
            return self.overrides[key](request)
        if key == "GET /invoices/1042":
            return _json(
                200,
                {
                    "id": 1042,
                    "status": "paid",
                    "total": 310.25,
                    "issuedAt": "2026-10-01T08:00:00+02:00",
                    "lines": [{"sku": "SKU-7", "quantity": 1}, {"sku": "SKU-8", "quantity": 4}],
                    "customer": "acme",
                },
            )
        if key == "GET /invoices/9999":
            return _json(404, {"error": "no such invoice"})
        if key == "GET /invoices":
            return _json(
                200,
                {
                    "invoices": [
                        {"id": 7, "currency": "USD", "tags": {"priority": "low", "team": "ops"}},
                        {"id": 8, "currency": "EUR", "tags": {}},
                    ],
                    "page": {"number": 3, "last": True},
                },
            )
        if key == "POST /invoices":
            return httpx.Response(201, headers={"Location": "/invoices/9001"})
        if key == "GET /summary":
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "year": 2026,
                        "entries": [{"account": "4000", "balance": 99.0}, {"account": "5100", "balance": 0.5}],
                        "currency": "EUR",
                    }
                ),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        return httpx.Response(500, text="unexpected request")

    def client(self) -> httpx.Client:
        """An httpx client that talks to this fake."""
        return httpx.Client(transport=httpx.MockTransport(self))
