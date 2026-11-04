"""Export git delivery: the rules — MFX-38.1 (#4328).

An export job (MFX-4.x) ends with a download. Git delivery sends the same bundle where specs live: a
directory of the consumer's repository, on a branch with a **pull request** (or as a **direct
commit** to a branch), the pull request carrying the export's fidelity summary and a link to the
full report. This module is the pure half — no database, no network:

* **The request** (:class:`GitDeliveryRequest`, :func:`normalize_request`) — which registered
  repository, which directory, which base branch, and ``pr`` or ``commit``.
* **The files** (:func:`bundle_files_from_emit`, :func:`bundle_files_from_artifact`,
  :func:`delivery_files`) — every file the export produced at its bundle-relative path, so a
  multi-file bundle lands as the same directory tree, plus a delivery manifest
  (``<path>/.apiome/export-delivery.json``) naming them. The manifest is what lets a later delivery
  remove a file the export no longer produces while never touching a file Apiome did not write
  (the SDK-4.2 rule, :func:`app.sdk_git_delivery_changes.plan_changes`).
* **The branch** (:func:`export_branch_name`) — one per project, target and path, so a re-export
  updates the same branch and the same pull request instead of opening another.
* **The words** (:func:`pull_request_title`, :func:`pull_request_body`, :func:`commit_message`) —
  deterministic (no clock), so re-delivering the same job writes nothing.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from .sdk_git_delivery_changes import DeliveryFile, join_repo_path
from .sdk_git_delivery_targets import (
    GitDeliveryTargetError,
    normalize_base_branch,
    normalize_target_path,
    ref_name_problem,
    ref_segment,
)

__all__ = [
    "BRANCH_PREFIX",
    "DELIVERY_MODES",
    "EXPORT_DELIVERY_MANIFEST_SCHEMA_VERSION",
    "MANIFEST_RELATIVE_PATH",
    "PULL_REQUEST_MARKER",
    "BundleFile",
    "DeliverySubject",
    "ExportGitDeliveryRequestError",
    "GitDeliveryRequest",
    "NormalizedRequest",
    "bundle_files_from_artifact",
    "bundle_files_from_emit",
    "commit_message",
    "delivery_files",
    "export_branch_name",
    "export_code",
    "fidelity_summary",
    "normalize_request",
    "pull_request_body",
    "pull_request_title",
    "report_url",
]

#: Every delivery branch starts with this, so a base branch can never be one of them.
BRANCH_PREFIX = "apiome/export-"
BRANCH_MAX_CHARS = 200
#: ``pr``: a delivery branch and one pull request it keeps current. ``commit``: straight onto the base.
DELIVERY_MODES = ("pr", "commit")
#: The manifest's addressable shape.
EXPORT_DELIVERY_MANIFEST_SCHEMA_VERSION = "export.git-delivery.v1"
#: Where the manifest lives, relative to the target path.
MANIFEST_RELATIVE_PATH = ".apiome/export-delivery.json"
#: The first line of every pull request body, so a reader (and a test) knows Apiome wrote it.
PULL_REQUEST_MARKER = "<!-- apiome:export-git-delivery -->"
#: GitHub refuses a pull request body longer than 65,536 characters.
PULL_REQUEST_BODY_MAX_CHARS = 60_000
#: How many changed files the pull request body lists before folding the rest into a count.
BODY_FILE_ROWS = 50
#: The bundle manifest names :func:`app.export_job_engine.build_export_zip` may add at the zip root.
_BUNDLE_MANIFEST_NAMES = ("manifest.json", "export-manifest.json")
#: The codes the reused SDK-4.2 client and target helpers raise, re-prefixed for this channel.
_SDK_PREFIX = "sdk-git-delivery-"
_EXPORT_PREFIX = "export-git-delivery-"


class ExportGitDeliveryRequestError(ValueError):
    """A delivery request that cannot be accepted.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid export git delivery request")


