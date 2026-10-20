"""Backstage and Compass import — CDG-5.5 (#5983): reading the catalogs.

Teams leaving Backstage or Atlassian Compass bring a catalog of components, systems, domains, groups
and APIs. This module is the pure half of the import: it reads a Backstage ``catalog-info.yaml`` or a
Compass export into a :class:`ParsedCatalog` — what would be staged — plus every field it could not
map. Nothing here touches the database; :mod:`app.catalog_migration_store` stages the result.

=================================  ===============================================================
Read from                          Becomes
=================================  ===============================================================
Backstage ``Component``,           a **component suggestion** (category ``component`` / ``system``
``System``, ``Domain``             / ``domain``): name, description, type, lifecycle, the system or
                                   domain it belongs to, links, owner, and its ``dependsOn`` /
                                   ``consumesApis`` as declared references
Backstage ``Group``                a **team suggestion**: display name, description, email, and the
                                   chat / on-call / docs links
Backstage ``API`` with             an **API to import** through the import pipeline, as a catalog
``spec.definition``                item; its ``spec.owner`` becomes an owner suggestion
Compass component                  a component suggestion: name, description, type, links
                                   (``CHAT_CHANNEL``, ``ON_CALL``, ``DOCUMENT``, ``REPOSITORY``, …)
                                   and ``DEPENDS_ON`` relationships as declared references
Compass ``ownerId``                a team suggestion (named from the export's ``teams`` when present)
=================================  ===============================================================

Every other field is listed as an :class:`UnmappedField` — the field's path, never its value
(annotations and custom fields can hold anything) — so the import report can say exactly what did
not come across.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml

from .declared_dependencies import DeclaredReference, backstage_name

__all__ = [
    "COMPASS_MAX_BYTES",
    "COMPASS_MAX_COMPONENTS",
    "LINK_TYPES",
    "MAX_UNMAPPED",
    "SOURCE_BACKSTAGE",
    "SOURCE_COMPASS",
    "CatalogParseError",
    "ParsedCatalog",
    "StagedApi",
    "StagedComponent",
    "StagedLink",
    "StagedTeam",
    "UnmappedField",
    "classify_link",
    "backstage_owner_ref",
    "compass_source_ref",
    "imply_backstage_teams",
    "parse_backstage_file",
    "parse_compass_export",
    "slugify",
]

#: The two catalogs this importer reads (``entity_owners.source`` and V299 ``source`` values).
SOURCE_BACKSTAGE = "backstage"
SOURCE_COMPASS = "compass"

#: The link types a component keeps (V299 ``catalog_components.links[].type``).
LINK_TYPES = ("chat", "on_call", "document", "repository", "dashboard", "other")

#: Most unmapped fields one report keeps; the report also stores how many there were in all.
MAX_UNMAPPED = 500

#: Largest Compass export accepted, and most components read from one.
COMPASS_MAX_BYTES = 5 * 1024 * 1024
COMPASS_MAX_COMPONENTS = 2000

#: Most entities read from one ``catalog-info.yaml``.
BACKSTAGE_MAX_ENTITIES = 200

#: Longest name, description and type kept (V299 column limits).
_MAX_NAME = 400
_MAX_DESCRIPTION = 4000
_MAX_TYPE = 64
_MAX_REF = 600
_MAX_URL = 2000

#: A slug, shaped like every other handle (V284 / V299).
_SLUG_SHAPE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")

#: Backstage kinds staged as components, and the category each becomes.
_COMPONENT_KINDS = {"component": "component", "system": "system", "domain": "domain"}

#: Compass link types, mapped onto :data:`LINK_TYPES`.
_COMPASS_LINK_TYPES = {
    "CHAT_CHANNEL": "chat",
    "ON_CALL": "on_call",
    "DOCUMENT": "document",
    "REPOSITORY": "repository",
    "DASHBOARD": "dashboard",
}

#: Words in a Backstage link's ``type``, ``icon`` or ``title`` that say what kind of link it is,
#: checked in this order.
_LINK_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("on_call", ("oncall", "on-call", "on_call", "pagerduty", "opsgenie")),
    ("chat", ("chat", "slack", "teams", "discord", "mattermost")),
    ("repository", ("github", "gitlab", "bitbucket", "repo", "source")),
    ("dashboard", ("dashboard", "grafana", "datadog", "kibana")),
    ("document", ("doc", "wiki", "confluence", "runbook", "readme", "handbook")),
)

#: Backstage fields this importer maps, per kind (``metadata.*`` is shared by every kind).
_BACKSTAGE_METADATA = {"name", "namespace", "title", "description", "links"}
_BACKSTAGE_SPEC: Dict[str, set] = {
    "component": {
        "type",
        "lifecycle",
        "owner",
        "system",
        "subcomponentOf",
        "providesApis",
        "consumesApis",
        "dependsOn",
    },
    "system": {"type", "owner", "domain", "dependsOn"},
    "domain": {"type", "owner", "subdomainOf"},
    "group": {"type", "profile"},
    "api": {"type", "owner", "definition"},
}
#: Backstage top-level keys this importer reads.
_BACKSTAGE_TOP = {"apiVersion", "kind", "metadata", "spec"}

#: Compass component fields this importer maps.
_COMPASS_COMPONENT = {"id", "name", "slug", "typeId", "type", "description", "ownerId", "links", "relationships"}

#: The ``$text`` / ``$openapi`` / ``$json`` / ``$yaml`` substitutions Backstage allows in
#: ``spec.definition``.
_DEFINITION_SUBSTITUTIONS = ("$text", "$openapi", "$asyncapi", "$json", "$yaml", "$graphql")


class CatalogParseError(ValueError):
    """A Compass export that cannot be read at all, with a stable code.

    Attributes:
        code: ``migration-invalid`` (not JSON, wrong shape) or ``migration-too-large``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StagedLink:
    """One link a component (or a team) carries.

    Attributes:
        type: One of :data:`LINK_TYPES`.
        url: An ``http(s)`` URL.
        title: The link's label, when it has one.
    """

    type: str
    url: str
    title: Optional[str] = None

    def as_json(self) -> Dict[str, Any]:
        """The link as stored in V299 ``links`` (``title`` omitted when empty)."""
        out: Dict[str, Any] = {"type": self.type, "url": self.url}
        if self.title:
            out["title"] = self.title
        return out


