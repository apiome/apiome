"""OpenAPI validation pack facade (CLX-2.2 / #4852).

Runs curated Spectral / Vacuum / Redocly adapters under a selected profile.
The default bulk runner is selected from the parity corpus — **not** from speed
claims. Spectral remains the compatibility reference and default until Vacuum
demonstrates equivalent enabled-rule output on that corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .external_linter_adapter import (
    AdapterInput,
    AdapterRunResult,
    InputFormat,
    ScanMode,
    load_builtin_adapters,
    run_adapter,
)
from .external_linter_runner import RestrictedRunner
from .openapi_validation_adapters import (
    REDOCLY_OAS_ADAPTER_ID,
    SPECTRAL_OAS_ADAPTER_ID,
    VACUUM_OAS_ADAPTER_ID,
    RedoclyOasAdapter,
    SpectralOasAdapter,
    VacuumOasAdapter,
)
from .openapi_validation_profiles import (
    PROFILE_BASELINE,
    VALIDATION_PROFILES,
    normalize_profile,
)
from .schema_lint import LintFinding
from .toolchain_packaging import probe_tool
from .toolchain_sandbox import SandboxPolicy

__all__ = [
    "DEFAULT_BULK_RUNNER",
    "BULK_RUNNER_IDS",
    "SECONDARY_RUNNER_IDS",
    "OpenApiValidationPackResult",
    "run_openapi_validation_pack",
    "list_openapi_validation_adapters",
    "parity_default_runner_rationale",
]

# ---------------------------------------------------------------------------
# Default bulk runner — parity-selected (Spectral remains the reference).
#
# The openapi_validation_parity corpus compares enabled-rule findings across
# Spectral (reference), Vacuum, and Redocly on shared fixtures. Vacuum has not
# demonstrated equivalent enabled-rule output on that corpus, so the default
# bulk runner stays Spectral. Flip only after the parity matrix is green.
# ---------------------------------------------------------------------------
DEFAULT_BULK_RUNNER = SPECTRAL_OAS_ADAPTER_ID

BULK_RUNNER_IDS: Tuple[str, ...] = (
    SPECTRAL_OAS_ADAPTER_ID,
    VACUUM_OAS_ADAPTER_ID,
)
SECONDARY_RUNNER_IDS: Tuple[str, ...] = (REDOCLY_OAS_ADAPTER_ID,)

_ADAPTER_BY_ID: Dict[str, type] = {
    SPECTRAL_OAS_ADAPTER_ID: SpectralOasAdapter,
    VACUUM_OAS_ADAPTER_ID: VacuumOasAdapter,
    REDOCLY_OAS_ADAPTER_ID: RedoclyOasAdapter,
}


def parity_default_runner_rationale() -> str:
    """Human-readable rationale stamped into discovery / docs."""
    return (
        "DEFAULT_BULK_RUNNER is spectral.oas because the OpenAPI validation parity "
        "corpus treats Spectral as the compatibility reference; Vacuum has not yet "
        "demonstrated equivalent enabled-rule findings on that corpus. Selection is "
        "parity-based, not speed-based."
    )


@dataclass
class OpenApiValidationPackResult:
    """Outcome of one validation-pack invocation."""

    profile: str
    runner_id: str
    adapter_result: AdapterRunResult
    lint_findings: List[LintFinding] = field(default_factory=list)
    secondary: List[AdapterRunResult] = field(default_factory=list)

    def to_evidence_run(
        self,
        *,
        subject_id: str,
        subject_type: str = "catalog_revision",
        scanner_version: Optional[str] = None,
        input_fingerprint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Project the primary adapter run into a CLX-1.1 evidence-run dict."""
        return self.adapter_result.to_evidence_run(
            subject_id=subject_id,
            subject_type=subject_type,
            profile=self.profile,
            input_fingerprint=input_fingerprint,
            config={
                "runner_id": self.runner_id,
                "profile": self.profile,
                "scanner_version": scanner_version,
            },
        )


