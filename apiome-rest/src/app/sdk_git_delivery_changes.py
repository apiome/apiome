"""What a git delivery writes — SDK-4.2 (#4496).

A delivery commits the SDK-4.1 package layout (:class:`app.sdk_distribution.Distribution`'s file
list) under a directory of the tenant's repository. This module is the pure half of that: where
each file lands, what the delivery manifest says, and — given what the base branch already holds —
exactly which files a commit adds, modifies and removes. It never touches the network, so every
rule below is tested without GitHub.

**Only generated files are ever removed.** An SDK directory in a real repository holds more than
the generator wrote: a CI workflow, a ``LICENSE``, a hand-written helper. A delivery that replaced
the directory wholesale would delete them, and one that never deleted anything would leave the
snippet of an operation that no longer exists lying around forever. So every delivery commits a
**manifest** (``<target>/.apiome/sdk-delivery.json``) naming the files it generated, and the next
delivery removes only files that the *previous* manifest named and the new one does not. A file
Apiome never wrote is never touched — including on the first delivery into an existing directory.

**Unchanged files are not rewritten.** Each file's git blob id is computed locally
(:func:`git_blob_sha`) and compared with the blob the base branch holds at that path, so a
delivery sends GitHub only what differs, and "nothing differs" is a decision made before a single
object is created.

**Deterministic.** The manifest carries no timestamps and no run ids — only the provenance and the
content digests — so identical inputs produce an identical tree, which is what makes re-running a
delivery a no-op rather than a new commit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .sdk_distribution import Distribution

__all__ = [
    "CHANGE_ADDED",
    "CHANGE_DELETED",
    "CHANGE_MODIFIED",
    "DELIVERY_MANIFEST_SCHEMA_VERSION",
    "FILE_MODE",
    "MANIFEST_RELATIVE_PATH",
    "OVERVIEW_MAX_FILES",
    "ChangeSet",
    "DeliveryFile",
    "ExistingEntry",
    "build_manifest",
    "delivery_files",
    "git_blob_sha",
    "join_repo_path",
    "manifest_paths",
    "plan_changes",
]

#: The addressable shape of the delivery manifest.
DELIVERY_MANIFEST_SCHEMA_VERSION = "sdk.git-delivery.v1"

#: Where the manifest lives, relative to the target path. A dot-directory, so package managers and
#: most tooling ignore it; neither SDK-4.1 layout publishes it (``package.json``'s ``files`` and the
#: sdist's package list both leave it out).
MANIFEST_RELATIVE_PATH = ".apiome/sdk-delivery.json"

#: The git file mode every delivered file is committed with (a regular, non-executable file).
FILE_MODE = "100644"

#: How many individual paths a change overview lists. The counts are always exact; the list is a
#: preview, bounded so a stored run row and a pull request body stay a readable size.
OVERVIEW_MAX_FILES = 200

#: Change kinds, as the overview and the pull request body spell them.
CHANGE_ADDED = "added"
CHANGE_MODIFIED = "modified"
CHANGE_DELETED = "removed"

#: Largest manifest a delivery will read back. A manifest lists a few hundred paths; anything far
#: larger is not one of ours.
_MANIFEST_MAX_BYTES = 1_000_000


def git_blob_sha(text: str) -> str:
    """Compute the git blob id of a text file.

    Git names a blob by the SHA-1 of ``"blob <length>\\0"`` followed by the content, so the id of a
    file can be known without asking the repository — which is how a delivery decides a file is
    unchanged without uploading it.

    Args:
        text: The file's content, encoded as UTF-8.

    Returns:
        The 40-character hex object id.
    """
    data = (text or "").encode("utf-8")
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def join_repo_path(target_path: str, relative: str) -> str:
    """Place a package-relative path under the target directory.

    Args:
        target_path: The normalised target directory (``''`` for the repository root).
        relative: The path inside the package (``snippets/getWidget.ts``).

    Returns:
        The repository-relative path (``sdks/ts/snippets/getWidget.ts``).
    """
    relative = relative.strip("/")
    return f"{target_path}/{relative}" if target_path else relative


@dataclass(frozen=True)
class DeliveryFile:
    """One file a delivery commits.

    Attributes:
        path: Repository-relative path.
        text: UTF-8 content.
        subject: What the file is (``metadata``, ``readme``, ``contract``, ``module``,
            ``manifest``, or an operation id).
    """

    path: str
    text: str
    subject: str

    @property
    def size_bytes(self) -> int:
        """The file's UTF-8 length."""
        return len(self.text.encode("utf-8"))

    @property
    def blob_sha(self) -> str:
        """The git blob id this file will have once committed."""
        return git_blob_sha(self.text)


@dataclass(frozen=True)
class ExistingEntry:
    """One entry the base branch already holds under the target path.

    Attributes:
        path: Repository-relative path.
        sha: The git object id.
        type: ``blob``, ``tree`` or ``commit`` (a submodule).
        mode: The git file mode.
    """

    path: str
    sha: str
    type: str = "blob"
    mode: str = FILE_MODE