@dataclass(frozen=True)
class StagedComponent:
    """A component, system or domain, as it would be registered.

    Attributes:
        external_ref: Its reference in its own catalog (``component:default/payments``, a Compass ARI).
        name: Display name.
        slug: Suggested slug.
        category: ``component``, ``system`` or ``domain``.
        source_ref: Its declaring source (``backstage:<path>`` or ``compass:<id hash>``).
        description: Description, or ``None``.
        component_type: Backstage ``spec.type`` or the Compass type, or ``None``.
        lifecycle: Backstage ``spec.lifecycle``, or ``None``.
        parent_ref: The system or domain it belongs to, as written, or ``None``.
        links: Its links.
        owner_ref: Its owner, as written (``group:default/payments``, a Compass team ARI), or ``None``.
        provides: Backstage ``providesApis`` names (the APIs it is).
        references: What it depends on / consumes, as declared references.
    """

    external_ref: str
    name: str
    slug: str
    category: str
    source_ref: str
    description: Optional[str] = None
    component_type: Optional[str] = None
    lifecycle: Optional[str] = None
    parent_ref: Optional[str] = None
    links: Tuple[StagedLink, ...] = ()
    owner_ref: Optional[str] = None
    provides: Tuple[str, ...] = ()
    references: Tuple[DeclaredReference, ...] = ()

    def payload(self) -> Dict[str, Any]:
        """What V299 ``catalog_import_suggestions.payload`` keeps for this component."""
        return {
            "category": self.category,
            "sourceRef": self.source_ref,
            "description": self.description,
            "componentType": self.component_type,
            "lifecycle": self.lifecycle,
            "parentRef": self.parent_ref,
            "links": [link.as_json() for link in self.links],
            "ownerRef": self.owner_ref,
            "provides": list(self.provides),
            "references": [
                {"reference": ref.reference, "edgeKind": ref.edge_kind, "slug": ref.slug} for ref in self.references
            ],
        }


