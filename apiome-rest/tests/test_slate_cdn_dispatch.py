"""Sending purges to a lane's CDN — Slate 10.2 (private-suite#120).

:mod:`app.slate_cdn_dispatch` against ``httpx.MockTransport``; no socket is ever opened. Asserted:

* **Every provider failure is an outcome, never an exception** — a deploy has already committed by
  the time a purge is sent, and the operator needs the reason, not a 500.
* **The credential never leaves its header**, even when a provider echoes it back in an error.
* **A custom endpoint on a private address is refused before the credential is sent.**
* **The deploy hook purges the changed pages of both releases, and logs what happened.**
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List
from unittest.mock import patch

import httpx
import pytest

from app import slate_cdn_dispatch
from app.slate_cdn import plan_cdn_purge
from app.slate_cdn_dispatch import CdnPurgeOutcome, dispatch_deploy_purge, send_purge
from app.ssrf_guard import build_guarded_async_client

SECRET = "tok_super_secret_value"
ZONE = "0123456789abcdef0123456789abcdef"

PROVIDER_ROW: Dict[str, Any] = {
    "provider": "cloudflare",
    "target": ZONE,
    "auth_header_name": None,
    "credential_ciphertext": b"sealed",
    "credential_key_version": 1,
    "purge_on_deploy": True,
}


@pytest.fixture(autouse=True)
def _vault():
    """Open every sealed credential to SECRET; the vault itself is tested in the store suite."""
    with patch("app.slate_cdn_dispatch.unseal_cdn_credential", return_value=SECRET) as unseal:
        yield unseal


def factory(handler: Callable[[httpx.Request], httpx.Response], seen: List[httpx.Request]):
    """A client factory whose transport records each request and answers with ``handler``."""

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))


def plan(provider: str = "cloudflare", paths=("/a", "/b")):
    """A small purge plan for one verified host."""
    return plan_cdn_purge(
        provider=provider, hosts=["docs.example.com"], paths=list(paths), purge_all_if_empty=False
    )


class TestSendPurge:
    async def test_a_cloudflare_purge_succeeds_and_counts_its_urls(self) -> None:
        seen: List[httpx.Request] = []
        outcome = await send_purge(
            PROVIDER_ROW,
            plan(),
            context={},
            client_factory=factory(lambda r: httpx.Response(200, json={"success": True}), seen),
        )
        assert outcome.status == "succeeded"
        assert outcome.url_count == 2
        assert outcome.requests_sent == 1
        assert outcome.sentence == "2 URLs purged at Cloudflare."
        assert seen[0].headers["Authorization"] == f"Bearer {SECRET}"
        assert str(seen[0].url) == f"https://api.cloudflare.com/client/v4/zones/{ZONE}/purge_cache"

    @pytest.mark.parametrize(
        "status, code", [(401, "cdn-auth-rejected"), (429, "cdn-rate-limited"), (503, "cdn-provider-error")]
    )
    async def test_a_provider_refusal_is_an_outcome(self, status: int, code: str) -> None:
        outcome = await send_purge(
            PROVIDER_ROW,
            plan(),
            context={},
            client_factory=factory(lambda r: httpx.Response(status, json={}), []),
        )
        assert outcome.status == "failed"
        assert outcome.error_code == code
        assert outcome.http_status == status

    async def test_an_echoed_credential_is_redacted(self) -> None:
        outcome = await send_purge(
            PROVIDER_ROW,
            plan(),
            context={},
            client_factory=factory(
                lambda r: httpx.Response(
                    400, json={"errors": [{"message": f"token {SECRET} is not valid"}]}
                ),
                [],
            ),
        )
        assert outcome.error_message == "token [redacted] is not valid"

    async def test_the_first_failure_stops_the_batch(self) -> None:
        seen: List[httpx.Request] = []
        outcome = await send_purge(
            {**PROVIDER_ROW, "provider": "fastly", "target": "svc1"},
            plan("fastly", paths=("/a", "/b", "/c")),
            context={},
            client_factory=factory(lambda r: httpx.Response(401), seen),
        )
        assert len(seen) == 1
        assert outcome.requests_sent == 1
        assert outcome.status == "failed"

    async def test_an_unreachable_cdn_is_an_outcome(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        outcome = await send_purge(
            PROVIDER_ROW, plan(), context={}, client_factory=factory(boom, [])
        )
        assert outcome.error_code == "cdn-unreachable"

    async def test_a_slow_cdn_times_out(self, monkeypatch) -> None:
        monkeypatch.setattr(slate_cdn_dispatch, "DEADLINE_SECONDS", 0.05)

        async def slow(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1)
            return httpx.Response(200)

        outcome = await send_purge(
            PROVIDER_ROW,
            plan(),
            context={},
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow)),
        )
        assert outcome.error_code == "cdn-timeout"

    async def test_a_custom_endpoint_on_a_private_address_is_refused(self) -> None:
        seen: List[httpx.Request] = []
        outcome = await send_purge(
            {
                **PROVIDER_ROW,
                "provider": "custom",
                "target": "https://127.0.0.1/purge",
                "auth_header_name": "X-Token",
            },
            plan("custom"),
            context={},
            client_factory=lambda: build_guarded_async_client(
                transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200))
            ),
        )
        assert outcome.error_code == "cdn-target-refused"
        assert seen == []

    async def test_an_unopenable_credential_fails_without_sending(self, _vault) -> None:
        _vault.return_value = None
        seen: List[httpx.Request] = []
        outcome = await send_purge(
            PROVIDER_ROW, plan(), context={}, client_factory=factory(lambda r: httpx.Response(200), seen)
        )
        assert outcome.status == "failed"
        assert outcome.error_code == "cdn-credential-unavailable"
        assert seen == []

    async def test_a_skipped_plan_sends_nothing(self) -> None:
        empty = plan_cdn_purge(provider="cloudflare", hosts=[], paths=["/a"], purge_all_if_empty=True)
        outcome = await send_purge(
            PROVIDER_ROW, empty, context={}, client_factory=factory(lambda r: httpx.Response(200), [])
        )
        assert outcome.status == "skipped"
        assert outcome.error_code == "cdn-no-hosts"


class TestDeployPurge:
    async def run(self, *, provider_row=PROVIDER_ROW, handler=None, routes=None, hosts=None):
        seen: List[httpx.Request] = []
        routes = routes if routes is not None else {"rel-1": ["/a"], "rel-0": ["/b"]}
        with patch("app.slate_cdn_dispatch.get_provider", return_value=provider_row), \
             patch(
                 "app.slate_cdn_dispatch.routes_for_release",
                 side_effect=lambda db, release_id: routes.get(release_id, []),
             ), \
             patch(
                 "app.slate_cdn_dispatch.verified_hosts",
                 return_value=hosts if hosts is not None else ["docs.example.com"],
             ), \
             patch("app.slate_cdn_dispatch.record_dispatch", return_value={"id": "d-1"}) as recorded:
            outcome = await dispatch_deploy_purge(
                object(),
                tenant_id="t1",
                environment_id="env-1",
                release_id="rel-1",
                replaced_release_id="rel-0",
                actor_id="user-1",
                actor_name="ken@example.com",
                client_factory=factory(
                    handler or (lambda r: httpx.Response(200, json={"success": True})), seen
                ),
            )
        return outcome, recorded, seen

    async def test_the_changed_pages_of_both_releases_are_purged_and_logged(self) -> None:
        outcome, recorded, seen = await self.run()
        assert outcome is not None and outcome.status == "succeeded"
        assert outcome.dispatch_id == "d-1"
        assert json.loads(seen[0].content)["files"] == [
            "https://docs.example.com/a",
            "https://docs.example.com/b",
        ]
        kwargs = recorded.call_args.kwargs
        assert kwargs["trigger"] == "deploy"
        assert kwargs["release_id"] == "rel-1"
        assert kwargs["status"] == "succeeded"

    async def test_a_release_with_no_changed_page_record_purges_everything(self) -> None:
        outcome, _, seen = await self.run(routes={})
        assert outcome is not None and outcome.mode == "purge-all"
        assert json.loads(seen[0].content) == {"purge_everything": True}

    async def test_a_lane_without_a_cdn_does_nothing(self) -> None:
        outcome, recorded, seen = await self.run(provider_row=None)
        assert outcome is None
        recorded.assert_not_called()
        assert seen == []

    async def test_purge_on_deploy_off_is_skipped_and_not_logged(self) -> None:
        outcome, recorded, seen = await self.run(
            provider_row={**PROVIDER_ROW, "purge_on_deploy": False}
        )
        assert outcome is not None and outcome.error_code == "cdn-purge-on-deploy-off"
        recorded.assert_not_called()
        assert seen == []

    async def test_a_failure_is_logged_with_its_code(self) -> None:
        outcome, recorded, _ = await self.run(handler=lambda r: httpx.Response(403))
        assert outcome is not None and outcome.error_code == "cdn-auth-rejected"
        assert recorded.call_args.kwargs["error_code"] == "cdn-auth-rejected"

    async def test_an_unexpected_error_never_raises(self) -> None:
        with patch("app.slate_cdn_dispatch.plan_cdn_purge", side_effect=RuntimeError("bug")):
            outcome, recorded, _ = await self.run()
        assert isinstance(outcome, CdnPurgeOutcome)
        assert outcome.error_code == "cdn-dispatch-error"
        assert recorded.call_args.kwargs["status"] == "failed"

    async def test_an_unreadable_provider_row_never_raises(self) -> None:
        with patch("app.slate_cdn_dispatch.get_provider", side_effect=RuntimeError("db down")):
            outcome = await dispatch_deploy_purge(
                object(),
                tenant_id="t1",
                environment_id="env-1",
                release_id="rel-1",
                replaced_release_id=None,
                actor_id=None,
                actor_name="bot",
                client_factory=factory(lambda r: httpx.Response(200), []),
            )
        assert outcome is None
