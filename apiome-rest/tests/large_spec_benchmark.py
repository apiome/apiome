"""Large-spec performance benchmark and gate — COA-5.11 (#7087).

Measures what the document store (COA-EPIC-5) is for: how long the classified diff, the
compatibility check, ``/v1/schema`` and an export take on very large OpenAPI revisions, cold
(nothing cached) and warm (the rendered document is in the store), and how much memory each
allocates. The numbers are held to a committed baseline and to two absolute latency targets.

What is measured
----------------

Every fixture is a *base* revision and two *head* revisions of it — a **small** change (a handful
of edits) and a **large** change (about a fifth of the classes touched). Revisions are stored as
the normalized class and property rows the OpenAPI generator reads, in an in-memory database, with
a real filesystem document store — the same :func:`app.rendered_documents.rendered_document` the
product calls, so a regression in the cache or the generator is a regression here.

Stage names are ``<operation>-<cold|warm>`` or ``<operation>-<small|large>-<cold|warm>``:

* ``schema`` — what ``GET /v1/schema/…`` does for the head revision: the rendered document, read
  whole. (The HTTP framing is not measured; it is constant per request.)
* ``diff`` — read both revisions' documents through the cache, parse, and run
  :func:`app.change_taxonomy.classify_openapi_changes` (the classified diff, COA-5.6).
* ``compat`` — the same reads, then :class:`app.compatibility_engine.CompatibilityCheckEngine`.
* ``compare`` — what the UI's Compare view fetches (COA-5.13): the members' documents of the base
  and the head (``GET /v1/versions/…/document``, :data:`KIND_OPENAPI_MEMBERS`), each read whole.
* ``export`` — the head's document from the cache, loaded as the export source
  (:func:`app.catalog_conversion.build_conversion_source`) and emitted as OpenAPI 3.1.

**Cold** starts every stage from an empty store and cache table, so the revision is generated from
its rows and written to the store. **Warm** repeats the call with the document stored. A warm run
must do no generation at all; :attr:`LargeSpecMeasurement.detail` records how many renders the warm
stages caused, and the suite fails when it is not zero.

Wall-clock and memory are measured in separate passes (:func:`measure_unbiased`): tracemalloc slows
Python several times over, so timing under it would turn a 1.5 s diff into a 6 s one and make the
latency targets meaningless.

Budgets and targets
-------------------

The baseline (``tests/scale/large_spec_budgets.json``) reuses the scale suite's comparison rules
(:func:`scale_benchmark.compare`): a stage fails when it is over ``baseline × margin`` *and* over a
noise floor. Separately, the budget file's ``targets`` are absolute: a warm diff of two large
revisions under 2 s and a warm schema read under 200 ms, enforced on every fixture marked
``enforce_targets`` (the public-API-sized ones; the 50 MB stress fixture is held to its baseline
only, because no budget of 2 s is honest for 50 MB of JSON).

Regenerate the baseline in one command::

    RUN_LARGE_SPEC_SUITE=1 pytest tests/test_large_spec_benchmark.py --update-large-spec-budgets
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, TypeVar
from unittest import mock

import app.database as database_module
from app.canonical_model import CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.change_taxonomy import classify_openapi_changes
from app.compatibility_engine import CompatibilityCheckEngine
from app.document_store import FilesystemDocumentStore
from app.emitter import load_builtin_emitters
from app.export_service import emit_canonical
from app.rendered_documents import KIND_OPENAPI, KIND_OPENAPI_MEMBERS, rendered_document
from scale_benchmark import (
    BUDGETS_PATH,
    FixtureMeasurement,
    StageMeasurement,
    _process_peak_rss_bytes,
    build_report,
)

__all__ = [
    "LARGE_BUDGETS_PATH",
    "LARGE_REPORT_PATH_ENV",
    "MAX_STAGE_PEAK_BYTES",
    "MAX_STAGE_SECONDS",
    "STAGES",
    "LargeSpecFixture",
    "LargeSpecMeasurement",
    "TargetMiss",
    "benchmark_large_spec",
    "build_large_report",
    "fixture_specs",
    "large_report_path",
    "measure_unbiased",
    "target_misses",
]

# ===========================================================================
# Vocabulary
# ===========================================================================

#: Environment variable that redirects the report artifact.
LARGE_REPORT_PATH_ENV = "LARGE_SPEC_REPORT_PATH"

#: The committed baseline, next to the scale suite's.
LARGE_BUDGETS_PATH = BUDGETS_PATH.with_name("large_spec_budgets.json")

#: Absolute ceilings per stage. Far above any sane baseline: they catch a hang or a runaway, not a
#: regression (the baseline does that). Memory is generous because a 50 MB document parses to
#: several hundred MiB of Python objects, and a diff holds two.
MAX_STAGE_SECONDS = 600.0
MAX_STAGE_PEAK_BYTES = 8 * 1024 * 1024 * 1024

#: The change sizes a diff or compatibility stage is measured for.
CHANGE_SIZES: Tuple[str, ...] = ("small", "large")

#: Every stage a fixture is measured on, in report order.
STAGES: Tuple[str, ...] = (
    "schema-cold",
    "schema-warm",
    *(f"diff-{size}-{temp}" for size in CHANGE_SIZES for temp in ("cold", "warm")),
    *(f"compat-{size}-{temp}" for size in CHANGE_SIZES for temp in ("cold", "warm")),
    "compare-cold",
    "compare-warm",
    "export-cold",
    "export-warm",
)

#: Stage → target key (in the budget file's ``targets``) that stage is held to.
TARGET_STAGES: Dict[str, str] = {
    "diff-small-warm": "warm_diff_ms",
    "diff-large-warm": "warm_diff_ms",
    "schema-warm": "warm_schema_ms",
}

#: Targets used when the budget file has none (the issue's proposal).
DEFAULT_TARGETS: Dict[str, float] = {"warm_diff_ms": 2000.0, "warm_schema_ms": 200.0}

TENANT = "large-spec-tenant"
EXPORT_TARGET = "openapi-3.1"

T = TypeVar("T")


# ===========================================================================
# Fixtures: synthetic revisions as normalized rows
# ===========================================================================


@dataclass(frozen=True)
class LargeSpecFixture:
    """One synthetic large API, described by its size.

    Attributes:
        name: The fixture's key in the budget file.
        summary: What public API it is shaped like.
        classes: Number of classes (OpenAPI component schemas).
        properties: Properties per class.
        description_bytes: Length of each class and property description. Tunes the document size
            without changing its structure.
        enforce_targets: Whether the absolute latency targets apply (see the module docstring).
        export: Whether the export stages run. The export path refuses a source over the intake
            limit (``max_decoded_bytes``, 10 MiB), so the 50 MB fixture cannot be exported and is
            measured on the cached-document stages only.
    """

    name: str
    summary: str
    classes: int
    properties: int
    description_bytes: int
    enforce_targets: bool = True
    export: bool = True

    @property
    def stages(self) -> Tuple[str, ...]:
        """The stages this fixture is measured on, in report order."""
        return STAGES if self.export else tuple(name for name in STAGES if not name.startswith("export-"))


def fixture_specs() -> List[LargeSpecFixture]:
    """The fixtures the nightly suite measures.

    Public specs (GitHub REST, Stripe, Azure) cannot be committed or fetched hermetically, so each
    is represented by a synthetic revision shaped like it: a similar count of schemas, a similar
    number of properties per schema and a similar document size. The fourth is the 50 MB stress
    revision.

    Returns:
        The fixture specs, smallest first.
    """
    return [
        LargeSpecFixture("github-rest-shaped", "GitHub REST: many mid-sized schemas", 1200, 20, 200),
        LargeSpecFixture("stripe-shaped", "Stripe: fewer schemas, wide objects", 900, 30, 150),
        LargeSpecFixture("azure-shaped", "Azure: thousands of narrow schemas", 2500, 12, 250),
        LargeSpecFixture("synthetic-50mb", "Synthetic 50 MB stress revision", 7000, 20, 300, enforce_targets=False, export=False),
    ]


def _pad(text: str, size: int) -> str:
    """Return ``text`` repeated and cut to exactly ``size`` characters."""
    return (text * (size // max(len(text), 1) + 1))[:size]


def _class_rows(
    version: str, fixture: LargeSpecFixture, *, changed: Callable[[int], bool], drop: Callable[[int], bool]
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """Build one revision's class and property rows.

    Args:
        version: A label folded into row ids, so revisions never share an id.
        fixture: The size to build.
        changed: Whether the class at an index is edited (a retyped, a removed and an added
            property) relative to the base.
        drop: Whether the class at an index is absent from the revision.

    Returns:
        ``(classes, properties_by_class_id)`` in the shape the generator's database reads return.
    """
    description = _pad("Describes one resource the service exposes. ", fixture.description_bytes)
    classes: List[Dict[str, Any]] = []
    properties: Dict[str, List[Dict[str, Any]]] = {}
    for index in range(fixture.classes):
        if drop(index):
            continue
        class_id = f"{version}-c{index}"
        classes.append(
            {"id": class_id, "name": f"Resource{index:05d}", "description": description, "schema": {"type": "object"}}
        )
        rows: List[Dict[str, Any]] = []
        edited = changed(index)
        for slot in range(fixture.properties):
            if edited and slot == 1:
                continue  # a removed property
            kind = "integer" if edited and slot == 0 else "string"  # a retyped property
            rows.append(
                {
                    "id": f"{class_id}-p{slot}",
                    "class_id": class_id,
                    "name": f"field{slot:02d}",
                    "data": {"type": kind, "description": description},
                    "parent_id": None,
                }
            )
        if edited:  # an added property
            rows.append(
                {
                    "id": f"{class_id}-added",
                    "class_id": class_id,
                    "name": "addedField",
                    "data": {"type": "boolean"},
                    "parent_id": None,
                }
            )
        properties[class_id] = rows
    return classes, properties


#: Revision labels, and which classes each edits or drops relative to the base. A *small* change
#: touches a handful of classes; a *large* one a fifth of them and drops every 50th.
_REVISIONS: Dict[str, Tuple[Callable[[int], bool], Callable[[int], bool]]] = {
    "base": (lambda _i: False, lambda _i: False),
    "small": (lambda i: i % 400 == 0, lambda i: i == 3),
    "large": (lambda i: i % 5 == 0, lambda i: i % 50 == 7),
}


class _Database:
    """The slice of the database layer the cache and the OpenAPI generator read.

    Several revisions, a document-link table that :meth:`reset_cache` empties (the "cold" state),
    and a count of generator runs (:attr:`renders`).
    """

    def __init__(self, fixture: LargeSpecFixture) -> None:
        self.versions: Dict[str, Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]] = {}
        self.ids: Dict[str, str] = {}
        for index, (label, (changed, drop)) in enumerate(_REVISIONS.items(), start=1):
            self.ids[label] = f"00000000-0000-4000-8000-{index:012d}"
            self.versions[self.ids[label]] = _class_rows(label, fixture, changed=changed, drop=drop)
        self.objects: Dict[str, Dict[str, Any]] = {}
        self.documents: Dict[Tuple[Any, ...], str] = {}
        self.renders = 0

    def reset_cache(self) -> None:
        """Forget every recorded document: the next read of any revision renders it."""
        self.objects.clear()
        self.documents.clear()

    def get_rendered_document_context(self, *, tenant_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        if tenant_id != TENANT or version_id not in self.versions:
            return None
        return {
            "id": version_id,
            "version_id": "1.0.0",
            "metadata": None,
            "content_stamp": 0,
            "published": False,
            "project_slug": "large",
            "project_description": "A large API",
            "project_metadata": None,
            "tenant_slug": "bench",
        }

    def find_version_document(self, *, tenant_id, version_id, role, content_stamp=None, generator=None,
                              generator_version=None) -> Optional[Dict[str, Any]]:
        object_id = self.documents.get((version_id, role, content_stamp, generator, generator_version))
        return dict(self.objects[object_id], object_id=object_id) if object_id else None

    def upsert_document_object(self, *, tenant_id, sha256, size_bytes, media_type, encoding, backend,
                               storage_key) -> str:
        self.objects[sha256] = {
            "sha256": sha256, "size_bytes": size_bytes, "media_type": media_type, "encoding": encoding,
        }
        return sha256

    def set_version_document(self, *, tenant_id, version_id, role, object_id, content_stamp=None,
                             generator=None, generator_version=None) -> bool:
        self.documents[(version_id, role, content_stamp, generator, generator_version)] = object_id
        return True

    def get_classes_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        self.renders += 1
        return [dict(row) for row in self.versions[version_id][0]]

    def get_properties_for_classes(self, class_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        wanted = set(class_ids)
        merged: Dict[str, List[Dict[str, Any]]] = {}
        for _classes, properties in self.versions.values():
            merged.update({cid: rows for cid, rows in properties.items() if cid in wanted})
        return {cid: list(merged.get(cid, [])) for cid in class_ids}

    def get_paths_for_version(self, version_id: str) -> list:
        return []

    def get_security_schemes_for_version(self, version_id: str) -> list:
        return []

    def get_servers_for_version(self, version_id: str) -> list:
        return []

    def get_materializable_pins_for_version(self, version_id: str) -> list:
        return []


# ===========================================================================
# Measurement
# ===========================================================================


def measure_unbiased(stage: str, prepare: Callable[[], None], call: Callable[[], T]) -> Tuple[T, StageMeasurement]:
    """Measure a call's wall-clock and peak memory in two separate passes.

    The wall-clock pass runs without tracemalloc, which would otherwise inflate it several times
    over; the memory pass repeats the call under tracemalloc. ``prepare`` runs before each pass, so
    a cold stage starts cold both times and a warm stage starts warm both times.

    Args:
        stage: The stage name to label the measurement with.
        prepare: Puts the system in the stage's starting state (empty or filled cache).
        call: The zero-argument callable to measure.

    Returns:
        ``(value, measurement)`` — the value of the timed pass, and its cost.
    """
    prepare()
    started = time.perf_counter()
    value = call()
    wall_ms = (time.perf_counter() - started) * 1000.0
    prepare()
    tracemalloc.start()
    try:
        call()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return value, StageMeasurement(stage=stage, wall_ms=wall_ms, peak_bytes=peak)


@dataclass(frozen=True)
class LargeSpecMeasurement(FixtureMeasurement):
    """A :class:`FixtureMeasurement` that also knows whether its targets apply.

    Attributes:
        enforce_targets: Whether the absolute latency targets apply to this fixture.
    """

    enforce_targets: bool = True


@contextmanager
def _revision_environment(fixture: LargeSpecFixture) -> Iterator[Tuple[_Database, FilesystemDocumentStore]]:
    """Install an in-memory database and a scratch filesystem store for one fixture.

    Args:
        fixture: The fixture whose revisions to build.

    Yields:
        ``(database, store)``; the store's directory is removed on exit.
    """
    scratch = Path(tempfile.mkdtemp(prefix="apiome-large-spec-"))
    db = _Database(fixture)
    store = FilesystemDocumentStore(path=str(scratch), prefix="apiome")
    try:
        with mock.patch.object(database_module, "db", db):
            yield db, store
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _read_spec(db: _Database, store: FilesystemDocumentStore, label: str) -> Dict[str, Any]:
    """Read one revision's OpenAPI document through the cache and parse it (what the diff reads)."""
    document = rendered_document(db.ids[label], KIND_OPENAPI, tenant_id=TENANT, database=db, store=store)
    assert document is not None, f"revision {label!r} did not render"
    return document.json()


