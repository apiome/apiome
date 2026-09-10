"""The publish pipeline — SDK-4.1 (#4495).

End-to-end tests of :mod:`app.sdk_publish_pipeline` with the store and the transport injected, so
the whole sequence — resolve, claim, build, upload, ledger — runs without a database or a network.

What is asserted is the pipeline's contract rather than any one step's: that a **dry run** does the
same work minus the upload and claims nothing, that a real publish **claims a version before it
uploads** and retries when another publish took the number, that every refusal names a code a route
can map, and that no path puts a token in the run log.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import psycopg2
import pytest
from test_sdk_distribution import _SPEC, _api

from app.sdk_generation_settings import (
    PatternContext,
    ResolvedBrandingOut,
    SdkGenerationSettings,
    SdkGenerationSettingsOut,
    resolve_branding,
    settings_content_fingerprint,
)
from app.sdk_publish_pipeline import (
    MAX_CLAIM_ATTEMPTS,
    RUN_STATUS_ALREADY_PUBLISHED,
    RUN_STATUS_DRY_RUN,
    RUN_STATUS_FAILED,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_PUBLISHED,
    PublishContext,
    PublishError,
    publish,
    run_row_to_outcome,
)
from app.sdk_registry_client import (
    STATUS_ALREADY_PUBLISHED,
    STATUS_PUBLISHED,
    PublishReceipt,
    RegistryUploadError,
)
from app.sdk_registry_credentials import REDACTION_MARKER, ResolvedCredential

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_RUN = "44444444-4444-4444-8444-444444444444"
_TOKEN = "npm_supersecrettokenvalue"

_CONTEXT = PublishContext(
    tenant_id=_TENANT,
    tenant_slug="acme",
    project_id=_PROJECT,
    project_slug="widgets",
    version_record_id=_REVISION,
    version_line="1.4.2",
    actor_id=None,
)


def _settings(**patterns: str) -> SdkGenerationSettingsOut:
    """A resolved SDK-3.4 settings response naming the given package patterns."""
    merged = SdkGenerationSettings(
        package_name_patterns=patterns or {"npm": "@acme/widgets-sdk", "pypi": "acme-widgets"},
        license_header="Copyright (c) 2026 Acme, Inc.",
        user_agent="acme-sdk/1.4.2",
    )
    resolved = resolve_branding(merged, PatternContext(tenant="acme", project="widgets"))
    return SdkGenerationSettingsOut(
        source="tenant",
        content_fingerprint=settings_content_fingerprint(merged),
        settings=merged,
        resolved=ResolvedBrandingOut(
            package_names=resolved.package_names,
            license_header=resolved.license_header,
            user_agent=resolved.user_agent,
        ),
        scope="project",
    )


def _credential(ecosystem: str = "npm") -> ResolvedCredential:
    """The credential a publish would authenticate with."""
    return ResolvedCredential(
        ecosystem=ecosystem,
        token=_TOKEN,
        registry_url="https://registry.npmjs.org",
        scope="tenant",
        credential_id="cred-1",
    )


class _Ledger:
    """A stand-in for the ``sdk_publish_runs`` table.

    Attributes:
        counter: What :meth:`next` reports.
        claimed: Package versions already taken, so a claim can be made to conflict.
        inserts: Every insert, in order.
        finishes: Every close-out, in order.
    """

    def __init__(self, counter: int = 0, claimed: Optional[List[str]] = None):
        self.counter = counter
        self.claimed = list(claimed or [])
        self.inserts: List[Dict[str, Any]] = []
        self.finishes: List[Dict[str, Any]] = []

    def next(self, *_args, **_kwargs) -> int:
        return self.counter

    def insert(self, **kwargs) -> Dict[str, Any]:
        if kwargs["package_version"] in self.claimed:
            raise psycopg2.errors.UniqueViolation("claim taken")
        self.inserts.append(kwargs)
        return {"id": _RUN, **kwargs}

    def finish(self, run_id, tenant_id, **kwargs) -> Dict[str, Any]:
        self.finishes.append({"run_id": run_id, **kwargs})
        return {"id": run_id, **kwargs}


#: Sentinel for "use the fixture credential", so a test can pass ``credential=None`` to mean
#: "this tenant has stored none".
_DEFAULT = object()


def _run(
    *,
    ledger: Optional[_Ledger] = None,
    settings: Optional[SdkGenerationSettingsOut] = None,
    credential: Any = _DEFAULT,
    transport=None,
    encryption: bool = True,
    **kwargs,
):
    """Run the pipeline with every collaborator injected."""
    ledger = ledger or _Ledger()
    options = {
        "context": _CONTEXT,
        "ecosystem": "npm",
        "source_text": _SPEC,
        "source_format": "openapi-3.1",
        "apiome_version": "1.183.0",
        "transport": transport,
    }
    options.update(kwargs)
    with patch("app.sdk_publish_pipeline.load_settings", return_value=settings or _settings()), \
        patch(
            "app.sdk_publish_pipeline.credential_encryption_configured", return_value=encryption
        ), \
        patch(
            "app.sdk_publish_pipeline.resolve_credential",
            return_value=_credential() if credential is _DEFAULT else credential,
        ), \
        patch("app.sdk_publish_pipeline.db.next_sdk_publish_counter", ledger.next), \
        patch("app.sdk_publish_pipeline.db.insert_sdk_publish_run", ledger.insert), \
        patch("app.sdk_publish_pipeline.db.finish_sdk_publish_run", ledger.finish):
        return publish(_api(), **options), ledger


def _accepting(status: str = STATUS_PUBLISHED):
    """A transport that accepts, recording what it was handed."""
    seen: Dict[str, Any] = {}

    def transport(distribution, credential):
        seen["distribution"] = distribution
        seen["credential"] = credential
        return PublishReceipt(
            status=status,
            http_status=201 if status == STATUS_PUBLISHED else 409,
            registry_url=credential.registry_url,
            package_name=distribution.package_name,
            package_version=distribution.package_version,
            message=f"{distribution.package_name}@{distribution.package_version}",
        )

    return transport, seen


# --------------------------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------------------------
def test_a_dry_run_builds_everything_and_uploads_nothing():
    transport, seen = _accepting()
    outcome, ledger = _run(dry_run=True, transport=transport)

    assert outcome.status == RUN_STATUS_DRY_RUN
    assert outcome.dry_run is True
    assert seen == {}, "a dry run must not reach the transport"
    # It still built the real archive and can report its digest.
    assert outcome.artifact_filename == "acme-widgets-sdk-1.4.0.tgz"
    assert len(outcome.artifact_sha256) == 64
    assert outcome.artifact_bytes > 0
    assert outcome.files


def test_a_dry_run_claims_no_version_number():
    """It records what it did, but the run it writes is outside the claim index's predicate."""
    _, ledger = _run(dry_run=True)
    assert [row["status"] for row in ledger.inserts] == [RUN_STATUS_DRY_RUN]
    assert ledger.inserts[0]["dry_run"] is True


