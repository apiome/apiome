"""CNCF xRegistry crawl — MFI-18.5 (#3978) / MFI-19.2 (#3980), declared by the ``cloudevents`` adapter.

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
left out and reported in the sync summary's findings.

The **message registry** and **endpoint registry** (MFI-19.2) are crawled the same way and imported
with the ``xregistry`` adapter (:mod:`app.xregistry_import_source`):

4. ``GET <base>/messagegroups`` → ``GET <base>/messagegroups/<gid>/messages``: each message group
   becomes one catalog item keyed ``messagegroups/<gid>``, its document an xRegistry document
   holding that group and its messages.
5. ``GET <base>/endpoints`` → ``GET <base>/endpoints/<eid>/messages``: each endpoint becomes one
   catalog item keyed ``endpoints/<eid>``, its document holding the endpoint, its inline messages
   and the message groups it references, so the endpoint's operations resolve on their own.

A registry that does not serve one of the three collections (``404``) simply has none; a root that
serves none of them fails the sync. Message groups and endpoints report no revision, so the engine
compares content digests. Scope ``groups`` limits schema and message groups to those ids (an
endpoint is still crawled, with the groups it references); scope ``include`` picks the registries
(``schemas``, ``messages``, ``endpoints``; all by default).
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

from .catalog_connectors import CODE_INVALID, ConnectorError
from .refresh_source import ERROR_CLASS_UNEXPECTED, RefreshSourceError
from .registry_crawl import (
    ERROR_CLASS_INVALID_CONFIGURATION,
    Page,
    RegistryCrawl,
    RegistryEntry,
    RegistryHttp,
    link_next,
    paginate,
    parse_instant,
    register_registry_crawl,
)
from .xregistry_parser import group_refs

__all__ = ["XREGISTRY", "XRegistryCrawl", "import_kind_for_format"]

#: The registries a crawl can include (scope ``include``).
INCLUDE_VALUES: Tuple[str, ...] = ("schemas", "messages", "endpoints")

#: The import-source key message groups and endpoints are imported with.
_DOCUMENT_KIND = "xregistry"

#: Registry bookkeeping left out of assembled documents (it moves without the model changing).
_BOOKKEEPING = frozenset({"self", "epoch", "createdat", "modifiedat", "xid", "messagesurl", "messagescount"})

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
    label = "CNCF xRegistry (schemas, messages, endpoints)"
    import_source = "cloudevents"
    scope_keys = ("groups", "include")

    def validate_scope(self, scope: Mapping[str, Any]) -> None:
        """``groups``, when given, is a non-empty list of group ids; ``include`` a non-empty subset
        of :data:`INCLUDE_VALUES`."""
        groups = scope.get("groups")
        if groups is not None and (
            not isinstance(groups, list) or not groups or not all(isinstance(g, str) and g.strip() for g in groups)
        ):
            raise ConnectorError(CODE_INVALID, "groups must be a non-empty list of schema or message group ids.")
        include = scope.get("include")
        if include is not None and (
            not isinstance(include, list) or not include or not all(value in INCLUDE_VALUES for value in include)
        ):
            raise ConnectorError(
                CODE_INVALID, f"include must be a non-empty list of: {', '.join(INCLUDE_VALUES)}."
            )

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

    @classmethod
    def _optional_map_pages(
        cls, http: RegistryHttp, url: str, what: str
    ) -> Optional[List[Tuple[str, Mapping[str, Any]]]]:
        """Like :meth:`_map_pages`, but ``None`` when the registry does not serve the collection (404)."""
        try:
            return cls._map_pages(http, url, what)
        except RefreshSourceError as exc:
            if exc.http_status == 404:
                return None
            raise

    def list_entries(
        self, http: RegistryHttp, base_url: str, scope: Mapping[str, Any]
    ) -> List[RegistryEntry]:
        """Walk the schema, message and endpoint registries the scope includes.

        Args:
            http: The bounded HTTP surface.
            base_url: The registry root.
            scope: The connector scope (``groups``, ``include``).

        Returns:
            One entry per importable schema, message group and endpoint.

        Raises:
            RefreshSourceError: When the root serves none of the included collections, or a
                listing fails.
        """
        include = set(scope.get("include") or INCLUDE_VALUES)
        wanted = set(scope.get("groups") or [])
        entries: List[RegistryEntry] = []
        served = False
        message_groups: Dict[str, Dict[str, Any]] = {}
        if "schemas" in include:
            schema_entries = self._schema_entries(http, base_url, wanted)
            served = served or schema_entries is not None
            entries.extend(schema_entries or [])
        if "messages" in include or "endpoints" in include:
            listed = self._message_groups(http, base_url)
            served = served or listed is not None
            message_groups = listed or {}
        if "messages" in include:
            for gid, group in message_groups.items():
                if wanted and gid not in wanted:
                    continue
                if not group.get("messages"):
                    # An empty group defines nothing to catalog (its document would not parse).
                    http.findings.append({"remoteId": f"messagegroups/{gid}", "reason": "no-messages"})
                    continue
                document = {"messagegroups": {gid: group}}
                entries.append(self._document_entry(base_url, "messagegroups", gid, group, document))
        if "endpoints" in include:
            endpoints = self._endpoints(http, base_url)
            served = served or endpoints is not None
            for eid, endpoint in (endpoints or {}).items():
                document: Dict[str, Any] = {"endpoints": {eid: endpoint}}
                referenced = {gid: message_groups[gid] for gid in group_refs(endpoint) if gid in message_groups}
                if referenced:
                    document["messagegroups"] = referenced
                entries.append(self._document_entry(base_url, "endpoints", eid, endpoint, document))
        if not served:
            raise RefreshSourceError(
                "The registry root serves none of /schemagroups, /messagegroups or /endpoints; "
                "it does not look like an xRegistry.",
                http_status=404,
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        return entries

    def _schema_entries(
        self, http: RegistryHttp, base_url: str, wanted: set
    ) -> Optional[List[RegistryEntry]]:
        """Walk ``schemagroups`` → ``schemas``: one entry per importable schema, ``None`` when unserved."""
        groups = self._optional_map_pages(http, f"{base_url}/schemagroups", "schemagroups")
        if groups is None:
            return None
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

    def _message_groups(self, http: RegistryHttp, base_url: str) -> Optional[Dict[str, Dict[str, Any]]]:
        """Every message group with its messages, or ``None`` when ``/messagegroups`` is unserved."""
        groups = self._optional_map_pages(http, f"{base_url}/messagegroups", "messagegroups")
        if groups is None:
            return None
        assembled: Dict[str, Dict[str, Any]] = {}
        for gid, group in groups:
            url = group.get("messagesurl") if isinstance(group.get("messagesurl"), str) else None
            url = url or f"{base_url}/messagegroups/{quote(gid, safe='')}/messages"
            assembled[gid] = self._with_messages(http, group, url)
        return assembled

    def _endpoints(self, http: RegistryHttp, base_url: str) -> Optional[Dict[str, Dict[str, Any]]]:
        """Every endpoint with its inline messages, or ``None`` when ``/endpoints`` is unserved."""
        endpoints = self._optional_map_pages(http, f"{base_url}/endpoints", "endpoints")
        if endpoints is None:
            return None
        assembled: Dict[str, Dict[str, Any]] = {}
        for eid, endpoint in endpoints:
            url = endpoint.get("messagesurl") if isinstance(endpoint.get("messagesurl"), str) else None
            url = url or f"{base_url}/endpoints/{quote(eid, safe='')}/messages"
            assembled[eid] = self._with_messages(http, endpoint, url)
        return assembled

    def _with_messages(self, http: RegistryHttp, holder: Mapping[str, Any], url: str) -> Dict[str, Any]:
        """``holder`` without bookkeeping, its ``messages`` the listing at ``url`` (kept inline when
        the listing already carried them; none when the collection is unserved)."""
        assembled = _without_bookkeeping(holder)
        if isinstance(holder.get("messages"), Mapping):
            messages = list(holder["messages"].items())
        else:
            messages = self._optional_map_pages(http, url, "messages") or []
        if messages:
            assembled["messages"] = {mid: _without_bookkeeping(m) for mid, m in messages if isinstance(m, Mapping)}
        return assembled

    @staticmethod
    def _document_entry(
        base_url: str, collection: str, entity_id: str, entity: Mapping[str, Any], document: Mapping[str, Any]
    ) -> RegistryEntry:
        """A message group or endpoint as an entry carrying its assembled xRegistry document."""
        return RegistryEntry(
            remote_id=f"{collection}/{entity_id}",
            import_kind=_DOCUMENT_KIND,
            filename=f"{entity_id}.xreg.json",
            name=str(entity.get("name") or entity_id),
            revision=None,
            document_url=None,
            content=json.dumps(document, sort_keys=True).encode("utf-8"),
            source_uri=f"{base_url}/{collection}/{quote(entity_id, safe='')}",
            raw={k: v for k, v in entity.items() if k != "messages"},
        )

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


def _without_bookkeeping(entity: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of ``entity`` without the registry bookkeeping in :data:`_BOOKKEEPING`."""
    return {k: v for k, v in entity.items() if k not in _BOOKKEEPING}


XREGISTRY: RegistryCrawl = register_registry_crawl(XRegistryCrawl())