@dataclass(frozen=True)
class StagedTeam:
    """A team, as it would be created.

    Attributes:
        external_ref: Its reference in its own catalog (``group:default/payments``, a team ARI).
        name: Display name.
        slug: Suggested slug.
        description: Description, or ``None``.
        contact_email: Email, or ``None``.
        chat_url: Chat link, or ``None``.
        oncall_url: On-call link, or ``None``.
        docs_url: Docs link, or ``None``.
        named: ``False`` when the export only gave an id and the name was made up from it.
    """

    external_ref: str
    name: str
    slug: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    chat_url: Optional[str] = None
    oncall_url: Optional[str] = None
    docs_url: Optional[str] = None
    named: bool = True

    def payload(self) -> Dict[str, Any]:
        """What V299 ``catalog_import_suggestions.payload`` keeps for this team."""
        return {
            "description": self.description,
            "contactEmail": self.contact_email,
            "chatUrl": self.chat_url,
            "oncallUrl": self.oncall_url,
            "docsUrl": self.docs_url,
            "named": self.named,
        }


@dataclass(frozen=True)
class StagedApi:
    """A Backstage ``kind: API`` whose definition is imported through the pipeline.

    Attributes:
        external_ref: ``api:<namespace>/<name>``.
        name: Display name.
        slug: Suggested catalog-item slug.
        path: The ``catalog-info`` file that declares it.
        api_type: ``spec.type`` (openapi, asyncapi, graphql, grpc, …), or ``None``.
        definition: The definition text when it is inline, else ``None``.
        definition_path: The repository path a ``$text``-style substitution points at, else ``None``.
        owner_ref: ``spec.owner``, or ``None``.
    """

    external_ref: str
    name: str
    slug: str
    path: str
    api_type: Optional[str] = None
    definition: Optional[str] = None
    definition_path: Optional[str] = None
    owner_ref: Optional[str] = None


@dataclass(frozen=True)
class UnmappedField:
    """A field the importer read but could not map.

    Attributes:
        entity: The entity it belongs to (``component:default/payments``, ``compass:Payments``).
        field: Its path (``metadata.annotations.github.com/project-slug``).
        reason: Why it was not mapped.
    """

    entity: str
    field: str
    reason: str

    def as_json(self) -> Dict[str, str]:
        """The field as stored in V299 ``catalog_import_runs.unmapped``."""
        return {"entity": self.entity, "field": self.field, "reason": self.reason}


@dataclass
class ParsedCatalog:
    """Everything one file or export yields.

    Attributes:
        entities: How many entities were read.
        components: Component suggestions.
        teams: Team suggestions.
        apis: APIs to import (Backstage only).
        unmapped: Every field not mapped.
    """

    entities: int = 0
    components: List[StagedComponent] = field(default_factory=list)
    teams: List[StagedTeam] = field(default_factory=list)
    apis: List[StagedApi] = field(default_factory=list)
    unmapped: List[UnmappedField] = field(default_factory=list)

    def extend(self, other: "ParsedCatalog") -> None:
        """Add another file's results to this one."""
        self.entities += other.entities
        self.components.extend(other.components)
        self.teams.extend(other.teams)
        self.apis.extend(other.apis)
        self.unmapped.extend(other.unmapped)


# ---------------------------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------------------------


def slugify(text: str, fallback: str = "item") -> str:
    """A handle for a name: lowercase, ``a-z0-9-``, at most 128 characters.

    Args:
        text: The name.
        fallback: Used when nothing of the name is left.

    Returns:
        A slug matching the V299 slug shape.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:128].strip("-")
    if not slug or not _SLUG_SHAPE.match(slug):
        slug = re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-")[:128].strip("-") or "item"
    return slug


def _text(value: Any, limit: int) -> Optional[str]:
    """A trimmed string of at most ``limit`` characters, or ``None``."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _http_url(value: Any) -> Optional[str]:
    """``value`` when it is an ``http(s)`` URL, else ``None``."""
    text = _text(value, _MAX_URL)
    if text and re.match(r"^https?://[^\s]+$", text, re.IGNORECASE):
        return text
    return None


