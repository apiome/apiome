"""DICOM JSON reader — FMT-6.7 (#5451).

Reads the DICOM JSON model (PS3.18 Annex F) — what a DICOMweb server returns for QIDO-RS searches
and WADO-RS metadata: an object whose keys are 8-hex-digit tags (``"00100010"``), each value an
object with a ``vr`` and, optionally, a ``Value`` array, a ``BulkDataURI`` or an ``InlineBinary``. A
top-level array is a list of datasets. Sequences (``SQ``) hold item objects in ``Value``; person
names (``PN``) hold ``{"Alphabetic", "Ideographic", "Phonetic"}`` objects.

The pixel-data boundary holds here too: a Pixel Data or Overlay Data attribute's ``BulkDataURI`` is
not followed and its ``InlineBinary`` is not decoded — the element is recorded as present and
skipped, exactly as the Part 10 reader records it.

A JSON syntax error is raised **without** a taxonomy code so the intake pipeline classifies it (a
UTF-16 upload is an encoding fault, not a malformed document); every structural fault the reader
finds itself carries ``INPUT_MALFORMED``, and a JSON document with no DICOM attribute in it is
``FORMAT_MISMATCH``.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Sequence, Tuple

from .dicom_dictionary import VR_SPECS, is_pixel_data_tag, parse_tag_key, tag_hex
from .dicom_model import (
    FORM_JSON,
    VALUE_BULK_DATA,
    VALUE_EMPTY,
    VALUE_INLINE,
    VALUE_INLINE_BINARY,
    VALUE_PIXEL_SKIPPED,
    VALUE_SEQUENCE,
    DicomDataset,
    DicomElement,
    DicomItem,
    DicomParseError,
    PixelDataSkip,
)

__all__ = [
    "MAX_JSON_ATTRIBUTES",
    "MAX_JSON_DEPTH",
    "dataset_objects",
    "has_dicom_json_marker",
    "is_dicom_json",
    "is_dicom_json_document",
    "looks_like_dicom_json",
    "parse_dicom_json",
    "parse_dicom_json_object",
]

#: Deepest sequence nesting read before the document is refused as too deep.
MAX_JSON_DEPTH = 32
#: Most attributes one document may carry (every nesting level counted).
MAX_JSON_ATTRIBUTES = 200_000

#: Person-name component groups, in the order Part 10 joins them with ``=``.
_PN_COMPONENTS = ("Alphabetic", "Ideographic", "Phonetic")
#: A cheap text marker for a document too broken to parse: a tag key followed by a ``vr``.
_TEXT_MARKER = re.compile(r'"[0-9A-Fa-f]{8}"\s*:\s*\{\s*"vr"\s*:\s*"[A-Z]{2}"')


def dataset_objects(document: Any) -> Optional[List[dict]]:
    """The dataset objects of a parsed JSON document — one object, or an array of them."""
    if isinstance(document, dict):
        return [document]
    if isinstance(document, list) and document and all(isinstance(item, dict) for item in document):
        return list(document)
    return None


def _attribute_share(obj: dict) -> Tuple[int, int]:
    """``(dicom_attributes, keys)`` for one object."""
    hits = sum(
        1
        for key, value in obj.items()
        if parse_tag_key(key) is not None and isinstance(value, dict) and "vr" in value
    )
    return hits, len(obj)


def is_dicom_json_document(document: Any) -> bool:
    """Whether a parsed document is DICOM JSON: every key of every dataset is a tag with a ``vr``."""
    objects = dataset_objects(document)
    if not objects:
        return False
    for obj in objects:
        hits, keys = _attribute_share(obj)
        if not keys or hits != keys:
            return False
    return True


def looks_like_dicom_json(document: Any) -> bool:
    """Whether a parsed document has *any* DICOM attribute — enough to read it and say what is wrong."""
    objects = dataset_objects(document)
    return bool(objects) and any(_attribute_share(obj)[0] for obj in objects)


def is_dicom_json(text: Optional[str]) -> bool:
    """Whether ``text`` parses as a DICOM JSON document. Never raises."""
    if not text or not text.lstrip().startswith(("{", "[")):
        return False
    try:
        return is_dicom_json_document(json.loads(text))
    except (ValueError, RecursionError):
        return False


def has_dicom_json_marker(text: Optional[str]) -> bool:
    """Whether ``text`` carries a DICOM JSON attribute spelling, parseable or not. Never raises."""
    return bool(text) and _TEXT_MARKER.search(text[:65536]) is not None


def _malformed(path: str, message: str) -> DicomParseError:
    return DicomParseError(f"DICOM JSON attribute {path}: {message}", code="INPUT_MALFORMED")


class _Budget:
    """Counts attributes across one document."""

    def __init__(self) -> None:
        self.attributes = 0

    def take(self) -> None:
        self.attributes += 1
        if self.attributes > MAX_JSON_ATTRIBUTES:
            raise DicomParseError(
                f"The DICOM JSON document carries more than {MAX_JSON_ATTRIBUTES} attributes.",
                code="INPUT_TOO_LARGE",
            )


def _person_name(value: Any, path: str) -> str:
    """Render a PN value object in its Part 10 spelling (``Alphabetic=Ideographic=Phonetic``)."""
    if value is None:
        return ""
    if not isinstance(value, dict) or any(key not in _PN_COMPONENTS for key in value):
        raise _malformed(path, "a PN value must be an object of Alphabetic / Ideographic / Phonetic")
    parts = [value.get(component) or "" for component in _PN_COMPONENTS]
    if not all(isinstance(part, str) for part in parts):
        raise _malformed(path, "PN components must be strings")
    return "=".join(parts).rstrip("=")


def _scalar(value: Any, vr: str, path: str) -> str:
    """Render one non-PN, non-SQ value as text."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise _malformed(path, f"a {vr} value must be a string or a number")
    return value if isinstance(value, str) else repr(value) if isinstance(value, float) else str(value)