@dataclass(frozen=True)
class ChangeSet:
    """Exactly what a delivery's commit changes relative to the base branch.

    Attributes:
        added: Files the base branch does not have.
        modified: Files whose content differs from the base branch's.
        deleted: Paths a previous delivery generated that this one no longer does.
        unchanged: Paths whose content is already identical on the base branch.
    """

    added: List[DeliveryFile] = field(default_factory=list)
    modified: List[DeliveryFile] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Whether committing would change the base branch at all."""
        return bool(self.added or self.modified or self.deleted)

    @property
    def written(self) -> List[DeliveryFile]:
        """The files a commit must write (added and modified), in path order."""
        return sorted([*self.added, *self.modified], key=lambda item: item.path)

    def overview(self, max_files: int = OVERVIEW_MAX_FILES) -> Dict[str, Any]:
        """Summarise the change for a run row and a pull request body.

        Args:
            max_files: How many individual paths to list.

        Returns:
            ``{added, modified, removed, unchanged}`` counts, a ``files`` list of
            ``{path, change}`` in path order (added, modified and removed only — unchanged files
            are counted, not listed), and ``truncated`` when the list was capped.
        """
        entries = [{"path": item.path, "change": CHANGE_ADDED} for item in self.added]
        entries += [{"path": item.path, "change": CHANGE_MODIFIED} for item in self.modified]
        entries += [{"path": path, "change": CHANGE_DELETED} for path in self.deleted]
        entries.sort(key=lambda entry: entry["path"])
        limit = max(0, int(max_files))
        return {
            CHANGE_ADDED: len(self.added),
            CHANGE_MODIFIED: len(self.modified),
            CHANGE_DELETED: len(self.deleted),
            "unchanged": len(self.unchanged),
            "files": entries[:limit],
            "truncated": len(entries) > limit,
        }


def build_manifest(distribution: Distribution) -> str:
    """Render the delivery manifest committed beside the SDK.

    Args:
        distribution: The built SDK-4.1 distribution being delivered.

    Returns:
        Stable, pretty-printed JSON: the provenance, and one ``{path, sha256}`` per generated file
        with paths relative to the target directory. No timestamps, so identical inputs yield an
        identical manifest.
    """
    document = {
        "schemaVersion": DELIVERY_MANIFEST_SCHEMA_VERSION,
        "notice": (
            "Generated by Apiome (SDK-4.2 git delivery). The files listed here are regenerated on "
            "every delivery; a file listed here that a later delivery no longer generates is "
            "removed. Files not listed here are never touched."
        ),
        "ecosystem": distribution.ecosystem,
        "packageName": distribution.package_name,
        "packageVersion": distribution.package_version,
        "provenance": distribution.provenance,
        "files": [{"path": item.path, "sha256": item.sha256} for item in distribution.files],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def delivery_files(distribution: Distribution, target_path: str) -> List[DeliveryFile]:
    """Every file a delivery commits, placed under the target directory.

    Args:
        distribution: The built SDK-4.1 distribution. Its file paths are package-relative — the
            archive's ``package/`` root is a tarball convention, not part of the layout.
        target_path: The normalised target directory.

    Returns:
        The distribution's files plus the manifest, in path order.
    """
    files = [
        DeliveryFile(join_repo_path(target_path, item.path), item.text, item.subject)
        for item in distribution.files
    ]
    files.append(
        DeliveryFile(
            join_repo_path(target_path, MANIFEST_RELATIVE_PATH),
            build_manifest(distribution),
            "manifest",
        )
    )
    return sorted(files, key=lambda item: item.path)


def manifest_paths(text: Optional[str], target_path: str) -> Set[str]:
    """Read which files a previous delivery generated.

    Tolerant by design: a manifest that is missing, malformed, oversized or hand-edited yields
    fewer paths, never an error — the worst outcome of a bad manifest must be a stale file left
    behind, not a failed delivery or a deleted file Apiome did not write.

    Args:
        text: The manifest committed on the base branch, or ``None`` when there is none.
        target_path: The normalised target directory the manifest sits under.

    Returns:
        Repository-relative paths. A listed path that is absolute, climbs with ``..``, or reaches
        into ``.git`` is dropped, so a manifest can never name a file outside the target directory.
    """
    if not text or len(text.encode("utf-8")) > _MANIFEST_MAX_BYTES:
        return set()
    try:
        document = json.loads(text)
    except ValueError:
        return set()
    if not isinstance(document, dict) or not isinstance(document.get("files"), list):
        return set()
    paths: Set[str] = set()
    for entry in document["files"]:
        raw = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(raw, str) or not raw.strip() or raw.startswith("/") or "\\" in raw:
            continue
        segments = [segment for segment in raw.split("/") if segment]
        if not segments or any(segment in (".", "..") for segment in segments):
            continue
        if any(segment.lower() == ".git" for segment in segments):
            continue
        paths.add(join_repo_path(target_path, "/".join(segments)))
    return paths


def plan_changes(
    files: Iterable[DeliveryFile],
    existing: Mapping[str, ExistingEntry],
    previous_manifest: Iterable[str] = (),
) -> ChangeSet:
    """Decide what a commit adds, modifies and removes.

    Args:
        files: What this delivery generates, with repository-relative paths.
        existing: What the base branch holds under the target directory, keyed by
            repository-relative path.
        previous_manifest: The paths the base branch's manifest says a previous delivery generated
            (:func:`manifest_paths`).

    Returns:
        The :class:`ChangeSet`. A path is *unchanged* only when the base branch holds a blob with
        the same id; a path the base branch holds as a directory or submodule is *modified* (the
        commit replaces it). A path is *deleted* only when the previous manifest named it, the base
        branch still holds it as a blob, and this delivery no longer generates it.
    """
    generated = {item.path: item for item in files}
    added: List[DeliveryFile] = []
    modified: List[DeliveryFile] = []
    unchanged: List[str] = []
    for path in sorted(generated):
        item = generated[path]
        current = existing.get(path)
        if current is None:
            added.append(item)
        elif current.type == "blob" and current.sha == item.blob_sha:
            unchanged.append(path)
        else:
            modified.append(item)

    deleted = sorted(
        path
        for path in set(previous_manifest)
        if path not in generated
        and path in existing
        and existing[path].type == "blob"
    )
    return ChangeSet(added=added, modified=modified, deleted=deleted, unchanged=unchanged)
