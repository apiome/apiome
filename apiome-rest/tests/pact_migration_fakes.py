"""A small source broker and an in-memory run store for the migration-run tests — PFX-8.16 (#7313)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import unquote

import httpx

from app.pact_migration_run_store import as_utc

SOURCE = "https://broker.example.com"

PACT = {
    "consumer": {"name": "Web"},
    "provider": {"name": "API"},
    "interactions": [
        {"description": "an order", "request": {"method": "GET", "path": "/o/1"}, "response": {"status": 200}}
    ],
    "metadata": {"pactSpecification": {"version": "2.0.0"}},
}


def _day(day: int) -> str:
    return f"2025-03-{day:02d}T09:00:00Z"


def _version(number: str, day: int, *, branch: Optional[str] = None, tag: Optional[str] = None) -> Dict[str, Any]:
    inner: Dict[str, Any] = {}
    if branch:
        inner["branchVersions"] = [{"name": branch}]
    if tag:
        inner["tags"] = [{"name": tag, "createdAt": _day(day)}]
    return {"number": number, "createdAt": _day(day), "_embedded": inner}


def _row(version: str, day: int, result: Optional[int]) -> Dict[str, Any]:
    # Links name the broker's internal address, as a broker behind a proxy does.
    base = f"http://internal.broker:9292/pacts/provider/API/consumer/Web/version/{version}"
    row: Dict[str, Any] = {
        "consumer": {"name": "Web", "version": {"number": version}},
        "provider": {"name": "API"},
        "pact": {"createdAt": _day(day), "_links": {"self": {"href": base}}},
    }
    if result is not None:
        row["verificationResult"] = {
            "verifiedAt": _day(day),
            "_links": {"self": {"href": f"{base}/verification-results/{result}"}},
        }
    return row


def documents() -> Dict[str, Any]:
    """The source: 2 pacticipants, 4 versions, 3 pacts, 3 results, 1 environment, 1 deployment, 1 webhook."""
    pact = "/pacts/provider/API/consumer/Web/version/"
    return {
        "/pacticipants": {
            "_embedded": {
                "pacticipants": [
                    {"name": "Web", "mainBranch": "main", "_embedded": {"labels": [{"name": "team-web"}]}},
                    {"name": "API", "displayName": "Orders API"},
                ]
            }
        },
        "/pacticipants/Web/versions": {
            "_embedded": {
                "versions": [
                    _version("3", 3, branch="main"),
                    _version("2", 2, branch="main", tag="prod"),
                    _version("1", 1, branch="main"),
                ]
            }
        },
        "/pacticipants/API/versions": {"_embedded": {"versions": [_version("10", 2, branch="main")]}},
        "/integrations": {"_embedded": {"integrations": [{"consumer": {"name": "Web"}, "provider": {"name": "API"}}]}},
        "/matrix": {"matrix": [_row("1", 1, 1), _row("1", 1, 2), _row("2", 2, 3), _row("3", 3, None)]},
        pact + "1": {**PACT, "createdAt": _day(1), "_links": {}},
        pact + "2": {**PACT, "createdAt": _day(2), "_links": {}},
        pact + "3": {**PACT, "createdAt": _day(3), "_links": {}},
        pact + "1/verification-results/1": {"success": False, "providerApplicationVersion": "10"},
        pact + "1/verification-results/2": {"success": True, "providerApplicationVersion": "10"},
        pact + "2/verification-results/3": {"success": True, "providerApplicationVersion": "10"},
        "/environments": {"_embedded": {"environments": [{"uuid": "e1", "name": "production", "production": True}]}},
        "/environments/e1/deployed-versions/currently-deployed": {
            "_embedded": {
                "deployedVersions": [
                    {"createdAt": _day(2), "_embedded": {"pacticipant": {"name": "Web"}, "version": {"number": "2"}}}
                ]
            }
        },
        "/webhooks": {"_links": {"pb:webhooks": [{"href": "/webhooks/w1", "title": "ci"}]}},
        "/webhooks/w1": {
            "description": "ci",
            "events": [{"name": "contract_content_changed"}],
            "request": {
                "method": "POST",
                "url": "https://ci.example.com/hook",
                "headers": {"Authorization": "**********"},
            },
        },
    }


class FakeSource:
    """An httpx transport answering from :func:`documents`, recording what was asked.

    Attributes:
        docs: ``{path: document | status code}``; a missing path answers 404.
        requests: Every request received.
    """

    def __init__(self, docs: Optional[Dict[str, Any]] = None) -> None:
        self.docs = documents() if docs is None else docs
        self.requests: List[httpx.Request] = []

    def paths(self) -> List[str]:
        """The paths asked, in order."""
        return [unquote(request.url.path) for request in self.requests]

    def transport(self) -> httpx.MockTransport:
        """The transport to give a ``SourceBroker``."""

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            answer = self.docs.get(unquote(request.url.path), 404)
            if isinstance(answer, int):
                return httpx.Response(answer, json={"error": "no"})
            return httpx.Response(200, json=answer)

        return httpx.MockTransport(handle)


class FakeStore:
    """The functions of ``app.pact_migration_run_store`` the job uses, in memory.

    Attributes:
        rows: ``{run id: row}``.
        done: ``{run id: keys}``.
        saves: Every ``save_progress`` payload, in order.
        stop_when: Asked at every save: answer "stop" when it says so (``None``: never).
    """

    as_utc = staticmethod(as_utc)

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.done: Dict[str, Set[str]] = {}
        self.saves: List[Dict[str, Any]] = []
        self.stop_when: Optional[Callable[[], bool]] = None

    def row(
        self, mode: str = "copy", options: Optional[Dict[str, Any]] = None, run_id: str = "run-1"
    ) -> Dict[str, Any]:
        """Create a running row."""
        row = {
            "id": run_id,
            "tenant_id": "tenant-acme",
            "source": SOURCE,
            "auth_kind": "token",
            "mode": mode,
            "status": "running",
            "phase": "reading",
            "options": options or {},
            "counts": {},
            "facts": {"product": "Pact Broker"},
            "findings": [],
            "failures": [],
            "failures_dropped": 0,
            "log": [],
            "log_seq": 0,
            "error": None,
            "stop_requested": False,
            "started_by_label": "ada@example.com",
            "created_at": datetime(2026, 11, 27, 14, 0, tzinfo=timezone.utc),
            "finished_at": None,
        }
        self.rows[run_id] = row
        return copy.deepcopy(row)

    def save_progress(self, _db: Any, run_id: str, **fields: Any) -> bool:
        self.saves.append(copy.deepcopy(fields))
        self.rows[run_id].update(copy.deepcopy(fields))
        return self.stop_when is not None and self.stop_when()

    def finish_run(self, _db: Any, run_id: str, status: str, *, error: Optional[str] = None) -> None:
        self.rows[run_id].update(status=status, error=error, finished_at=datetime.now(timezone.utc))
        if status == "completed":
            self.rows[run_id]["phase"] = "done"

    def add_done(self, _db: Any, run_id: str, keys: Iterable[str]) -> None:
        self.done.setdefault(run_id, set()).update(keys)

    def done_keys(self, _db: Any, _tenant_id: str, _source: str) -> Set[str]:
        return {key for keys in self.done.values() for key in keys}
