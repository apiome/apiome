"""CDN / edge provider decisions — Slate 10.2 (private-suite#120).

Pure tests over :mod:`app.slate_cdn`: what a valid configuration is, what a purge sends, and how
a provider's answer is read. Three properties get the most attention, because each fails quietly:

* **The credential appears in one header and nowhere else.** Not in a URL, not in a body, not in
  an error message.
* **Vendor endpoints are constants.** No configuration value can move a Cloudflare token to
  another host.
* **A scope too large to list purges everything, and says so** — never a silent partial purge.
"""

from __future__ import annotations

import json

import pytest

from app.slate_cdn import (
    CLOUDFLARE_API,
    CLOUDFLARE_BATCH,
    CODE_CREDENTIAL_REQUIRED,
    CODE_INVALID,
    FASTLY_API,
    SAMPLE_LIMIT,
    URL_CAPS,
    CdnConfigError,
    build_requests,
    classify_response,
    error_sentence,
    normalize_config,
    plan_cdn_purge,
    purge_urls,
    redact,
)

ZONE = "0123456789abcdef0123456789abcdef"
SECRET = "tok_super_secret_value"


def config(**overrides):
    """Normalize a configuration with valid Cloudflare defaults."""
    base = {
        "provider": "cloudflare",
        "target": ZONE,
        "auth_header_name": None,
        "credential": SECRET,
        "existing_provider": None,
    }
    base.update(overrides)
    return normalize_config(**base)


class TestNormalizeConfig:
    def test_a_cloudflare_zone_is_lowercased_and_accepted(self) -> None:
        normalized = config(target=f"  {ZONE.upper()} ")
        assert normalized.provider == "cloudflare"
        assert normalized.target == ZONE
        assert normalized.auth_header_name is None
        assert normalized.credential == SECRET

    def test_a_malformed_zone_id_is_refused_with_a_field_message(self) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(target="example.com")
        assert caught.value.code == CODE_INVALID
        assert "32-character" in caught.value.errors[0]

    def test_a_fastly_service_id_is_accepted(self) -> None:
        normalized = config(provider="Fastly", target="SU1Z0isxPaozGVKXdv0eY")
        assert normalized.provider == "fastly"
        assert normalized.target == "SU1Z0isxPaozGVKXdv0eY"

    def test_a_fastly_service_id_with_punctuation_is_refused(self) -> None:
        with pytest.raises(CdnConfigError):
            config(provider="fastly", target="svc/../purge_all")

    def test_a_custom_endpoint_needs_https_and_a_header(self) -> None:
        normalized = config(
            provider="custom",
            target="https://purge.example.com/hooks/cdn",
            auth_header_name="X-Purge-Token",
        )
        assert normalized.target == "https://purge.example.com/hooks/cdn"
        assert normalized.auth_header_name == "X-Purge-Token"

    @pytest.mark.parametrize(
        "url, fragment",
        [
            ("http://purge.example.com", "https://"),
            ("https://user:pw@purge.example.com", "user name or password"),
            ("https://purge.example.com/#x", "fragment"),
            ("", "required"),
        ],
    )
    def test_an_unsafe_custom_url_is_refused(self, url: str, fragment: str) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(provider="custom", target=url, auth_header_name="X-Token")
        assert any(fragment in error for error in caught.value.errors)

    @pytest.mark.parametrize("header", ["Host", "content-type", "Cookie", "X Token", ""])
    def test_a_custom_header_must_be_a_settable_token(self, header: str) -> None:
        with pytest.raises(CdnConfigError):
            config(provider="custom", target="https://purge.example.com", auth_header_name=header)

    def test_every_bad_field_is_reported_at_once(self) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(
                provider="custom",
                target="http://x",
                auth_header_name="Host",
                credential="a\nb",
            )
        assert len(caught.value.errors) == 3

    def test_an_unknown_provider_is_refused(self) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(provider="akamai")
        assert caught.value.code == CODE_INVALID

    def test_a_credential_with_a_line_break_is_refused(self) -> None:
        # A CR/LF in a header value is header injection.
        with pytest.raises(CdnConfigError):
            config(credential="token\r\nX-Evil: 1")

    def test_an_oversized_credential_is_refused(self) -> None:
        with pytest.raises(CdnConfigError):
            config(credential="x" * 5000)

    def test_a_first_save_requires_a_credential(self) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(credential="  ")
        assert caught.value.code == CODE_CREDENTIAL_REQUIRED

    def test_an_update_for_the_same_provider_may_keep_the_credential(self) -> None:
        normalized = config(credential="", existing_provider="cloudflare")
        assert normalized.credential is None

    def test_switching_provider_requires_a_new_credential(self) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(provider="fastly", target="abc123", credential="", existing_provider="cloudflare")
        assert caught.value.code == CODE_CREDENTIAL_REQUIRED
        assert "new provider" in caught.value.errors[0]

    def test_no_error_message_quotes_the_credential(self) -> None:
        with pytest.raises(CdnConfigError) as caught:
            config(target="bad", credential=SECRET + "\n")
        assert SECRET not in str(caught.value)


