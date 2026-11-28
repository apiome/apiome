"""The Contracts guided set-up — PFX-8.20 (#7317).

Without a database (``test_pact_setup_db`` runs the SQL):

* sections: done when the thing exists whoever made it, the first one not done is next, a migrated
  workspace arrives with the first two done, a mark only counts where nothing else can prove it;
* detection: projects as providers with their repository and owner, unbound repositories as
  consumers, each matched to the pacticipant that already exists; an unusable name is left out;
* the workflow: both steps, one step, never none; a name with a line break is refused;
* GitHub secrets: sealed and written once per repository; every repository that cannot be written
  is skipped with its reason; the key never appears in a result;
* GitHub pull requests: opened, found already open, skipped when the file is already there or the
  account cannot push — always with the workflow's text; a preview calls nothing;
* the routes: reading needs ``pacts:view``, everything else ``pacts:delete``; the tenant is the
  authenticated one; an unknown field is refused; a preview is not recorded.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from nacl import public
from pydantic import ValidationError

from app import pact_setup_github as github_module
from app.auth import validate_authentication
from app.consumer_contract_store import ConsumerActor
from app.main import app
from app.pact_setup import (
    SECRET_NAMES,
    SETUP_BRANCH,
    WORKFLOW_PATH,
    PactSetupCiKey,
    PactSetupFacts,
    PactSetupPullRequestRepository,
    PactSetupPullRequestsRequest,
    PactSetupSave,
    PactSetupSaved,
    check_broker_base_url,
    derive_sections,
    detect_candidates,
    workflow_text,
)
from app.pact_setup_github import open_pull_requests, seal_secret, write_secrets
from app.pact_setup_store import read_state, record_github, save_progress

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
REPO = "22222222-2222-4222-8222-222222222222"
OTHER_REPO = "44444444-4444-4444-8444-444444444444"
KEY_ID = "55555555-5555-4555-8555-555555555555"
ACTOR = ConsumerActor(user_id="33333333-3333-4333-8333-333333333333", label="ada@example.com")
_AUTH = {"tenant_id": TENANT, "user_id": "u-1", "auth_method": "jwt", "user_email": "ada@example.com"}
_ROUTES = "app.pact_setup_routes"
BROKER = "https://api.apiome.dev/v1/tenants/acme/pact-broker"
API_KEY = "apk_live_0123456789abcdef"


def _states(facts: PactSetupFacts, saved: Optional[PactSetupSaved] = None) -> List[str]:
    return [section.state for section in derive_sections(facts, saved or PactSetupSaved())]


# ---------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------


def test_an_empty_workspace_starts_at_the_first_section() -> None:
    sections = derive_sections(PactSetupFacts(), PactSetupSaved())
    assert [section.id for section in sections] == [
        "pacticipants",
        "environments",
        "pipelines",
        "first-pact",
        "provider",
        "gates",
    ]
    assert [section.state for section in sections] == ["next", "todo", "todo", "todo", "todo", "todo"]
    assert sections[0].title == "Who talks to whom"


def test_what_exists_is_done_whoever_made_it() -> None:
    facts = PactSetupFacts(pacticipants=3, environments=["production", "staging"], pacts=2)
    sections = derive_sections(facts, PactSetupSaved())
    assert [section.state for section in sections] == ["done", "done", "next", "done", "todo", "todo"]
    assert sections[0].summary == "3 pacticipants"
    assert sections[1].summary == "production and staging"
    assert sections[3].summary == "2 pacts published"


def test_a_migrated_workspace_arrives_with_the_first_two_done() -> None:
    assert _states(PactSetupFacts(migrated=True))[:3] == ["done", "done", "next"]


def test_a_mark_counts_only_where_nothing_else_proves_the_section() -> None:
    # Marking "pacticipants" cannot make a workspace with none look set up.
    marked = PactSetupSaved(marked=["pacticipants", "pipelines", "provider", "gates"])
    assert _states(PactSetupFacts(), marked) == ["next", "todo", "done", "todo", "done", "done"]


def test_a_recorded_key_or_a_source_finishes_its_section() -> None:
    saved = PactSetupSaved(ci_key=PactSetupCiKey(id=KEY_ID, prefix="apk_9f2c"))
    facts = PactSetupFacts(pacticipants=1, environments=["production"], pacts=1, contract_sources=1)
    sections = derive_sections(facts, saved)
    assert [section.state for section in sections] == ["done", "done", "done", "done", "done", "next"]
    assert sections[2].summary == "Key apk_9f2c"
    assert sections[4].summary == "Spec as the contract for 1 provider"


def test_many_environments_are_summed_up() -> None:
    facts = PactSetupFacts(environments=["dev", "production", "qa", "staging", "uat"])
    assert derive_sections(facts, PactSetupSaved())[1].summary == "dev, production, qa and 2 more"


# ---------------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------------

_PROJECTS = [
    {
        "id": "p-1",
        "slug": "billing-api",
        "name": "Billing API",
        "owner": "Payments team",
        "repository_id": REPO,
        "repository_branch": "release",
    },
    {
        "id": "p-2",
        "slug": "payments-api",
        "name": "Payments API",
        "owner": None,
        "repository_id": None,
        "repository_branch": None,
    },
]
_REPOSITORIES = [
    {
        "id": REPO,
        "provider": "github",
        "repository_full_name": "acme/billing-service",
        "default_branch": "main",
        "clone_url": "https://github.com/acme/billing-service.git",
    },
    {
        "id": OTHER_REPO,
        "provider": "github",
        "repository_full_name": "acme/orders-ui",
        "default_branch": "trunk",
        "clone_url": "https://github.com/acme/orders-ui.git",
    },
]


def test_projects_are_providers_and_unbound_repositories_consumers() -> None:
    found = detect_candidates(_PROJECTS, _REPOSITORIES, [])
    assert [(item.name, item.role, item.source) for item in found] == [
        ("Billing API", "provider", "project"),
        ("Payments API", "provider", "project"),
        ("orders-ui", "consumer", "repository"),
    ]
    billing, payments, orders = found
    assert billing.project == "billing-api" and billing.owner == "Payments team"
    assert billing.repository_url == "https://github.com/acme/billing-service" and billing.main_branch == "release"
    assert payments.repository_url is None and payments.owner is None and payments.main_branch is None
    assert orders.source_label == "Repository · acme/orders-ui" and orders.main_branch == "trunk"
    assert orders.repository_id == OTHER_REPO
    assert all(item.pacticipant is None for item in found)


def test_a_candidate_names_the_pacticipant_that_already_exists() -> None:
    existing = [
        # Bound to the project under another name.
        {"slug": "billing-service", "name": "Billing Service", "project_id": "p-1", "repository_url": None},
        # Same repository, written differently.
        {"slug": "orders", "name": "Orders", "project_id": None, "repository_url": "git@github.com:Acme/Orders-UI.git"},
        # Same name.
        {"slug": "payments-api", "name": "payments api", "project_id": None, "repository_url": None},
    ]
    found = {item.name: item.pacticipant for item in detect_candidates(_PROJECTS, _REPOSITORIES, existing)}
    assert found == {"Billing API": "billing-service", "orders-ui": "orders", "Payments API": "payments-api"}


def test_a_name_that_cannot_be_a_pacticipant_is_left_out() -> None:
    projects = [{"id": "p-9", "slug": "odd", "name": "two\nlines"}, {"id": "p-8", "slug": "blank", "name": "  "}]
    assert detect_candidates(projects, [], []) == []


def test_a_non_github_repository_keeps_its_http_address() -> None:
    repositories = [
        {
            "id": REPO,
            "provider": "gitlab",
            "repository_full_name": "",
            "default_branch": None,
            "clone_url": "https://gitlab.com/acme/ledger.git",
        }
    ]
    (found,) = detect_candidates([], repositories, [])
    assert found.name == "ledger" and found.repository_url == "https://gitlab.com/acme/ledger"


# ---------------------------------------------------------------------------------------------
# The workflow and the broker address
# ---------------------------------------------------------------------------------------------


def test_the_workflow_asks_and_records() -> None:
    text = workflow_text(pacticipant="Billing Service", environment="production", default_branch="trunk")
    assert 'branches: ["trunk"]' in text
    assert "PACT_BROKER_BASE_URL: ${{ secrets.PACT_BROKER_BASE_URL }}" in text
    assert text.count("uses: apiome/apiome/pact-action@main") == 2
    assert "command: can-i-deploy" in text and "command: record-deployment" in text
    assert text.count('pacticipant: "Billing Service"') == 2 and text.count('environment: "production"') == 2
    assert text.endswith("\n")
    import yaml

    parsed = yaml.safe_load(text)
    assert [step.get("with", {}).get("command") for step in parsed["jobs"]["contracts"]["steps"]] == [
        None,
        "can-i-deploy",
        "record-deployment",
    ]


def test_the_workflow_can_have_one_step_but_not_none() -> None:
    only_gate = workflow_text(pacticipant="a", environment="e", record_deployment=False)
    assert "can-i-deploy" in only_gate and "record-deployment" not in only_gate
    only_record = workflow_text(pacticipant="a", environment="e", can_i_deploy=False)
    assert "record-deployment" in only_record and "can-i-deploy" not in only_record
    with pytest.raises(ValueError, match="at least one"):
        workflow_text(pacticipant="a", environment="e", can_i_deploy=False, record_deployment=False)


def test_a_name_cannot_break_out_of_the_workflow() -> None:
    with pytest.raises(ValueError, match="pacticipant"):
        workflow_text(pacticipant="a\n  run: curl evil", environment="production")
    with pytest.raises(ValueError, match="environment"):
        workflow_text(pacticipant="a", environment="")
    import yaml

    quoted = yaml.safe_load(workflow_text(pacticipant='He said "hi": #1', environment="production"))
    assert quoted["jobs"]["contracts"]["steps"][1]["with"]["pacticipant"] == 'He said "hi": #1'


@pytest.mark.parametrize(
    "url",
    ["", "ftp://x/y", "https://user:pw@api.apiome.dev/x", "https://api.apiome.dev/x?y=1", "https://a b/c", "x" * 600],
)
def test_a_broker_address_must_be_a_plain_url(url: str) -> None:
    with pytest.raises(ValueError):
        check_broker_base_url(url)


def test_a_broker_address_loses_its_trailing_slash() -> None:
    assert check_broker_base_url(f"{BROKER}/") == BROKER


# ---------------------------------------------------------------------------------------------
# A stand-in for api.github.com
# ---------------------------------------------------------------------------------------------


class _GitHub:
    """One repository on a fake api.github.com: branches, a tree, pull requests and secrets."""

    def __init__(self) -> None:
        self.private = public.PrivateKey.generate()
        self.requests: List[httpx.Request] = []
        self.secrets: Dict[str, str] = {}
        self.branches: Dict[str, str] = {"main": "base-sha"}
        self.files: Dict[str, str] = {}
        self.pulls: List[Dict[str, Any]] = []
        self.can_push = True
        self.archived = False
        self.fail: Dict[str, Tuple[int, str]] = {}
        self.new_tree: Optional[Dict[str, Any]] = None

    def __call__(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def calls(self) -> List[str]:
        return [f"{request.method} {request.url.path}" for request in self.requests]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.split("/repos/acme/billing-service", 1)[-1]
        key = f"{request.method} {path}"
        for prefix, (status, message) in self.fail.items():
            if key.startswith(prefix):
                return httpx.Response(status, json={"message": message})
        body = json.loads(request.content) if request.content else {}
        if key == "GET ":
            return httpx.Response(
                200,
                json={
                    "full_name": "acme/billing-service",
                    "owner": {"login": "acme"},
                    "default_branch": "main",
                    "archived": self.archived,
                    "permissions": {"push": self.can_push},
                },
            )
        if key == "GET /actions/secrets/public-key":
            encoded = base64.b64encode(bytes(self.private.public_key)).decode()
            return httpx.Response(200, json={"key_id": "k-1", "key": encoded})
        if request.method == "PUT" and path.startswith("/actions/secrets/"):
            assert body["key_id"] == "k-1"
            sealed = base64.b64decode(body["encrypted_value"])
            self.secrets[path.rsplit("/", 1)[-1]] = public.SealedBox(self.private).decrypt(sealed).decode()
            return httpx.Response(201)
        if request.method == "GET" and path.startswith("/git/ref/heads/"):
            sha = self.branches.get(path.split("/git/ref/heads/", 1)[1])
            return httpx.Response(200, json={"object": {"sha": sha}}) if sha else httpx.Response(404, json={})
        if request.method == "GET" and path.startswith("/git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": "root"}})
        if request.method == "GET" and path.startswith("/git/trees/"):
            return httpx.Response(200, json={"tree": self._tree(path.rsplit("/", 1)[-1]), "truncated": False})
        if request.method == "GET" and path.startswith("/git/blobs/"):
            text = self.files[WORKFLOW_PATH]
            return httpx.Response(200, json={"size": len(text), "content": base64.b64encode(text.encode()).decode()})
        if key == "POST /git/trees":
            self.new_tree = body
            return httpx.Response(201, json={"sha": "new-tree"})
        if key == "POST /git/commits":
            return httpx.Response(201, json={"sha": "new-commit"})
        if key == "POST /git/refs":
            name = body["ref"].split("refs/heads/", 1)[1]
            if name in self.branches:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.branches[name] = body["sha"]
            return httpx.Response(201, json={})
        if request.method == "PATCH" and path.startswith("/git/refs/heads/"):
            self.branches[path.split("/git/refs/heads/", 1)[1]] = body["sha"]
            return httpx.Response(200, json={})
        if key == "GET /pulls":
            return httpx.Response(200, json=self.pulls)
        if key == "POST /pulls":
            pull = {
                "number": 7,
                "html_url": "https://github.com/acme/billing-service/pull/7",
                "title": body["title"],
                "body": body["body"],
                "base": {"ref": body["base"]},
            }
            self.pulls.append(pull)
            return httpx.Response(201, json=pull)
        return httpx.Response(500, json={"message": f"unexpected {key}"})

    def _tree(self, sha: str) -> List[Dict[str, Any]]:
        if WORKFLOW_PATH not in self.files:
            return []
        if sha == "root":
            return [{"path": ".github", "type": "tree", "sha": "t-github"}]
        if sha == "t-github":
            return [{"path": "workflows", "type": "tree", "sha": "t-workflows"}]
        return [{"path": "apiome-contracts.yml", "type": "blob", "sha": "b-1", "mode": "100644"}]


def _repository(**overrides: Any) -> Dict[str, Any]:
    row = {
        "id": REPO,
        "provider": "github",
        "clone_url": "https://github.com/acme/billing-service.git",
        "repository_full_name": "acme/billing-service",
        "default_branch": "main",
        "linked_account_id": "la-1",
        "created_by": "u-1",
    }
    row.update(overrides)
    return row


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> Iterator[Dict[str, Any]]:
    """A database that knows one repository, a linked-account token, and the fake GitHub."""
    rows: Dict[str, Dict[str, Any]] = {REPO: _repository()}
    monkeypatch.setattr(github_module, "get_repository", lambda _fetch, _tenant, repository_id: rows.get(repository_id))
    monkeypatch.setattr(github_module, "resolve_linked_account_token", lambda _db, _row: "gh-token-secret")
    yield {"rows": rows, "github": _GitHub(), "db": MagicMock()}


# ---------------------------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------------------------


def test_a_sealed_secret_opens_with_the_repository_key() -> None:
    private = public.PrivateKey.generate()
    sealed = seal_secret(base64.b64encode(bytes(private.public_key)).decode(), "s3cret")
    assert public.SealedBox(private).decrypt(base64.b64decode(sealed)) == b"s3cret"
    with pytest.raises(RuntimeError, match="public key"):
        seal_secret("not-a-key", "s3cret")


def test_both_secrets_are_sealed_and_written(github: Dict[str, Any]) -> None:
    fake = github["github"]
    results, updates = write_secrets(
        github["db"], TENANT, [REPO, REPO], broker_base_url=BROKER, token=API_KEY, client_factory=fake
    )
    assert [(item.status, item.names) for item in results] == [("written", list(SECRET_NAMES))]
    assert fake.secrets == {"PACT_BROKER_BASE_URL": BROKER, "PACT_BROKER_TOKEN": API_KEY}
    assert list(updates) == [REPO] and set(updates[REPO]) == {"secrets_at"}
    # The key is sealed on the wire and absent from everything handed back.
    assert all(API_KEY.encode() not in request.content for request in fake.requests)
    assert API_KEY not in json.dumps([item.model_dump() for item in results]) + json.dumps(updates)
    assert all(request.url.host == "api.github.com" for request in fake.requests)


@pytest.mark.parametrize(
    ("row", "token", "reason"),
    [
        (None, "t", "not registered in this workspace"),
        (_repository(provider="gitlab"), "t", "Only github.com"),
        (_repository(linked_account_id=None), "t", "without a linked GitHub account"),
        (_repository(), None, "no longer holds a token"),
    ],
)
def test_a_repository_that_cannot_be_written_is_skipped_with_the_reason(
    github: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    row: Optional[Dict[str, Any]],
    token: Optional[str],
    reason: str,
) -> None:
    github["rows"].clear()
    if row is not None:
        github["rows"][REPO] = row
    monkeypatch.setattr(github_module, "resolve_linked_account_token", lambda _db, _row: token)
    fake = github["github"]
    results, updates = write_secrets(
        github["db"], TENANT, [REPO], broker_base_url=BROKER, token=API_KEY, client_factory=fake
    )
    assert results[0].status == "skipped" and reason in (results[0].reason or "")
    assert updates == {} and fake.requests == []


def test_a_refused_secret_says_why_and_what_was_written(github: Dict[str, Any]) -> None:
    fake = github["github"]
    fake.fail["PUT /actions/secrets/PACT_BROKER_TOKEN"] = (403, f"Resource not accessible ({API_KEY})")
    results, updates = write_secrets(
        github["db"], TENANT, [REPO], broker_base_url=BROKER, token=API_KEY, client_factory=fake
    )
    (result,) = results
    assert result.status == "skipped" and result.names == ["PACT_BROKER_BASE_URL"]
    assert (
        "admin access for secrets" in (result.reason or "")
        and "Written before that: PACT_BROKER_BASE_URL" in result.reason
    )
    assert API_KEY not in result.reason and "gh-token-secret" not in result.reason
    assert updates == {}


def test_one_refusal_does_not_stop_the_other_repositories(github: Dict[str, Any]) -> None:
    fake = github["github"]
    results, updates = write_secrets(
        github["db"], TENANT, [OTHER_REPO, REPO], broker_base_url=BROKER, token=API_KEY, client_factory=fake
    )
    assert [(item.repository_id, item.status) for item in results] == [(OTHER_REPO, "skipped"), (REPO, "written")]
    assert list(updates) == [REPO]


# ---------------------------------------------------------------------------------------------
# Pull requests
# ---------------------------------------------------------------------------------------------


def _request(**overrides: Any) -> PactSetupPullRequestsRequest:
    body: Dict[str, Any] = {
        "repositories": [PactSetupPullRequestRepository(repository_id=REPO, pacticipant="Billing Service")],
        "environment": "production",
    }
    body.update(overrides)
    return PactSetupPullRequestsRequest(**body)


def test_a_pull_request_adds_the_workflow(github: Dict[str, Any]) -> None:
    fake = github["github"]
    results, updates = open_pull_requests(github["db"], TENANT, _request(), client_factory=fake)
    (result,) = results
    assert result.status == "opened" and result.number == 7 and result.path == WORKFLOW_PATH
    assert result.url == "https://github.com/acme/billing-service/pull/7"
    assert fake.branches[SETUP_BRANCH] == "new-commit"
    assert fake.new_tree == {
        "base_tree": "root",
        "tree": [{"path": WORKFLOW_PATH, "mode": "100644", "type": "blob", "content": result.content}],
    }
    assert 'pacticipant: "Billing Service"' in result.content
    assert "can-i-deploy" in fake.pulls[0]["body"] and fake.pulls[0]["base"]["ref"] == "main"
    assert updates == {REPO: {"pull_request_url": result.url, "pull_request_number": 7}}


def test_an_open_pull_request_is_found_not_duplicated(github: Dict[str, Any]) -> None:
    fake = github["github"]
    open_pull_requests(github["db"], TENANT, _request(), client_factory=fake)
    results, updates = open_pull_requests(github["db"], TENANT, _request(record_deployment=False), client_factory=fake)
    (result,) = results
    assert result.status == "exists" and result.number == 7 and "already open" in (result.reason or "")
    assert len(fake.pulls) == 1 and "POST /repos/acme/billing-service/pulls" in fake.calls()
    assert fake.calls().count("POST /repos/acme/billing-service/pulls") == 1
    # The branch was brought up to date with the new choice.
    assert "record-deployment" not in fake.new_tree["tree"][0]["content"]
    assert updates[REPO]["pull_request_number"] == 7


def test_a_workflow_already_on_the_default_branch_is_not_added_again(github: Dict[str, Any]) -> None:
    fake = github["github"]
    fake.files[WORKFLOW_PATH] = workflow_text(pacticipant="Billing Service", environment="production")
    results, updates = open_pull_requests(github["db"], TENANT, _request(), client_factory=fake)
    assert results[0].status == "skipped" and "already on main" in (results[0].reason or "")
    assert updates == {} and not any(call.startswith("POST") for call in fake.calls())


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ({"can_push": False}, "cannot push"),
        ({"archived": True}, "archived"),
        ({"branches": {}}, "no commits on main"),
        ({"fail": {"POST /git/refs": (403, "Resource not accessible")}}, "write access for a pull request"),
        ({"fail": {"GET ": (401, "Bad credentials")}}, "Re-link the GitHub account"),
        ({"fail": {"GET ": (503, "down")}}, "GitHub failed"),
    ],
)
def test_a_repository_that_refuses_is_skipped_with_the_workflow(
    github: Dict[str, Any], setup: Dict[str, Any], reason: str
) -> None:
    fake = github["github"]
    for name, value in setup.items():
        setattr(fake, name, value)
    results, updates = open_pull_requests(github["db"], TENANT, _request(), client_factory=fake)
    (result,) = results
    assert result.status == "skipped" and reason in (result.reason or "")
    assert "command: can-i-deploy" in result.content and updates == {}
    assert "gh-token-secret" not in (result.reason or "")


def test_a_preview_calls_nothing(github: Dict[str, Any]) -> None:
    fake = github["github"]
    github["rows"][REPO] = _repository(linked_account_id=None, default_branch="trunk")
    body = _request(
        preview=True,
        repositories=[
            PactSetupPullRequestRepository(repository_id=REPO, pacticipant="Billing Service"),
            PactSetupPullRequestRepository(repository_id=OTHER_REPO, pacticipant="Orders UI"),
        ],
    )
    results, updates = open_pull_requests(github["db"], TENANT, body, client_factory=fake)
    assert [(item.status, item.reason) for item in results] == [
        ("preview", None),
        ("skipped", "This repository is not registered in this workspace."),
    ]
    assert 'branches: ["trunk"]' in results[0].content and fake.requests == [] and updates == {}


def test_a_bad_name_stops_before_github_is_called(github: Dict[str, Any]) -> None:
    fake = github["github"]
    with pytest.raises(ValueError, match="at least one"):
        open_pull_requests(
            github["db"], TENANT, _request(can_i_deploy=False, record_deployment=False), client_factory=fake
        )
    bad = _request(repositories=[PactSetupPullRequestRepository(repository_id=REPO, pacticipant="a\nb")])
    with pytest.raises(ValueError, match="pacticipant"):
        open_pull_requests(github["db"], TENANT, bad, client_factory=fake)
    assert fake.requests == []


# ---------------------------------------------------------------------------------------------
# The store, without SQL
# ---------------------------------------------------------------------------------------------


class _Cursor:
    """Records statements; ``fetchone`` answers the locked row."""

    def __init__(self, row: Optional[Dict[str, Any]] = None) -> None:
        self.row = row
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.row


def _db(cursor: _Cursor) -> MagicMock:
    database = MagicMock()
    database._guarded_tx.side_effect = lambda work: work(cursor)
    return database


def test_a_save_changes_only_what_it_sends_and_audits() -> None:
    cursor = _Cursor(
        {
            "marked": ["gates"],
            "first_pact_path": "tests",
            "ci_key_id": None,
            "ci_key_prefix": None,
            "github": {REPO: {"secrets_at": "2026-11-30T10:00:00+00:00"}},
        }
    )
    database = _db(cursor)
    body = PactSetupSave(mark={"pipelines": True, "gates": False}, ci_key=PactSetupCiKey(id=KEY_ID, prefix="apk_9f2c"))
    save_progress(database, TENANT, body, actor=ACTOR)
    (_, lock_params), (_, params) = cursor.statements
    assert lock_params == (TENANT,)
    assert params[:5] == (TENANT, ["pipelines"], "tests", KEY_ID, "apk_9f2c")
    assert json.loads(params[5]) == {REPO: {"secrets_at": "2026-11-30T10:00:00+00:00"}}
    assert params[6:] == (ACTOR.user_id, "ada@example.com")
    audit = database._append_access_audit.call_args.kwargs
    assert audit["tenant_id"] == TENANT and audit["action"] == "pacts.setup.update"


def test_a_key_can_be_forgotten_but_not_both_given_and_forgotten() -> None:
    cursor = _Cursor(
        {"marked": [], "first_pact_path": None, "ci_key_id": KEY_ID, "ci_key_prefix": "apk_9f2c", "github": {}}
    )
    save_progress(_db(cursor), TENANT, PactSetupSave(forget_ci_key=True), actor=ACTOR)
    assert cursor.statements[1][1][3:5] == (None, None)
    with pytest.raises(ValueError, match="not both"):
        save_progress(
            _db(_Cursor()),
            TENANT,
            PactSetupSave(forget_ci_key=True, ci_key=PactSetupCiKey(id=KEY_ID, prefix="p")),
            actor=ACTOR,
        )
    with pytest.raises(ValueError, match="UUID"):
        save_progress(_db(_Cursor()), TENANT, PactSetupSave(ci_key=PactSetupCiKey(id="nope", prefix="p")), actor=ACTOR)


def test_a_github_action_is_recorded_per_repository_even_when_all_were_skipped() -> None:
    cursor = _Cursor(None)
    database = _db(cursor)
    record_github(
        database, TENANT, actor=ACTOR, action="pacts.setup.github.secrets", updates={}, detail={"repositories": []}
    )
    assert json.loads(cursor.statements[1][1][5]) == {}
    assert database._append_access_audit.call_args.kwargs["action"] == "pacts.setup.github.secrets"
    record_github(
        database,
        TENANT,
        actor=ACTOR,
        action="pacts.setup.github.pull_requests",
        updates={REPO: {"pull_request_url": "https://x/pull/7", "pull_request_number": 7}},
        detail={},
    )
    assert json.loads(cursor.statements[3][1][5]) == {
        REPO: {"pull_request_url": "https://x/pull/7", "pull_request_number": 7}
    }


def test_a_malformed_tenant_reads_as_an_empty_workspace() -> None:
    fetch = MagicMock()
    state = read_state(fetch, "not-a-uuid", can_edit=True)
    assert state.done == 0 and state.total == 6 and not state.complete and state.can_edit
    assert state.github.linked is False and state.github.reason
    fetch.assert_not_called()


def test_an_unknown_section_or_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        PactSetupSave(mark={"billing": True})  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        PactSetupSave(first_pact_path="mock")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PactSetupSave(done=["gates"])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def routes() -> Iterator[Dict[str, MagicMock]]:
    app.dependency_overrides[validate_authentication] = lambda: dict(_AUTH)
    state = read_state(MagicMock(), "not-a-uuid")
    with (
        patch(f"{_ROUTES}.db") as database,
        patch(f"{_ROUTES}.enforce_permission", return_value="u-1") as enforce,
        patch(f"{_ROUTES}.has_permission", return_value=True) as has,
        patch(f"{_ROUTES}.read_state", return_value=state) as read,
        patch(f"{_ROUTES}.save_progress") as save,
        patch(f"{_ROUTES}.record_github") as record,
        patch(f"{_ROUTES}.write_secrets", return_value=([], {})) as secrets,
        patch(f"{_ROUTES}.open_pull_requests", return_value=([], {})) as pulls,
    ):
        yield {
            "db": database,
            "enforce": enforce,
            "has": has,
            "read": read,
            "save": save,
            "record": record,
            "secrets": secrets,
            "pulls": pulls,
        }
    app.dependency_overrides.clear()


def _permission(mock: MagicMock) -> str:
    resource, action = mock.call_args.args[2:4]
    return f"{getattr(resource, 'value', resource)}:{getattr(action, 'value', action)}"


def test_reading_needs_view_and_uses_the_authenticated_tenant(routes: Dict[str, MagicMock]) -> None:
    response = client.get("/v1/tenants/someone-else/pact-setup")
    assert response.status_code == 200 and response.json()["total"] == 6
    assert _permission(routes["enforce"]) == "pacts:view"
    assert routes["read"].call_args.args[1] == TENANT and routes["read"].call_args.kwargs == {"can_edit": True}
    routes["has"].return_value = False
    client.get("/v1/tenants/acme/pact-setup")
    assert routes["read"].call_args.kwargs == {"can_edit": False}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "/v1/tenants/acme/pact-setup", {"mark": {"gates": True}}),
        (
            "post",
            "/v1/tenants/acme/pact-setup/github/secrets",
            {"repository_ids": [REPO], "broker_base_url": BROKER, "token": API_KEY},
        ),
        (
            "post",
            "/v1/tenants/acme/pact-setup/github/pull-requests",
            {"repositories": [{"repository_id": REPO, "pacticipant": "Billing Service"}], "environment": "production"},
        ),
    ],
)
def test_every_write_needs_the_contracts_admin_permission(
    routes: Dict[str, MagicMock], method: str, path: str, body: Dict[str, Any]
) -> None:
    assert getattr(client, method)(path, json=body).status_code == 200
    assert _permission(routes["enforce"]) == "pacts:delete"
    routes["enforce"].side_effect = HTTPException(status_code=403, detail="Permission denied")
    assert getattr(client, method)(path, json=body).status_code == 403
    for name in ("save", "secrets", "pulls", "record"):
        assert routes[name].call_count <= 1


def test_saving_passes_the_change_and_answers_the_new_state(routes: Dict[str, MagicMock]) -> None:
    response = client.put("/v1/tenants/acme/pact-setup", json={"first_pact_path": "spec"})
    assert response.status_code == 200
    assert routes["save"].call_args.args[1] == TENANT and routes["save"].call_args.args[2].first_pact_path == "spec"
    routes["save"].side_effect = ValueError("ci_key.id must be the key's id (a UUID)")
    refused = client.put("/v1/tenants/acme/pact-setup", json={"ci_key": {"id": "x", "prefix": "p"}})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "pact-setup-invalid"
    assert client.put("/v1/tenants/acme/pact-setup", json={"marked": ["gates"]}).status_code == 422


def test_secrets_check_the_address_and_record_outcomes_without_the_key(routes: Dict[str, MagicMock]) -> None:
    body = {"repository_ids": [REPO], "broker_base_url": f"{BROKER}/", "token": API_KEY}
    assert client.post("/v1/tenants/acme/pact-setup/github/secrets", json=body).status_code == 200
    assert routes["secrets"].call_args.kwargs == {"broker_base_url": BROKER, "token": API_KEY}
    recorded = routes["record"].call_args.kwargs
    assert recorded["action"] == "pacts.setup.github.secrets" and API_KEY not in json.dumps(recorded["detail"])
    bad = client.post("/v1/tenants/acme/pact-setup/github/secrets", json={**body, "broker_base_url": "ftp://x"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "pact-setup-invalid-broker-url"
    assert (
        client.post("/v1/tenants/acme/pact-setup/github/secrets", json={**body, "repository_ids": []}).status_code
        == 422
    )
    assert routes["secrets"].call_count == 1


def test_a_preview_is_not_recorded_and_a_bad_workflow_is_a_422(routes: Dict[str, MagicMock]) -> None:
    body = {"repositories": [{"repository_id": REPO, "pacticipant": "Billing Service"}], "environment": "production"}
    path = "/v1/tenants/acme/pact-setup/github/pull-requests"
    assert client.post(path, json={**body, "preview": True}).status_code == 200
    routes["record"].assert_not_called()
    assert client.post(path, json=body).status_code == 200
    assert routes["record"].call_args.kwargs["action"] == "pacts.setup.github.pull_requests"
    routes["pulls"].side_effect = ValueError("choose at least one of can-i-deploy and record-deployment")
    refused = client.post(path, json={**body, "can_i_deploy": False, "record_deployment": False})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "pact-setup-invalid-workflow"