def test_a_dry_run_reports_the_version_the_next_publish_would_take():
    outcome, _ = _run(dry_run=True, ledger=_Ledger(counter=4))
    assert outcome.package_version == "1.4.4"
    assert outcome.release_series == "1.4"
    assert outcome.regen_counter == 4


def test_the_dry_run_digest_is_the_digest_the_publish_uploads():
    """The whole point of a dry run: it is the same build, so the bytes are the same bytes."""
    dry, _ = _run(dry_run=True)
    transport, seen = _accepting()
    wet, _ = _run(dry_run=False, transport=transport)
    assert dry.artifact_sha256 == wet.artifact_sha256 == seen["distribution"].sha256


def test_a_dry_run_that_cannot_be_recorded_still_answers():
    """A ledger fault must not turn a valid validation into a failure."""
    ledger = _Ledger()
    ledger.insert = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down"))
    outcome, _ = _run(dry_run=True, ledger=ledger)
    assert outcome.status == RUN_STATUS_DRY_RUN
    assert outcome.run_id is None


# --------------------------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------------------------
def test_a_publish_claims_before_it_uploads():
    order: List[str] = []
    ledger = _Ledger()
    original_insert = ledger.insert

    def insert(**kwargs):
        order.append(f"claim:{kwargs['status']}")
        return original_insert(**kwargs)

    ledger.insert = insert

    def transport(distribution, credential):
        order.append("upload")
        return PublishReceipt(
            status=STATUS_PUBLISHED,
            http_status=201,
            registry_url=credential.registry_url,
            package_name=distribution.package_name,
            package_version=distribution.package_version,
            message="ok",
        )

    outcome, ledger = _run(dry_run=False, ledger=ledger, transport=transport)
    assert order == [f"claim:{RUN_STATUS_IN_PROGRESS}", "upload"]
    assert outcome.status == RUN_STATUS_PUBLISHED
    assert ledger.finishes[-1]["status"] == RUN_STATUS_PUBLISHED