def classify_link(*words: Optional[str]) -> str:
    """Which :data:`LINK_TYPES` a Backstage link is, from its ``type``, ``icon`` and ``title``.

    Args:
        words: The link's type, icon and title (any may be ``None``).

    Returns:
        A link type; ``other`` when no word says.
    """
    haystack = " ".join(str(word or "").lower() for word in words)
    for link_type, needles in _LINK_WORDS:
        if any(needle in haystack for needle in needles):
            return link_type
    return "other"


def _list(value: Any) -> List[str]:
    """A Backstage relation value as a list of strings (a list, or one string)."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if isinstance(item, (str, int)) and str(item).strip()]
    return []


def _walk_unmapped(entity: str, prefix: str, value: Any, reason: str) -> Iterable[UnmappedField]:
    """One :class:`UnmappedField` per leaf key under an unmapped mapping (labels, annotations)."""
    if isinstance(value, Mapping) and value:
        for key in value:
            yield UnmappedField(entity, f"{prefix}.{key}", reason)
    else:
        yield UnmappedField(entity, prefix, reason)


# ---------------------------------------------------------------------------------------------
# Backstage
# ---------------------------------------------------------------------------------------------


def _backstage_ref(kind: str, metadata: Mapping[str, Any]) -> str:
    """``<kind>:<namespace>/<name>`` — the entity's reference in Backstage."""
    namespace = _text(metadata.get("namespace"), 120) or "default"
    name = _text(metadata.get("name"), 255) or "unnamed"
    return f"{kind}:{namespace}/{name}".lower()[:_MAX_REF]


def _backstage_links(entity: str, metadata: Mapping[str, Any], unmapped: List[UnmappedField]) -> List[StagedLink]:
    """``metadata.links`` as staged links; a link without an ``http(s)`` URL is listed as unmapped."""
    links: List[StagedLink] = []
    raw = metadata.get("links")
    if raw is None:
        return links
    if not isinstance(raw, list):
        unmapped.append(UnmappedField(entity, "metadata.links", "not a list"))
        return links
    for index, item in enumerate(raw):
        url = _http_url(item.get("url")) if isinstance(item, Mapping) else None
        if url is None:
            unmapped.append(UnmappedField(entity, f"metadata.links[{index}]", "no http(s) url"))
            continue
        title = _text(item.get("title"), 200)
        links.append(StagedLink(classify_link(item.get("type"), item.get("icon"), title), url, title))
    return links


def _definition(
    entity: str, path: str, spec: Mapping[str, Any], unmapped: List[UnmappedField]
) -> Tuple[Optional[str], Optional[str]]:
    """An API's ``spec.definition``: ``(inline text, None)`` or ``(None, repository path)``.

    A substitution (``$text: ./openapi.yaml``) is resolved against the ``catalog-info`` file's
    folder; a URL or a path leaving the repository is listed as unmapped.
    """
    raw = spec.get("definition")
    if isinstance(raw, str):
        return (raw, None) if raw.strip() else (None, None)
    if isinstance(raw, Mapping):
        for key in _DEFINITION_SUBSTITUTIONS:
            target = raw.get(key)
            if not isinstance(target, str) or not target.strip():
                continue
            target = target.strip()
            if re.match(r"^[a-z][a-z0-9+.-]*://", target, re.IGNORECASE):
                unmapped.append(UnmappedField(entity, f"spec.definition.{key}", "URL definitions are not fetched"))
                return (None, None)
            resolved = _join_repo_path(path, target)
            if resolved is None:
                unmapped.append(UnmappedField(entity, f"spec.definition.{key}", "path leaves the repository"))
                return (None, None)
            return (None, resolved)
    if raw is not None:
        unmapped.append(UnmappedField(entity, "spec.definition", "not text or a $text substitution"))
    return (None, None)


