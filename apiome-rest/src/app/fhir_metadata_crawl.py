"""FHIR server ``/metadata`` crawl — MFI-18.5 (#3978), declared by the ``fhir`` adapter.

A FHIR server describes itself at ``GET <base>/metadata``: a **CapabilityStatement** listing the
resources it serves, their interactions and the profiles (StructureDefinitions) they conform to.
The crawl treats that server as a registry:

* the CapabilityStatement itself is one catalog item (``remote_id`` ``CapabilityStatement``),
  revised by its ``version`` plus ``date`` (or ``meta.lastUpdated``), else its content digest;
* with scope ``includeProfiles: true``, every profile its resources declare (``profile`` and
  ``supportedProfile``) is one more catalog item, keyed by the profile's canonical URL and fetched
  from the same server by FHIR search (``GET <base>/StructureDefinition?url=<canonical>``, first
  match of the returned Bundle). Profiles carry no listing revision, so the engine compares their
  content: only a changed StructureDefinition is imported again.

Requests ask for ``application/fhir+json``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote

from .catalog_connectors import CODE_INVALID, ConnectorError
from .refresh_source import ERROR_CLASS_UNEXPECTED, FetchedDocument, RefreshSourceError
from .registry_crawl import (
    RegistryCrawl,
    RegistryEntry,
    RegistryHttp,
    content_revision,
    parse_instant,
    register_registry_crawl,
)

__all__ = ["FHIR_METADATA", "FhirMetadataCrawl", "declared_profiles"]

_FHIR_JSON = "application/fhir+json, application/json;q=0.9"

#: The inventory id of the server's CapabilityStatement.
CAPABILITY_STATEMENT_ID = "CapabilityStatement"


def _json_body(http: RegistryHttp, url: str) -> Any:
    response = http.get(url, accept=_FHIR_JSON)
    try:
        return response.json()
    except ValueError as exc:
        raise RefreshSourceError(
            f"The FHIR server answered {url} with a body that is not JSON.", error_class=ERROR_CLASS_UNEXPECTED
        ) from exc


def declared_profiles(statement: Mapping[str, Any]) -> List[str]:
    """Every profile canonical URL a CapabilityStatement's resources declare, deduplicated in order.

    Args:
        statement: The CapabilityStatement.

    Returns:
        ``rest[].resource[].profile`` and ``supportedProfile[]`` values.
    """
    out: List[str] = []
    for rest in statement.get("rest") or []:
        if not isinstance(rest, Mapping):
            continue
        for resource in rest.get("resource") or []:
            if not isinstance(resource, Mapping):
                continue
            for value in [resource.get("profile"), *(resource.get("supportedProfile") or [])]:
                if isinstance(value, str) and value.strip() and value.strip() not in out:
                    out.append(value.strip())
    return out


class FhirMetadataCrawl(RegistryCrawl):
    """Crawl one FHIR server's ``/metadata`` (see the module docstring)."""

    protocol = "fhir-metadata"
    label = "FHIR server /metadata"
    import_source = "fhir"
    scope_keys = ("includeProfiles",)

    def validate_scope(self, scope: Mapping[str, Any]) -> None:
        """``includeProfiles``, when given, is a boolean."""
        if "includeProfiles" in scope and not isinstance(scope["includeProfiles"], bool):
            raise ConnectorError(CODE_INVALID, "includeProfiles must be true or false.")

    def list_entries(
        self, http: RegistryHttp, base_url: str, scope: Mapping[str, Any]
    ) -> List[RegistryEntry]:
        """Read ``/metadata``; return the CapabilityStatement and, optionally, its profiles."""
        statement = _json_body(http, f"{base_url}/metadata")
        if not isinstance(statement, Mapping) or statement.get("resourceType") != "CapabilityStatement":
            raise RefreshSourceError(
                f"{base_url}/metadata did not return a FHIR CapabilityStatement.", error_class=ERROR_CLASS_UNEXPECTED
            )
        meta = statement.get("meta") if isinstance(statement.get("meta"), Mapping) else {}
        stamp = statement.get("date") or meta.get("lastUpdated")
        version = statement.get("version") or (statement.get("software") or {}).get("version")
        revision = "+".join(str(p) for p in (version, stamp) if p) or content_revision(statement)
        entries = [
            RegistryEntry(
                remote_id=CAPABILITY_STATEMENT_ID,
                import_kind="fhir",
                filename="CapabilityStatement.fhir.json",
                name=str(statement.get("title") or statement.get("name") or "CapabilityStatement"),
                revision=revision,
                updated_at=parse_instant(stamp),
                content=json.dumps(statement, sort_keys=True).encode("utf-8"),
                source_uri=f"{base_url}/metadata",
                raw={"fhirVersion": statement.get("fhirVersion"), "software": statement.get("software")},
            )
        ]
        if scope.get("includeProfiles") is True:
            for canonical in declared_profiles(statement):
                tail = canonical.rstrip("/").rsplit("/", 1)[-1] or "profile"
                entries.append(
                    RegistryEntry(
                        remote_id=canonical,
                        import_kind="fhir",
                        filename=f"{tail}.structuredefinition.json",
                        name=tail,
                        document_url=f"{base_url}/StructureDefinition?url={quote(canonical, safe='')}",
                        source_uri=canonical,
                        raw={"profile": canonical},
                    )
                )
        return entries

    def fetch_entry(self, http: RegistryHttp, entry: RegistryEntry) -> FetchedDocument:
        """The CapabilityStatement as listed; a profile as the first StructureDefinition the search returns."""
        if entry.content is not None or not entry.document_url:
            return super().fetch_entry(http, entry)
        body = _json_body(http, entry.document_url)
        resource: Optional[Dict[str, Any]] = None
        if isinstance(body, Mapping) and body.get("resourceType") == "StructureDefinition":
            resource = dict(body)
        elif isinstance(body, Mapping) and body.get("resourceType") == "Bundle":
            for item in body.get("entry") or []:
                candidate = item.get("resource") if isinstance(item, Mapping) else None
                if isinstance(candidate, Mapping) and candidate.get("resourceType") == "StructureDefinition":
                    resource = dict(candidate)
                    break
        if resource is None:
            raise RefreshSourceError(
                f"The FHIR server has no StructureDefinition for {entry.remote_id}.", http_status=404
            )
        return FetchedDocument(
            content=json.dumps(resource, sort_keys=True).encode("utf-8"),
            filename=entry.filename,
            import_kind=entry.import_kind,
            revision=entry.revision,
            source_uri=entry.source_uri,
        )


FHIR_METADATA: RegistryCrawl = register_registry_crawl(FhirMetadataCrawl())
