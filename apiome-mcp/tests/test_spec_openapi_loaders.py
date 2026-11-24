"""DBP-1.22 (#7205): the set-based OpenAPI loader — statements run and the rows assembled."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_invocation_fakes import RecordingPool
from apiome_mcp.spec_openapi_loaders import (
    OpenApiInputs,
    fetch_openapi_generation_inputs_async,
    load_openapi_inputs,
)
from spec_fakes import DOCUMENT_STATEMENTS, FakeSpecDb


def _load(db: FakeSpecDb, **kwargs: Any) -> tuple[OpenApiInputs, RecordingPool]:
    pool = RecordingPool(db)

    async def run() -> OpenApiInputs:
        async with pool.connection() as conn:
            return await load_openapi_inputs(conn, db.spec_id, **kwargs)

    return asyncio.run(run()), pool


@pytest.mark.parametrize("operations", [10, 1000])
def test_document_load_runs_eleven_statements_for_any_size(operations: int) -> None:
    db = FakeSpecDb(operations=operations)
    inputs, pool = _load(db)
    assert tuple(db.kinds) == DOCUMENT_STATEMENTS
    assert len(pool.statements) == 11
    assert len(inputs.paths_data) == operations // 2
    assert sum(len(p["operations"]) for p in inputs.paths_data) == operations


def test_statement_text_is_the_same_for_any_size() -> None:
    """One text per statement: a prepared statement or a plan cache entry serves every spec."""
    small, large = (FakeSpecDb(operations=n) for n in (10, 1000))
    _, small_pool = _load(small)
    _, large_pool = _load(large)
    assert [sql for sql, _ in small_pool.statements] == [sql for sql, _ in large_pool.statements]
    for sql, params in large_pool.statements:
        assert " IN (" not in sql
        assert tuple(params) == (large.spec_id,)


@pytest.mark.parametrize(
    ("part", "kinds"),
    [
        ("operations", ("paths", "operations", "descriptions")),
        ("components", ("classes", "properties", "security", "pins")),
    ],
)
def test_narrow_parts_read_only_what_they_need(part: str, kinds: tuple[str, ...]) -> None:
    db = FakeSpecDb(operations=10)
    inputs, _ = _load(db, part=part)
    assert tuple(db.kinds) == kinds
    if part == "operations":
        assert inputs.classes == [] and inputs.security_scheme_rows == []
        op = inputs.paths_data[0]["operations"][0]
        assert op["description"]["operation_id"] == "op0"
        assert (op["parameters"], op["requestBody"], op["responses"]) == ([], None, [])
    else:
        assert inputs.paths_data == [] and inputs.server_rows == []
        assert len(inputs.classes) == 2


def test_rows_are_grouped_under_their_operation_and_path() -> None:
    db = FakeSpecDb(operations=4)
    inputs, _ = _load(db)
    first, second = inputs.paths_data
    assert (first["pathname"], first["summary"]) == ("/resources00000/{id}", "Resource 0")
    get, post = first["operations"]
    assert set(get) == {"id", "operation", "description", "parameters", "requestBody", "responses"}
    assert (get["operation"], post["operation"]) == ("GET", "POST")
    assert [p["name"] for p in get["parameters"]] == ["id", "expand"]
    assert [r["status_code"] for r in post["responses"]] == ["200", "404"]
    assert get["requestBody"] is None
    # The grouping key never leaks into the rows the generator reads.
    assert "loader_path_operation_id" not in get["description"]
    assert "loader_path_operation_id" not in post["requestBody"]
    # json_agg text is parsed.
    assert post["requestBody"]["content_types"][0]["media_type"] == "application/json"
    assert [op["description"]["operation_id"] for op in second["operations"]] == ["op2", "op3"]


def test_classes_carry_string_ids_and_every_class_has_a_property_list() -> None:
    db = FakeSpecDb(operations=10)
    inputs, _ = _load(db)
    assert all(isinstance(c["id"], str) and isinstance(c["version_id"], str) for c in inputs.classes)
    assert set(inputs.all_properties) == {c["id"] for c in inputs.classes}
    assert all(len(props) == 3 for props in inputs.all_properties.values())


def test_generator_kwargs_pass_every_row_set_explicitly() -> None:
    """``None`` would make the generator read the rows itself over apiome-rest's connection."""
    kwargs = OpenApiInputs().generator_kwargs()
    assert set(kwargs) == {
        "classes",
        "all_properties",
        "paths_data",
        "security_scheme_rows",
        "server_rows",
        "component_pin_rows",
    }
    assert all(value is not None for value in kwargs.values())


def test_revision_without_paths_stops_after_the_paths_statement() -> None:
    db = FakeSpecDb(operations=0)
    inputs, _ = _load(db, part="operations")
    assert db.kinds == ["paths"]
    assert inputs.paths_data == []


def test_five_tuple_entry_point_keeps_its_shape_for_apiome_mock() -> None:
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)

    async def run() -> tuple[Any, ...]:
        async with pool.connection() as conn:
            return await fetch_openapi_generation_inputs_async(conn, db.spec_id)

    classes, all_properties, paths_data, security_rows, server_rows = asyncio.run(run())
    assert len(pool.statements) == 10  # no component pins: the tuple has no slot for them
    assert "pins" not in db.kinds
    reference, _ = _load(FakeSpecDb(operations=10))
    assert (classes, all_properties, paths_data, security_rows, server_rows) == (
        reference.classes,
        reference.all_properties,
        reference.paths_data,
        reference.security_scheme_rows,
        reference.server_rows,
    )
