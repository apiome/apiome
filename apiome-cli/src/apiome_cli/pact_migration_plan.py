"""What ``apiome pact migrate`` sends, worked out from what the source broker returned — PFX-6.7 (#6959).

Pure functions: :mod:`apiome_cli.client.pact_migration_source` reads the source (Pact Broker or
PactFlow) over HTTP; this module turns its HAL documents into the records
``POST /v1/tenants/{t}/pact-migration/import`` takes, says what cannot be carried over, keeps the
resume state and cuts the records into batches.

**Nothing is dropped without a word.** Whatever a source document holds that Apiome cannot take —
a redacted webhook secret, an unknown webhook event, a display name, a secret's value — is a
:class:`Finding` printed in the report, with what to do about it.

**Record keys.** Every record has a *source key* (:func:`source_key`): what the resume state stores
once the record is imported, so a second run skips it — and skips fetching a pact or a result whose
key is already done.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

#: The record kinds in the order they are sent: what a record refers to is sent before it.
KINDS: tuple[str, ...] = (
    "pacticipant",
    "environment",
    "version",
    "pact",
    "verification",
    "deployment",
    "release",
    "webhook",
)

#: The webhook events Apiome fires (apiome-db V436).
WEBHOOK_EVENTS: frozenset[str] = frozenset(
    {
        "contract_published",
        "contract_content_changed",
        "contract_requiring_verification_published",
        "provider_verification_published",
        "provider_verification_succeeded",
        "provider_verification_failed",
        "consumer_version_branch_created",
    }
)

#: What a Pact Broker returns in place of a secret value.
REDACTED = "**********"

#: The most records one import request may carry (the server's limit).
MAX_BATCH_RECORDS = 100

#: The default most bytes of JSON one import request carries (pacts can be large).
DEFAULT_BATCH_BYTES = 4 * 1024 * 1024

#: ``${user.<name>}`` — a PactFlow (and Apiome) secret reference.
_SECRET_REFERENCE = re.compile(r"\$\{user\.([A-Za-z][A-Za-z0-9_]{0,63})\}")

#: The number at the end of a verification result's URL.
_RESULT_NUMBER = re.compile(r"/verification-results/(\d+)/?$")

#: What the source holds that the migration does not read, said once in every report.
NOT_READ: tuple[str, ...] = (
    "deployment history (versions no longer deployed) and releases whose support ended: the source "
    "lists only current deployments and releases",
    "PactFlow teams, users, roles, API tokens and provider contracts: set them up in Apiome",
    "webhook execution history (triggered webhooks and their logs)",
)


@dataclass(frozen=True)
class Finding:
    """Something the source holds that cannot be carried over as it is.

    Attributes:
        kind: The record kind it concerns (``webhook``, ``pacticipant``, ``secret``, …).
        subject: What it is about (a webhook's description, a pacticipant's name, a secret's name).
        detail: What is not carried over and what to do.
    """

    kind: str
    subject: str
    detail: str


@dataclass
class Plan:
    """The records to send, by kind, and what cannot be carried over.

    Attributes:
        records: ``{kind: [(source key, record)]}`` — a pact or verification record may still lack
            its document (``content`` / ``result`` is ``None``) until it is fetched.
        findings: Everything not portable, in the order found.
        read_counts: How many items of each kind the source returned.
    """

    records: dict[str, list[tuple[str, dict[str, Any]]]] = field(
        default_factory=lambda: {k: [] for k in KINDS}
    )
    findings: list[Finding] = field(default_factory=list)
    read_counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, record: dict[str, Any]) -> None:
        """Queue a record under its kind."""
        self.records[record["kind"]].append((key, record))
        self.read_counts[record["kind"]] = self.read_counts.get(record["kind"], 0) + 1

    def note(self, kind: str, subject: str, detail: str) -> None:
        """Record something not portable."""
        self.findings.append(Finding(kind, subject, detail))


# ---------------------------------------------------------------------------------------------
# Reading HAL documents
# ---------------------------------------------------------------------------------------------


def embedded(document: Any, *names: str) -> list[dict[str, Any]]:
    """The first ``_embedded`` list (or top-level list) of ``document`` under one of ``names``.

    Pact Broker versions differ in where a collection sits (``_embedded.pacticipants`` or
    ``pacticipants``), so both are read.

    Args:
        document: A HAL document.
        names: The collection's possible names.

    Returns:
        The objects of the collection, or ``[]``.
    """
    if not isinstance(document, Mapping):
        return []
    for container in (document.get("_embedded"), document):
        if not isinstance(container, Mapping):
            continue
        for name in names:
            items = container.get(name)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def link(document: Any, rel: str) -> Optional[str]:
    """The ``href`` of a single ``_links`` relation, or ``None``."""
    links = document.get("_links") if isinstance(document, Mapping) else None
    target = links.get(rel) if isinstance(links, Mapping) else None
    if isinstance(target, list):
        target = target[0] if target else None
    href = target.get("href") if isinstance(target, Mapping) else None
    return href if isinstance(href, str) and href else None


def links(document: Any, rel: str) -> list[dict[str, Any]]:
    """Every entry of a ``_links`` relation that is a list (``pb:webhooks``), or ``[]``."""
    entries = (
        document.get("_links", {}).get(rel) if isinstance(document, Mapping) else None
    )
    if isinstance(entries, Mapping):
        entries = [entries]
    return [
        entry
        for entry in entries or []
        if isinstance(entry, dict) and isinstance(entry.get("href"), str)
    ]


def _name(value: Any) -> Optional[str]:
    """``value`` or ``value["name"]`` as a non-blank string."""
    if isinstance(value, Mapping):
        value = value.get("name")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _str(document: Mapping[str, Any], *keys: str) -> Optional[str]:
    """The first of ``keys`` holding a non-blank string."""
    for key in keys:
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---------------------------------------------------------------------------------------------
# Source keys
# ---------------------------------------------------------------------------------------------


def source_key(record: Mapping[str, Any]) -> str:
    """The resume-state key of a record: its kind and the names that identify it at the source.

    Args:
        record: An import record.

    Returns:
        E.g. ``version:Billing Service/1.0.0`` or ``verification:Ledger/Billing/1.0.0/3``.
    """
    kind = record["kind"]
    if kind == "pacticipant":
        parts = [record["name"]]
    elif kind == "environment":
        parts = [record["name"]]
    elif kind == "version":
        parts = [record["pacticipant"], record["number"]]
    elif kind == "pact":
        parts = [record["provider"], record["consumer"], record["consumer_version"]]
    elif kind == "verification":
        parts = [
            record["provider"],
            record["consumer"],
            record["consumer_version"],
            str(record["number"]),
        ]
    elif kind in ("deployment", "release"):
        parts = [
            record["pacticipant"],
            record["version"],
            record["environment"],
            record.get("application_instance") or "",
        ]
    else:
        parts = [
            record.get("uuid") or json.dumps(record.get("webhook"), sort_keys=True)
        ]
    return f"{kind}:" + "/".join(parts)


# ---------------------------------------------------------------------------------------------
# One builder per source document
# ---------------------------------------------------------------------------------------------


def add_pacticipant(plan: Plan, document: Mapping[str, Any]) -> Optional[str]:
    """Queue a pacticipant from ``GET /pacticipants``.

    Args:
        plan: The plan.
        document: One embedded pacticipant.

    Returns:
        Its name, or ``None`` when it has none (noted).
    """
    name = _name(document)
    if not name:
        plan.note(
            "pacticipant",
            "(unnamed)",
            "the source returned a pacticipant without a name; it was skipped",
        )
        return None
    display = _str(document, "displayName")
    if display and display != name:
        plan.note(
            "pacticipant",
            name,
            f"display name '{display}' is not carried over: an Apiome pacticipant has one name (the one pacts use)",
        )
    labels = [
        label
        for label in (_name(item) for item in embedded(document, "labels"))
        if label
    ]
    record = {
        "kind": "pacticipant",
        "name": name,
        "repository_url": _str(document, "repositoryUrl"),
        "main_branch": _str(document, "mainBranch"),
        "labels": labels,
        "created_at": _str(document, "createdAt"),
    }
    plan.add(source_key(record), record)
    return name


def add_versions(
    plan: Plan, pacticipant: str, documents: Iterable[Mapping[str, Any]]
) -> None:
    """Queue a pacticipant's versions from ``GET /pacticipants/{p}/versions``, oldest first.

    Apiome orders versions by when they were recorded, and a branch head only moves to a later one, so
    versions are sent in the source's creation order.

    Args:
        plan: The plan.
        pacticipant: Their pacticipant.
        documents: The embedded versions, in any order.
    """
    rows = []
    for position, document in enumerate(documents):
        number = _str(document, "number")
        if not number:
            plan.note(
                "version",
                pacticipant,
                "the source returned a version without a number; it was skipped",
            )
            continue
        branches = [
            b
            for b in (
                _name(item) for item in embedded(document, "branchVersions", "branches")
            )
            if b
        ]
        tags = []
        for item in embedded(document, "tags"):
            tag = _name(item)
            if tag:
                tags.append({"name": tag, "created_at": _str(item, "createdAt")})
        record = {
            "kind": "version",
            "pacticipant": pacticipant,
            "number": number,
            "build_url": _str(document, "buildUrl"),
            "branches": branches,
            "tags": tags,
            "created_at": _str(document, "createdAt"),
        }
        rows.append((record["created_at"] or "", -position, record))
    # The source lists newest first; a missing time sorts first, ties keep the source's (reversed) order.
    for _, _, record in sorted(rows, key=lambda row: (row[0], row[1])):
        plan.add(source_key(record), record)


def matrix_rows(document: Any, consumer: str, provider: str) -> list[dict[str, Any]]:
    """The rows of a ``GET /matrix`` answer that are this integration, consumer → provider."""
    rows = document.get("matrix") if isinstance(document, Mapping) else None
    return [
        row
        for row in rows or []
        if isinstance(row, dict)
        and _name(row.get("consumer")) == consumer
        and _name(row.get("provider")) == provider
    ]


def _version_number(party: Any) -> Optional[str]:
    """``row["consumer"]["version"]["number"]``."""
    version = party.get("version") if isinstance(party, Mapping) else None
    return _str(version, "number") if isinstance(version, Mapping) else None


def add_integration(
    plan: Plan, consumer: str, provider: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    """Queue an integration's pacts and verification results from its matrix rows.

    The documents are fetched later (only for keys not done yet), so each record is queued with
    ``content`` / ``result`` set to ``None`` and the URL to fetch it from returned.

    Args:
        plan: The plan.
        consumer: The consumer's name.
        provider: The provider's name.
        rows: The integration's matrix rows.

    Returns:
        ``{source key: URL}`` of every pact and result to fetch.
    """
    to_fetch: dict[str, str] = {}
    seen_results: set[str] = set()
    pacts: list[tuple[str, str, dict[str, Any]]] = []
    results: list[tuple[str, str, dict[str, Any]]] = []
    for row in rows:
        consumer_version = _version_number(row.get("consumer"))
        pact = row.get("pact") if isinstance(row.get("pact"), Mapping) else {}
        pact_href = link(pact, "self")
        if not consumer_version or not pact_href:
            continue
        record = {
            "kind": "pact",
            "consumer": consumer,
            "provider": provider,
            "consumer_version": consumer_version,
            "content": None,
            "created_at": _str(pact, "createdAt"),
        }
        key = source_key(record)
        if key not in to_fetch:
            to_fetch[key] = pact_href
            pacts.append((record["created_at"] or "", key, record))
        result = row.get("verificationResult")
        result_href = link(result, "self") if isinstance(result, Mapping) else None
        match = _RESULT_NUMBER.search(result_href or "")
        if not result_href or not match:
            continue
        verification = {
            "kind": "verification",
            "consumer": consumer,
            "provider": provider,
            "consumer_version": consumer_version,
            "number": int(match.group(1)),
            "result": None,
            "created_at": _str(result, "verifiedAt"),
        }
        if result_href in seen_results:
            continue  # The same result shows once per consumer version that published its pact.
        seen_results.add(result_href)
        verification_key = source_key(verification)
        to_fetch[verification_key] = result_href
        results.append(
            (verification["created_at"] or "", verification_key, verification)
        )
    for _, key, record in sorted(pacts, key=lambda item: item[0]):
        plan.add(key, record)
    for _, key, record in sorted(results, key=lambda item: item[0]):
        plan.add(key, record)
    return to_fetch


def pact_content(document: Mapping[str, Any]) -> dict[str, Any]:
    """A pact as published: the source's decoration (``_links``, ``_embedded``, ``createdAt``) removed."""
    return {
        key: value
        for key, value in document.items()
        if key not in ("_links", "_embedded", "createdAt")
    }


def verification_body(document: Mapping[str, Any]) -> dict[str, Any]:
    """A verification result as a verifier publishes it, from ``GET …/verification-results/{n}``.

    ``testResults`` is kept when it is a shape Apiome stores (an array, or an object with a ``tests``
    array); otherwise it is left out — :func:`test_results_dropped` says so for the report.
    """
    body: dict[str, Any] = {
        "success": document.get("success"),
        "providerApplicationVersion": _str(
            document, "providerApplicationVersion", "providerVersion"
        ),
    }
    for key in ("buildUrl", "verifiedBy"):
        if document.get(key) is not None:
            body[key] = document[key]
    if not test_results_dropped(document) and document.get("testResults") is not None:
        body["testResults"] = document["testResults"]
    return body


def test_results_dropped(document: Mapping[str, Any]) -> bool:
    """Whether a result's ``testResults`` is in a shape Apiome does not store (it is then left out)."""
    results = document.get("testResults")
    if results is None or isinstance(results, list):
        return False
    return not (isinstance(results, Mapping) and isinstance(results.get("tests"), list))


def verification_time(document: Mapping[str, Any]) -> Optional[str]:
    """When a result was recorded: ``verificationDate``, else ``createdAt``, else ``executionDate``."""
    return _str(document, "verificationDate", "createdAt", "executionDate")


def add_environment(plan: Plan, document: Mapping[str, Any]) -> Optional[str]:
    """Queue an environment from ``GET /environments``; returns its ``uuid`` (to read what is deployed)."""
    name = _str(document, "name")
    if not name:
        plan.note(
            "environment",
            "(unnamed)",
            "the source returned an environment without a name; it was skipped",
        )
        return None
    contacts = (
        document.get("contacts") if isinstance(document.get("contacts"), list) else []
    )
    record = {
        "kind": "environment",
        "name": name,
        "display_name": _str(document, "displayName"),
        "production": bool(document.get("production")),
        "contacts": contacts,
        "created_at": _str(document, "createdAt"),
    }
    plan.add(source_key(record), record)
    return _str(document, "uuid")


def add_placements(
    plan: Plan, kind: str, environment: str, documents: Iterable[Mapping[str, Any]]
) -> None:
    """Queue the current deployments (``kind="deployment"``) or releases of an environment.

    Args:
        plan: The plan.
        kind: ``deployment`` or ``release``.
        environment: The environment's name.
        documents: The embedded ``deployedVersions`` / ``releasedVersions``.
    """
    rows = []
    for document in documents:
        inner = (
            document.get("_embedded")
            if isinstance(document.get("_embedded"), Mapping)
            else {}
        )
        pacticipant = _name(inner.get("pacticipant"))
        version = (
            _str(inner.get("version") or {}, "number")
            if isinstance(inner.get("version"), Mapping)
            else None
        )
        if not pacticipant or not version:
            plan.note(
                kind,
                environment,
                f"a {kind} without its pacticipant or version was skipped",
            )
            continue
        record: dict[str, Any] = {
            "kind": kind,
            "pacticipant": pacticipant,
            "version": version,
            "environment": environment,
            "created_at": _str(document, "createdAt"),
        }
        if kind == "deployment":
            record["application_instance"] = _str(
                document, "applicationInstance", "target"
            )
        rows.append((record["created_at"] or "", record))
    for _, record in sorted(rows, key=lambda row: row[0]):
        plan.add(source_key(record), record)


def secret_references(value: Any) -> list[str]:
    """Every ``${user.<name>}`` name in a JSON value, in order, once each."""
    found: list[str] = []
    for name in _SECRET_REFERENCE.findall(json.dumps(value)):
        if name not in found:
            found.append(name)
    return found


def add_webhook(plan: Plan, href: str, document: Mapping[str, Any]) -> None:
    """Queue a webhook from ``GET /webhooks/{uuid}``, leaving out what cannot be imported.

    * A redacted secret (``**********`` header, password) is left out and the webhook imported
      **disabled**, so it does not call its target without credentials; re-enter the secret, then
      enable it.
    * An event Apiome does not fire is left out; with none left the webhook is not imported.
    * A ``${user.<name>}`` reference stays: Apiome resolves the same syntax, from its own secrets.

    Args:
        plan: The plan.
        href: Where it was read (its last segment is the uuid).
        document: The webhook.
    """
    uuid = href.rstrip("/").rsplit("/", 1)[-1]
    subject = _str(document, "description") or uuid
    request = (
        dict(document.get("request") or {})
        if isinstance(document.get("request"), Mapping)
        else {}
    )
    body: dict[str, Any] = {"request": request}
    for key in ("description", "consumer", "provider", "enabled"):
        if document.get(key) is not None:
            body[key] = document[key]
    events = [_name(event) for event in document.get("events") or []]
    kept = [event for event in events if event in WEBHOOK_EVENTS]
    dropped = [event for event in events if event and event not in WEBHOOK_EVENTS]
    if dropped:
        plan.note(
            "webhook",
            subject,
            f"event(s) {', '.join(dropped)} are not fired by Apiome and were left out",
        )
    if events and not kept:
        plan.note(
            "webhook", subject, "not imported: none of its events is one Apiome fires"
        )
        return
    if kept:
        body["events"] = [{"name": event} for event in kept]
    redacted: list[str] = []
    headers = (
        request.get("headers") if isinstance(request.get("headers"), Mapping) else None
    )
    if headers:
        request["headers"] = {
            name: value for name, value in headers.items() if value != REDACTED
        }
        redacted += [
            f"header {name}" for name, value in headers.items() if value == REDACTED
        ]
    if request.get("password") == REDACTED:
        request.pop("password")
        redacted.append("basic-auth password")
    if redacted:
        body["enabled"] = False
        plan.note(
            "webhook",
            subject,
            f"the source does not export {', '.join(redacted)}: imported disabled — re-enter the value(s) "
            "(or a ${user.<name>} secret reference) and enable it",
        )
    for name in secret_references(body):
        plan.note(
            "webhook",
            subject,
            f"refers to the secret {name}: create it in Apiome first (POST /v1/tenants/<tenant>/pact-secrets), "
            "or this webhook is refused",
        )
    record = {
        "kind": "webhook",
        "uuid": uuid,
        "webhook": body,
        "created_at": _str(document, "createdAt"),
    }
    plan.add(source_key(record), record)


def add_secrets(plan: Plan, documents: Iterable[Mapping[str, Any]]) -> None:
    """Note PactFlow's secrets (``GET /secrets``): their names are listed, values are never exported."""
    for document in documents:
        name = _str(document, "name") or "(unnamed)"
        plan.note(
            "secret",
            name,
            "PactFlow does not export secret values: create it in Apiome with the same name "
            "(POST /v1/tenants/<tenant>/pact-secrets) before importing the webhooks that use it",
        )


# ---------------------------------------------------------------------------------------------
# Resume state and batches
# ---------------------------------------------------------------------------------------------

#: The outcomes after which a record need not be sent again.
DONE_OUTCOMES = frozenset({"created", "updated", "unchanged"})


@dataclass
class MigrationState:
    """What earlier runs imported, so a re-run skips it.

    Attributes:
        path: The state file.
        source: The source broker URL it belongs to.
        target: The Apiome workspace it belongs to.
        done: Source keys already imported.
    """

    path: Path
    source: str
    target: str
    done: set[str] = field(default_factory=set)

    @classmethod
    def load(
        cls, path: Path, *, source: str, target: str, restart: bool = False
    ) -> "MigrationState":
        """Read the state file, or start empty.

        Args:
            path: The file.
            source: The source broker URL of this run.
            target: The target workspace of this run.
            restart: Ignore what the file holds.

        Returns:
            The state.

        Raises:
            ValueError: When the file belongs to another source or workspace, or is not a state file.
        """
        state = cls(path=path, source=source, target=target)
        if restart or not path.exists():
            return state
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"{path} is not a migration state file ({exc}); pass --restart to start over"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("done"), list):
            raise ValueError(
                f"{path} is not a migration state file; pass --restart to start over"
            )
        if data.get("source") != source or data.get("target") != target:
            raise ValueError(
                f"{path} records a migration from {data.get('source')} to {data.get('target')}, not this one; "
                "pass another --state file, or --restart"
            )
        state.done = {key for key in data["done"] if isinstance(key, str)}
        return state

    def save(self) -> None:
        """Write the state file (atomically: a temporary file renamed over it)."""
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "source": self.source,
                    "target": self.target,
                    "done": sorted(self.done),
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def batches(
    items: Iterable[tuple[str, dict[str, Any]]],
    *,
    max_records: int = MAX_BATCH_RECORDS,
    max_bytes: int = DEFAULT_BATCH_BYTES,
) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    """Cut records into import requests of at most ``max_records`` and about ``max_bytes`` each.

    A single record larger than ``max_bytes`` goes alone (the server may still refuse it as too large).

    Args:
        items: ``(source key, record)`` pairs, in sending order.
        max_records: Records per request.
        max_bytes: Approximate JSON bytes per request.

    Yields:
        The batches, in order.
    """
    batch: list[tuple[str, dict[str, Any]]] = []
    size = 0
    for item in items:
        item_size = len(json.dumps(item[1]))
        if batch and (len(batch) >= max_records or size + item_size > max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += item_size
    if batch:
        yield batch