def _element(
    tag: int, body: Any, *, path: str, depth: int, budget: _Budget, pixel: List[PixelDataSkip]
) -> DicomElement:
    """Read one attribute object."""
    budget.take()
    if not isinstance(body, dict):
        raise _malformed(path, "the attribute must be an object with a `vr`")
    vr = body.get("vr")
    if not isinstance(vr, str) or vr not in VR_SPECS:
        raise _malformed(path, f"`vr` {vr!r} is not a DICOM value representation")
    unknown = sorted(set(body) - {"vr", "Value", "BulkDataURI", "InlineBinary"})
    if unknown:
        raise _malformed(path, f"unexpected member(s) {', '.join(unknown)}")
    carriers = [name for name in ("Value", "BulkDataURI", "InlineBinary") if name in body]
    if len(carriers) > 1:
        raise _malformed(path, f"carries both {carriers[0]} and {carriers[1]}")

    if is_pixel_data_tag(tag):
        # Never followed, never decoded: only the presence and form are recorded.
        form = "BulkDataURI" if "BulkDataURI" in body else "InlineBinary" if "InlineBinary" in body else None
        if form is None and body.get("Value"):
            form = "Value"
        skip = PixelDataSkip(tag=tag, vr=vr, path=path, json_form=form)
        pixel.append(skip)
        return DicomElement(tag=tag, vr=vr, path=path, value_form=VALUE_PIXEL_SKIPPED, value_length=None, pixel=skip)

    if "BulkDataURI" in body:
        uri = body["BulkDataURI"]
        if not isinstance(uri, str):
            raise _malformed(path, "`BulkDataURI` must be a string")
        return DicomElement(tag=tag, vr=vr, path=path, value_form=VALUE_BULK_DATA, value_length=None)
    if "InlineBinary" in body:
        encoded = body["InlineBinary"]
        if not isinstance(encoded, str):
            raise _malformed(path, "`InlineBinary` must be a base64 string")
        # Base64 length ≈ 4/3 of the bytes; the value itself is never decoded.
        return DicomElement(
            tag=tag, vr=vr, path=path, value_form=VALUE_INLINE_BINARY, value_length=len(encoded) * 3 // 4
        )

    values = body.get("Value")
    if values is None:
        return DicomElement(tag=tag, vr=vr, path=path, value_form=VALUE_EMPTY)
    if not isinstance(values, list):
        raise _malformed(path, "`Value` must be an array")

    if vr == "SQ":
        if depth >= MAX_JSON_DEPTH:
            raise DicomParseError(
                f"Sequences nest more than {MAX_JSON_DEPTH} levels deep at {path}.", code="INPUT_DEPTH_LIMIT"
            )
        items: List[DicomItem] = []
        for index, item in enumerate(values):
            item_path = f"{path}/Value/{index}"
            if not isinstance(item, dict):
                raise _malformed(item_path, "a sequence item must be an object")
            items.append(
                DicomItem(
                    elements=_elements(item, path=item_path, depth=depth + 1, budget=budget, pixel=pixel),
                    path=item_path,
                )
            )
        return DicomElement(tag=tag, vr=vr, path=path, value_form=VALUE_SEQUENCE, value_length=None, items=tuple(items))

    if vr == "PN":
        rendered = tuple(_person_name(value, f"{path}/Value/{index}") for index, value in enumerate(values))
    else:
        rendered = tuple(_scalar(value, vr, f"{path}/Value/{index}") for index, value in enumerate(values))
    return DicomElement(
        tag=tag,
        vr=vr,
        path=path,
        value_form=VALUE_INLINE if rendered else VALUE_EMPTY,
        values=rendered,
        value_length=sum(len(value) for value in rendered) + max(len(rendered) - 1, 0),
    )


