"""DICOM parser facade — FMT-6.7 (#5451).

One entry point per intake shape, all returning a :class:`~app.dicom_model.DicomDocument`:

* :func:`parse_dicom_text` — DICOM JSON, pasted or uploaded (:mod:`app.dicom_json`);
* :func:`parse_dicom_bytes` — a binary Part 10 file (:mod:`app.dicom_part10`);
* :func:`parse_dicom_fileset` — an archive of DICOM JSON documents: a study-level query result and
  the instances it lists, read root first.

Every dataset is then held to one semantic rule: it names its **SOP Class UID** ``(0008,0016)`` —
the class whose information object definition it instantiates — unless it is a query/retrieve
result (it carries a Query/Retrieve Level or a study/series-level count or retrieve URL), which
describes a study rather than instantiating a class.
"""

from __future__ import annotations

import json
from typing import List, Optional, Tuple

from .dicom_dictionary import QUERY_RESULT_TAGS, SOP_CLASS_UID, tag_text
from .dicom_json import looks_like_dicom_json, parse_dicom_json
from .dicom_model import FORM_JSON, FORM_PART10, DicomDataset, DicomDocument, DicomParseError
from .dicom_part10 import PART10_SUFFIXES, parse_part10

__all__ = [
    "is_query_result",
    "parse_dicom_bytes",
    "parse_dicom_fileset",
    "parse_dicom_text",
    "require_dataset_semantics",
]


def is_query_result(dataset: DicomDataset) -> bool:
    """Whether ``dataset`` is a query/retrieve result rather than an instance."""
    return any(dataset.element(tag) is not None for tag in QUERY_RESULT_TAGS)


def require_dataset_semantics(dataset: DicomDataset) -> None:
    """Refuse a dataset that neither names a SOP class nor is a query result.

    Raises:
        DicomParseError: ``INPUT_SEMANTIC_INVALID``.
    """
    if dataset.first_value(SOP_CLASS_UID) or is_query_result(dataset):
        return
    where = f" in {dataset.label}" if dataset.label else ""
    raise DicomParseError(
        f"The dataset{where} has no SOP Class UID {tag_text(SOP_CLASS_UID)}, so it does not say "
        "which information object definition it is an instance of; and it carries no "
        "query/retrieve attribute that would make it a query result.",
        code="INPUT_SEMANTIC_INVALID",
    )


def parse_dicom_text(text: str, *, label: Optional[str] = None) -> DicomDocument:
    """Read a DICOM JSON document.

    Raises:
        DicomParseError: See :func:`app.dicom_json.parse_dicom_json` and
            :func:`require_dataset_semantics`.
    """
    datasets = parse_dicom_json(text, label=label)
    for dataset in datasets:
        require_dataset_semantics(dataset)
    return DicomDocument(datasets=tuple(datasets), form=FORM_JSON, source=text)


def parse_dicom_bytes(data: bytes, *, label: Optional[str] = None) -> DicomDocument:
    """Read a binary Part 10 file's metadata layer (pixel data is stepped over, never read).

    Raises:
        DicomParseError: See :func:`app.dicom_part10.parse_part10` and
            :func:`require_dataset_semantics`.
    """
    dataset, analysed = parse_part10(data, label=label)
    require_dataset_semantics(dataset)
    return DicomDocument(datasets=(dataset,), form=FORM_PART10, source=analysed)


def _member_order(members: List[str], root: str) -> List[str]:
    return [root] + sorted(path for path in members if path != root)


def parse_dicom_fileset(members: dict, *, root: str) -> DicomDocument:
    """Read an archive of DICOM JSON documents, root first.

    A member that is not DICOM JSON (a README, a manifest) is skipped and recorded. A Part 10 member
    is skipped and recorded too: archive members reach the reader as decoded text, which a binary
    file does not survive — upload a Part 10 file on its own instead.

    Args:
        members: Member path → text.
        root: The root member's path (read first; it must be DICOM).

    Returns:
        A document holding every member's datasets, with ``skipped_members`` stated.

    Raises:
        DicomParseError: When the root is not readable DICOM JSON, or any DICOM member is broken.
    """
    datasets: List[DicomDataset] = []
    skipped: List[Tuple[str, str]] = []
    sources: List[str] = []
    for path in _member_order(list(members), root):
        text = members[path]
        if path.lower().endswith(PART10_SUFFIXES):
            if path == root:
                raise DicomParseError(
                    f"The archive's root {path} is a Part 10 file; archive members are read as text, "
                    "so upload a Part 10 file on its own.",
                    code="INPUT_SEMANTIC_INVALID",
                )
            skipped.append((path, "Part 10 member: archive members are read as text; upload it on its own"))
            continue
        if path != root:
            try:
                document = json.loads(text)
            except ValueError:
                document = None
            if not looks_like_dicom_json(document):
                skipped.append((path, "not DICOM JSON"))
                continue
        for dataset in parse_dicom_json(text, label=path):
            require_dataset_semantics(dataset)
            datasets.append(dataset)
        sources.append(text)
    return DicomDocument(
        datasets=tuple(datasets),
        form=FORM_JSON,
        source="\n".join(sources),
        fileset_root=root,
        skipped_members=tuple(skipped),
    )