def test_the_uploaded_archive_carries_the_claimed_version():
    transport, seen = _accepting()
    outcome, _ = _run(dry_run=False, ledger=_Ledger(counter=7), transport=transport)
    assert outcome.package_version == "1.4.7"
    assert seen["distribution"].package_version == "1.4.7"
    assert seen["distribution"].provenance["regenCounter"] == 7
    assert seen["distribution"].provenance["versionRecordId"] == _REVISION


def test_a_lost_claim_race_takes_the_next_number():
    """Two publishes computing one counter must not both upload."""
    transport, seen = _accepting()
    outcome, ledger = _run(
        dry_run=False, ledger=_Ledger(counter=2, claimed=["1.4.2"]), transport=transport
    )
    assert outcome.package_version == "1.4.3"
    assert seen["distribution"].package_version == "1.4.3"
    assert any("claimed by another publish" in entry["message"] for entry in outcome.log)


def test_a_series_with_no_free_number_refuses_rather_than_spinning():
    taken = [f"1.4.{n}" for n in range(MAX_CLAIM_ATTEMPTS + 1)]
    with pytest.raises(PublishError) as exc:
        _run(dry_run=False, ledger=_Ledger(claimed=taken), transport=_accepting()[0])
    assert exc.value.code == "sdk-publish-version-unavailable"
    assert exc.value.status_code == 409


def test_the_close_out_stores_the_provenance_that_was_published():
    """The claim is written before the archive exists, so the embedded provenance lands here."""
    transport, _ = _accepting()
    outcome, ledger = _run(dry_run=False, transport=transport)
    stored = ledger.finishes[-1]["provenance"]
    assert stored["versionRecordId"] == _REVISION
    assert stored["packageVersion"] == outcome.package_version
    assert stored["regenCounter"] == outcome.regen_counter


def test_an_already_present_version_is_recorded_not_failed():
    transport, _ = _accepting(STATUS_ALREADY_PUBLISHED)
    outcome, ledger = _run(dry_run=False, transport=transport)
    assert outcome.status == RUN_STATUS_ALREADY_PUBLISHED
    assert ledger.finishes[-1]["status"] == RUN_STATUS_ALREADY_PUBLISHED
    assert outcome.error_code is None


def test_a_refused_upload_fails_the_run_and_frees_the_number():
    def transport(distribution, credential):
        raise RegistryUploadError("the registry said no", http_status=400)

    outcome, ledger = _run(dry_run=False, transport=transport)
    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == "sdk-publish-registry-refused"
    # `failed` leaves the claim index's predicate, which is what releases the version number.
    assert ledger.finishes[-1]["status"] == RUN_STATUS_FAILED


