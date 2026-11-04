"""A tenant's published artifacts as one read-only xRegistry — MFX-34.2 (#4307).

The *expose-as* half of the xRegistry support: instead of downloading an export, an xRegistry-aware
tool points at Apiome and reads the registry over the xRegistry core HTTP API
(:mod:`app.xregistry_routes`). This module is the pure part: it composes the registry from the
artifacts the route chose, and renders each xRegistry entity. It performs no I/O.

Composition
-----------
Every artifact (a project at its latest published version) is projected with the MFX-34.1 emitter
(:func:`app.xregistry_emitter.build_xregistry_document`, registry id = the project slug), then merged:

* the artifact's schema group keeps the project slug as its id (``/schemagroups/<project>``), and
  its schemas' one version is named after the artifact's version label (``1.4.0``);
* each of its message groups is prefixed with the project slug (``/messagegroups/<project>.<group>``),
  so two artifacts' groups never collide; a message's ``dataschemaxid`` keeps pointing at its schema;
* an artifact with neither a type nor an event contributes nothing.

Entities
--------
:class:`XRegistryView` renders the xRegistry core entities over that composition — the registry root
(with ``schemagroupsurl`` / ``messagegroupsurl`` and counts), ``/capabilities``, ``/model``, each
group collection and group, each resource collection, a resource (a schema's **document**, or a
message's attributes — a message has no document), its ``$details``, and its versions. Every entity
carries ``xid``, ``self``, ``epoch``, ``createdat`` and ``modifiedat``; ``inline=*`` embeds every
collection below the requested entity.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .canonical_model import CanonicalApi
from .emitter import EmitPreconditionError
from .xregistry_emitter import (
    SPEC_VERSION,
    VERSION_ID,
    XRegistryEmitOptions,
    build_xregistry_document,
)

__all__ = [
    "DETAILS_SUFFIX",
    "GROUP_KINDS",
    "ComposedRegistry",
    "RegistryArtifact",
    "XRegistryNotFoundError",
    "XRegistryView",
    "compose_registry",
]

#: The suffix that asks for a resource's (or version's) attributes instead of its document.
DETAILS_SUFFIX = "$details"
#: Group collection → (group singular, resource collection, resource singular, has a document).
GROUP_KINDS: Dict[str, Tuple[str, str, str, bool]] = {
    "schemagroups": ("schemagroup", "schemas", "schema", True),
    "messagegroups": ("messagegroup", "messages", "message", False),
}
#: Every entity is served at its first (and only) epoch: the registry is read-only.
_EPOCH = 1
#: The timestamp used when an artifact has no publication time.
_EPOCH_TIME = "1970-01-01T00:00:00Z"


class XRegistryNotFoundError(LookupError):
    """Raised when a path names no entity of the registry (a route turns it into ``404``)."""


@dataclass(frozen=True)
class RegistryArtifact:
    """One artifact that contributes to the registry.

    Attributes:
        project_slug: The project's slug (the schema group id and the message-group prefix).
        name: The project's display name.
        version_label: The published version's label, used as the schemas' version id.
        published_at: When that version was published (an ISO-8601 string or a datetime), if known.
        api: The version's canonical model.
    """

    project_slug: str
    name: str
    version_label: str
    published_at: Any
    api: CanonicalApi


@dataclass
class ComposedRegistry:
    """The merged registry: groups by collection, each group with its resources.

    Attributes:
        registry_id: The registry's id (the tenant slug).
        name: The registry's display name (the tenant name).
        groups: ``"schemagroups"`` / ``"messagegroups"`` → group id → group attributes, each group
            holding its resource map under the resource collection name (``schemas`` / ``messages``).
        stamps: ``(collection, group id)`` → ``(createdat, modifiedat)`` of the artifact it came from.
        modified: The latest publication time of any artifact (the registry's ``modifiedat``).
    """

    registry_id: str
    name: str
    groups: Dict[str, Dict[str, Dict[str, Any]]] = field(
        default_factory=lambda: {collection: {} for collection in GROUP_KINDS}
    )
    stamps: Dict[Tuple[str, str], str] = field(default_factory=dict)
    modified: str = _EPOCH_TIME


def _timestamp(value: Any) -> str:
    """An RFC 3339 UTC timestamp for ``value`` (a datetime or an ISO string); the epoch when unknown."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str) and value.strip():
        try:
            return _timestamp(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            return _EPOCH_TIME
    return _EPOCH_TIME


def _version_id(label: str) -> str:
    """The artifact's version label as a legal xRegistry version id (``1.4.0`` stays ``1.4.0``)."""
    from .xregistry_emitter import _xid  # noqa: PLC0415 - the id rule lives with the emitter

    return _xid(label or VERSION_ID, VERSION_ID)


def _rename_versions(entry: Dict[str, Any], version_id: str) -> None:
    """Rename a projected schema's one version (``1``) to the artifact's version id, in place."""
    versions = entry.get("versions")
    if not isinstance(versions, dict) or list(versions) != [VERSION_ID]:
        return  # an opaque schema written back with its own version ids
    version = dict(versions[VERSION_ID])
    version["versionid"] = version_id
    entry["versions"] = {version_id: version}
    entry["defaultversionid"] = version_id


def compose_registry(registry_id: str, name: str, artifacts: Sequence[RegistryArtifact]) -> ComposedRegistry:
    """Merge the artifacts' xRegistry projections into one registry.

    Args:
        registry_id: The registry id (the tenant slug).
        name: The registry's display name.
        artifacts: The contributing artifacts, in a stable order (the route sorts them).

    Returns:
        The composed registry. An artifact with nothing to project is skipped.
    """
    from .xregistry_emitter import _xid  # noqa: PLC0415

    registry = ComposedRegistry(registry_id=registry_id, name=name)
    latest = _EPOCH_TIME
    for artifact in artifacts:
        try:
            plan = build_xregistry_document(artifact.api, XRegistryEmitOptions(registry_id=artifact.project_slug))
        except EmitPreconditionError:
            continue
        document = plan.document
        stamp = _timestamp(artifact.published_at)
        latest = max(latest, stamp)
        version_id = _version_id(artifact.version_label)
        for gid, group in (document.get("schemagroups") or {}).items():
            group = copy.deepcopy(group)
            group.setdefault("name", artifact.name)
            for entry in (group.get("schemas") or {}).values():
                _rename_versions(entry, version_id)
            registry.groups["schemagroups"][gid] = group
            registry.stamps[("schemagroups", gid)] = stamp
        for gid, group in (document.get("messagegroups") or {}).items():
            new_gid = _xid(f"{document['registryid']}.{gid}", "messages")
            group = copy.deepcopy(group)
            group["messagegroupid"] = new_gid
            registry.groups["messagegroups"][new_gid] = group
            registry.stamps[("messagegroups", new_gid)] = stamp
    registry.modified = latest
    return registry


# ===========================================================================
# Rendering the entities
# ===========================================================================


def _split_details(segment: str) -> Tuple[str, bool]:
    """``("Order", True)`` for ``"Order$details"``; ``(segment, False)`` otherwise."""
    if segment.endswith(DETAILS_SUFFIX):
        return segment[: -len(DETAILS_SUFFIX)], True
    return segment, False


class XRegistryView:
    """Renders the xRegistry core entities of a :class:`ComposedRegistry` under one base URL.

    Args:
        registry: The composed registry.
        base_url: The absolute URL of the registry root (``https://api.example.com/v1/xregistry/acme``),
            without a trailing slash; every ``self`` and ``*url`` attribute starts with it.
    """

    def __init__(self, registry: ComposedRegistry, base_url: str) -> None:
        self._registry = registry
        self._base = base_url.rstrip("/")

    # --- shared attributes ----------------------------------------------

    def _common(self, xid: str, self_path: str, stamp: str) -> Dict[str, Any]:
        """``xid``, ``self``, ``epoch``, ``createdat`` and ``modifiedat`` of one entity."""
        return {"xid": xid or "/", "self": f"{self._base}{self_path}", "epoch": _EPOCH,
                "createdat": stamp, "modifiedat": stamp}

    def _group_or_404(self, collection: str, gid: str) -> Dict[str, Any]:
        if collection not in GROUP_KINDS:
            raise XRegistryNotFoundError(f"There is no {collection!r} collection in this registry.")
        group = self._registry.groups[collection].get(gid)
        if group is None:
            raise XRegistryNotFoundError(f"/{collection}/{gid} is not in this registry.")
        return group

    def _resource_or_404(self, collection: str, gid: str, resources: str, rid: str) -> Dict[str, Any]:
        group = self._group_or_404(collection, gid)
        expected = GROUP_KINDS[collection][1]
        if resources != expected:
            raise XRegistryNotFoundError(f"A {GROUP_KINDS[collection][0]} holds {expected}, not {resources}.")
        resource = (group.get(expected) or {}).get(rid)
        if resource is None:
            raise XRegistryNotFoundError(f"/{collection}/{gid}/{expected}/{rid} is not in this registry.")
        return resource

    # --- the registry ------------------------------------------------------

    def root(self, *, inline: bool = False) -> Dict[str, Any]:
        """The registry entity: ids, timestamps and, per group collection, its URL and count."""
        entity: Dict[str, Any] = {"specversion": SPEC_VERSION, "registryid": self._registry.registry_id,
                                  "name": self._registry.name}
        entity.update(self._common("/", "/", self._registry.modified))
        for collection in GROUP_KINDS:
            entity[f"{collection}url"] = f"{self._base}/{collection}"
            entity[f"{collection}count"] = len(self._registry.groups[collection])
            if inline:
                entity[collection] = self.groups(collection, inline=True)
        return entity

    def capabilities(self) -> Dict[str, Any]:
        """What this server supports: read-only, the ``inline`` flag, no pagination."""
        return {
            "apis": ["/capabilities", "/model"],
            "flags": ["inline"],
            "mutable": [],
            "pagination": False,
            "schemas": [f"xRegistry-json/{SPEC_VERSION}"],
            "specversions": [SPEC_VERSION],
        }

    def model(self) -> Dict[str, Any]:
        """The registry model: the two group types and their resource types."""
        groups: Dict[str, Any] = {}
        for collection, (singular, resources, resource_singular, has_document) in GROUP_KINDS.items():
            groups[collection] = {
                "plural": collection,
                "singular": singular,
                "resources": {resources: {"plural": resources, "singular": resource_singular,
                                          "hasdocument": has_document, "maxversions": 1}},
            }
        return {"groups": groups}

    # --- groups ------------------------------------------------------------

    def groups(self, collection: str, *, inline: bool = False) -> Dict[str, Any]:
        """A group collection: group id → group entity."""
        if collection not in GROUP_KINDS:
            raise XRegistryNotFoundError(f"There is no {collection!r} collection in this registry.")
        return {gid: self.group(collection, gid, inline=inline) for gid in sorted(self._registry.groups[collection])}

    def group(self, collection: str, gid: str, *, inline: bool = False) -> Dict[str, Any]:
        """One group: its attributes, and its resource collection's URL and count."""
        group = self._group_or_404(collection, gid)
        singular, resources, _resource_singular, _doc = GROUP_KINDS[collection]
        entity = {key: value for key, value in group.items() if key != resources}
        entity[f"{singular}id"] = gid
        entity.update(self._common(f"/{collection}/{gid}", f"/{collection}/{gid}",
                                   self._registry.stamps.get((collection, gid), _EPOCH_TIME)))
        entity[f"{resources}url"] = f"{self._base}/{collection}/{gid}/{resources}"
        entity[f"{resources}count"] = len(group.get(resources) or {})
        if inline:
            entity[resources] = self.resources(collection, gid, resources)
        return entity

    # --- resources ---------------------------------------------------------

    def resources(self, collection: str, gid: str, resources: str) -> Dict[str, Any]:
        """A resource collection: resource id → the resource's attributes (its ``$details``)."""
        group = self._group_or_404(collection, gid)
        if resources != GROUP_KINDS[collection][1]:
            raise XRegistryNotFoundError(f"A {GROUP_KINDS[collection][0]} holds {GROUP_KINDS[collection][1]}.")
        return {rid: self.details(collection, gid, resources, rid) for rid in sorted(group.get(resources) or {})}

    def _default_version(self, resource: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """The resource's default version id and version body (a message has one implied version)."""
        versions = resource.get("versions")
        if isinstance(versions, Mapping) and versions:
            vid = str(resource.get("defaultversionid") or next(iter(versions)))
            return vid, dict(versions.get(vid) or {})
        return VERSION_ID, {}

    def details(self, collection: str, gid: str, resources: str, rid: str) -> Dict[str, Any]:
        """A resource's attributes: its own and its default version's, plus the version links."""
        resource = self._resource_or_404(collection, gid, resources, rid)
        singular = GROUP_KINDS[collection][2]
        vid, version = self._default_version(resource)
        path = f"/{collection}/{gid}/{resources}/{rid}"
        entity = {key: value for key, value in resource.items() if key not in ("versions",)}
        entity.update({key: value for key, value in version.items() if key != "schema"})
        entity[f"{singular}id"] = rid
        entity["versionid"] = vid
        entity.update(self._common(path, f"{path}{DETAILS_SUFFIX}",
                                   self._registry.stamps.get((collection, gid), _EPOCH_TIME)))
        entity["isdefault"] = True
        if GROUP_KINDS[collection][3]:
            entity[f"{singular}url"] = f"{self._base}{path}"
        entity["defaultversionid"] = vid
        entity["defaultversionurl"] = f"{self._base}{path}/versions/{vid}"
        entity["versionsurl"] = f"{self._base}{path}/versions"
        entity["versionscount"] = 1
        return entity

    def document(self, collection: str, gid: str, resources: str, rid: str) -> Tuple[Any, Dict[str, str]]:
        """A schema's document (the default version's) and its ``xRegistry-*`` headers.

        Returns:
            ``(document, headers)``. The document is the JSON Schema object, or a text (an opaque
            Avro / Protobuf schema written back as read); ``None`` when the schema has only a
            ``schemaurl`` (the ``Location`` header then names it).

        Raises:
            XRegistryNotFoundError: For an unknown path, or a resource without documents (a message).
        """
        if not GROUP_KINDS.get(collection, (None, None, None, False))[3]:
            raise XRegistryNotFoundError("A message has no document; ask for its attributes instead.")
        resource = self._resource_or_404(collection, gid, resources, rid)
        vid, version = self._default_version(resource)
        return version.get("schema"), self._document_headers(collection, gid, resources, rid, vid, version)

    def _document_headers(
        self, collection: str, gid: str, resources: str, rid: str, vid: str, version: Mapping[str, Any]
    ) -> Dict[str, str]:
        """The ``xRegistry-*`` headers that carry a document's attributes."""
        singular = GROUP_KINDS[collection][2]
        path = f"/{collection}/{gid}/{resources}/{rid}"
        headers = {
            f"xRegistry-{singular}id": rid,
            "xRegistry-versionid": vid,
            "xRegistry-xid": path,
            "xRegistry-self": f"{self._base}{path}",
            "xRegistry-epoch": str(_EPOCH),
            "xRegistry-isdefault": "true",
        }
        if isinstance(version.get("schemaurl"), str):
            headers["Location"] = version["schemaurl"]
        return headers

    # --- versions ----------------------------------------------------------

    def versions(self, collection: str, gid: str, resources: str, rid: str) -> Dict[str, Any]:
        """A resource's versions collection (one version: the artifact's published version)."""
        vid, _version = self._default_version(self._resource_or_404(collection, gid, resources, rid))
        return {vid: self.version_details(collection, gid, resources, rid, vid)}

    def version_details(self, collection: str, gid: str, resources: str, rid: str, vid: str) -> Dict[str, Any]:
        """One version's attributes."""
        resource = self._resource_or_404(collection, gid, resources, rid)
        default_vid, version = self._default_version(resource)
        if vid != default_vid:
            raise XRegistryNotFoundError(f"Version {vid!r} of {rid!r} is not in this registry.")
        entity = self.details(collection, gid, resources, rid)
        path = f"/{collection}/{gid}/{resources}/{rid}/versions/{vid}"
        for key in ("defaultversionid", "defaultversionurl", "versionsurl", "versionscount"):
            entity.pop(key, None)
        entity.update(self._common(path, f"{path}{DETAILS_SUFFIX}",
                                   self._registry.stamps.get((collection, gid), _EPOCH_TIME)))
        if GROUP_KINDS[collection][3]:
            entity[f"{GROUP_KINDS[collection][2]}url"] = f"{self._base}{path}"
        return entity

    def version_document(
        self, collection: str, gid: str, resources: str, rid: str, vid: str
    ) -> Tuple[Any, Dict[str, str]]:
        """One version's document and headers (see :meth:`document`)."""
        self.version_details(collection, gid, resources, rid, vid)  # 404 for an unknown version
        return self.document(collection, gid, resources, rid)


def split_details(segment: str) -> Tuple[str, bool]:
    """Public form of :func:`_split_details`, for the routes."""
    return _split_details(segment)


def resource_ids(registry: ComposedRegistry) -> List[str]:
    """Every resource xid of the registry, sorted — a convenience for tests and logs."""
    xids = []
    for collection, (_singular, resources, _r, _d) in GROUP_KINDS.items():
        for gid, group in registry.groups[collection].items():
            xids.extend(f"/{collection}/{gid}/{resources}/{rid}" for rid in group.get(resources) or {})
    return sorted(xids)

