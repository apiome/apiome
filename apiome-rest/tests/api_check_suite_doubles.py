"""Shared doubles for the GNC-3.1 (#4740) API change check suite tests.

The store tests and the route tests both run the real suite over doubled evidence: every
component's reader answers from data a test edits, and the provider answers in memory through the
real status adapter. One copy keeps the two suites judging the same fixtures.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx

from app import api_check_suite_evidence, api_check_suite_store
from app.api_check_suite import BreakingFacts, ContractFacts, LintFacts, SdkFacts
from app.api_check_suite_evidence import Classification
from app.consumer_impact import ConsumerImpactReport

__all__ = ["Evidence", "Provider", "install_evidence"]


class Provider:
    """An in-memory provider API the status adapter publishes to.

    Attributes:
        status: The status code to answer with.
        calls: One entry per request: ``(method, url)``.
    """

    def __init__(self) -> None:
        self.status = 201
        self.calls: List[Any] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request, recording what was asked."""
        self.calls.append((request.method, str(request.url)))
        return httpx.Response(self.status, json={"id": 4242})

    def factory(self):
        """A client factory bound to this provider."""

        def build() -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(self.handle))

        return build


class Evidence:
    """Every component's evidence, as data a test edits, in place of the real readers.

    Attributes:
        document: The draft document; its digest is the suite's content key.
        lint: What the lint reader returns.
        breaking: What the classification reader returns.
        consumers: What the consumer intersection returns.
        contract: What the contract reader returns.
        sdk: What the SDK reader returns.
        broken: Readers that raise instead of answering.
        model_error: A specific error the canonical-model loader raises, when set.
        calls: How often each reader was asked.
    """

    def __init__(self) -> None:
        self.document: Dict[str, Any] = {"openapi": "3.1.0", "info": {"title": "Pets"}}
        self.lint = LintFacts(
            grade="A",
            score=96,
            severity_counts={"error": 0, "warning": 1},
            guide={"id": "g", "name": "Acme"},
            report_fingerprint="sha256:lint-report",
        )
        self.breaking = Classification(facts=BreakingFacts(baseline_revision_id=None))
        self.consumers: Optional[ConsumerImpactReport] = None
        self.contract = ContractFacts(applicable=True)
        self.sdk = SdkFacts(operation_count=2, total_operation_count=2, kit_digest="sha256:kit")
        self.broken: set = set()
        self.model_error: Optional[Exception] = None
        self.calls: Counter = Counter()

    def _answer(self, name: str, value: Any) -> Any:
        self.calls[name] += 1
        if name in self.broken:
            raise RuntimeError(f"{name} unreadable")
        return value

    def read_draft(self, _tenant_id: str, _version: Any):
        """The draft document and its digest."""
        blob = json.dumps(self.document, sort_keys=True)
        return dict(self.document), f"sha256:{hashlib.sha256(blob.encode()).hexdigest()}"

    async def read_lint(self, **_kwargs: Any) -> LintFacts:
        return self._answer("lint", self.lint)

    def read_breaking(self, **_kwargs: Any) -> Classification:
        return self._answer("breaking", self.breaking)

    def consumer_impact(self, *_args: Any, **_kwargs: Any) -> Optional[ConsumerImpactReport]:
        return self._answer("consumers", self.consumers)

    def load_source(self, *_args: Any) -> Any:
        if self.model_error is not None:
            self.calls["model"] += 1
            raise self.model_error
        return self._answer("model", SimpleNamespace(api=None, source_text=None, source_format=None))

    def read_contract(self, **_kwargs: Any) -> ContractFacts:
        return self._answer("contract", self.contract)

    def read_sdk(self, **_kwargs: Any) -> SdkFacts:
        return self._answer("sdk", self.sdk)


def install_evidence(monkeypatch) -> Evidence:
    """Swap every evidence reader beneath the suite for one :class:`Evidence` double.

    Args:
        monkeypatch: The pytest fixture.

    Returns:
        The double, for a test to edit.
    """
    doubles = Evidence()
    monkeypatch.setattr(api_check_suite_store, "read_draft_document", doubles.read_draft)
    monkeypatch.setattr(api_check_suite_evidence, "read_lint_facts", doubles.read_lint)
    monkeypatch.setattr(api_check_suite_evidence, "read_breaking_facts", doubles.read_breaking)
    monkeypatch.setattr(api_check_suite_evidence, "read_contract_facts", doubles.read_contract)
    monkeypatch.setattr(api_check_suite_evidence, "read_sdk_facts", doubles.read_sdk)
    monkeypatch.setattr("app.export_source.load_export_source", doubles.load_source)
    monkeypatch.setattr(
        "app.consumer_impact_service.consumer_impact_for_diff", doubles.consumer_impact
    )
    return doubles