class GitDeliveryRequest(BaseModel):
    """Where to deliver an export: ``POST …/jobs/{job_id}/deliveries/git``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    repository_id: str = Field(
        alias="repositoryId",
        description="A repository registered in this workspace through a linked GitHub account "
        "(`GET /v1/tenants/{tenant}/repositories`). Its linked account is the credential.",
    )
    target_path: str = Field(
        default="",
        alias="targetPath",
        description="Directory inside the repository the bundle is written under (`specs/orders`). "
        "Empty means the repository root. A multi-file bundle keeps its own directory tree below it.",
    )
    base_branch: Optional[str] = Field(
        default=None,
        alias="baseBranch",
        description="The branch the pull request targets (mode `pr`) or the commit lands on (mode "
        "`commit`). Empty means the repository's default branch.",
    )
    mode: Literal["pr", "commit"] = Field(
        default="pr",
        description="`pr` (default): commit to a delivery branch and open — or update — one pull "
        "request. `commit`: commit straight onto the base branch, fast-forward only.",
    )


@dataclass(frozen=True)
class NormalizedRequest:
    """A validated request.

    Attributes:
        repository_id: The registered repository.
        target_path: The normalised directory (``''`` for the root).
        base_branch: The base branch, or ``None`` for the repository's default.
        mode: ``pr`` or ``commit``.
    """

    repository_id: str
    target_path: str
    base_branch: Optional[str]
    mode: str


def normalize_request(request: GitDeliveryRequest) -> NormalizedRequest:
    """Validate and normalise a delivery request.

    Args:
        request: The request body.

    Returns:
        The :class:`NormalizedRequest`.

    Raises:
        ExportGitDeliveryRequestError: For a blank repository, a path outside the repository or into
            ``.git``, an illegal branch name, or a base branch that is one of Apiome's own delivery
            branches (a pull request into one would rewrite its own base).
    """
    problems: List[str] = []
    repository_id = (request.repository_id or "").strip()
    if not repository_id:
        problems.append("repositoryId is required")
    target_path = ""
    try:
        target_path = normalize_target_path(request.target_path)
    except GitDeliveryTargetError as exc:
        problems.extend(exc.errors)
    base_branch: Optional[str] = None
    try:
        base_branch = normalize_base_branch(request.base_branch)
    except GitDeliveryTargetError as exc:
        problems.extend(exc.errors)
    if base_branch and base_branch.startswith(BRANCH_PREFIX):
        problems.append(
            f"baseBranch cannot be one of Apiome's own export delivery branches ({BRANCH_PREFIX}…): a "
            "delivery force-updates those"
        )
    if problems:
        raise ExportGitDeliveryRequestError(*problems)
    return NormalizedRequest(repository_id=repository_id, target_path=target_path, base_branch=base_branch,
                             mode=request.mode)


def export_code(code: str) -> str:
    """Re-prefix a code raised by the reused SDK-4.2 client or target helpers for this channel.

    Args:
        code: ``sdk-git-delivery-push-rejected`` …

    Returns:
        ``export-git-delivery-push-rejected`` …; any other code unchanged.
    """
    return _EXPORT_PREFIX + code[len(_SDK_PREFIX):] if code.startswith(_SDK_PREFIX) else code


# -------------------------------------------------------------------------------------------
# The branch
# -------------------------------------------------------------------------------------------


def export_branch_name(artifact_slug: Optional[str], target: Optional[str], target_path: str) -> str:
    """The delivery branch for one artifact, export target and repository path.

    Deterministic, so a re-export of the same artifact to the same place finds the branch — and the
    pull request — the last delivery wrote. The version is deliberately *not* part of it: a new
    version updates the open pull request rather than opening another. A short digest of the path
    keeps two deliveries of one artifact into different directories of one repository apart.

    Args:
        artifact_slug: The project's slug (or the artifact id).
        target: The export target (``openapi-3.1``), or ``multi`` for a multi-target job.
        target_path: The normalised repository path.

    Returns:
        ``apiome/export-orders-openapi-3.1`` (repository root) or
        ``apiome/export-orders-openapi-3.1-3f2a9c`` (a sub-directory). Always a legal ref name of
        at most :data:`BRANCH_MAX_CHARS` characters.
    """
    name = f"{BRANCH_PREFIX}{ref_segment(artifact_slug, 'artifact')}-{ref_segment(target, 'export')}"
    if target_path:
        name += "-" + hashlib.sha256(target_path.encode("utf-8")).hexdigest()[:6]
    name = name[:BRANCH_MAX_CHARS].rstrip(".-")
    assert ref_name_problem(name) is None, name  # ref_segment only ever yields legal pieces
    return name


# -------------------------------------------------------------------------------------------
# The files
# -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BundleFile:
    """One file of an export bundle.

    Attributes:
        path: Bundle-relative path (``orders/openapi.yaml``).
        text: UTF-8 content.
    """

    path: str
    text: str


def _safe_relative(path: str) -> Optional[str]:
    """A bundle path that cannot climb out of the target directory, or ``None``."""
    raw = (path or "").replace("\\", "/")
    segments = [segment for segment in raw.split("/") if segment]
    if not segments or any(segment in (".", "..") for segment in segments):
        return None
    if any(segment.lower() == ".git" for segment in segments) or raw.startswith("/"):
        return None
    return "/".join(segments)


def bundle_files_from_emit(files: Iterable[Tuple[str, str]]) -> List[BundleFile]:
    """The bundle files from an export's emitted ``(path, serialized text)`` pairs.

    Args:
        files: Each emitted file's bundle-relative path and serialized content.

    Returns:
        The files in path order, unsafe paths dropped.
    """
    out = {}
    for path, text in files:
        safe = _safe_relative(path)
        if safe is not None:
            out[safe] = BundleFile(safe, text)
    return [out[path] for path in sorted(out)]


def bundle_files_from_artifact(
    body: Union[str, bytes], *, media_type: Optional[str], listed_paths: Sequence[str], multi_target: bool
) -> List[BundleFile]:
    """The bundle files from a stored download artifact (any instance can read it).

    Args:
        body: A single file's text, or a zip bundle's bytes.
        media_type: The artifact's media type.
        listed_paths: The file paths the job result lists (``result.files``).
        multi_target: Whether the job exported several targets (its zip holds one directory per
            target, which is kept).

    Returns:
        The files in path order. A zip's own bundle manifest is left out: the delivery commits a
        manifest of its own.

    Raises:
        ValueError: When a zip cannot be read or holds a file that is not UTF-8 text.
    """
    if isinstance(body, str):
        path = listed_paths[0] if listed_paths else "export.txt"
        return bundle_files_from_emit([(path, body)])
    if (media_type or "").split(";")[0].strip() != "application/zip" and not body.startswith(b"PK"):
        path = listed_paths[0] if listed_paths else "export.txt"
        return bundle_files_from_emit([(path, body.decode("utf-8"))])
    listed = set(listed_paths)
    pairs: List[Tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if not multi_target and listed and name not in listed:
                continue
            if "/" not in name and (name in _BUNDLE_MANIFEST_NAMES or name.startswith("export-manifest-")):
                if multi_target or name not in listed:
                    continue
            pairs.append((name, archive.read(info).decode("utf-8")))
    return bundle_files_from_emit(pairs)


@dataclass(frozen=True)
class DeliverySubject:
    """What is being delivered — the facts the manifest, the branch and the pull request name.

    Attributes:
        tenant_slug: The tenant.
        job_id: The export job.
        artifact_id: The exported artifact.
        artifact_slug: Its slug (the project's), or ``None``.
        artifact_name: Its human name, or ``None``.
        version_record_id: The exported revision.
        version_label: Its version label.
        target: The resolved export target, or ``multi``.
        targets: Every target of a multi-target job.
        snapshot_hash: The export's source snapshot hash (MFX-3.x), for provenance.
        fidelity: The export's fidelity summary (:func:`fidelity_summary`).
        report_url: Where the full fidelity report opens.
    """

    tenant_slug: str
    job_id: str
    artifact_id: str
    artifact_slug: Optional[str]
    artifact_name: Optional[str]
    version_record_id: Optional[str]
    version_label: Optional[str]
    target: str
    targets: Tuple[str, ...]
    snapshot_hash: Optional[str]
    fidelity: Dict[str, Any]
    report_url: Optional[str]


def _manifest(subject: DeliverySubject, files: Sequence[BundleFile]) -> str:
    """The delivery manifest: provenance and one ``{path, sha256}`` per file. No clock, no job id."""
    document = {
        "schemaVersion": EXPORT_DELIVERY_MANIFEST_SCHEMA_VERSION,
        "notice": (
            "Generated by Apiome (MFX-38.1 export git delivery). The files listed here are rewritten "
            "on every delivery; a file listed here that a later export no longer produces is removed. "
            "Files not listed here are never touched."
        ),
        "artifact": subject.artifact_slug or subject.artifact_id,
        "version": subject.version_label,
        "target": subject.target,
        "snapshotHash": subject.snapshot_hash,
        "fidelity": subject.fidelity,
        "files": [
            {"path": item.path, "sha256": hashlib.sha256(item.text.encode("utf-8")).hexdigest()}
            for item in files
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def delivery_files(subject: DeliverySubject, files: Sequence[BundleFile], target_path: str) -> List[DeliveryFile]:
    """Every file a delivery commits, placed under the target directory.

    Args:
        subject: What is being delivered.
        files: The bundle's files, at bundle-relative paths.
        target_path: The normalised repository path.

    Returns:
        The bundle's files plus the manifest, in path order. A multi-file bundle keeps its directory
        tree below the target path.
    """
    out = [DeliveryFile(join_repo_path(target_path, item.path), item.text, "export") for item in files]
    out.append(DeliveryFile(join_repo_path(target_path, MANIFEST_RELATIVE_PATH), _manifest(subject, files),
                            "manifest"))
    return sorted(out, key=lambda item: item.path)


# -------------------------------------------------------------------------------------------
# The words
# -------------------------------------------------------------------------------------------


def fidelity_summary(fidelity: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The part of an export's fidelity envelope a pull request and a run record carry.

    Args:
        fidelity: ``ExportJobResult.fidelity`` (or one target's, for a multi-target job), as JSON.

    Returns:
        ``{tier, preservedPercent, total, preserved, dropped, approximated, synthesized, headline}``
        — what is known; an empty dict when nothing is.
    """
    if not isinstance(fidelity, Mapping):
        return {}
    summary = fidelity.get("summary") if isinstance(fidelity.get("summary"), Mapping) else {}
    advisory = fidelity.get("advisory") if isinstance(fidelity.get("advisory"), Mapping) else {}
    out: Dict[str, Any] = {}
    for key, name in (("tier", "tier"), ("preserved_percent", "preservedPercent"), ("total", "total"),
                      ("preserved", "preserved"), ("dropped", "dropped"), ("approximated", "approximated"),
                      ("synthesized", "synthesized")):
        if summary.get(key) is not None:
            out[name] = summary[key]
    headline = advisory.get("headline") or advisory.get("message")
    if headline:
        out["headline"] = str(headline)
    return out


def report_url(ui_public_url: Optional[str], subject_artifact: str, version_record_id: Optional[str],
               target: Optional[str]) -> Optional[str]:
    """Where the export's full fidelity report opens: Export studio's review step for the same export.

    Args:
        ui_public_url: The public base URL of apiome-ui (``APIOME_UI_PUBLIC_URL``).
        subject_artifact: The exported artifact id.
        version_record_id: The exported revision.
        target: The export target (omitted for a multi-target job).

    Returns:
        ``https://…/ade/dashboard/export/studio?artifact=…&version=…&target=…&step=review``, or
        ``None`` when the UI address is unknown.
    """
    base = (ui_public_url or "").strip().rstrip("/")
    if not base:
        return None
    from urllib.parse import urlencode  # noqa: PLC0415

    params = {"artifact": subject_artifact}
    if version_record_id:
        params["version"] = version_record_id
    if target and target != "multi":
        params["target"] = target
    params["step"] = "review"
    return f"{base}/ade/dashboard/export/studio?{urlencode(params)}"


def _label(subject: DeliverySubject) -> str:
    name = subject.artifact_name or subject.artifact_slug or subject.artifact_id
    return f"{name} {subject.version_label}" if subject.version_label else name


def pull_request_title(subject: DeliverySubject) -> str:
    """``Apiome export: Orders API 1.4.0 → openapi-3.1``."""
    targets = ", ".join(subject.targets) if subject.target == "multi" and subject.targets else subject.target
    return f"Apiome export: {_label(subject)} → {targets}"[:250]


def commit_message(subject: DeliverySubject) -> str:
    """The commit's message: the title, then the provenance."""
    lines = [pull_request_title(subject), ""]
    lines.append(f"Exported by Apiome from {subject.artifact_slug or subject.artifact_id}"
                 + (f" {subject.version_label}" if subject.version_label else "") + ".")
    if subject.fidelity.get("tier"):
        lines.append(f"Fidelity: {subject.fidelity['tier']}, {subject.fidelity.get('preservedPercent', 0)}% "
                     "preserved.")
    if subject.snapshot_hash:
        lines.append(f"Snapshot: {subject.snapshot_hash}")
    return "\n".join(lines) + "\n"


def pull_request_body(subject: DeliverySubject, changes: Mapping[str, Any], *, target_path: str,
                      mode: str = "pr") -> str:
    """The pull request description: the fidelity summary, the report link, and what changed.

    Args:
        subject: What is being delivered.
        changes: The change overview (:meth:`app.sdk_git_delivery_changes.ChangeSet.overview`).
        target_path: The normalised repository path.
        mode: ``pr`` — the body explains the branch is Apiome's and is rebuilt on each delivery.

    Returns:
        Markdown, at most :data:`PULL_REQUEST_BODY_MAX_CHARS` characters, deterministic for the same
        inputs.
    """
    fidelity = subject.fidelity
    lines = [PULL_REQUEST_MARKER, f"## {pull_request_title(subject)}", ""]
    lines.append(f"Apiome exported **{_label(subject)}** to **{subject.target}** and wrote the bundle to "
                 f"`{target_path or '/'}`.")
    lines.append("")
    lines.append("### Fidelity")
    lines.append("")
    if fidelity:
        lines.append("| Tier | Preserved | Constructs | Dropped | Approximated | Made up |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        lines.append(
            f"| {fidelity.get('tier', '—')} | {fidelity.get('preservedPercent', '—')}% | "
            f"{fidelity.get('total', '—')} | {fidelity.get('dropped', '—')} | "
            f"{fidelity.get('approximated', '—')} | {fidelity.get('synthesized', '—')} |"
        )
        if fidelity.get("headline"):
            lines.extend(["", f"> {fidelity['headline']}"])
    else:
        lines.append("No fidelity report was recorded for this export.")
    lines.append("")
    if subject.report_url:
        lines.append(f"**[Open the full fidelity report]({subject.report_url})** — every construct that "
                     "was kept, approximated, dropped or made up.")
        lines.append("")
    lines.append("### Changes")
    lines.append("")
    lines.append(f"{changes.get('added', 0)} added · {changes.get('modified', 0)} modified · "
                 f"{changes.get('removed', 0)} removed · {changes.get('unchanged', 0)} unchanged")
    files = list(changes.get("files") or [])
    if files:
        lines.extend(["", "| File | Change |", "| --- | --- |"])
        for entry in files[:BODY_FILE_ROWS]:
            lines.append(f"| `{entry.get('path')}` | {entry.get('change')} |")
        listed = sum(int(changes.get(key) or 0) for key in ("added", "modified", "removed"))
        if listed > min(len(files), BODY_FILE_ROWS):
            lines.append(f"| … and {listed - min(len(files), BODY_FILE_ROWS)} more | |")
    lines.append("")
    lines.append("### Provenance")
    lines.append("")
    lines.append(f"- Export job: `{subject.job_id}`")
    if subject.version_record_id:
        lines.append(f"- Revision: `{subject.version_record_id}`")
    if subject.snapshot_hash:
        lines.append(f"- Snapshot: `{subject.snapshot_hash}`")
    if mode == "pr":
        lines.extend([
            "",
            "_This branch is Apiome's: each delivery of this export rebuilds it on the latest base branch "
            "and updates this pull request. Files Apiome did not write are never touched._",
        ])
    body = "\n".join(lines) + "\n"
    return body if len(body) <= PULL_REQUEST_BODY_MAX_CHARS else body[: PULL_REQUEST_BODY_MAX_CHARS - 2] + "…\n"