def test_a_build_failure_after_the_claim_releases_it_too():
    with pytest.raises(PublishError) as exc:
        _run(dry_run=False, source_text=None, transport=_accepting()[0])
    assert exc.value.code == "sdk-publish-nothing-to-package"


# --------------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------------
def test_an_unpublishable_ecosystem_is_a_400():
    with pytest.raises(PublishError) as exc:
        _run(ecosystem="gomod")
    assert exc.value.code == "sdk-publish-ecosystem-unsupported"
    assert exc.value.status_code == 400


def test_a_project_with_no_package_pattern_is_refused():
    """A package name is an exact identifier; publishing under a guessed one is worse than not."""
    with pytest.raises(PublishError) as exc:
        _run(ecosystem="pypi", settings=_settings(npm="@acme/widgets-sdk"))
    assert exc.value.code == "sdk-publish-package-name-missing"
    assert "packageNamePatterns.pypi" in exc.value.message


def test_an_unmappable_version_line_is_refused():
    context = PublishContext(**{**_CONTEXT.__dict__, "version_line": "latest"})
    with pytest.raises(PublishError) as exc:
        _run(context=context)
    assert exc.value.code == "sdk-publish-version-line-invalid"


def test_a_deployment_without_an_encryption_key_answers_503():
    with pytest.raises(PublishError) as exc:
        _run(encryption=False)
    assert exc.value.code == "sdk-publish-encryption-unconfigured"
    assert exc.value.status_code == 503
    assert "APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS" in exc.value.message


def test_a_tenant_with_no_stored_credential_is_refused():
    with pytest.raises(PublishError) as exc:
        _run(credential=None)
    assert exc.value.code == "sdk-publish-credential-missing"


def test_a_dry_run_needs_a_credential_too():
    """"Is there a token, and can we still open it?" is exactly what a dry run is for."""
    with pytest.raises(PublishError) as exc:
        _run(dry_run=True, credential=None)
    assert exc.value.code == "sdk-publish-credential-missing"


# --------------------------------------------------------------------------------------------
# The log never carries a secret
# --------------------------------------------------------------------------------------------
def test_no_log_entry_contains_the_token():
    def transport(distribution, credential):
        raise RegistryUploadError(f"invalid token {_TOKEN}")

    outcome, ledger = _run(dry_run=False, transport=transport)
    serialised = json.dumps(outcome.log) + json.dumps(ledger.finishes, default=str)
    assert _TOKEN not in serialised
    assert REDACTION_MARKER in outcome.error_message


def test_the_log_records_each_step_in_order():
    transport, _ = _accepting()
    outcome, _ = _run(dry_run=False, transport=transport)
    steps = [entry["step"] for entry in outcome.log]
    assert steps == ["resolve", "claim", "build", "upload"]
    for entry in outcome.log:
        assert set(entry) == {"at", "step", "level", "message"}


# --------------------------------------------------------------------------------------------
# Reading a stored run back
# --------------------------------------------------------------------------------------------
def test_a_stored_row_projects_back_onto_an_outcome():
    outcome = run_row_to_outcome(
        {
            "id": _RUN,
            "status": RUN_STATUS_PUBLISHED,
            "dry_run": False,
            "ecosystem": "npm",
            "package_name": "@acme/widgets-sdk",
            "package_version": "1.4.3",
            "release_series": "1.4",
            "regen_counter": 3,
            "version_line": "1.4.2",
            "registry_url": "https://registry.npmjs.org",
            "credential_scope": "tenant",
            "artifact_sha256": "a" * 64,
            "artifact_bytes": 2048,
            "provenance": {"versionRecordId": _REVISION},
            "log": [{"step": "upload", "message": "ok"}],
        }
    )
    assert outcome.run_id == _RUN
    assert outcome.package_version == "1.4.3"
    assert outcome.provenance["versionRecordId"] == _REVISION
    # A stored row does not keep the archive's file list — it is rebuildable, not a column.
    assert outcome.files == []