def _read_bytes(
    db: _Database, store: FilesystemDocumentStore, label: str, kind: str = KIND_OPENAPI
) -> bytes:
    """Read one revision's rendered document whole.

    ``KIND_OPENAPI`` is what ``GET /v1/schema`` streams; ``KIND_OPENAPI_MEMBERS`` is what
    ``GET /v1/versions/…/document`` streams to the UI.
    """
    document = rendered_document(db.ids[label], kind, tenant_id=TENANT, database=db, store=store)
    assert document is not None, f"revision {label!r} did not render"
    return document.content()


def _read_compare_sides(db: _Database, store: FilesystemDocumentStore) -> int:
    """Read the two members' documents the UI's Compare view fetches; return their total size."""
    return sum(len(_read_bytes(db, store, label, KIND_OPENAPI_MEMBERS)) for label in ("base", "small"))


def _export(db: _Database, store: FilesystemDocumentStore, label: str) -> int:
    """Load a revision's document as an export source and emit it; return the emitted file count."""
    text = _read_bytes(db, store, label).decode("utf-8")
    item = {
        "id": db.ids[label],
        "slug": "large",
        "source_format": "openapi",
        "protocol": "rest",
        "format_metadata": {"sourceContent": text, "sourceLabel": "large.json"},
        "tool_versions": {},
        "metadata": {},
    }
    source = build_conversion_source(item, source_version_id=db.ids[label])
    api: CanonicalApi = source.api
    return len(emit_canonical(api, EXPORT_TARGET).files)


