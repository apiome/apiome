"""Archive intake of multi-file IDL sets — MFI-14.1 (#3794).

Archive intake chooses a root among the members it recognises. ``.raml``, ``.smithy``,
``.thrift`` and ``.tsp`` were not root candidates, so an archive of a RAML, Smithy, Thrift or
TypeSpec set was refused with "no document with a recognisable import format" before its adapter
ever saw it. These tests zip the fixture sets and check each resolves to its entry point.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Dict

import pytest

from app.archive_intake import rank_root_candidates, unpack_archive

_REST = Path(__file__).resolve().parents[1]
_EXAMPLES = _REST.parent / "apiome-ui" / "examples"


def _zip(directory: Path) -> bytes:
    """Zip every file under ``directory`` (paths relative to it)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(directory)))
    return buffer.getvalue()


@pytest.mark.parametrize(
    "directory, root",
    [
        (_REST / "tests/fixtures/typespec_compile/petstore", "main.tsp"),
        (_EXAMPLES / "thrift/07-orders-set", "api.thrift"),
        (_REST / "tests/fixtures/raml_amf/petstore", "api.raml"),
        (_REST / "tests/fixtures/raml_amf/library", "api.raml"),
        (_REST / "tests/fixtures/smithy_ast/weather/model", "main.smithy"),
    ],
)
def test_an_idl_set_archive_resolves_its_entry_point(directory: Path, root: str):
    unpacked = unpack_archive(_zip(directory), source_label=f"{directory.name}.zip")
    assert unpacked.root_path == root


def test_a_file_that_references_siblings_outranks_the_files_it_references():
    members: Dict[str, str] = {
        # Alphabetically first, so only the reference boost can put main.tsp ahead.
        "a-models.tsp": "namespace Shop;\nmodel Item { id: string; }\n",
        "main.tsp": 'import "./a-models.tsp";\nnamespace Shop;\nmodel Order { id: string; }\n',
    }
    ranked = rank_root_candidates(members)
    assert ranked[0].path == "main.tsp"
    assert ranked[0].score > ranked[1].score


def test_a_reference_outside_the_archive_earns_no_boost():
    members = {
        "a.thrift": 'include "../outside.thrift"\nstruct A { 1: i32 x }\n',
        "b.thrift": "struct B { 1: i32 x }\n",
    }
    ranked = {candidate.path: candidate.score for candidate in rank_root_candidates(members)}
    assert ranked["a.thrift"] == ranked["b.thrift"]
