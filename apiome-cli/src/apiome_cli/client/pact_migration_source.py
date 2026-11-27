"""Reading a Pact Broker or PactFlow workspace through its REST API — PFX-6.7 (#6959).

``apiome pact migrate --from https://… --token …`` reads the source with these documented routes
(all ``GET``, HAL JSON):

* ``/pacticipants`` — names, repository, main branch, labels (every page, ``_links.next``);
* ``/pacticipants/{p}/versions`` — numbers, build URLs, branches, tags (every page);
* ``/integrations`` — every consumer → provider pair, then for each
  ``/matrix?q[][pacticipant]=C&q[][pacticipant]=P&limit=N`` — every pact and verification result of
  the pair, each read from its own link;
* ``/environments`` and, per environment, ``…/deployed-versions/currently-deployed`` and
  ``…/released-versions/currently-supported``;
* ``/webhooks`` — every webhook, each read from its link;
* ``/secrets`` (PactFlow only; a ``404`` from an open-source broker is expected) — names only.

**The token stays on the source host.** A link the source returns is followed on the ``--from``
host even when it names another origin (a broker behind a proxy often advertises its internal
address), so the token is never sent anywhere else.
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from apiome_cli.client.errors import CliError
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.pact_migration_plan import (
    Plan,
    pact_content,
    test_results_dropped,
    verification_body,
    verification_time,
    add_environment,
    add_integration,
    add_pacticipant,
    add_placements,
    add_secrets,
    add_versions,
    add_webhook,
    embedded,
    link,
    links,
    matrix_rows,
)

#: Page size asked of paged collections (the Pact Broker's maximum is 100).
PAGE_SIZE = 100

#: Matrix rows asked per integration; a pair that returns this many is reported as possibly truncated.
DEFAULT_MATRIX_LIMIT = 1000

#: The most pages followed for one collection, so a source that loops its ``next`` link cannot hang a run.
_MAX_PAGES = 10_000


def _segment(value: str) -> str:
    """A name as one URL path segment."""
    return quote(value, safe="")


class SourceBroker:
    """A read-only client for the source broker.

    Args:
        base_url: The source's base URL (``https://broker.example.com`` or a PactFlow
            ``https://<team>.pactflow.io``), optionally with a path prefix.
        token: A bearer token (PactFlow read token, or a Pact Broker token).
        username: Basic-auth user for an open-source broker without tokens.
        password: Basic-auth password.
        verify: Whether to verify TLS certificates.
        timeout: Seconds per request.
        transport: An httpx transport (tests).
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify: bool = True,
        timeout: float = 60.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        parts = urlsplit(base_url.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise CliError(
                f"--from must be an http(s) URL of the source broker, not {base_url!r}",
                exit_code=EXIT_ERROR,
            )
        self.base_url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")
        )
        self._origin = (parts.scheme, parts.netloc)
        headers = {"Accept": "application/hal+json, application/json"}
        auth = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif username or password:
            auth = httpx.BasicAuth(username or "", password or "")
        self._client = httpx.Client(
            headers=headers,
            auth=auth,
            verify=verify,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        """Close the connection pool."""
        self._client.close()

    def __enter__(self) -> "SourceBroker":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def url(self, href: str) -> str:
        """The URL to read for ``href`` — always on the ``--from`` host.

        Args:
            href: A path (``/pacticipants``) or a link the source returned.

        Returns:
            An absolute URL on the source's scheme and host.
        """
        if href.startswith("/"):
            return self.base_url + href
        parts = urlsplit(urljoin(self.base_url + "/", href))
        return urlunsplit((*self._origin, parts.path, parts.query, ""))

    def get(self, href: str, *, missing_ok: bool = False) -> Optional[dict[str, Any]]:
        """Read one document.

        Args:
            href: The path or link.
            missing_ok: Answer ``None`` for a ``404`` instead of failing.

        Returns:
            The JSON object, or ``None`` for an allowed ``404``.

        Raises:
            CliError: For a refusal, another error status, a body that is not a JSON object, or a
                connection failure — naming the path, never the token.
        """
        url = self.url(href)
        path = urlsplit(url).path
        try:
            response = self._client.get(url)
        except httpx.RequestError as exc:
            raise CliError(
                f"could not read {path} from the source broker: {exc}",
                exit_code=EXIT_ERROR,
            ) from exc
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code in (401, 403):
            raise CliError(
                f"the source broker refused {path} (HTTP {response.status_code}): check --token "
                "(a read token is enough) or --username/--password",
                exit_code=EXIT_ERROR,
            )
        if response.status_code >= 300:
            raise CliError(
                f"the source broker answered HTTP {response.status_code} for {path}",
                exit_code=EXIT_ERROR,
            )
        try:
            document = response.json()
        except ValueError as exc:
            raise CliError(
                f"the source broker's answer for {path} is not JSON",
                exit_code=EXIT_ERROR,
            ) from exc
        if not isinstance(document, dict):
            raise CliError(
                f"the source broker's answer for {path} is not a JSON object",
                exit_code=EXIT_ERROR,
            )
        return document

    def collect(self, href: str, *names: str) -> list[dict[str, Any]]:
        """Every item of a paged collection, following ``_links.next``.

        Args:
            href: The first page.
            names: Where the items sit (``pacticipants``, …).

        Returns:
            The items of every page, in order.
        """
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        next_href: Optional[str] = href
        for _ in range(_MAX_PAGES):
            if not next_href or next_href in seen:
                break
            seen.add(next_href)
            page = self.get(next_href) or {}
            items += embedded(page, *names)
            next_href = link(page, "next")
        return items


def read_source(
    broker: SourceBroker,
    plan: Plan,
    *,
    matrix_limit: int = DEFAULT_MATRIX_LIMIT,
    progress: Optional[Callable[[str], None]] = None,
) -> dict[str, str]:
    """Read everything the migration carries over into ``plan``.

    Pacts and verification results are queued without their documents; the URLs to fetch them from
    are returned so only records not imported yet are fetched (:func:`fetch_document`).

    Args:
        broker: The source.
        plan: Where records and findings go.
        matrix_limit: Matrix rows asked per integration.
        progress: Called with a short line as each part is read (stderr in the command).

    Returns:
        ``{source key: URL}`` for every pact and verification result.
    """
    say = progress or (lambda _line: None)
    say("Reading pacticipants")
    names = [
        name
        for name in (
            add_pacticipant(plan, document)
            for document in broker.collect(
                f"/pacticipants?{urlencode({'size': PAGE_SIZE})}", "pacticipants"
            )
        )
        if name
    ]
    for name in names:
        say(f"Reading versions of {name}")
        versions = broker.collect(
            f"/pacticipants/{_segment(name)}/versions?{urlencode({'size': PAGE_SIZE})}",
            "versions",
        )
        add_versions(plan, name, versions)

    say("Reading integrations")
    to_fetch: dict[str, str] = {}
    integrations = embedded(broker.get("/integrations") or {}, "integrations")
    for integration in integrations:
        consumer = (integration.get("consumer") or {}).get("name")
        provider = (integration.get("provider") or {}).get("name")
        if not consumer or not provider:
            plan.note(
                "pact",
                "(integration)",
                "an integration without a consumer or provider name was skipped",
            )
            continue
        query = urlencode(
            [
                ("q[][pacticipant]", consumer),
                ("q[][pacticipant]", provider),
                ("limit", str(matrix_limit)),
            ],
            safe="[]",
        )
        document = broker.get(f"/matrix?{query}") or {}
        raw_rows = (
            document.get("matrix") if isinstance(document.get("matrix"), list) else []
        )
        if len(raw_rows) >= matrix_limit:
            plan.note(
                "pact",
                f"{consumer} → {provider}",
                f"the source returned {len(raw_rows)} matrix rows, the limit asked: older pacts or results may be "
                "missing — run again with a larger --matrix-limit",
            )
        to_fetch.update(
            add_integration(
                plan, consumer, provider, matrix_rows(document, consumer, provider)
            )
        )

    say("Reading environments")
    for environment in broker.collect("/environments", "environments"):
        uuid = add_environment(plan, environment)
        name = environment.get("name")
        if not uuid or not isinstance(name, str):
            continue
        base = f"/environments/{_segment(uuid)}"
        deployed = (
            broker.get(f"{base}/deployed-versions/currently-deployed", missing_ok=True)
            or {}
        )
        add_placements(plan, "deployment", name, embedded(deployed, "deployedVersions"))
        released = (
            broker.get(f"{base}/released-versions/currently-supported", missing_ok=True)
            or {}
        )
        add_placements(plan, "release", name, embedded(released, "releasedVersions"))

    say("Reading webhooks")
    for entry in links(broker.get("/webhooks", missing_ok=True) or {}, "pb:webhooks"):
        document = broker.get(entry["href"], missing_ok=True)
        if document is None:
            plan.note(
                "webhook",
                entry.get("title") or entry["href"],
                "listed by the source but not readable; skipped",
            )
            continue
        add_webhook(plan, entry["href"], document)

    secrets = broker.get("/secrets", missing_ok=True)
    if secrets is not None:
        add_secrets(plan, embedded(secrets, "secrets"))
    return to_fetch


def fetch_document(
    broker: SourceBroker, record: dict[str, Any], href: str, plan: Optional[Plan] = None
) -> Optional[str]:
    """Read the document a queued pact or verification record still lacks, into the record.

    A pact's ``content`` is the pact without the source's decoration; a result's ``result`` is the
    body a verifier publishes. The document's own time replaces the matrix's when it has one.

    Args:
        broker: The source.
        record: A ``pact`` or ``verification`` record whose document is ``None``.
        href: Where to read it.
        plan: Where to note what of the document is left out (test results Apiome cannot store).

    Returns:
        ``None`` when read; otherwise why it could not be (the source no longer has it).
    """
    document = broker.get(href, missing_ok=True)
    if document is None:
        return f"the source listed it but answered 404 for {urlsplit(broker.url(href)).path}"
    if record["kind"] == "pact":
        record["content"] = pact_content(document)
        record["created_at"] = document.get("createdAt") or record.get("created_at")
        return None
    record["result"] = verification_body(document)
    record["created_at"] = verification_time(document) or record.get("created_at")
    if plan is not None and test_results_dropped(document):
        plan.note(
            "verification",
            f"{record['provider']}/{record['consumer']}/{record['consumer_version']} #{record['number']}",
            "its testResults are neither an array nor an object with a tests array: imported without them",
        )
    return None