def benchmark_large_spec(fixture: LargeSpecFixture) -> LargeSpecMeasurement:
    """Run one fixture through every stage in :data:`STAGES`.

    Synchronous; do not call it from a running event loop.

    Args:
        fixture: The fixture to build and measure.

    Returns:
        The measurement. Its ``detail`` carries the document size, the number of generator runs the
        warm stages caused (must be 0) and the diff's change counts.
    """
    load_builtin_emitters()
    stages: Dict[str, StageMeasurement] = {}
    detail: Dict[str, Any] = {}

    with _revision_environment(fixture) as (db, store):

        def cold() -> None:
            db.reset_cache()

        def warm_up() -> None:
            for label in _REVISIONS:
                _read_bytes(db, store, label)
                _read_bytes(db, store, label, KIND_OPENAPI_MEMBERS)

        def stage(name: str, prepare: Callable[[], None], call: Callable[[], Any]) -> Any:
            renders: List[int] = []

            def counted() -> Any:
                before = db.renders
                value = call()
                renders.append(db.renders - before)
                return value

            value, stages[name] = measure_unbiased(name, prepare, counted)
            if name.endswith("-warm"):
                # The first (timed) pass: a warm stage must not run the generator at all.
                detail.setdefault("warm_renders", {})[name] = renders[0]
            return value

        warm_up()
        detail["document_bytes"] = len(_read_bytes(db, store, "base"))
        db.renders = 0

        stage("schema-cold", cold, lambda: _read_bytes(db, store, "small"))
        stage("schema-warm", warm_up, lambda: _read_bytes(db, store, "small"))

        for size in CHANGE_SIZES:

            def diff(size: str = size) -> Any:
                return classify_openapi_changes(_read_spec(db, store, "base"), _read_spec(db, store, size))

            def compat(size: str = size) -> Any:
                return CompatibilityCheckEngine.run(_read_spec(db, store, "base"), _read_spec(db, store, size))

            result = stage(f"diff-{size}-cold", cold, diff)
            stage(f"diff-{size}-warm", warm_up, diff)
            detail[f"diff_{size}_changes"] = len(result.changes)
            verdict = stage(f"compat-{size}-cold", cold, compat)
            stage(f"compat-{size}-warm", warm_up, compat)
            detail[f"compat_{size}_findings"] = len(verdict.findings)

        stage("compare-cold", cold, lambda: _read_compare_sides(db, store))
        detail["compare_bytes"] = stage("compare-warm", warm_up, lambda: _read_compare_sides(db, store))

        if fixture.export:
            emitted = stage("export-cold", cold, lambda: _export(db, store, "small"))
            stage("export-warm", warm_up, lambda: _export(db, store, "small"))
            detail["emitted_files"] = emitted

    return LargeSpecMeasurement(
        name=fixture.name,
        paradigm="rest",
        adapter_key="openapi",
        export_target=EXPORT_TARGET,
        source_bytes=int(detail["document_bytes"]),
        stages={name: stages[name] for name in fixture.stages},
        process_peak_rss_bytes=_process_peak_rss_bytes(),
        detail=detail,
        enforce_targets=fixture.enforce_targets,
    )