class TestPlanCdnPurge:
    def test_urls_join_every_verified_host_with_every_path(self) -> None:
        assert purge_urls(["docs.example.com", "Docs.Example.com."], ["/a", "b"]) == [
            "https://docs.example.com/a",
            "https://docs.example.com/b",
        ]

    def test_a_lane_without_verified_hosts_is_skipped(self) -> None:
        plan = plan_cdn_purge(provider="cloudflare", hosts=[], paths=["/a"], purge_all_if_empty=True)
        assert plan.skipped_code == "cdn-no-hosts"

    def test_a_small_scope_is_purged_by_url(self) -> None:
        plan = plan_cdn_purge(
            provider="cloudflare", hosts=["d.example.com"], paths=["/a", "/b"], purge_all_if_empty=False
        )
        assert plan.mode == "urls"
        assert plan.url_count == 2
        assert plan.urls == ("https://d.example.com/a", "https://d.example.com/b")

    @pytest.mark.parametrize("provider", ["cloudflare", "fastly", "custom"])
    def test_a_scope_over_the_cap_purges_everything_and_counts_what_it_covered(
        self, provider: str
    ) -> None:
        paths = [f"/p{index}" for index in range(URL_CAPS[provider] + 1)]
        plan = plan_cdn_purge(
            provider=provider, hosts=["d.example.com"], paths=paths, purge_all_if_empty=False
        )
        assert plan.mode == "purge-all"
        assert plan.url_count == len(paths)
        assert plan.urls == ()
        assert len(plan.sample_urls) == SAMPLE_LIMIT

    def test_a_deploy_with_no_changed_page_record_purges_everything(self) -> None:
        plan = plan_cdn_purge(
            provider="fastly", hosts=["d.example.com"], paths=[], purge_all_if_empty=True
        )
        assert plan.mode == "purge-all"
        assert plan.skipped_code is None

    def test_a_manual_purge_with_nothing_in_scope_is_skipped(self) -> None:
        plan = plan_cdn_purge(
            provider="fastly", hosts=["d.example.com"], paths=[], purge_all_if_empty=False
        )
        assert plan.skipped_code == "cdn-nothing-to-purge"


def plan_for(provider: str, count: int, *, mode_all: bool = False):
    """A plan over ``count`` paths, or purge-all."""
    paths = [] if mode_all else [f"/p{index}" for index in range(count)]
    return plan_cdn_purge(
        provider=provider, hosts=["d.example.com"], paths=paths, purge_all_if_empty=True
    )


