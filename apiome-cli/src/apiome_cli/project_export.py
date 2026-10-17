"""``apiome projects export`` — one document holding a whole project (CLI 3.6, #3207).

The format is ``apiome.project-export`` version :data:`EXPORTER_VERSION`, documented in
``apiome-docs/docs/reference/cli-export-format.md``. This module is everything but the HTTP:

* :func:`resolve_sections` — which sections ``--include`` / ``--exclude`` select;
* :func:`select_versions` — the ``--versions`` filter (labels match with or without a ``v``);
* :class:`ExportWriter` — writes the document **section by section** and **one version at a
  time**, so memory holds one version rather than the project; with ``deterministic`` on, the
  bytes equal ``json.dumps(document, sort_keys=True, separators=(",", ":"))`` plus a newline, and
  their SHA-256 is computed as they are written;
* :func:`build_export` — fetches each section through a ``fetch(path) -> json`` callable and feeds
  the writer, so the whole pipeline is testable without a server.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO, Any, Callable, Iterable, Optional, Sequence

from apiome_cli.client import api_paths

#: Version of the export document format. Bump it on any incompatible change.
EXPORTER_VERSION = 1

#: The document's ``format`` marker.
EXPORT_FORMAT = "apiome.project-export"

#: Every section ``--include`` accepts, in the order the issue lists them.
ALL_SECTIONS: tuple[str, ...] = (
    "versions",
    "classes",
    "properties",
    "paths",
    "tags",
    "migrations",
    "data",
)

#: Sections exported when ``--include`` is not given: all but ``data``.
DEFAULT_SECTIONS: tuple[str, ...] = tuple(s for s in ALL_SECTIONS if s != "data")

#: Sections that live inside each version, so they need ``versions``.
VERSION_SCOPED: tuple[str, ...] = ("classes", "paths")

#: Why ``data`` cannot be exported yet — shown when it is asked for.
DATA_UNAVAILABLE = (
    "The 'data' section cannot be exported yet: the API has no way to list a project's data "
    "records. Leave it out (it is excluded by default)."
)


class ExportError(ValueError):
    """An option the export refuses, with a message for stderr (exit 2)."""


def _split(value: Optional[str]) -> list[str]:
    """``"a, b,,c"`` → ``["a", "b", "c"]``."""
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def resolve_sections(include: Optional[str], exclude: Optional[str]) -> tuple[str, ...]:
    """The sections to export, in :data:`ALL_SECTIONS` order.

    Args:
        include: ``--include`` (comma-separated); ``None`` means :data:`DEFAULT_SECTIONS`.
        exclude: ``--exclude`` (comma-separated), removed from the result.

    Returns:
        The selected sections.

    Raises:
        ExportError: On an unknown section name, or when ``data`` is selected.
    """
    wanted = _split(include) if include is not None else list(DEFAULT_SECTIONS)
    removed = _split(exclude)
    unknown = sorted({name for name in [*wanted, *removed] if name not in ALL_SECTIONS})
    if unknown:
        raise ExportError(
            f"Unknown section(s): {', '.join(unknown)}. Choose from: {', '.join(ALL_SECTIONS)}."
        )
    selected = tuple(s for s in ALL_SECTIONS if s in wanted and s not in removed)
    if "data" in selected:
        raise ExportError(DATA_UNAVAILABLE)
    if "versions" not in selected and any(s in selected for s in VERSION_SCOPED):
        raise ExportError("'classes' and 'paths' live inside versions; include 'versions' too.")
    return selected


def _label_key(label: Any) -> str:
    """A version label compared loosely: lower case, without a leading ``v`` before a digit."""
    text = str(label or "").strip().lower()
    if len(text) > 1 and text[0] == "v" and text[1].isdigit():
        return text[1:]
    return text


def select_versions(
    versions: Sequence[dict[str, Any]], wanted: Optional[str]
) -> list[dict[str, Any]]:
    """The versions to export, oldest first (``created_at``, then id) — a stable order.

    Args:
        versions: The project's versions, as ``GET /v1/versions/{tenant}/{project}`` returns them.
        wanted: ``--versions`` (comma-separated labels), or ``None`` for every version.

    Raises:
        ExportError: When a requested label matches no version.
    """
    ordered = sorted(versions, key=lambda v: (str(v.get("created_at") or ""), str(v.get("id"))))
    if not wanted:
        return ordered
    labels = [part.strip() for part in wanted.split(",") if part.strip()]
    keys = {_label_key(label) for label in labels}
    chosen = [v for v in ordered if _label_key(v.get("version_id")) in keys]
    found = {_label_key(v.get("version_id")) for v in chosen}
    missing = [label for label in labels if _label_key(label) not in found]
    if missing:
        raise ExportError(f"No version labelled {', '.join(repr(m) for m in missing)}.")
    return chosen


def _dumps(value: Any, deterministic: bool) -> str:
    """One JSON value, canonical (sorted keys, no spaces) when ``deterministic``."""
    return json.dumps(
        value,
        sort_keys=deterministic,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


@dataclass
class ExportCounts:
    """What the document holds, for the stderr summary."""

    versions: int = 0
    classes: int = 0
    class_properties: int = 0
    properties: int = 0
    paths: int = 0
    operations: int = 0
    tags: int = 0
    migrations: int = 0

    def summary(self) -> str:
        """``Exported 8 versions, 24 classes, …`` — every count, singular or plural."""

        def n(count: int, singular: str, plural: str) -> str:
            return f"{count:,} {singular if count == 1 else plural}"

        return "Exported " + ", ".join(
            [
                n(self.versions, "version", "versions"),
                n(self.classes, "class", "classes"),
                n(self.properties, "property", "properties"),
                n(self.paths, "path", "paths"),
                n(self.tags, "tag", "tags"),
                n(self.migrations, "migration plan", "migration plans"),
            ]
        )


class ExportWriter:
    """Write the export document incrementally, hashing the bytes as they go.

    The document is one JSON object. Its top-level members are written in key order (sorted
    when deterministic, the same order :func:`json.dumps` would use), the ``versions`` array one
    element at a time. :meth:`finish` closes the object and adds a trailing newline.

    Args:
        stream: Where the bytes go (a file, ``sys.stdout.buffer``, or a gzip stream).
        deterministic: Sort keys everywhere (default); otherwise keep the server's order.
    """

    def __init__(self, stream: IO[bytes], *, deterministic: bool = True) -> None:
        self._stream = stream
        self._deterministic = deterministic
        self._hash = hashlib.sha256()
        self._bytes = 0
        self._first_member = True
        self._first_element = True
        # The opening brace waits for the first member, so an export that fails before it has
        # anything to write (an unknown --versions label) leaves stdout empty, not a fragment.

    def _write(self, text: str) -> None:
        data = text.encode("utf-8")
        self._hash.update(data)
        self._bytes += len(data)
        self._stream.write(data)

    def _key(self, key: str) -> None:
        self._write(("{" if self._first_member else ",") + json.dumps(key) + ":")
        self._first_member = False

    def member(self, key: str, value: Any) -> None:
        """Write one top-level member whole."""
        self._key(key)
        self._write(_dumps(value, self._deterministic))

    def begin_array(self, key: str) -> None:
        """Open a top-level array member written element by element."""
        self._key(key)
        self._write("[")
        self._first_element = True

    def element(self, value: Any) -> None:
        """Append one element to the open array."""
        self._write(("" if self._first_element else ",") + _dumps(value, self._deterministic))
        self._first_element = False

    def end_array(self) -> None:
        """Close the open array."""
        self._write("]")

    def finish(self) -> None:
        """Close the document."""
        self._write(("{" if self._first_member else "") + "}\n")

    @property
    def sha256(self) -> str:
        """Hex SHA-256 of the document bytes written so far (before any compression)."""
        return self._hash.hexdigest()

    @property
    def size(self) -> int:
        """Document bytes written so far (before any compression)."""
        return self._bytes


Fetch = Callable[[str], Any]


@dataclass
class ExportPlan:
    """Everything :func:`build_export` needs besides the fetcher and the writer."""

    tenant_slug: str
    project_id: str
    sections: tuple[str, ...]
    versions_filter: Optional[str] = None
    deterministic: bool = True
    exported_at: Optional[str] = None
    counts: ExportCounts = field(default_factory=ExportCounts)


def _version_payload(fetch: Fetch, plan: ExportPlan, version: dict[str, Any]) -> dict[str, Any]:
    """One element of ``versions``: the version row, plus its classes and paths if selected."""
    payload: dict[str, Any] = {"version": version}
    version_id = version["id"]
    if "classes" in plan.sections:
        classes = fetch(api_paths.classes_with_properties_tags(plan.tenant_slug, version_id)) or []
        payload["classes"] = classes
        plan.counts.classes += len(classes)
        plan.counts.class_properties += sum(len(c.get("properties") or []) for c in classes)
    if "paths" in plan.sections:
        listed = fetch(api_paths.paths(plan.tenant_slug, version_id)) or []
        full = []
        for path in sorted(listed, key=lambda p: (str(p.get("pathname")), str(p.get("id")))):
            detail = fetch(api_paths.path_full(plan.tenant_slug, version_id, path["id"]))
            full.append(detail)
            plan.counts.operations += len((detail or {}).get("operations") or [])
        payload["paths"] = full
        plan.counts.paths += len(full)
    return payload


def iter_export(fetch: Fetch, plan: ExportPlan) -> Iterable[tuple[str, str, Any]]:
    """Yield the document as ``(kind, key, value)`` steps, in top-level key order.

    ``kind`` is ``member`` (a whole value), ``begin``/``element``/``end`` (the streamed
    ``versions`` array). Shared by the JSON writer and the in-memory YAML path.
    """
    project = fetch(api_paths.project(plan.tenant_slug, plan.project_id))
    versions: list[dict[str, Any]] = []
    if "versions" in plan.sections or "tags" in plan.sections:
        listed = fetch(api_paths.versions(plan.tenant_slug, plan.project_id)) or []
        versions = select_versions(listed, plan.versions_filter)
    exported_ids = {str(v["id"]) for v in versions}

    members: dict[str, Callable[[], Any]] = {
        "exporterVersion": lambda: EXPORTER_VERSION,
        "format": lambda: EXPORT_FORMAT,
        "project": lambda: project,
        "sections": lambda: list(plan.sections),
    }
    if plan.exported_at:
        members["exportedAt"] = lambda: plan.exported_at
    if plan.versions_filter:
        members["versionsFilter"] = lambda: [v.get("version_id") for v in versions]
    if "properties" in plan.sections:

        def properties() -> Any:
            rows = fetch(api_paths.properties(plan.tenant_slug, plan.project_id)) or []
            plan.counts.properties = len(rows)
            return rows

        members["properties"] = properties
    if "tags" in plan.sections:

        def tags() -> Any:
            class_tags = fetch(api_paths.project_tags(plan.tenant_slug, plan.project_id)) or []
            version_tags = [
                tag
                for tag in fetch(api_paths.version_tags(plan.tenant_slug, plan.project_id)) or []
                if not plan.versions_filter or str(tag.get("version_id")) in exported_ids
            ]
            plan.counts.tags = len(class_tags) + len(version_tags)
            return {"classTags": class_tags, "versionTags": version_tags}

        members["tags"] = tags
    if "migrations" in plan.sections:

        def migrations() -> Any:
            plans = (fetch(api_paths.project_migration_plans(plan.tenant_slug, plan.project_id))
                     or {}).get("plans") or []
            if plan.versions_filter:
                plans = [
                    p for p in plans
                    if str(p.get("from_version_id")) in exported_ids
                    and str(p.get("to_version_id")) in exported_ids
                ]
            plan.counts.migrations = len(plans)
            return plans

        members["migrations"] = migrations

    keys = list(members)
    if "versions" in plan.sections:
        keys.append("versions")
    if plan.deterministic:
        keys.sort()
    for key in keys:
        if key == "versions":
            yield ("begin", key, None)
            for version in versions:
                plan.counts.versions += 1
                yield ("element", key, _version_payload(fetch, plan, version))
            yield ("end", key, None)
        else:
            yield ("member", key, members[key]())


def build_export(fetch: Fetch, plan: ExportPlan, writer: ExportWriter) -> ExportCounts:
    """Stream the whole export through ``writer``. Returns the counts."""
    for kind, key, value in iter_export(fetch, plan):
        if kind == "member":
            writer.member(key, value)
        elif kind == "begin":
            writer.begin_array(key)
        elif kind == "element":
            writer.element(value)
        else:
            writer.end_array()
    writer.finish()
    return plan.counts


def build_document(fetch: Fetch, plan: ExportPlan) -> dict[str, Any]:
    """The whole export as one in-memory object (the YAML path, which cannot stream)."""
    document: dict[str, Any] = {}
    for kind, key, value in iter_export(fetch, plan):
        if kind == "member":
            document[key] = value
        elif kind == "begin":
            document[key] = []
        elif kind == "element":
            document[key].append(value)
    return _sorted(document) if plan.deterministic else document


def _sorted(value: Any) -> Any:
    """``value`` with every mapping's keys sorted (YAML keeps insertion order)."""
    if isinstance(value, dict):
        return {k: _sorted(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted(v) for v in value]
    return value


def utc_now() -> str:
    """The ``exportedAt`` stamp used only with ``--no-deterministic``."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def human_size(size: int) -> str:
    """``4404019`` → ``4.2 MiB``."""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