# ===========================================================================
# Targets and report
# ===========================================================================


@dataclass(frozen=True)
class TargetMiss:
    """One stage over an absolute latency target.

    Attributes:
        fixture: The fixture name.
        stage: The stage name.
        target: The target's key in the budget file (``warm_diff_ms`` / ``warm_schema_ms``).
        limit_ms: The target, in milliseconds.
        measured_ms: What this run measured.
    """

    fixture: str
    stage: str
    target: str
    limit_ms: float
    measured_ms: float

    def describe(self) -> str:
        """Render the miss as a one-line, reviewer-readable failure."""
        return (
            f"{self.fixture} · {self.stage}: {self.measured_ms:.0f} ms is over the "
            f"{self.target} target of {self.limit_ms:.0f} ms"
        )

    def as_dict(self) -> Dict[str, Any]:
        """Return the JSON-serializable form used by the report."""
        return {
            "fixture": self.fixture,
            "stage": self.stage,
            "target": self.target,
            "limit_ms": self.limit_ms,
            "measured_ms": round(self.measured_ms, 1),
        }


def target_misses(measurements: List[LargeSpecMeasurement], document: Dict[str, Any]) -> List[TargetMiss]:
    """Return the stages over the absolute latency targets.

    Args:
        measurements: One entry per fixture.
        document: The budget document (its ``targets`` override :data:`DEFAULT_TARGETS`).

    Returns:
        The misses; fixtures that do not ``enforce_targets`` contribute none.
    """
    targets = {**DEFAULT_TARGETS, **(document.get("targets") or {})}
    misses: List[TargetMiss] = []
    for measurement in measurements:
        if not measurement.enforce_targets:
            continue
        for stage, key in TARGET_STAGES.items():
            wall = measurement.stages[stage].wall_ms
            if wall > float(targets[key]):
                misses.append(TargetMiss(measurement.name, stage, key, float(targets[key]), wall))
    return misses