class TestBuildRequests:
    def test_cloudflare_batches_files_under_bearer_auth(self) -> None:
        requests = build_requests(
            plan_for("cloudflare", CLOUDFLARE_BATCH + 1),
            target=ZONE,
            auth_header_name=None,
            secret=SECRET,
            context={},
        )
        assert len(requests) == 2
        assert all(r.url == f"{CLOUDFLARE_API}/zones/{ZONE}/purge_cache" for r in requests)
        assert requests[0].headers == {"Authorization": f"Bearer {SECRET}"}
        assert len(requests[0].json["files"]) == CLOUDFLARE_BATCH
        assert len(requests[1].json["files"]) == 1

    def test_cloudflare_purge_all_purges_everything(self) -> None:
        (request,) = build_requests(
            plan_for("cloudflare", 0, mode_all=True),
            target=ZONE,
            auth_header_name=None,
            secret=SECRET,
            context={},
        )
        assert request.json == {"purge_everything": True}

    def test_fastly_purges_each_url_without_its_scheme(self) -> None:
        requests = build_requests(
            plan_for("fastly", 2), target="svc1", auth_header_name=None, secret=SECRET, context={}
        )
        assert [r.url for r in requests] == [
            f"{FASTLY_API}/purge/d.example.com/p0",
            f"{FASTLY_API}/purge/d.example.com/p1",
        ]
        assert requests[0].headers["Fastly-Key"] == SECRET

    def test_fastly_purge_all_targets_the_service(self) -> None:
        (request,) = build_requests(
            plan_for("fastly", 0, mode_all=True),
            target="svc1",
            auth_header_name=None,
            secret=SECRET,
            context={},
        )
        assert request.url == f"{FASTLY_API}/service/svc1/purge_all"

    def test_a_custom_endpoint_receives_one_call_with_context(self) -> None:
        (request,) = build_requests(
            plan_for("custom", 2),
            target="https://purge.example.com/hook",
            auth_header_name="X-Purge-Token",
            secret=SECRET,
            context={"trigger": "deploy", "releaseId": "rel-1", "environmentId": None},
        )
        assert request.url == "https://purge.example.com/hook"
        assert request.headers == {"X-Purge-Token": SECRET}
        assert request.json["urls"] == ["https://d.example.com/p0", "https://d.example.com/p1"]
        assert request.json["purgeAll"] is False
        assert request.json["trigger"] == "deploy"
        assert "environmentId" not in request.json

    @pytest.mark.parametrize("provider", ["cloudflare", "fastly", "custom"])
    def test_the_secret_is_only_ever_in_a_header(self, provider: str) -> None:
        requests = build_requests(
            plan_for(provider, 3),
            target=ZONE if provider == "cloudflare" else (
                "svc1" if provider == "fastly" else "https://purge.example.com"
            ),
            auth_header_name="X-Token" if provider == "custom" else None,
            secret=SECRET,
            context={"trigger": "manual"},
        )
        for request in requests:
            assert SECRET not in request.url
            assert SECRET not in json.dumps(request.json or {})
            assert SECRET not in repr(request)

    def test_a_skipped_plan_sends_nothing(self) -> None:
        plan = plan_cdn_purge(provider="cloudflare", hosts=[], paths=["/a"], purge_all_if_empty=True)
        assert build_requests(plan, target=ZONE, auth_header_name=None, secret=SECRET, context={}) == []


class TestClassifyResponse:
    @pytest.mark.parametrize(
        "status, code",
        [(401, "cdn-auth-rejected"), (403, "cdn-auth-rejected"), (429, "cdn-rate-limited"),
         (400, "cdn-rejected"), (404, "cdn-rejected"), (502, "cdn-provider-error")],
    )
    def test_statuses_map_to_codes(self, status: int, code: str) -> None:
        verdict = classify_response("fastly", status, None)
        assert verdict is not None and verdict[0] == code

    def test_a_success_is_none(self) -> None:
        assert classify_response("fastly", 200, {"status": "ok"}) is None
        assert classify_response("cloudflare", 200, {"success": True}) is None

    def test_cloudflare_success_false_is_a_rejection_with_its_message(self) -> None:
        verdict = classify_response(
            "cloudflare", 200, {"success": False, "errors": [{"message": "Invalid zone"}]}
        )
        assert verdict == ("cdn-rejected", "Invalid zone")


class TestRedactAndSentences:
    def test_redact_removes_the_secret_and_bounds_length(self) -> None:
        assert redact(f"bad token {SECRET}", SECRET) == "bad token [redacted]"
        assert len(redact("x" * 1000, SECRET) or "") == 300
        assert redact(None, SECRET) is None

    def test_every_error_code_has_a_sentence(self) -> None:
        for code in (
            "cdn-auth-rejected",
            "cdn-rate-limited",
            "cdn-rejected",
            "cdn-provider-error",
            "cdn-unreachable",
            "cdn-timeout",
            "cdn-target-refused",
            "cdn-credential-unavailable",
            "cdn-no-hosts",
            "cdn-nothing-to-purge",
            "cdn-dispatch-error",
        ):
            assert error_sentence(code) != code
        assert error_sentence(None) is None
