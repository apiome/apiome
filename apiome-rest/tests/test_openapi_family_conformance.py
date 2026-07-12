"""OpenAPI-family conformance matrix — MFI-30.4 (#4397).

The OpenAPI family spans Swagger 2.0 → OAS 3.2 + Arazzo across the format-detection
sniffer and the import-source SPI. This module is the regression gate: every family
fixture must agree on detect vs normalize, produce stable canonical entity counts and
fingerprints, route to publishable Projects, and — where the OpenAPI 3.1 emitter is
the inverse of the normalizer — satisfy the ``normalize(emit(normalize(doc)))`` fixed
point.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import pytest
import yaml

from app.arazzo_import_source import ArazzoImportSource
from app.canonical_model import ApiParadigm, CanonicalApi
from app.emitter import get_emitter
from app.format_detection import detect_format
from app.import_routing import ImportTarget, PUBLISHABLE_FORMATS, decide_import_routing
from app.import_source import (
    DetectionInput,
    ImportSource,
    canonical_fingerprint,
    get_import_source,
    load_builtin_import_sources,
)
from app.normalizer import get_normalizer
from app.openapi_emitter import OpenApiEmitter
from app.openapi_import_source import OpenApiImportSource
from app.openapi_normalizer import OpenApiNormalizer

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "openapi_family"


@dataclass(frozen=True)
class EntityCounts:
    """Expected canonical surface tallies for a fixture."""

    services: int
    operations: int
    types: int


@dataclass(frozen=True)
class OpenApiFamilyCase:
    """One row in the OpenAPI-family conformance matrix."""

    case_id: str
    fixture_name: str
    expected_format: str
    source_key: str
    entity_counts: EntityCounts
    emit_roundtrip: bool
    publishable: bool = True


_MATRIX: Tuple[OpenApiFamilyCase, ...] = (
    OpenApiFamilyCase(
        case_id="swagger-2.0",
        fixture_name="swagger-2.0-petstore.yaml",
        expected_format="swagger-2.0",
        source_key="openapi",
        entity_counts=EntityCounts(services=1, operations=2, types=1),
        emit_roundtrip=False,
    ),
    OpenApiFamilyCase(
        case_id="openapi-3.0",
        fixture_name="openapi-3.0-inventory.yaml",
        expected_format="openapi-3.0",
        source_key="openapi",
        entity_counts=EntityCounts(services=1, operations=2, types=1),
        emit_roundtrip=False,
    ),
    OpenApiFamilyCase(
        case_id="openapi-3.1",
        fixture_name="openapi-3.1-petstore.yaml",
        expected_format="openapi-3.1",
        source_key="openapi",
        entity_counts=EntityCounts(services=1, operations=1, types=1),
        emit_roundtrip=True,
    ),
    OpenApiFamilyCase(
        case_id="openapi-3.2",
        fixture_name="openapi-3.2-search.yaml",
        expected_format="openapi-3.2",
        source_key="openapi",
        entity_counts=EntityCounts(services=2, operations=3, types=1),
        emit_roundtrip=False,
    ),
    OpenApiFamilyCase(
        case_id="arazzo",
        fixture_name="arazzo-checkout.yaml",
        expected_format="arazzo",
        source_key="arazzo",
        entity_counts=EntityCounts(services=1, operations=2, types=0),
        emit_roundtrip=True,
        publishable=False,
    ),
)


def _load_fixture(name: str) -> dict:
    path = _FIXTURES_DIR / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _adapter_for(source_key: str) -> ImportSource:
    load_builtin_import_sources()
    return get_import_source(source_key)


def _entity_counts(model: CanonicalApi) -> EntityCounts:
    return EntityCounts(
        services=len(model.services),
        operations=len(model.operations()),
        types=len(model.types),
    )


def _normalize_via_adapter(
    adapter: ImportSource, document: dict, *, include_raw: bool = False
) -> CanonicalApi:
    return adapter.normalize(document, include_raw=include_raw)


def _assert_detect_normalize_agree(
    case: OpenApiFamilyCase,
    document: dict,
    adapter: ImportSource,
) -> CanonicalApi:
    """Both pipelines must name the same format and normalize must succeed."""
    adapter_detection = adapter.detect(DetectionInput(document=document))
    assert adapter_detection.matched, (
        f"{case.case_id}: adapter detect() did not match — detect/normalize disagreement"
    )
    assert adapter_detection.format == case.expected_format, (
        f"{case.case_id}: adapter detect format {adapter_detection.format!r} != "
        f"expected {case.expected_format!r}"
    )

    sniffer = detect_format(DetectionInput(document=document))
    assert sniffer.matched, (
        f"{case.case_id}: format_detection did not match — detect/normalize disagreement"
    )
    assert sniffer.detected is not None
    assert sniffer.detected.format == case.expected_format, (
        f"{case.case_id}: sniffer format {sniffer.detected.format!r} != "
        f"expected {case.expected_format!r}"
    )
    assert sniffer.detected.importable is True, (
        f"{case.case_id}: {case.expected_format!r} must be importable in format_detection"
    )
    assert sniffer.detected.source_key == case.source_key, (
        f"{case.case_id}: sniffer source_key {sniffer.detected.source_key!r} != "
        f"expected {case.source_key!r}"
    )

    normalizer_cls = get_normalizer(case.expected_format)
    assert normalizer_cls is not None, (
        f"{case.case_id}: no normalizer registered for detected format "
        f"{case.expected_format!r} — detect/normalize disagreement"
    )

    model = _normalize_via_adapter(adapter, document)
    assert model.format == case.expected_format, (
        f"{case.case_id}: normalized model.format {model.format!r} != "
        f"detected {case.expected_format!r} — detect/normalize disagreement"
    )
    assert model.paradigm is ApiParadigm.REST
    return model


def _assert_entity_counts(case: OpenApiFamilyCase, model: CanonicalApi) -> None:
    actual = _entity_counts(model)
    assert actual == case.entity_counts, (
        f"{case.case_id}: canonical entity counts {actual} != expected {case.entity_counts}"
    )


def _assert_fingerprint_stable(
    case: OpenApiFamilyCase,
    adapter: ImportSource,
    document: dict,
) -> None:
    first = _normalize_via_adapter(adapter, document)
    second = _normalize_via_adapter(adapter, document)
    fp_first = adapter.fingerprint(first)
    fp_second = adapter.fingerprint(second)
    assert fp_first == fp_second, (
        f"{case.case_id}: fingerprint unstable across identical normalizations"
    )
    assert fp_first == canonical_fingerprint(first), (
        f"{case.case_id}: adapter.fingerprint() disagrees with canonical_fingerprint()"
    )

    shuffled = copy.deepcopy(document)
    if "paths" in shuffled and isinstance(shuffled["paths"], dict):
        paths = shuffled["paths"]
        shuffled["paths"] = dict(reversed(list(paths.items())))
    shuffled_model = _normalize_via_adapter(adapter, shuffled, include_raw=False)
    assert adapter.fingerprint(shuffled_model) == fp_first, (
        f"{case.case_id}: fingerprint changed after harmless path reorder"
    )


def _assert_emit_roundtrip(case: OpenApiFamilyCase, model: CanonicalApi) -> None:
    emitter_cls = get_emitter("openapi-3.1")
    assert emitter_cls is OpenApiEmitter
    emitted = emitter_cls().emit(model).document
    round_tripped = OpenApiNormalizer().normalize(emitted, include_raw=False)
    assert model.model_dump() == round_tripped.model_dump(), (
        f"{case.case_id}: normalize(emit(normalize(doc))) != normalize(doc)"
    )


def _assert_routing(
    case: OpenApiFamilyCase,
    adapter: ImportSource,
    model: CanonicalApi,
) -> None:
    decision = decide_import_routing(adapter, model)
    if case.publishable:
        assert case.expected_format in PUBLISHABLE_FORMATS, (
            f"{case.case_id}: {case.expected_format!r} missing from PUBLISHABLE_FORMATS"
        )
        assert decision.target is ImportTarget.PROJECT, (
            f"{case.case_id}: routing target {decision.target!r} != PROJECT — "
            f"reason: {decision.reason}"
        )
        assert decision.publishable is True
        return

    assert decision.target is ImportTarget.CATALOG, (
        f"{case.case_id}: routing target {decision.target!r} != CATALOG — reason: {decision.reason}"
    )
    assert decision.publishable is False


@pytest.fixture(scope="module")
def openapi_adapter() -> OpenApiImportSource:
    return OpenApiImportSource()


@pytest.fixture(scope="module")
def arazzo_adapter() -> ArazzoImportSource:
    return ArazzoImportSource()


def _adapter_for_case(
    case: OpenApiFamilyCase,
    openapi_adapter: OpenApiImportSource,
    arazzo_adapter: ArazzoImportSource,
) -> ImportSource:
    if case.source_key == "openapi":
        return openapi_adapter
    if case.source_key == "arazzo":
        return arazzo_adapter
    raise AssertionError(f"unknown source_key {case.source_key!r}")


@pytest.mark.parametrize("case", _MATRIX, ids=[c.case_id for c in _MATRIX])
def test_openapi_family_conformance_matrix(
    case: OpenApiFamilyCase,
    openapi_adapter: OpenApiImportSource,
    arazzo_adapter: ArazzoImportSource,
) -> None:
    document = _load_fixture(case.fixture_name)
    adapter = _adapter_for_case(case, openapi_adapter, arazzo_adapter)

    model = _assert_detect_normalize_agree(case, document, adapter)
    _assert_entity_counts(case, model)
    _assert_fingerprint_stable(case, adapter, document)
    _assert_routing(case, adapter, model)

    if case.emit_roundtrip:
        if case.source_key == "arazzo":
            roundtrip_model = _normalize_via_adapter(adapter, document, include_raw=True)
            emitter_cls = get_emitter("arazzo")
            assert emitter_cls is not None
            emitted = emitter_cls().emit(roundtrip_model)
            text = str(emitted.files[0].content)
            from app.arazzo_emitter import validate_arazzo_document

            validate_arazzo_document(text)
        else:
            roundtrip_model = _normalize_via_adapter(adapter, document, include_raw=False)
            _assert_emit_roundtrip(case, roundtrip_model)


def test_matrix_covers_all_publishable_openapi_family_formats() -> None:
    """Every publishable OpenAPI-family format has a conformance fixture row."""
    covered = {case.expected_format for case in _MATRIX if case.publishable}
    assert covered == PUBLISHABLE_FORMATS


def test_matrix_fixture_files_exist() -> None:
    missing = [case.fixture_name for case in _MATRIX if not (_FIXTURES_DIR / case.fixture_name).is_file()]
    assert not missing, f"missing fixture files: {missing}"