def _join_repo_path(base_file: str, target: str) -> Optional[str]:
    """``target`` relative to ``base_file``'s folder, normalized; ``None`` if it leaves the root."""
    parts = [part for part in str(base_file).replace("\\", "/").split("/")[:-1] if part]
    if target.startswith("/"):
        parts = []
    for piece in target.replace("\\", "/").split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(piece)
    return "/".join(parts) or None


def _backstage_references(spec: Mapping[str, Any]) -> List[DeclaredReference]:
    """``consumesApis`` (as ``consumes``) and ``dependsOn`` (as ``depends_on``), without repeats."""
    seen = set()
    references: List[DeclaredReference] = []
    for key, edge_kind in (("consumesApis", "consumes"), ("dependsOn", "depends_on")):
        for value in _list(spec.get(key)):
            name = backstage_name(value)
            if not name or (name, edge_kind) in seen:
                continue
            seen.add((name, edge_kind))
            references.append(DeclaredReference(reference=value[:512], edge_kind=edge_kind, slug=name))
    return references


def parse_backstage_file(path: str, text: str) -> ParsedCatalog:
    """Read one ``catalog-info.yaml`` (one or more YAML documents).

    Args:
        path: The file's repository path (its entities' ``source_ref`` is ``backstage:<path>``).
        text: The file's text.

    Returns:
        The staged components, teams and APIs, and every unmapped field. Malformed YAML yields one
        unmapped entry for the file and nothing else.
    """
    parsed = ParsedCatalog()
    source_ref = f"backstage:{path}"
    try:
        documents = list(yaml.safe_load_all(text or ""))
    except yaml.YAMLError:
        parsed.unmapped.append(UnmappedField(path, "(file)", "not valid YAML"))
        return parsed
    for doc in documents[:BACKSTAGE_MAX_ENTITIES]:
        if not isinstance(doc, Mapping):
            continue
        parsed.entities += 1
        kind = str(doc.get("kind") or "").strip().lower()
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), Mapping) else {}
        spec = doc.get("spec") if isinstance(doc.get("spec"), Mapping) else {}
        entity = _backstage_ref(kind or "entity", metadata)
        if kind not in _BACKSTAGE_SPEC:
            parsed.unmapped.append(UnmappedField(entity, "kind", f"kind {doc.get('kind')!r} is not imported"))
            continue
        name = _text(metadata.get("name"), 255)
        if not name:
            parsed.unmapped.append(UnmappedField(entity, "metadata.name", "missing, so the entity was skipped"))
            continue
        unmapped = parsed.unmapped
        for key in doc:
            if key not in _BACKSTAGE_TOP:
                unmapped.extend(_walk_unmapped(entity, str(key), doc[key], "not imported"))
        for key in metadata:
            if key not in _BACKSTAGE_METADATA:
                unmapped.extend(_walk_unmapped(entity, f"metadata.{key}", metadata[key], "no Apiome field"))
        for key in spec:
            if key not in _BACKSTAGE_SPEC[kind]:
                unmapped.extend(_walk_unmapped(entity, f"spec.{key}", spec[key], "no Apiome field"))
        display = _text(metadata.get("title"), _MAX_NAME) or name
        description = _text(metadata.get("description"), _MAX_DESCRIPTION)
        links = _backstage_links(entity, metadata, unmapped)
        owner = backstage_owner_ref(spec.get("owner"))
        if owner and owner.startswith("user:"):
            unmapped.append(
                UnmappedField(entity, "spec.owner", "owned by a user, not a group: Apiome owners are teams")
            )
            owner = None
        if kind == "group":
            parsed.teams.append(_backstage_team(entity, name, display, description, spec, links, unmapped))
        elif kind == "api":
            definition, definition_path = _definition(entity, path, spec, unmapped)
            if definition is None and definition_path is None:
                unmapped.append(UnmappedField(entity, "spec.definition", "no definition to import"))
                continue
            parsed.apis.append(
                StagedApi(
                    external_ref=entity,
                    name=display,
                    slug=slugify(name, "api"),
                    path=path,
                    api_type=_text(spec.get("type"), _MAX_TYPE),
                    definition=definition,
                    definition_path=definition_path,
                    owner_ref=owner,
                )
            )
        else:
            parent = spec.get("system") or spec.get("domain") or spec.get("subdomainOf")
            if kind == "component" and not parent and spec.get("subcomponentOf"):
                parent = spec.get("subcomponentOf")
            elif kind == "component" and spec.get("subcomponentOf"):
                unmapped.append(UnmappedField(entity, "spec.subcomponentOf", "only one parent is kept (spec.system)"))
            parsed.components.append(
                StagedComponent(
                    external_ref=entity,
                    name=display,
                    slug=slugify(name, kind),
                    category=_COMPONENT_KINDS[kind],
                    source_ref=source_ref,
                    description=description,
                    component_type=_text(spec.get("type"), _MAX_TYPE),
                    lifecycle=_text(spec.get("lifecycle"), _MAX_TYPE),
                    parent_ref=_text(parent, _MAX_REF),
                    links=tuple(links),
                    owner_ref=owner,
                    provides=tuple(n for n in (backstage_name(v) for v in _list(spec.get("providesApis"))) if n),
                    references=tuple(_backstage_references(spec)),
                )
            )
    if len(documents) > BACKSTAGE_MAX_ENTITIES:
        parsed.unmapped.append(
            UnmappedField(path, "(file)", f"only the first {BACKSTAGE_MAX_ENTITIES} entities are read")
        )
    return parsed