def _elements(
    obj: dict, *, path: str, depth: int, budget: _Budget, pixel: List[PixelDataSkip]
) -> Tuple[DicomElement, ...]:
    """Read every attribute of one dataset or item object, in tag order."""
    read: List[DicomElement] = []
    for key, body in obj.items():
        tag = parse_tag_key(key)
        if tag is None:
            raise _malformed(f"{path}/{key}", "the key is not an 8-hex-digit DICOM tag")
        read.append(_element(tag, body, path=f"{path}/{tag_hex(tag)}", depth=depth, budget=budget, pixel=pixel))
    return tuple(sorted(read, key=lambda element: element.tag))


def parse_dicom_json_object(
    obj: dict, *, label: Optional[str], path: str = "", budget: Optional[_Budget] = None
) -> DicomDataset:
    """Read one dataset object.

    Args:
        obj: The parsed dataset object.
        label: The member or upload name it came from.
        path: JSON pointer prefix of the object (``/0`` inside an array).
        budget: Attribute budget shared across one document.

    Returns:
        The dataset.

    Raises:
        DicomParseError: ``INPUT_MALFORMED`` for a structural fault, or a resource-limit code.
    """
    pixel: List[PixelDataSkip] = []
    elements = _elements(obj, path=path, depth=0, budget=budget or _Budget(), pixel=pixel)
    # Elements are read in tag order; the skips are reported in the same order.
    ordered = tuple(sorted(pixel, key=lambda skip: skip.path))
    return DicomDataset(elements=elements, path=path, form=FORM_JSON, label=label, pixel_data=ordered)


def parse_dicom_json(text: str, *, label: Optional[str] = None) -> Sequence[DicomDataset]:
    """Read a DICOM JSON document — one dataset object or an array of them.

    Args:
        text: The document text.
        label: The upload's name, recorded on each dataset.

    Returns:
        The datasets, in document order.

    Raises:
        DicomParseError: Without a code for a JSON syntax fault (the pipeline classifies it);
            ``FORMAT_MISMATCH`` for JSON that holds no DICOM attribute; ``INPUT_MALFORMED`` for a
            structural fault.
    """
    try:
        document = json.loads(text)
    except RecursionError as exc:
        raise DicomParseError("The DICOM JSON document nests too deeply.", code="INPUT_DEPTH_LIMIT") from exc
    except ValueError as exc:
        raise DicomParseError(f"The DICOM JSON document is not valid JSON: {exc}") from exc
    objects = dataset_objects(document)
    if objects is None or not looks_like_dicom_json(document):
        raise DicomParseError(
            "This JSON is not the DICOM JSON model: no key is an 8-hex-digit tag holding an object "
            "with a `vr` (PS3.18 Annex F).",
            code="FORMAT_MISMATCH",
        )
    budget = _Budget()
    single = isinstance(document, dict)
    return [
        parse_dicom_json_object(obj, label=label, path="" if single else f"/{index}", budget=budget)
        for index, obj in enumerate(objects)
    ]
