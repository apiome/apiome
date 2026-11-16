#!/usr/bin/env python3
"""Record descriptor sets and ``buf breaking`` verdicts for the Protobuf category cases — XPC-4.3 (#5747).

``tests/fixtures/proto_breaking_categories/cases.json`` lists one ``.proto`` change per case. For
every case this script compiles both sides with ``buf build`` and runs ``buf breaking`` under each
of the four categories, then writes ``recordings.json`` next to it:

* ``descriptors`` — each side's target ``FileDescriptorSet`` (base64), so
  ``tests/test_proto_breaking_categories.py`` grades the structural rules without ``buf``;
* ``buf`` — the ``buf breaking`` rule types reported per category, so the test checks that the
  structural rules agree with ``buf`` or that the case lists the disagreement.

It needs the bundled ``buf`` (or ``APIOME_BUF_BIN`` pointing at one)::

    APIOME_BUF_BIN=/path/to/buf uv run python scripts/record_proto_breaking_fixtures.py
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, List

from google.protobuf import descriptor_pb2

from app.proto_breaking import BufBreakingStrictness, run_buf_breaking
from app.proto_descriptor import ProtoFile, compile_proto_descriptor_set

_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "proto_breaking_categories"


def _files(side: Dict[str, str]) -> List[ProtoFile]:
    """A case side's ``{path: source}`` as :class:`ProtoFile`\\s, in path order."""
    return [ProtoFile(path=path, content=content) for path, content in sorted(side.items())]


async def _descriptor(side: Dict[str, str]) -> str:
    """Compile a side and return its target files' ``FileDescriptorSet`` as base64."""
    compiled = await compile_proto_descriptor_set(_files(side))
    targets = {f.name for f in compiled.target_files}
    out = descriptor_pb2.FileDescriptorSet()
    out.file.extend(f for f in compiled.proto.file if f.name in targets)
    return base64.b64encode(out.SerializeToString(deterministic=True)).decode("ascii")


async def _record_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Compile both sides of ``case`` and run ``buf breaking`` under every category."""
    verdicts: Dict[str, List[str]] = {}
    for category in BufBreakingStrictness:
        result = await run_buf_breaking(_files(case["new"]), _files(case["old"]), strictness=category)
        rules = sorted({change.rule.rsplit(".", 1)[-1].upper() for change in result.changes})
        verdicts[category.value] = rules
    return {
        "descriptors": {"old": await _descriptor(case["old"]), "new": await _descriptor(case["new"])},
        "buf": verdicts,
    }


async def _main() -> None:
    cases = json.loads((_FIXTURES / "cases.json").read_text())["cases"]
    recordings = {case["id"]: await _record_case(case) for case in cases}
    target = _FIXTURES / "recordings.json"
    target.write_text(json.dumps(recordings, indent=2, sort_keys=True) + "\n")
    print(f"recorded {len(recordings)} cases → {target}")


if __name__ == "__main__":
    asyncio.run(_main())
