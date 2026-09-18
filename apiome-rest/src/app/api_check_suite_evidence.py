"""Gathering the API change check suite's evidence — GNC-3.1 (#4740).

:mod:`app.api_check_suite` holds the rules and knows nothing about storage. This module reads the
five components' facts from where the platform already produces them and hands them to those rules.
Nothing here is a new analysis:

============  ==============================================================================
Component     Read through
============  ==============================================================================
lint          :func:`app.lint_routes.build_lint_report` — the stored-first report (#5259): the
              revision's stored report when it still matches the content, otherwise one lint,
              persisted, so the next reader gets the stored one.
breaking      :func:`app.change_taxonomy.classify_openapi_changes` of the draft against
              :meth:`Database.get_prior_published_baseline_revision_id` — the baseline CTG-3.1
              and CTG-3.4 classify against — rendered by the CTG-1.3 changelog builder.
consumers     :func:`app.consumer_impact_service.consumer_impact_for_diff` over that same
              classification: one diff, two questions, never two chances to disagree.
contract      The newest ECA-1.3 run whose recorded source names this revision (V267 index), and
              a recompile of that run's own reference to prove it is still this draft's suite.
sdk           :func:`app.sdk_kit.build_client_kit` from the revision's canonical model, branded
              with the project's SDK-3.4 settings — the SDK manifest.
============  ==============================================================================

**The heavy reads run on worker threads.** Classifying against the baseline, loading the canonical
model and building the client kit are synchronous and can take a while on a large API, so they are
handed to ``asyncio.to_thread`` rather than holding the event loop — the rule GNC-2.2 follows for its
provider call.

**Every component fails soft, on its own.** Each is gathered inside its own guard: an unreadable
store or a model that fails to load costs *that* component — reported ``pending`` with
``evidence-unavailable`` — and nothing else. A version with no captured source document (designed in
the app, never imported) is different: no suite or kit *can* be built from it, which is a fact about
the version, so contract and sdk are ``skipped`` with ``no-captured-source``. A component the policy
switched off is not read at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

from .api_check_suite import (
    COMPONENT_BREAKING,
    COMPONENT_CONSUMERS,
    COMPONENT_CONTRACT,
    COMPONENT_LABELS,
    COMPONENT_LINT,
    COMPONENT_SDK,
    COMPONENTS,
    REQUIREMENT_OFF,
    BreakingFacts,
    CheckSuitePolicy,
    ContractFacts,
    LintFacts,
    SdkFacts,
    SuiteComponent,
    disabled_component,
    judge_breaking,
    judge_consumers,
    judge_contract,
    judge_lint,
    judge_sdk,
    unavailable_component,
    unbuildable_component,
)
from .database import db
from .deploy_gate import DeployGateThresholds

logger = logging.getLogger(__name__)

__all__ = [
    "Classification",
    "evidence_links",
    "gather_components",
    "read_breaking_facts",
    "read_contract_facts",
    "read_lint_facts",
    "read_sdk_facts",
]

#: How many of a revision's newest contract runs are read. Only the newest decides; one row is
#: enough, and the accessor clamps anyway.
_CONTRACT_RUN_LIMIT = 1

#: Statuses with which :func:`app.export_source.load_export_source` says a revision has no
#: reconstructable source (as opposed to "not found" or a fault).
_UNBUILDABLE_STATUSES = (400, 422)


def evidence_links(tenant_slug: str, project_id: str, version_id: str) -> Dict[str, str]:
    """API paths a reader follows for each component's evidence.

    Args:
        tenant_slug: The tenant in the URL.
        project_id: The project.
        version_id: The revision judged.

    Returns:
        One path per component (the contract path is refined to the run when there is one).
    """
    return {
        COMPONENT_LINT: f"/v1/versions/{tenant_slug}/{project_id}/{version_id}/lint",
        COMPONENT_BREAKING: (
            f"/v1/versions/{tenant_slug}/{project_id}/{version_id}/breaking-publish-guardrail"
        ),
        COMPONENT_CONSUMERS: f"/v1/tenants/{tenant_slug}/projects/{project_id}/consumers",
        COMPONENT_CONTRACT: f"/v1/tenants/{tenant_slug}/verification-runs",
        COMPONENT_SDK: f"/v1/projects/{tenant_slug}/{project_id}/sdk-settings",
    }


# ---------------------------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------------------------


async def read_lint_facts(
    *, tenant_id: str, tenant_slug: str, project_id: str, version: Mapping[str, Any]
) -> LintFacts:
    """Read the revision's lint report, stored-first.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug (the report path rebuilds the document under it).
        project_id: The owning project.
        version: The revision row.

    Returns:
        The report's facts.
    """
    from .lint_routes import build_lint_report  # Lazy: a routes module, imported only when used.

    report = await build_lint_report(dict(version), project_id, tenant_slug, tenant_id)
    return LintFacts(
        grade=str(report.grade).strip().upper() if report.grade else None,
        score=int(report.score) if report.score is not None else None,
        severity_counts=dict(report.severity_counts or {}),
        error_findings=[
            {"rule": str(f.rule), "path": str(f.path), "message": str(f.message)}
            for f in report.findings
            if str(f.severity) == "error"
        ],
        # The pinned guide *revision* is left out on purpose: a freshly linted report carries it and
        # the same report served from the revision record does not, so including it would make the
        # first re-run look like new evidence. The report fingerprint already pins the content.
        guide={
            "id": report.guide_id,
            "name": report.guide_name,
            "source": report.guide_source,
        },
        report_fingerprint=report.report_fingerprint,
    )


# ---------------------------------------------------------------------------------------------
# breaking + consumers
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Classification:
    """The draft classified against the previous published revision.

    Attributes:
        facts: What the breaking component judges.
        diff: The classified diff, for the consumer intersection; ``None`` without a baseline.
    """

    facts: BreakingFacts
    diff: Optional[Any] = None


def read_breaking_facts(
    *, tenant_id: str, project_id: str, version: Mapping[str, Any], draft_document: Mapping[str, Any]
) -> Classification:
    """Classify the draft against the previous published revision on its line.

    The baseline document is rebuilt the same way the draft's was (:func:`app.spec_sync_store.
    read_draft_document`), so a difference between the two is a difference in the API and never in
    how either was generated.

    Args:
        tenant_id: The caller's tenant.
        project_id: The owning project.
        version: The revision row.
        draft_document: The draft, already rebuilt.

    Returns:
        The classification. Without a baseline this is the first publication on the line.

    Raises:
        LookupError: When the baseline the database names cannot be read.
    """
    from .change_taxonomy import classify_openapi_changes
    from .changelog_generator import build_changelog
    from .spec_sync_store import read_draft_document

    baseline_id = db.get_prior_published_baseline_revision_id(
        project_id, tenant_id, str(version["id"])
    )
    if not baseline_id:
        return Classification(facts=BreakingFacts(baseline_revision_id=None))

    baseline = db.get_version_by_id(str(baseline_id), tenant_id)
    if not baseline:
        raise LookupError(f"Baseline revision {baseline_id} could not be read.")
    baseline_document, _digest = read_draft_document(tenant_id, baseline)
    baseline_label = str(baseline.get("version_id") or "") or None

    diff = classify_openapi_changes(baseline_document, dict(draft_document))
    changelog = build_changelog(
        diff, from_version=baseline_label, to_version=str(version.get("version_id") or "") or None
    )
    breaking = [
        {
            "pointer": str(entry.pointer),
            "ruleId": str(entry.rule_id),
            "pathGroup": str(entry.path_group),
            "summary": str(entry.summary),
        }
        for entry in changelog.entries
        if entry.severity == "breaking"
    ]
    return Classification(
        facts=BreakingFacts(
            baseline_revision_id=str(baseline_id),
            baseline_label=baseline_label,
            max_severity=changelog.max_severity,
            counts=dict(changelog.counts or {}),
            breaking_changes=breaking,
        ),
        diff=diff,
    )


# ---------------------------------------------------------------------------------------------
# contract
# ---------------------------------------------------------------------------------------------


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp deterministically.

    Args:
        value: A datetime, a string, or ``None``.

    Returns:
        ISO 8601 text, or ``None``.
    """
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _recompiled_digest(tenant_id: str, reference: Optional[str]) -> Optional[str]:
    """Compile a run's own reference again, with the default options, and return the digest.

    Args:
        tenant_id: The caller's tenant.
        reference: The reference the run's suite was compiled from.

    Returns:
        The digest today, or ``None`` when the reference no longer compiles to a suite.
    """
    if not reference:
        return None
    from .contract_suite_service import (
        ContractSuiteCompileRequest,
        SchemaReferenceError,
        compile_version_contract_suite,
    )

    try:
        response = compile_version_contract_suite(
            reference, ContractSuiteCompileRequest(), tenant_id=tenant_id
        )
    except SchemaReferenceError:
        return None
    if not response.ok or response.manifest is None:
        return None
    return response.manifest.digest


def read_contract_facts(
    *, tenant_id: str, version_id: str, api: Any
) -> ContractFacts:
    """Read the newest contract run of this revision, and whether it is still current.

    Args:
        tenant_id: The caller's tenant.
        version_id: The revision judged.
        api: Its canonical model — a version with no service has no contract to execute.

    Returns:
        The contract facts.
    """
    applicable = bool(getattr(api, "services", None))
    if not applicable:
        return ContractFacts(applicable=False)
    rows = db.list_verification_runs_for_revision(
        tenant_id, version_id, limit=_CONTRACT_RUN_LIMIT
    )
    if not rows:
        return ContractFacts(applicable=True)
    row = rows[0]
    source = row.get("source") if isinstance(row.get("source"), Mapping) else {}
    reference = str(source.get("reference") or "") or None
    run = {
        "id": str(row.get("id") or ""),
        "outcome": str(row.get("outcome") or ""),
        "suiteDigest": str(row.get("suite_digest") or ""),
        "reference": reference,
        "targetSlug": row.get("target_slug"),
        "finishedAt": _iso(row.get("finished_at")),
        "cases": {
            "total": int(row.get("total_cases") or 0),
            "passed": int(row.get("passed_cases") or 0),
            "failed": int(row.get("failed_cases") or 0),
            "errored": int(row.get("errored_cases") or 0),
            "skipped": int(row.get("skipped_cases") or 0),
        },
    }
    return ContractFacts(
        applicable=True,
        run=run,
        current_digest=_recompiled_digest(tenant_id, reference),
    )


# ---------------------------------------------------------------------------------------------
# sdk
# ---------------------------------------------------------------------------------------------


def read_sdk_facts(
    *,
    tenant_id: str,
    tenant_slug: str,
    project: Mapping[str, Any],
    version: Mapping[str, Any],
    source: Any,
) -> SdkFacts:
    """Build the client kit from the draft and read its manifest.

    The kit is byte-deterministic (SDK-3.3), so the sha256 of its bytes is a stable evidence id:
    the same draft under the same SDK settings yields the same digest.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug, for the kit's coordinates.
        project: The project row.
        version: The revision row.
        source: The loaded :class:`app.export_source.ExportSource`.

    Returns:
        The manifest's facts.
    """
    from .sdk_generation_settings import PatternContext, ResolvedBranding
    from .sdk_generation_settings_store import load_settings
    from .sdk_kit import KitCoordinates, build_client_kit

    project_id = str(project["id"])
    project_slug = str(project.get("slug") or project_id)
    label = str(version.get("version_id") or version["id"])
    settings_out = load_settings(
        tenant_id, project_id, PatternContext(tenant=tenant_slug, project=project_slug, version=label)
    )
    kit = build_client_kit(
        source.api,
        coordinates=KitCoordinates(
            tenant_slug=tenant_slug,
            project_slug=project_slug,
            version_slug=label,
            version_record_id=str(version["id"]),
            version_label=label,
        ),
        branding=ResolvedBranding(
            package_names=dict(settings_out.resolved.package_names),
            license_header=settings_out.resolved.license_header,
            user_agent=settings_out.resolved.user_agent,
        ),
        source_text=source.source_text,
        source_format=source.source_format,
        settings_fingerprint=settings_out.content_fingerprint,
    )
    manifest = kit.manifest
    go_client = manifest.get("go_client") or {}
    server_stubs = manifest.get("server_stubs") or {}
    return SdkFacts(
        operation_count=int(manifest.get("operation_count") or 0),
        total_operation_count=int(manifest.get("total_operation_count") or 0),
        skipped_operations=len(manifest.get("skipped") or []),
        go_client_error=None if go_client.get("included") else str(go_client.get("error") or "not generated"),
        server_stub_error=(
            None if server_stubs.get("included") else str(server_stubs.get("error") or "not generated")
        ),
        kit_digest=f"sha256:{hashlib.sha256(kit.content).hexdigest()}",
        go_package=go_client.get("package_name"),
        file_count=len(manifest.get("files") or []),
    )


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def _unavailable(component: str, requirement: str, link: Optional[str]) -> SuiteComponent:
    """The component as reported when gathering it raised.

    Args:
        component: The component.
        requirement: Its requirement.
        link: Where its evidence would be.

    Returns:
        A pending ``evidence-unavailable`` component.
    """
    label = COMPONENT_LABELS.get(component, component)
    return unavailable_component(
        component,
        requirement,
        detail=(
            f"The {label.lower()} evidence could not be read, so it has no verdict yet. This is "
            "not the same as it passing; re-run the suite."
        ),
        link=link,
    )


async def _guarded(
    component: str,
    requirement: str,
    link: Optional[str],
    gather: Callable[[], Awaitable[SuiteComponent]],
) -> SuiteComponent:
    """Run one component's gathering, turning any failure into a pending component.

    Args:
        component: The component.
        requirement: Its requirement.
        link: Where its evidence lives.
        gather: A zero-argument coroutine factory returning the judged component.

    Returns:
        The component, or a pending one describing the failure.
    """
    try:
        return await gather()
    except Exception:  # noqa: BLE001 - one unreadable component must not fail the suite
        logger.warning("Check-suite component %r could not be gathered", component, exc_info=True)
        return _unavailable(component, requirement, link)


async def gather_components(
    *,
    tenant_id: str,
    tenant_slug: str,
    project: Mapping[str, Any],
    version: Mapping[str, Any],
    draft_document: Mapping[str, Any],
    policy: CheckSuitePolicy,
    thresholds: DeployGateThresholds,
) -> List[SuiteComponent]:
    """Judge all five components for one draft, in report order.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug, for the evidence links and the kit's coordinates.
        project: The project row.
        version: The revision row.
        draft_document: The draft, already rebuilt (its digest is the suite's content key).
        policy: The suite policy in force.
        thresholds: The deploy-gate thresholds the CTG components are judged against.

    Returns:
        One component per entry of :data:`app.api_check_suite.COMPONENTS`.
    """
    project_id = str(project["id"])
    version_id = str(version["id"])
    links = evidence_links(tenant_slug, project_id, version_id)
    requirement = {component: policy.requirement(component) for component in COMPONENTS}
    judged: Dict[str, SuiteComponent] = {}

    # ---- lint ----------------------------------------------------------------------------
    async def lint() -> SuiteComponent:
        facts = await read_lint_facts(
            tenant_id=tenant_id, tenant_slug=tenant_slug, project_id=project_id, version=version
        )
        return judge_lint(
            facts,
            thresholds=thresholds.lint,
            requirement=requirement[COMPONENT_LINT],
            link=links[COMPONENT_LINT],
        )

    if requirement[COMPONENT_LINT] != REQUIREMENT_OFF:
        judged[COMPONENT_LINT] = await _guarded(
            COMPONENT_LINT, requirement[COMPONENT_LINT], links[COMPONENT_LINT], lint
        )

    # ---- breaking + consumers: one classification, two questions --------------------------
    wants_classification = any(
        requirement[c] != REQUIREMENT_OFF for c in (COMPONENT_BREAKING, COMPONENT_CONSUMERS)
    )
    classification: Optional[Classification] = None
    if wants_classification:
        try:
            classification = await asyncio.to_thread(
                read_breaking_facts,
                tenant_id=tenant_id,
                project_id=project_id,
                version=version,
                draft_document=draft_document,
            )
        except Exception:  # noqa: BLE001 - both dependent components degrade below
            logger.warning(
                "Check suite could not classify revision %s", version_id, exc_info=True
            )

    async def breaking() -> SuiteComponent:
        if classification is None:
            raise LookupError("classification unavailable")
        return judge_breaking(
            classification.facts,
            thresholds=thresholds.breaking,
            requirement=requirement[COMPONENT_BREAKING],
            link=links[COMPONENT_BREAKING],
        )

    async def consumers() -> SuiteComponent:
        if classification is None:
            raise LookupError("classification unavailable")
        report = None
        if classification.diff is not None:
            from .consumer_impact_service import consumer_impact_for_diff

            report = await asyncio.to_thread(
                consumer_impact_for_diff,
                tenant_id,
                project_id,
                classification.diff,
                base_version_id=classification.facts.baseline_revision_id,
            )
        return judge_consumers(
            report,
            thresholds=thresholds.consumers,
            requirement=requirement[COMPONENT_CONSUMERS],
            link=links[COMPONENT_CONSUMERS],
        )

    for component, gather in ((COMPONENT_BREAKING, breaking), (COMPONENT_CONSUMERS, consumers)):
        if requirement[component] != REQUIREMENT_OFF:
            judged[component] = await _guarded(
                component, requirement[component], links[component], gather
            )

    # ---- contract + sdk: one canonical model, two questions --------------------------------
    wants_model = any(requirement[c] != REQUIREMENT_OFF for c in (COMPONENT_CONTRACT, COMPONENT_SDK))
    source: Optional[Any] = None
    unbuildable: Optional[str] = None
    if wants_model:
        from .export_source import ExportSourceError, load_export_source

        try:
            source = await asyncio.to_thread(load_export_source, tenant_id, project_id, version_id)
        except ExportSourceError as exc:
            if exc.status_code in _UNBUILDABLE_STATUSES:
                # A version with no captured source document (one designed in the app rather than
                # imported) has no canonical model to build a suite or a kit from. That is a fact
                # about the version, not a read that failed — both components simply do not apply.
                unbuildable = str(exc)
            else:
                logger.warning(
                    "Check suite could not load the canonical model of revision %s",
                    version_id,
                    exc_info=True,
                )
        except Exception:  # noqa: BLE001 - both dependent components degrade below
            logger.warning(
                "Check suite could not load the canonical model of revision %s",
                version_id,
                exc_info=True,
            )

    async def contract() -> SuiteComponent:
        if unbuildable is not None:
            return unbuildable_component(
                COMPONENT_CONTRACT,
                requirement[COMPONENT_CONTRACT],
                reason=unbuildable,
                link=links[COMPONENT_CONTRACT],
            )
        if source is None:
            raise LookupError("canonical model unavailable")
        facts = await asyncio.to_thread(
            read_contract_facts, tenant_id=tenant_id, version_id=version_id, api=source.api
        )
        link = links[COMPONENT_CONTRACT]
        if facts.run and facts.run.get("id"):
            link = f"{link}/{facts.run['id']}"
        return judge_contract(facts, requirement=requirement[COMPONENT_CONTRACT], link=link)

    async def sdk() -> SuiteComponent:
        if unbuildable is not None:
            return unbuildable_component(
                COMPONENT_SDK,
                requirement[COMPONENT_SDK],
                reason=unbuildable,
                link=links[COMPONENT_SDK],
            )
        if source is None:
            raise LookupError("canonical model unavailable")
        facts = await asyncio.to_thread(
            read_sdk_facts,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            project=project,
            version=version,
            source=source,
        )
        return judge_sdk(facts, requirement=requirement[COMPONENT_SDK], link=links[COMPONENT_SDK])

    for component, gather in ((COMPONENT_CONTRACT, contract), (COMPONENT_SDK, sdk)):
        if requirement[component] != REQUIREMENT_OFF:
            judged[component] = await _guarded(
                component, requirement[component], links[component], gather
            )

    return [judged.get(component) or disabled_component(component) for component in COMPONENTS]
