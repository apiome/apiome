"""The rules of ``apiome properties copy`` (CLI 6.6, #3228).

Copies library properties from one project to another in the same tenant by composing the
existing endpoints: the source and destination lists (``GET /v1/properties/{tenant}/{project}``,
which carry each property's ``description`` and ``data``), then one ``POST`` per new property — or
a ``PUT`` with ``expectedUpdatedAt`` per overwritten one (``--update``). There is no bulk endpoint.
Properties have no tags, so there is nothing to carry over beyond ``name``, ``description`` and
``data``. These functions hold the decisions, without HTTP:

* :func:`parse_names` / :func:`parse_destination` — the arguments; ``--to <tenant>/<project>``
  naming another tenant is refused (:class:`CrossTenantCopy`, exit 4);
* :func:`plan_copy` — what happens to each property: ``create``, ``update`` or ``skip``;
* :func:`dangling_refs` — ``$ref`` values that match no primitive of the tenant (exit 7, before
  anything is written).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional, Sequence
from urllib.parse import urlparse

#: The registry namespace primitive ``$id`` values live under (``apiome-rest`` ``REGISTRY_BASE_URL``).
REGISTRY_BASE_URL = "https://api.apiome.dev/types/"

#: What a planned copy does.
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_SKIP = "skip"


class CopyArgumentError(ValueError):
    """A combination of arguments the command refuses (exit 2)."""


class CrossTenantCopy(ValueError):
    """``--to`` names a project in another tenant (exit 4)."""


@dataclass(frozen=True)
class CopyItem:
    """One property's planned copy."""

    #: The source property (a list item: ``id``, ``name``, ``description``, ``data``).
    source: Mapping[str, Any]
    #: Its name in the destination (``--rename``, else the source name).
    target: str
    #: :data:`ACTION_CREATE`, :data:`ACTION_UPDATE` or :data:`ACTION_SKIP`.
    action: str
    #: The destination property with that name, when there is one.
    existing: Optional[Mapping[str, Any]] = None


def parse_names(raw: Optional[str]) -> list[str]:
    """``'amount, currency,,amount'`` → ``['amount', 'currency']`` (order kept, repeats dropped)."""
    names: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def check_arguments(names: Sequence[str], *, all_props: bool, rename: Optional[str], update: bool, skip: bool) -> None:
    """Refuse combinations that cannot work.

    Raises:
        CopyArgumentError: No names and no ``--all``, both, ``--rename`` with anything but one name,
            or ``--update`` with ``--skip-conflicts``.
    """
    if all_props and names:
        raise CopyArgumentError("Name the properties or pass --all, not both.")
    if not all_props and not names:
        raise CopyArgumentError("Name the properties to copy (comma-separated) or pass --all.")
    if rename is not None and (all_props or len(names) != 1):
        raise CopyArgumentError("--rename works with exactly one property name.")
    if rename is not None and not rename.strip():
        raise CopyArgumentError("--rename needs a name.")
    if update and skip:
        raise CopyArgumentError("Pass --update or --skip-conflicts, not both.")


def parse_destination(to: str, current_tenant: str) -> str:
    """The destination project reference from ``--to``.

    ``<project>`` is a project of the current tenant. ``<tenant>/<project>`` is accepted when
    ``<tenant>`` is the current one (any case).

    Raises:
        CrossTenantCopy: When ``<tenant>`` is another tenant.
        CopyArgumentError: When ``--to`` is empty or has more than one ``/``.
    """
    value = to.strip()
    parts = value.split("/")
    if not value or len(parts) > 2 or not all(p.strip() for p in parts):
        raise CopyArgumentError(f"--to {to!r}: use <project> or <tenant>/<project>.")
    if len(parts) == 1:
        return value
    tenant, project = (p.strip() for p in parts)
    if tenant.lower() != current_tenant.lower():
        raise CrossTenantCopy(
            f"Cannot copy to tenant {tenant!r}: properties are copied within one tenant ({current_tenant!r}). "
            "Export them and import them in the other tenant instead."
        )
    return project


def plan_copy(
    sources: Sequence[Mapping[str, Any]],
    destination: Sequence[Mapping[str, Any]],
    *,
    rename: Optional[str] = None,
    update: bool = False,
) -> list[CopyItem]:
    """What happens to each source property in the destination.

    A name the destination already has is a **conflict**: skipped by default, overwritten with
    ``update``. A source whose ``name``, ``description`` and ``data`` already equal the destination's
    is skipped either way (nothing would change).
    """
    by_name = {str(p.get("name")): p for p in destination}
    items = []
    for source in sources:
        target = rename.strip() if rename else str(source.get("name"))
        existing = by_name.get(target)
        if existing is None:
            action = ACTION_CREATE
        elif update and not _same_definition(source, existing):
            action = ACTION_UPDATE
        else:
            action = ACTION_SKIP
        items.append(CopyItem(source=source, target=target, action=action, existing=existing))
    return items


