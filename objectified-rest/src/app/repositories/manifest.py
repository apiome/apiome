from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import yaml
from jsonschema import Draft202012Validator, ValidationError

DetectedRepositorySpecFormat = Literal[
    "openapi_3_0",
    "openapi_3_1",
    "swagger_2_0",
    "asyncapi_2",
    "asyncapi_3",
    "arazzo_1",
    "json_schema",
    "graphql_sdl",
    "protobuf",
    "avro",
    "unknown_spec",
]

_MANIFEST_RELATIVE_PATH = ".objectified/repo.yaml"
_SCHEMA_RELATIVE_PATH = Path("schemas/repo-manifest.v1.json")


@dataclass(frozen=True)
class RepoManifestDefaults:
    poll_interval_sec: int | None
    branches: tuple[str, ...]


@dataclass(frozen=True)
class RepoManifestSpec:
    path: str
    format: DetectedRepositorySpecFormat | None
    poll_interval_sec: int | None


@dataclass(frozen=True)
class RepoManifest:
    version: int
    defaults: RepoManifestDefaults
    specs: tuple[RepoManifestSpec, ...]
    ignore: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryFileRow:
    path: str
    format: DetectedRepositorySpecFormat | None
    tracked: bool
    poll_interval_sec: int | None
    status: str
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RepositoryDiscoveryCandidate:
    path: str
    detected_format: DetectedRepositorySpecFormat


@dataclass(frozen=True)
class RepoManifestParseOutcome:
    manifest: RepoManifest | None
    manifest_error_row: RepositoryFileRow | None


def parse_repo_manifest(raw_manifest: str | None) -> RepoManifestParseOutcome:
    if raw_manifest is None or not raw_manifest.strip():
        return RepoManifestParseOutcome(manifest=None, manifest_error_row=None)

    try:
        parsed: Any = yaml.safe_load(raw_manifest)
    except yaml.YAMLError as exc:
        return RepoManifestParseOutcome(
            manifest=None,
            manifest_error_row=_manifest_error_row(f"invalid YAML: {exc}"),
        )

    if parsed is None:
        parsed = {}

    schema = _load_manifest_schema()
    validator = Draft202012Validator(schema)
    try:
        validator.validate(parsed)
    except ValidationError as exc:
        return RepoManifestParseOutcome(
            manifest=None,
            manifest_error_row=_manifest_error_row(_format_schema_error(exc)),
        )

    manifest = _to_repo_manifest(parsed)
    return RepoManifestParseOutcome(manifest=manifest, manifest_error_row=None)


def build_repository_file_rows(
    *,
    discoveries: Sequence[RepositoryDiscoveryCandidate],
    manifest: RepoManifest | None,
    branch_poll_interval_sec: int | None,
    manifest_error_row: RepositoryFileRow | None = None,
) -> list[RepositoryFileRow]:
    rows: list[RepositoryFileRow] = []
    if manifest_error_row is not None:
        rows.append(manifest_error_row)

    spec_by_path = {spec.path: spec for spec in (manifest.specs if manifest is not None else ())}
    default_poll_interval = manifest.defaults.poll_interval_sec if manifest is not None else None
    effective_branch_poll_interval = (
        branch_poll_interval_sec if branch_poll_interval_sec is not None else default_poll_interval
    )

    for discovery in discoveries:
        spec = spec_by_path.get(discovery.path)
        manifest_spec_poll = spec.poll_interval_sec if spec is not None else None
        rows.append(
            RepositoryFileRow(
                path=discovery.path,
                format=spec.format if spec is not None and spec.format is not None else discovery.detected_format,
                tracked=spec is not None,
                poll_interval_sec=manifest_spec_poll
                if manifest_spec_poll is not None
                else effective_branch_poll_interval,
                status="discovered",
            )
        )
    return rows


def _load_manifest_schema() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    schema_path = repo_root / _SCHEMA_RELATIVE_PATH
    with schema_path.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _to_repo_manifest(parsed: dict[str, Any]) -> RepoManifest:
    defaults = parsed.get("defaults") or {}
    specs = parsed.get("specs") or []
    ignore = parsed.get("ignore") or []

    return RepoManifest(
        version=int(parsed["version"]),
        defaults=RepoManifestDefaults(
            poll_interval_sec=defaults.get("pollIntervalSec"),
            branches=tuple(defaults.get("branches") or ()),
        ),
        specs=tuple(
            RepoManifestSpec(
                path=str(spec["path"]),
                format=spec.get("format"),
                poll_interval_sec=spec.get("pollIntervalSec"),
            )
            for spec in specs
        ),
        ignore=tuple(str(item) for item in ignore),
    )


def _manifest_error_row(message: str) -> RepositoryFileRow:
    return RepositoryFileRow(
        path=_MANIFEST_RELATIVE_PATH,
        format=None,
        tracked=True,
        poll_interval_sec=None,
        status="manifest_error",
        metadata={"error": message},
    )


def _format_schema_error(error: ValidationError) -> str:
    if error.path:
        pointer = ".".join(str(part) for part in error.path)
        return f"schema validation failed at '{pointer}': {error.message}"
    return f"schema validation failed: {error.message}"
