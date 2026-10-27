#!/usr/bin/env python3
"""Record Confluent Schema Registry verdicts for the Avro compatibility cases — MFI-12.4 (#3785).

``tests/fixtures/avro_compatibility/cases.json`` lists Avro schema changes; this script asks a live
Confluent Schema Registry for its verdict on each one under each listed level and writes the
answers to ``recordings.json`` next to it. ``tests/test_avro_compatibility.py`` replays them
offline against :mod:`app.avro_compatibility`.

For every case and level it uses a fresh subject (``<case id>--<level>``): sets the subject's level
to ``NONE``, registers the case's versions oldest first, sets the level under test, then asks
``POST /compatibility/subjects/{subject}/versions?verbose=true`` about the candidate. A case with more
than one version is also checked against version 1 alone (``…/versions/1``), recorded as
``<level>@1``.

A throwaway registry is enough. With Docker::

    docker run -d --rm --name kafka --network host apache/kafka:3.8.0
    docker run -d --rm --name schema-registry --network host \\
      -e SCHEMA_REGISTRY_HOST_NAME=localhost \\
      -e SCHEMA_REGISTRY_LISTENERS=http://127.0.0.1:18081 \\
      -e SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS=PLAINTEXT://localhost:9092 \\
      confluentinc/cp-schema-registry:7.7.1
    python scripts/record_avro_compatibility_fixtures.py --registry http://127.0.0.1:18081

Re-running against a registry that already holds the subjects is safe: each subject is
permanently deleted first.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import httpx

_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "avro_compatibility"
_MEDIA_TYPE = "application/vnd.schemaregistry.v1+json"


def _call(client: httpx.Client, method: str, path: str, body: Any = None) -> Any:
    response = client.request(method, path, json=body, headers={"Content-Type": _MEDIA_TYPE})
    if response.status_code >= 400 and response.status_code != 404:
        raise SystemExit(f"{method} {path} → {response.status_code}: {response.text}")
    return response.json() if response.content else None


def _record_case(client: httpx.Client, case: Dict[str, Any], level: str, version: str = "") -> Dict[str, Any]:
    subject = f"{case['id']}--{level}"
    _call(client, "DELETE", f"/subjects/{subject}")
    _call(client, "DELETE", f"/subjects/{subject}?permanent=true")
    _call(client, "PUT", f"/config/{subject}", {"compatibility": "NONE"})
    for schema in case["versions"]:
        _call(client, "POST", f"/subjects/{subject}/versions", {"schema": json.dumps(schema)})
    _call(client, "PUT", f"/config/{subject}", {"compatibility": level})
    path = f"/compatibility/subjects/{subject}/versions{'/' + version if version else ''}?verbose=true"
    verdict = _call(client, "POST", path, {"schema": json.dumps(case["candidate"])})
    return {"is_compatible": verdict["is_compatible"], "messages": verdict.get("messages", [])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", required=True, help="Base URL of a Confluent Schema Registry.")
    args = parser.parse_args()
    cases = json.loads((_FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]
    with httpx.Client(base_url=args.registry.rstrip("/"), timeout=30) as client:
        registry_version = _call(client, "GET", "/v1/metadata/version") or {}
        recordings: Dict[str, Dict[str, Any]] = {}
        for case in cases:
            verdicts = {level: _record_case(client, case, level) for level in case["levels"]}
            if len(case["versions"]) > 1:
                # ``<level>@1``: the same check against version 1 only (``…/versions/1``).
                verdicts.update({f"{level}@1": _record_case(client, case, level, "1") for level in case["levels"]})
            recordings[case["id"]] = verdicts
    out = {
        "_comment": "Recorded by scripts/record_avro_compatibility_fixtures.py; do not edit by hand.",
        "registry": registry_version.get("version"),
        "recordings": recordings,
    }
    (_FIXTURES / "recordings.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {sum(len(v) for v in recordings.values())} verdicts from Schema Registry {out['registry']}")


if __name__ == "__main__":
    main()
