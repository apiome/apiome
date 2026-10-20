"""CNCF xRegistry schema-registry crawl — MFI-18.5 (#3978), declared by the ``cloudevents`` adapter.

`xRegistry <https://xregistry.io>`_ is the CloudEvents project's registry model. Its **schema
registry** holds ``schemagroups``, each a map of ``schemas`` whose default version is a schema
document (JSON Schema, Avro, Protobuf, XSD). The crawl walks it over the xRegistry HTTP binding:

1. ``GET <base>/schemagroups`` — a JSON map keyed by group id (``Link: <…>; rel="next"`` pages it).
2. ``GET <base>/schemagroups/<gid>/schemas`` — a map keyed by schema id; each value is the
   schema's metadata: ``format`` (``JsonSchema/draft-07``, ``Avro/1.11.0``, ``Protobuf/3``,
   ``XSD/1.1`` …), ``versionid`` / ``defaultversionid``, ``epoch``, ``modifiedat``, ``name``,
   and optionally the document inline (``schema`` / ``schemabase64``) or by reference
   (``schemaurl``).
3. Each schema becomes one catalog item keyed ``schemagroups/<gid>/schemas/<sid>``, imported with
   the adapter its ``format`` names; its document is the default version's document view
   (``GET <base>/schemagroups/<gid>/schemas/<sid>``) unless the listing carried it.

The revision is ``<version>+e<epoch>``: xRegistry bumps ``epoch`` on every change to an entity,
so an unchanged schema is skipped on re-crawl. A schema whose ``format`` has no Apiome adapter is
left out and reported in the sync summary's findings. Scope ``groups`` limits the crawl to those
group ids.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

from .catalog_connectors import CODE_INVALID, ConnectorError
from .refresh_source import ERROR_CLASS_UNEXPECTED, RefreshSourceError
from .registry_crawl import (
    Page,
    RegistryCrawl,
    RegistryEntry,
    RegistryHttp,
    link_next,
    paginate,
    parse_instant,
    register_registry_crawl,
)

__all__ = ["XREGISTRY", "XRegistryCrawl", "import_kind_for_format"]

#: ``format`` prefix (lower-cased, before the ``/``) → (import-source key, file extension).
_FORMATS: Dict[str, Tuple[str, str]] = {
    "jsonschema": ("json-schema", ".schema.json"),
    "avro": ("avro", ".avsc"),
    "protobuf": ("grpc", ".proto"),
    "xsd": ("xsd", ".xsd"),
}


def import_kind_for_format(fmt: Any) -> Optional[Tuple[str, str]]:
    """Map an xRegistry ``format`` (``Avro/1.11.0``) to ``(import kind, file extension)``, or ``None``."""
    if not isinstance(fmt, str) or not fmt.strip():
        return None
    return _FORMATS.get(fmt.strip().split("/", 1)[0].lower())


class XRegistryCrawl(RegistryCrawl):
    """Crawl an xRegistry schema registry (see the module docstring)."""

    protocol = "xregistry"
    label = "CNCF xRegistry schema registry"
    import_source = "cloudevents"
    scope_keys = ("groups",)

    def validate_scope(self, scope: Mapping[str, Any]) -> None:
        """``groups``, when given, is a non-empty list of group ids."""
        groups = scope.get("groups")
        if groups is not None and (
            not isinstance(groups, list) or not groups or not all(isinstance(g, str) and g.strip() for g in groups)
        ):
            raise ConnectorError(CODE_INVALID, "groups must be a non-empty list of schema group ids.")

    @staticmethod
    def _map_pages(http: RegistryHttp, url: str, what: str) -> List[Tuple[str, Mapping[str, Any]]]:
        """Every ``(id, value)`` of a paged xRegistry collection map."""

        def page(token: Optional[str]) -> Page:
            response = http.get(token or url, accept="application/json")
            try:
                body = response.json()
            except ValueError as exc:
                raise RefreshSourceError(
                    f"The xRegistry answered with a {what} collection that is not JSON.",
                    error_class=ERROR_CLASS_UNEXPECTED,
                ) from exc
            if not isinstance(body, Mapping):
                raise RefreshSourceError(
                    f"The xRegistry answered with a {what} collection that is not a map.",
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
            items = [(str(k), v) for k, v in body.items() if isinstance(v, Mapping)]
            return Page(items=items, next_token=link_next(response))

        return list(paginate(page, what=what))

    def list_entries(
        self, http: RegistryHttp, base_url: str, scope: Mapping[str, Any]
    ) -> List[RegistryEntry]:
        """Walk ``schemagroups`` → ``schemas`` and return one entry per importable schema."""
        wanted = set(scope.get("groups") or [])
        groups = self._map_pages(http, f"{base_url}/schemagroups", "schemagroups")
        entries: List[RegistryEntry] = []
        for gid, group in groups:
            if wanted and gid not in wanted:
                continue
            schemas_url = group.get("schemasurl") if isinstance(group.get("schemasurl"), str) else None
            schemas_url = schemas_url or f"{base_url}/schemagroups/{quote(gid, safe='')}/schemas"
            for sid, meta in self._map_pages(http, schemas_url, "schemas"):
                entry = self._entry(base_url, gid, sid, meta)
                if entry is None:
                    http.findings.append(
                        {
                            "remoteId": f"schemagroups/{gid}/schemas/{sid}",
                            "reason": f"unsupported-format: {meta.get('format') or 'none'}",
                        }
                    )
                else:
                    entries.append(entry)
        return entries

    def _entry(self, base_url: str, gid: str, sid: str, meta: Mapping[str, Any]) -> Optional[RegistryEntry]:
        """One schema's entry, or ``None`` when its format has no Apiome adapter."""
        remote_id = f"schemagroups/{gid}/schemas/{sid}"
        kind = import_kind_for_format(meta.get("format"))
        if kind is None:
            return None
        import_kind, extension = kind
        version = meta.get("versionid") or meta.get("defaultversionid")
        epoch = meta.get("epoch")
        revision = "+".join(
            part for part in (str(version) if version else None, f"e{epoch}" if epoch is not None else None) if part
        ) or None
        resource_url = f"{base_url}/schemagroups/{quote(gid, safe='')}/schemas/{quote(sid, safe='')}"
        content: Optional[bytes] = None
        if isinstance(meta.get("schemabase64"), str):
            try:
                content = base64.b64decode(meta["schemabase64"], validate=True)
            except ValueError:
                content = None
        elif "schema" in meta and meta["schema"] is not None:
            inline = meta["schema"]
            content = inline.encode("utf-8") if isinstance(inline, str) else json.dumps(inline).encode("utf-8")
        document_url = meta["schemaurl"] if isinstance(meta.get("schemaurl"), str) else resource_url
        return RegistryEntry(
            remote_id=remote_id,
            import_kind=import_kind,
            filename=f"{sid}{extension}",
            name=str(meta.get("name") or sid),
            revision=revision,
            updated_at=parse_instant(meta.get("modifiedat")),
            document_url=document_url,
            content=content,
            source_uri=resource_url,
            raw={k: v for k, v in meta.items() if k not in ("schema", "schemabase64")},
        )


XREGISTRY: RegistryCrawl = register_registry_crawl(XRegistryCrawl())
