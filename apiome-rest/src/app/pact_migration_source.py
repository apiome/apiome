"""Reading a Pact Broker or PactFlow workspace from the server — PFX-8.16 (#7313).

The Migration wizard runs the PFX-6.7 engine as a job, so apiome-rest reads the source itself, with
the routes ``apiome pact migrate`` reads (all ``GET``, HAL JSON):

* ``/pacticipants`` and, per pacticipant, ``/pacticipants/{p}/versions`` (every page);
* ``/integrations``, then per pair ``/matrix?q[][pacticipant]=C&q[][pacticipant]=P&limit=N`` — every
  pact and verification result, each read from its own link when it is about to be imported;
* ``/environments`` with what is currently deployed and released in each;
* ``/webhooks``, each read from its link; ``/secrets`` (PactFlow) — names only.

**The source is only read.** Nothing here sends anything but ``GET``.

**The credentials stay on the source host and in memory.** A link the source returns is followed on
the source's own scheme and host even when it names another origin, redirects are not followed, and
the token or password lives only in this client — it is never written to the database or a log.

**The server is not a way into its own network.** Every request goes through
:func:`app.ssrf_guard.build_guarded_client`: the host must resolve to public addresses, so a "broker"
at ``169.254.169.254`` or ``localhost`` is refused (``pact-migration-source-invalid``). An answer over
:data:`MAX_DOCUMENT_BYTES` is refused instead of read into memory.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Collection, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from .pact_migration_plan import (
    KINDS,
    Plan,
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
    pact_content,
    test_results_dropped,
    verification_body,
    verification_time,
)
from .ssrf_guard import SSRFError, build_guarded_client, validate_host, validate_url_policy

__all__ = [
    "CODE_SOURCE_INVALID",
    "CODE_SOURCE_REFUSED",
    "CODE_SOURCE_UNREADABLE",
    "DEFAULT_MATRIX_LIMIT",
    "MAX_DOCUMENT_BYTES",
    "SourceBroker",
    "SourceError",
    "fetch_document",
    "product_of",
    "read_source",
]

#: The source URL is not one the server may read (HTTP 422).
CODE_SOURCE_INVALID = "pact-migration-source-invalid"
#: The source refused the credentials (HTTP 422).
CODE_SOURCE_REFUSED = "pact-migration-source-refused"
#: The source could not be reached, or answered something that is not a broker's (HTTP 422).
CODE_SOURCE_UNREADABLE = "pact-migration-source-unreadable"

#: Page size asked of paged collections (the Pact Broker's maximum is 100).
PAGE_SIZE = 100

#: Matrix rows asked per integration; a pair that returns this many is reported as possibly truncated.
DEFAULT_MATRIX_LIMIT = 1000

#: The most pages followed for one collection, so a source that loops its ``next`` link cannot hang a run.
_MAX_PAGES = 10_000

#: The largest answer read from the source (a matrix of a long-lived integration runs to megabytes).
#: A bigger one is refused rather than held in memory: the URL is the caller's, not Apiome's.
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024


class SourceError(Exception):
    """The source cannot be read.

    Attributes:
        code: ``pact-migration-source-invalid``, ``-refused`` or ``-unreadable``.
        http_status: The status the source answered, when it answered.
    """

    def __init__(self, code: str, message: str, *, http_status: Optional[int] = None) -> None:
        """Build the refusal.

        Args:
            code: Stable machine code.
            message: Human explanation — it names the host and path, never a credential.
            http_status: The source's status, if any.
        """
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _segment(value: str) -> str:
    """A name as one URL path segment."""
    return quote(value, safe="")


def product_of(base_url: str) -> str:
    """What the source calls itself: ``PactFlow`` for a ``pactflow.io`` host, else ``Pact Broker``."""
    host = (urlsplit(base_url).hostname or "").lower()
    return "PactFlow" if host == "pactflow.io" or host.endswith(".pactflow.io") else "Pact Broker"


class SourceBroker:
    """A read-only client for the source broker.

    Args:
        base_url: The source's base URL (``https://broker.example.com`` or a PactFlow
            ``https://<team>.pactflow.io``), optionally with a path prefix.
        token: A bearer token (a read-only one is enough).
        username: Basic-auth user for an open-source broker without tokens.
        password: Basic-auth password.
        timeout: Seconds per request.
        transport: An httpx transport (tests); with one, the host is not resolved.

    Raises:
        SourceError: ``pact-migration-source-invalid`` when the URL is not http(s), embeds
            credentials, or its host is not a public address.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 60.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        trimmed = (base_url or "").strip()
        parts = urlsplit(trimmed)
        try:
            host = validate_url_policy(trimmed)
            if transport is None:
                validate_host(host)
        except SSRFError as exc:
            raise SourceError(CODE_SOURCE_INVALID, f"the broker URL cannot be read from here: {exc}") from exc
        self.base_url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        self.host = parts.hostname or host
        self._origin = (parts.scheme, parts.netloc)
        self._credential = "the token" if token else "the username and password"
        headers = {"Accept": "application/hal+json, application/json"}
        auth = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif username or password:
            auth = httpx.BasicAuth(username or "", password or "")
        options: Dict[str, Any] = dict(headers=headers, auth=auth, timeout=timeout, follow_redirects=False)
        if transport is not None:
            self._client = httpx.Client(transport=transport, **options)
        else:
            self._client = build_guarded_client(**options)

    def close(self) -> None:
        """Close the connection pool (and let go of the credentials)."""
        self._client.close()

    def __enter__(self) -> "SourceBroker":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def url(self, href: str) -> str:
        """The URL to read for ``href`` — always on the source's own host.

        Args:
            href: A path (``/pacticipants``) or a link the source returned.

        Returns:
            An absolute URL on the source's scheme and host.
        """
        if href.startswith("/"):
            return self.base_url + href
        parts = urlsplit(urljoin(self.base_url + "/", href))
        return urlunsplit((*self._origin, parts.path, parts.query, ""))

    def get(self, href: str, *, missing_ok: bool = False, forbidden_ok: bool = False) -> Optional[Dict[str, Any]]:
        """Read one document.

        Args:
            href: The path or link.
            missing_ok: Answer ``None`` for a ``404`` instead of failing.
            forbidden_ok: Answer ``None`` for a ``403`` too (a read token that may not list secrets).

        Returns:
            The JSON object, or ``None`` for an allowed ``404`` / ``403``.

        Raises:
            SourceError: For a refusal, another error status, a body that is not a JSON object, or a
                connection failure — naming the host and path, never the credential.
        """
        url = self.url(href)
        path = urlsplit(url).path or "/"
        try:
            status, body = self._read(url)
        except SSRFError as exc:
            raise SourceError(CODE_SOURCE_INVALID, f"the broker URL cannot be read from here: {exc}") from exc
        except httpx.RequestError as exc:
            raise SourceError(
                CODE_SOURCE_UNREADABLE, f"Could not reach {self.host} ({type(exc).__name__}). Check the URL."
            ) from exc
        if body is None:
            raise SourceError(
                CODE_SOURCE_UNREADABLE,
                f"{self.host}'s answer for {path} is over {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB and was not read.",
            )
        if status == 404 and missing_ok:
            return None
        if status == 403 and forbidden_ok:
            return None
        if status in (401, 403):
            raise SourceError(
                CODE_SOURCE_REFUSED,
                f"Could not sign in to {self.host} ({status}). Check {self._credential}.",
                http_status=status,
            )
        if status >= 300:
            raise SourceError(
                CODE_SOURCE_UNREADABLE, f"{self.host} answered HTTP {status} for {path}.", http_status=status
            )
        try:
            document = json.loads(body)
        except ValueError as exc:
            raise SourceError(
                CODE_SOURCE_UNREADABLE, f"{self.host}'s answer for {path} is not JSON: is this a Pact Broker?"
            ) from exc
        if not isinstance(document, dict):
            raise SourceError(CODE_SOURCE_UNREADABLE, f"{self.host}'s answer for {path} is not a JSON object.")
        return document

    def _read(self, url: str) -> Tuple[int, Optional[bytes]]:
        """``GET`` one URL, reading at most :data:`MAX_DOCUMENT_BYTES` of its body.

        Args:
            url: The absolute URL.

        Returns:
            The status and the body — ``None`` for a successful answer over the limit (an error
            answer's body is not needed and is not read past the limit either).
        """
        with self._client.stream("GET", url) as response:
            chunks: List[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    return response.status_code, (None if response.status_code < 300 else b"")
                chunks.append(chunk)
            return response.status_code, b"".join(chunks)

    def collect(self, href: str, *names: str) -> List[Dict[str, Any]]:
        """Every item of a paged collection, following ``_links.next``.

        Args:
            href: The first page.
            names: Where the items sit (``pacticipants``, …).

        Returns:
            The items of every page, in order.
        """
        items: List[Dict[str, Any]] = []
        seen: set = set()
        next_href: Optional[str] = href
        for _ in range(_MAX_PAGES):
            if not next_href or next_href in seen:
                break
            seen.add(next_href)
            page = self.get(next_href) or {}
            items += embedded(page, *names)
            next_href = link(page, "next")
        return items

    def count_pacticipants(self) -> int:
        """How many pacticipants the source lists — the sign-in check of **Test connection**."""
        return len(self.collect(f"/pacticipants?{urlencode({'size': PAGE_SIZE})}", "pacticipants"))


def read_source(
    broker: SourceBroker,
    plan: Plan,
    *,
    kinds: Collection[str] = KINDS,
    matrix_limit: int = DEFAULT_MATRIX_LIMIT,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, str]:
    """Read what the migration carries over into ``plan``.

    Only what the chosen ``kinds`` need is asked of the source: versions are not listed when versions
    are not copied, the matrix is not read when neither pacts nor results are, and so on. Pacts and
    verification results are queued without their documents; the URLs to fetch them from are returned
    so only records not imported yet are fetched (:func:`fetch_document`).

    Args:
        broker: The source.
        plan: Where records and findings go.
        kinds: The record kinds chosen (all of them by default).
        matrix_limit: Matrix rows asked per integration.
        progress: Called with a short line as each part is read; it may raise to stop the read.

    Returns:
        ``{source key: URL}`` for every pact and verification result.
    """
    say = progress or (lambda _line: None)
    chosen = set(kinds)
    to_fetch: Dict[str, str] = {}

    if chosen & {"pacticipant", "version"}:
        say("Reading pacticipants")
        documents = broker.collect(f"/pacticipants?{urlencode({'size': PAGE_SIZE})}", "pacticipants")
        names = [name for name in (add_pacticipant(plan, document) for document in documents) if name]
        if "version" in chosen:
            for name in names:
                say(f"Reading versions of {name}")
                versions = broker.collect(
                    f"/pacticipants/{_segment(name)}/versions?{urlencode({'size': PAGE_SIZE})}", "versions"
                )
                add_versions(plan, name, versions)

    if chosen & {"pact", "verification"}:
        say("Reading integrations")
        for integration in embedded(broker.get("/integrations") or {}, "integrations"):
            consumer = (integration.get("consumer") or {}).get("name")
            provider = (integration.get("provider") or {}).get("name")
            if not consumer or not provider:
                plan.note("pact", "(integration)", "an integration without a consumer or provider name was skipped")
                continue
            say(f"Reading pacts of {consumer} → {provider}")
            query = urlencode(
                [("q[][pacticipant]", consumer), ("q[][pacticipant]", provider), ("limit", str(matrix_limit))],
                safe="[]",
            )
            document = broker.get(f"/matrix?{query}") or {}
            raw_rows = document.get("matrix") if isinstance(document.get("matrix"), list) else []
            if len(raw_rows) >= matrix_limit:
                plan.note(
                    "pact",
                    f"{consumer} → {provider}",
                    f"the source returned {len(raw_rows)} matrix rows, the limit asked: older pacts or results "
                    "may be missing — run again with a larger matrix limit",
                )
            to_fetch.update(add_integration(plan, consumer, provider, matrix_rows(document, consumer, provider)))

    if chosen & {"environment", "deployment", "release"}:
        say("Reading environments")
        for environment in broker.collect("/environments", "environments"):
            uuid = add_environment(plan, environment)
            name = environment.get("name")
            if not uuid or not isinstance(name, str):
                continue
            base = f"/environments/{_segment(uuid)}"
            if "deployment" in chosen:
                deployed = broker.get(f"{base}/deployed-versions/currently-deployed", missing_ok=True) or {}
                add_placements(plan, "deployment", name, embedded(deployed, "deployedVersions"))
            if "release" in chosen:
                released = broker.get(f"{base}/released-versions/currently-supported", missing_ok=True) or {}
                add_placements(plan, "release", name, embedded(released, "releasedVersions"))

    if "webhook" in chosen:
        say("Reading webhooks")
        for entry in links(broker.get("/webhooks", missing_ok=True) or {}, "pb:webhooks"):
            document = broker.get(entry["href"], missing_ok=True)
            if document is None:
                plan.note(
                    "webhook", entry.get("title") or entry["href"], "listed by the source but not readable; skipped"
                )
                continue
            add_webhook(plan, entry["href"], document)
        secrets = broker.get("/secrets", missing_ok=True, forbidden_ok=True)
        if secrets is not None:
            add_secrets(plan, embedded(secrets, "secrets"))
    return to_fetch


def fetch_document(
    broker: SourceBroker, record: Dict[str, Any], href: str, plan: Optional[Plan] = None
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