def warm_generation(measurements: List[LargeSpecMeasurement]) -> List[str]:
    """Return one line per warm stage that generated a document (there must be none)."""
    return [
        f"{m.name} · {stage}: {renders} generator run(s) on a warm cache"
        for m in measurements
        for stage, renders in (m.detail.get("warm_renders") or {}).items()
        if renders
    ]


def large_report_path() -> Path:
    """Where this run writes its report artifact (``LARGE_SPEC_REPORT_PATH`` or ``reports/``)."""
    override = os.environ.get(LARGE_REPORT_PATH_ENV)
    if override and override.strip():
        return Path(override)
    return Path(__file__).resolve().parents[1] / "reports" / "large-spec-benchmark.json"


def build_large_report(
    measurements: List[LargeSpecMeasurement],
    document: Dict[str, Any],
    regressions: List[Any],
    problems: List[str],
    breaches: List[Any],
) -> Dict[str, Any]:
    """Assemble the machine-readable report: the scale report plus targets and warm generation.

    Args:
        measurements: One entry per fixture.
        document: The budget document the run was compared against.
        regressions: Stage metrics over budget.
        problems: Structural problems with the budget file.
        breaches: Stage metrics over the absolute ceilings.

    Returns:
        The report payload.
    """
    report = build_report(measurements, document, regressions, problems, breaches)
    misses = target_misses(measurements, document)
    generated = warm_generation(measurements)
    report["totals"]["stages"] = max((len(m.stages) for m in measurements), default=0)
    report["policy"]["targets"] = {**DEFAULT_TARGETS, **(document.get("targets") or {})}
    report["policy"]["absolute_stage_seconds"] = MAX_STAGE_SECONDS
    report["policy"]["absolute_stage_peak_bytes"] = MAX_STAGE_PEAK_BYTES
    report["target_misses"] = [miss.as_dict() for miss in misses]
    report["warm_generation"] = generated
    report["passed"] = bool(report["passed"]) and not misses and not generated
    return report