def backstage_owner_ref(value: Any) -> Optional[str]:
    """A Backstage ``spec.owner`` as a full reference: ``team-a`` → ``group:default/team-a``.

    Args:
        value: The owner as written (``team-a``, ``group:team-a``, ``group:default/team-a``,
            ``user:jdoe``).

    Returns:
        ``<kind>:<namespace>/<name>``, lowercased (kind ``group`` when none is written), or ``None``.
    """
    raw = _text(value, _MAX_REF)
    if not raw:
        return None
    kind, _, rest = raw.partition(":") if ":" in raw else ("group", ":", raw)
    namespace, _, name = rest.rpartition("/") if "/" in rest else ("default", "/", rest)
    if not name.strip():
        return None
    return f"{kind.strip() or 'group'}:{namespace.strip() or 'default'}/{name.strip()}".lower()


def imply_backstage_teams(parsed: ParsedCatalog) -> None:
    """Add a team suggestion for every owner no ``Group`` entity describes.

    Backstage lets ``spec.owner`` name a group defined elsewhere (often in an org repository), so
    an owner with no ``Group`` in the scanned files still becomes a team suggestion, named after the
    group. Call it once over every file of a branch.

    Args:
        parsed: The branch's combined parse; changed in place.
    """
    known = {team.external_ref for team in parsed.teams}
    owners = [item.owner_ref for item in [*parsed.components, *parsed.apis] if item.owner_ref]
    for owner in owners:
        if owner in known:
            continue
        known.add(owner)
        name = owner.rsplit("/", 1)[-1]
        parsed.teams.append(StagedTeam(external_ref=owner, name=name[:200], slug=slugify(name, "team"), named=False))


def _backstage_team(
    entity: str,
    name: str,
    display: str,
    description: Optional[str],
    spec: Mapping[str, Any],
    links: Sequence[StagedLink],
    unmapped: List[UnmappedField],
) -> StagedTeam:
    """A Backstage ``Group`` as a team: profile name and email, and one link of each team kind."""
    profile = spec.get("profile") if isinstance(spec.get("profile"), Mapping) else {}
    for key in profile:
        if key not in ("displayName", "email"):
            unmapped.append(UnmappedField(entity, f"spec.profile.{key}", "no Apiome field"))
    email = _text(profile.get("email"), 320)
    chosen: Dict[str, str] = {}
    for link in links:
        field_name = {"chat": "chat", "on_call": "oncall", "document": "docs"}.get(link.type)
        if field_name and field_name not in chosen:
            chosen[field_name] = link.url
        else:
            unmapped.append(
                UnmappedField(entity, f"metadata.links ({link.type})", "a team keeps one chat, on-call and docs link")
            )
    return StagedTeam(
        external_ref=entity,
        name=_text(profile.get("displayName"), 200) or display[:200],
        slug=slugify(name, "team"),
        description=description,
        contact_email=email if email and "@" in email else None,
        chat_url=chosen.get("chat"),
        oncall_url=chosen.get("oncall"),
        docs_url=chosen.get("docs"),
    )