def _same_definition(source: Mapping[str, Any], existing: Mapping[str, Any]) -> bool:
    return (source.get("description") or None) == (existing.get("description") or None) and source.get(
        "data"
    ) == existing.get("data")


def iter_refs(schema: Any) -> Iterator[str]:
    """Every ``$ref`` string in a JSON Schema fragment, depth first."""
    if isinstance(schema, Mapping):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            yield ref
        for value in schema.values():
            yield from iter_refs(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from iter_refs(value)


def ref_resolves(ref: str, primitives: Sequence[Mapping[str, Any]]) -> bool:
    """Whether ``ref`` names a primitive of the tenant, or is not a primitive reference at all.

    * ``#…`` (inside the schema) and URLs outside the registry are not primitive references: ``True``;
    * a registry URL must equal a primitive's ``$id`` (``schema_id``);
    * a relative path (``std/v0/primitives/string``, ``../primitives/string``) must be the end of a
      primitive's ``$id``, ignoring leading ``./`` and ``../``.
    """
    value = ref.strip()
    if not value or value.startswith("#"):
        return True
    ids = [str(p.get("schema_id")) for p in primitives if p.get("schema_id")]
    if urlparse(value).scheme:
        if not value.startswith(REGISTRY_BASE_URL):
            return True
        return value.split("#", 1)[0] in ids
    path = value.split("#", 1)[0]
    while path.startswith(("./", "../")):
        path = path.split("/", 1)[1]
    return bool(path) and any(i == path or i.endswith("/" + path) for i in ids)


def dangling_refs(items: Sequence[CopyItem], primitives: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """``(property, $ref)`` for each reference to a primitive the tenant does not have (writes only)."""
    missing: list[tuple[str, str]] = []
    for item in items:
        if item.action == ACTION_SKIP:
            continue
        for ref in iter_refs(item.source.get("data")):
            if not ref_resolves(ref, primitives) and (item.target, ref) not in missing:
                missing.append((item.target, ref))
    return missing


def needs_primitives(items: Sequence[CopyItem]) -> bool:
    """Whether any property to write has a ``$ref`` worth checking (so the primitive list is fetched)."""
    return any(
        not ref.strip().startswith("#")
        for item in items
        if item.action != ACTION_SKIP
        for ref in iter_refs(item.source.get("data"))
    )


def request_body(item: CopyItem) -> dict[str, Any]:
    """The ``POST`` / ``PUT`` body: the source's definition under the target name.

    An absent description is sent as ``""`` on an update, which clears the destination's.
    """
    description = item.source.get("description") or None
    body: dict[str, Any] = {"name": item.target, "description": description, "data": item.source.get("data") or {}}
    if item.action == ACTION_UPDATE:
        body["description"] = description or ""
        if item.existing and item.existing.get("updated_at"):
            body["expectedUpdatedAt"] = item.existing["updated_at"]
    return body


def render_plan(items: Sequence[CopyItem], *, source_project: str, destination: str) -> str:
    """The ``--dry-run`` listing: one ``source → target  action`` row per property."""
    lines = [f"Copy from {source_project} → {destination}:"]
    width = max((len(str(i.source.get("name"))) for i in items), default=0)
    for item in items:
        note = {ACTION_CREATE: "create", ACTION_UPDATE: "update (exists; --update)", ACTION_SKIP: "skip"}[item.action]
        if item.action == ACTION_SKIP and item.existing is not None:
            note = "skip (exists; pass --update to overwrite)"
        lines.append(f"  {str(item.source.get('name')).ljust(width)}  → {item.target}  {note}")
    return "\n".join(lines)


def render_summary(results: Sequence[tuple[CopyItem, str]], *, source_project: str, destination: str) -> str:
    """The closing line(s) after the copy.

    Args:
        results: Each item with its outcome: ``created``, ``updated``, ``skipped`` or ``failed: …``.
    """
    if len(results) == 1 and results[0][1] == "created":
        item = results[0][0]
        renamed = f" as '{item.target}'" if item.target != item.source.get("name") else ""
        return f"✔ Copied '{item.source.get('name')}'{renamed} from {source_project} → {destination}."
    count = {key: sum(1 for _, r in results if r.startswith(key)) for key in ("created", "updated", "skipped", "failed")}
    copied = count["created"] + count["updated"]
    mark = "✘" if count["failed"] else "✔"
    noun = "property" if copied == 1 else "properties"
    line = f"{mark} Copied {copied} {noun} from {source_project} → {destination}"
    extra = [f"{count[k]} {k}" for k in ("updated", "skipped", "failed") if count[k]]
    lines = [line + (f" ({', '.join(extra)})." if extra else ".")]
    skipped = [i.target for i, r in results if r == "skipped"]
    if skipped:
        lines.append(f"  Skipped (already in {destination}): {', '.join(skipped)}")
    lines += [f"  {i.target}: {r.removeprefix('failed: ')}" for i, r in results if r.startswith("failed")]
    return "\n".join(lines)
