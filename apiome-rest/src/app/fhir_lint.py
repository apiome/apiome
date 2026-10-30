"""FHIR lint pack — profile and server hygiene (MFI-20.1, #3985).

Native rules for FHIR catalog items, registered under the ``fhir`` format key the FHIR normalizer
emits. Every rule reads what the import recorded on the model (``fhir_structure_definition`` /
``fhir_capability_statement`` extras, :mod:`app.fhir_normalizer`), so linting needs neither the
source text nor a re-parse. A resource *instance* has no profile metadata and gets no findings.

StructureDefinition (profile) rules:

* **fhir.profile-status** (warning) — the profile is ``draft``, ``retired`` or ``unknown``, so
  implementers should not rely on it yet (or any more).
* **fhir.profile-url** (error) — no canonical ``url``: nothing can reference or validate against it.
* **fhir.profile-version** (warning) — no ``fhirVersion``: tools cannot tell which release (R4, R5,
  R6) the profile is written for.
* **fhir.profile-base** (error) — a constraint (``derivation: constraint``) with no
  ``baseDefinition``, so there is nothing for it to constrain.
* **fhir.element-short** (info) — an element with neither ``short`` nor ``definition``.

CapabilityStatement (server) rules:

* **fhir.capability-version** (warning) — the statement does not say which ``fhirVersion`` the
  server speaks.
* **fhir.capability-profile** (info) — a resource the server offers with no ``profile`` or
  ``supportedProfile``, so clients cannot tell which constraints apply.
* **fhir.capability-search** (warning) — a resource that supports ``search-type`` but declares no
  ``searchParam``, so clients cannot tell what they may search on.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack

__all__ = ["FhirRulePack"]

#: Profile statuses that mean "do not rely on this".
_UNSETTLED_STATUSES = ("draft", "retired", "unknown")


def _structure(api: CanonicalApi) -> Dict[str, Any]:
    """The recorded StructureDefinition summary, or ``{}`` for any other FHIR document."""
    if api.extras.get("fhir_kind") != "structure_definition":
        return {}
    value = api.extras.get("fhir_structure_definition")
    return value if isinstance(value, dict) else {}


def _capability(api: CanonicalApi) -> Dict[str, Any]:
    """The recorded CapabilityStatement summary, or ``{}`` for any other FHIR document."""
    if api.extras.get("fhir_kind") != "capability_statement":
        return {}
    value = api.extras.get("fhir_capability_statement")
    return value if isinstance(value, dict) else {}


def _profile_path(structure: Mapping[str, Any]) -> str:
    return f"StructureDefinition/{structure.get('id') or structure.get('name') or ''}"


def _check_profile_status(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    structure = _structure(api)
    status = structure.get("status")
    if structure and status in _UNSETTLED_STATUSES:
        yield (f"{_profile_path(structure)}/status", f"The profile's status is `{status}`.")


def _check_profile_url(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    structure = _structure(api)
    if structure and not structure.get("url"):
        yield (f"{_profile_path(structure)}/url", "The profile has no canonical `url`.")


def _check_profile_version(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    structure = _structure(api)
    if structure and not api.extras.get("fhir_version"):
        yield (f"{_profile_path(structure)}/fhirVersion", "The profile does not say which `fhirVersion` it targets.")


def _check_profile_base(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    structure = _structure(api)
    if structure and structure.get("derivation") == "constraint" and not structure.get("baseDefinition"):
        yield (
            f"{_profile_path(structure)}/baseDefinition",
            "The profile is a constraint but names no `baseDefinition` to constrain.",
        )


def _check_element_short(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    structure = _structure(api)
    for element in structure.get("elements") or []:
        if isinstance(element, dict) and not element.get("short") and not element.get("definition"):
            yield (
                f"{_profile_path(structure)}/element/{element.get('path', '')}",
                f"Element `{element.get('path', '')}` has neither `short` nor `definition`.",
            )


def _check_capability_version(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    if _capability(api) and not api.extras.get("fhir_version"):
        yield ("CapabilityStatement/fhirVersion", "The CapabilityStatement does not say which `fhirVersion` it speaks.")


def _resources(api: CanonicalApi) -> List[Dict[str, Any]]:
    return [r for r in _capability(api).get("resources") or [] if isinstance(r, dict)]


def _check_capability_profile(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for resource in _resources(api):
        if not resource.get("profile") and not resource.get("supportedProfiles"):
            yield (
                f"CapabilityStatement/rest/resource/{resource.get('type', '')}",
                f"`{resource.get('type', '')}` declares no `profile` or `supportedProfile`.",
            )


def _check_capability_search(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for resource in _resources(api):
        if "search-type" in (resource.get("interactions") or []) and not resource.get("searchParams"):
            yield (
                f"CapabilityStatement/rest/resource/{resource.get('type', '')}/searchParam",
                f"`{resource.get('type', '')}` supports search but declares no `searchParam`.",
            )


class FhirRulePack(RulePack, register=True):
    """Native rules for FHIR artifacts (see the module docstring)."""

    format = "fhir"
    pack_id = "fhir"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="fhir.profile-status",
            category="structure",
            severity="warning",
            description="A FHIR profile should be active, not draft, retired or unknown.",
            check=_check_profile_status,
        ),
        LintRule(
            rule_id="fhir.profile-url",
            category="structure",
            severity="error",
            description="A FHIR profile must have a canonical url.",
            check=_check_profile_url,
        ),
        LintRule(
            rule_id="fhir.profile-version",
            category="structure",
            severity="warning",
            description="A FHIR profile should say which fhirVersion (R4, R5, R6) it targets.",
            check=_check_profile_version,
        ),
        LintRule(
            rule_id="fhir.profile-base",
            category="structure",
            severity="error",
            description="A FHIR constraint profile must name the baseDefinition it constrains.",
            check=_check_profile_base,
        ),
        LintRule(
            rule_id="fhir.element-short",
            category="documentation",
            severity="info",
            description="Every element a FHIR profile constrains should have a short label or a definition.",
            check=_check_element_short,
        ),
        LintRule(
            rule_id="fhir.capability-version",
            category="structure",
            severity="warning",
            description="A FHIR CapabilityStatement should say which fhirVersion the server speaks.",
            check=_check_capability_version,
        ),
        LintRule(
            rule_id="fhir.capability-profile",
            category="documentation",
            severity="info",
            description="Each resource a FHIR server offers should name the profile it conforms to.",
            check=_check_capability_profile,
        ),
        LintRule(
            rule_id="fhir.capability-search",
            category="structure",
            severity="warning",
            description="A FHIR resource that supports search should declare its search parameters.",
            check=_check_capability_search,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the FHIR native rules in deterministic execution order."""
        return list(self._RULES)