# ---------------------------------------------------------------------------------------------
# Compass
# ---------------------------------------------------------------------------------------------


def compass_source_ref(external_ref: str) -> str:
    """The declaring source of a Compass component's edges: ``compass:<hash of its id>``.

    Keyed on the component, not the upload, so uploading a newer export replaces its edges.
    """
    return "compass:" + hashlib.sha256(external_ref.encode("utf-8")).hexdigest()[:24]


def _compass_components(document: Any) -> Optional[List[Any]]:
    """The component list in an export: ``components``, a GraphQL ``searchComponents`` response,
    or a bare list."""
    if isinstance(document, list):
        return document
    if not isinstance(document, Mapping):
        return None
    if isinstance(document.get("components"), list):
        return document["components"]
    data = document.get("data")
    compass = data.get("compass") if isinstance(data, Mapping) else None
    search = compass.get("searchComponents") if isinstance(compass, Mapping) else None
    nodes = search.get("nodes") if isinstance(search, Mapping) else None
    if isinstance(nodes, list):
        return [node.get("component", node) if isinstance(node, Mapping) else node for node in nodes]
    return None


def _relationship_target(relationship: Mapping[str, Any]) -> Optional[str]:
    """The component a ``DEPENDS_ON`` relationship points at (``endNode.id``, ``nodeId``, …)."""
    for key in ("endNode", "target"):
        node = relationship.get(key)
        if isinstance(node, Mapping) and node.get("id"):
            return str(node["id"])
    for key in ("endNodeId", "nodeId", "targetId"):
        if relationship.get(key):
            return str(relationship[key])
    return None


def parse_compass_export(raw: bytes) -> ParsedCatalog:
    """Read an Atlassian Compass export.

    Accepted shapes: ``{"components": [...], "teams": [...]}``, a GraphQL
    ``data.compass.searchComponents.nodes`` response, or a bare list of components. A component is
    ``{id, name, typeId, description, ownerId, links: [{type, url, name}], relationships: [{type,
    endNode: {id}}]}``; ``teams`` (optional) is ``[{id, displayName, description}]``.

    Args:
        raw: The uploaded bytes.

    Returns:
        The staged components and teams, and every unmapped field.

    Raises:
        CatalogParseError: ``migration-too-large`` past :data:`COMPASS_MAX_BYTES`;
            ``migration-invalid`` when it is not JSON or holds no component list.
    """
    if len(raw) > COMPASS_MAX_BYTES:
        raise CatalogParseError(
            "migration-too-large", f"A Compass export can be at most {COMPASS_MAX_BYTES // (1024 * 1024)} MB."
        )
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogParseError("migration-invalid", "The file is not JSON.") from exc
    components = _compass_components(document)
    if components is None:
        raise CatalogParseError(
            "migration-invalid", "No component list found: expected `components`, or a searchComponents response."
        )
    parsed = ParsedCatalog()
    team_names: Dict[str, Mapping[str, Any]] = {}
    if isinstance(document, Mapping) and isinstance(document.get("teams"), list):
        for team in document["teams"]:
            if isinstance(team, Mapping) and team.get("id"):
                team_names[str(team["id"])] = team
    if isinstance(document, Mapping):
        for key in document:
            if key not in ("components", "teams", "data"):
                parsed.unmapped.extend(_walk_unmapped("export", str(key), document[key], "not imported"))

    rows = [row for row in components[:COMPASS_MAX_COMPONENTS] if isinstance(row, Mapping) and row.get("id")]
    slugs: Dict[str, str] = {}
    for row in rows:
        slugs[str(row["id"])] = slugify(str(row.get("slug") or row.get("name") or ""), "component")
    owners: Dict[str, StagedTeam] = {}
    for row in rows:
        parsed.entities += 1
        external_ref = str(row["id"])[:_MAX_REF]
        name = _text(row.get("name"), _MAX_NAME) or external_ref
        entity = f"compass:{name}"
        for key in row:
            if key not in _COMPASS_COMPONENT:
                parsed.unmapped.extend(_walk_unmapped(entity, str(key), row[key], "no Apiome field"))
        links = _compass_links(entity, row.get("links"), parsed.unmapped)
        references = _compass_references(entity, row.get("relationships"), slugs, parsed.unmapped)
        owner = _text(row.get("ownerId"), _MAX_REF)
        if owner and owner not in owners:
            owners[owner] = _compass_team(owner, team_names.get(owner))
        parsed.components.append(
            StagedComponent(
                external_ref=external_ref,
                name=name,
                slug=slugs[str(row["id"])],
                category="component",
                source_ref=compass_source_ref(external_ref),
                description=_text(row.get("description"), _MAX_DESCRIPTION),
                component_type=_text(row.get("typeId") or row.get("type"), _MAX_TYPE),
                links=tuple(links),
                owner_ref=owner,
                references=tuple(references),
            )
        )
    skipped = len(components) - len(rows)
    if len(components) > COMPASS_MAX_COMPONENTS:
        parsed.unmapped.append(
            UnmappedField("export", "components", f"only the first {COMPASS_MAX_COMPONENTS} components are read")
        )
    elif skipped:
        parsed.unmapped.append(UnmappedField("export", "components", f"{skipped} entries without an id were skipped"))
    parsed.teams.extend(owners.values())
    return parsed