async def run_openapi_validation_pack(
    *,
    document: Any = None,
    files: Optional[Mapping[str, str]] = None,
    profile: str = PROFILE_BASELINE,
    runner_id: Optional[str] = None,
    custom_rules: Optional[Mapping[str, Any]] = None,
    custom_rules_yaml: Optional[str] = None,
    guide_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    include_secondary: bool = False,
    runner: Optional[RestrictedRunner] = None,
    timeout: Optional[float] = None,
    policy: Optional[SandboxPolicy] = None,
) -> OpenApiValidationPackResult:
    """Run the OpenAPI validation pack under the selected profile.

    Args:
        document: Single OpenAPI document (dict or YAML/JSON string).
        files: Multi-file tree (relative path → content) for local ``$ref``.
        profile: ``baseline`` | ``tenant_guide`` | ``strict``.
        runner_id: Adapter id override; defaults to :data:`DEFAULT_BULK_RUNNER`.
        custom_rules: Tenant custom rule defs for ``tenant_guide``.
        custom_rules_yaml: Pre-serialized Spectral subset YAML for ``tenant_guide``.
        guide_rows: Optional ``style_guide_rules`` rows used to derive custom rules.
        include_secondary: When true, also run Redocly (and Vacuum when Spectral is
            primary) for dual evidence — not the default bulk path.
        runner: Restricted runner override.
        timeout: Optional wall-clock timeout.
        policy: Sandbox policy override (defaults to no-network).

    Returns:
        Pack result with primary adapter outcome and optional secondary runs.
    """
    load_builtin_adapters()
    resolved_profile = normalize_profile(profile)
    resolved_runner = (runner_id or DEFAULT_BULK_RUNNER).strip()
    if resolved_runner not in _ADAPTER_BY_ID:
        resolved_runner = DEFAULT_BULK_RUNNER

    metadata: Dict[str, Any] = {"profile": resolved_profile}
    if custom_rules:
        metadata["custom_rules"] = dict(custom_rules)
    if custom_rules_yaml:
        metadata["custom_rules_yaml"] = custom_rules_yaml
    if guide_rows:
        metadata["guide_rows"] = list(guide_rows)

    inputs = AdapterInput(
        document=document,
        files=dict(files) if files else {},
        format=InputFormat.OPENAPI,
        scan_mode=ScanMode.LINT,
        metadata=metadata,
    )

    primary = _ADAPTER_BY_ID[resolved_runner]()
    primary_result = await run_adapter(
        primary, inputs, runner=runner, timeout=timeout, policy=policy
    )

    secondary_results: List[AdapterRunResult] = []
    if include_secondary:
        for sid in (*BULK_RUNNER_IDS, *SECONDARY_RUNNER_IDS):
            if sid == resolved_runner:
                continue
            adapter_cls = _ADAPTER_BY_ID[sid]
            secondary_results.append(
                await run_adapter(
                    adapter_cls(), inputs, runner=runner, timeout=timeout, policy=policy
                )
            )

    return OpenApiValidationPackResult(
        profile=resolved_profile,
        runner_id=resolved_runner,
        adapter_result=primary_result,
        lint_findings=list(primary_result.lint_findings or []),
        secondary=secondary_results,
    )


def list_openapi_validation_adapters() -> List[Dict[str, Any]]:
    """Discovery payload for adapters, profiles, default runner, and tool availability."""
    load_builtin_adapters()
    out: List[Dict[str, Any]] = []
    for adapter_id, cls in _ADAPTER_BY_ID.items():
        decl = cls.declaration()
        avail = probe_tool(decl.tool_key)
        out.append(
            {
                "adapter_id": decl.adapter_id,
                "scanner_id": decl.scanner_id,
                "formats": list(decl.formats),
                "scan_modes": list(decl.scan_modes),
                "tool_key": decl.tool_key,
                "output_format": decl.output_format,
                "adapter_version": decl.adapter_version,
                "description": decl.description,
                "profiles": list(VALIDATION_PROFILES),
                "is_default_bulk_runner": adapter_id == DEFAULT_BULK_RUNNER,
                "tool_available": bool(getattr(avail, "available", False)),
                "pinned_version": getattr(avail, "pinned_version", None)
                if avail is not None
                else None,
            }
        )
    return out