def _compass_links(entity: str, raw: Any, unmapped: List[UnmappedField]) -> List[StagedLink]:
    """Compass ``links`` as staged links; a type outside the mapped ones is kept as ``other``."""
    links: List[StagedLink] = []
    if raw is None:
        return links
    if not isinstance(raw, list):
        unmapped.append(UnmappedField(entity, "links", "not a list"))
        return links
    for index, item in enumerate(raw):
        url = _http_url(item.get("url")) if isinstance(item, Mapping) else None
        if url is None:
            unmapped.append(UnmappedField(entity, f"links[{index}]", "no http(s) url"))
            continue
        link_type = _COMPASS_LINK_TYPES.get(str(item.get("type") or "").upper(), "other")
        links.append(StagedLink(link_type, url, _text(item.get("name") or item.get("title"), 200)))
    return links


def _compass_references(
    entity: str, raw: Any, slugs: Mapping[str, str], unmapped: List[UnmappedField]
) -> List[DeclaredReference]:
    """``DEPENDS_ON`` relationships as ``depends_on`` references to the target's slug."""
    references: List[DeclaredReference] = []
    if raw is None:
        return references
    if not isinstance(raw, list):
        unmapped.append(UnmappedField(entity, "relationships", "not a list"))
        return references
    seen = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            continue
        rel_type = str(item.get("type") or item.get("relationshipType") or "").upper()
        if rel_type != "DEPENDS_ON":
            unmapped.append(
                UnmappedField(entity, f"relationships[{index}]", f"relationship {rel_type or '?'} is not imported")
            )
            continue
        target = _relationship_target(item)
        slug = slugs.get(target or "")
        if not slug:
            unmapped.append(UnmappedField(entity, f"relationships[{index}]", "target component is not in the export"))
            continue
        if slug in seen:
            continue
        seen.add(slug)
        references.append(DeclaredReference(reference=f"component:{slug}", edge_kind="depends_on", slug=slug))
    return references


def _compass_team(owner_id: str, team: Optional[Mapping[str, Any]]) -> StagedTeam:
    """A Compass owner as a team, named from the export's ``teams`` entry when there is one."""
    tail = owner_id.rstrip("/").rsplit("/", 1)[-1]
    name = _text((team or {}).get("displayName") or (team or {}).get("name"), 200)
    return StagedTeam(
        external_ref=owner_id,
        name=name or f"Compass team {tail[:8]}",
        slug=slugify(name or f"compass-team-{tail[:8]}", "team"),
        description=_text((team or {}).get("description"), _MAX_DESCRIPTION),
        named=bool(name),
    )
