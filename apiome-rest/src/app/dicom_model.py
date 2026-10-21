"""DICOM native parse tree — FMT-6.7 (#5451).

What both DICOM readers produce — :mod:`app.dicom_part10` for binary Part 10 files and
:mod:`app.dicom_json` for the DICOM JSON model (PS3.18 Annex F) — so one normalizer and one
analyzer serve both forms:

.. code-block:: text

    DicomDocument         one upload: one or more datasets (a JSON array, a fileset)
      DicomDataset        one instance or query result; Part 10 adds its file meta group
        DicomElement      one attribute: tag, VR, length — and, for SQ, its items
          DicomItem       one sequence item: its own elements

Values are carried on :attr:`DicomElement.values` for the payload analysis only, where the
value-visibility policy governs them; the normalizer never copies one into the canonical model
except the few :data:`app.dicom_dictionary.STRUCTURAL_VALUE_TAGS`. A pixel-data element carries no
value at all — only a :class:`PixelDataSkip` saying it was there and was stepped over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional, Tuple, Union

__all__ = [
    "DicomDataset",
    "DicomDocument",
    "DicomElement",
    "DicomItem",
    "DicomParseError",
    "FORM_JSON",
    "FORM_PART10",
    "PixelDataSkip",
    "VALUE_BINARY",
    "VALUE_BULK_DATA",
    "VALUE_EMPTY",
    "VALUE_INLINE",
    "VALUE_INLINE_BINARY",
    "VALUE_PIXEL_SKIPPED",
    "VALUE_SEQUENCE",
]

#: A binary Part 10 file (PS3.10).
FORM_PART10 = "part10"
#: The DICOM JSON model (PS3.18 Annex F), as DICOMweb returns it.
FORM_JSON = "json"

#: How an element's value was written.
VALUE_INLINE = "inline"  # text or numbers, decoded into ``values``
VALUE_BINARY = "binary"  # OB/OW/UN … bytes in a Part 10 file: length only, never decoded
VALUE_BULK_DATA = "bulk-data-uri"  # DICOM JSON ``BulkDataURI``: the value lives elsewhere
VALUE_INLINE_BINARY = "inline-binary"  # DICOM JSON ``InlineBinary``: base64, never decoded
VALUE_EMPTY = "empty"  # zero-length value
VALUE_SEQUENCE = "sequence"  # SQ: see ``items``
VALUE_PIXEL_SKIPPED = "pixel-data-skipped"  # image content: stepped over, never read


class DicomParseError(ValueError):
    """A DICOM document the reader refuses, with the intake taxonomy code when it can classify it.

    Attributes:
        code: An :mod:`app.intake_error_taxonomy` code (``INPUT_TRUNCATED`` …), or ``None`` when the
            pipeline should classify the failure itself (a JSON syntax or text-encoding fault).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PixelDataSkip:
    """A pixel-data value the reader stepped over without reading it.

    Attributes:
        tag: The element's tag (``0x7FE00010``).
        vr: The VR it was written with (``OW``, ``OB``, ``OF`` …).
        path: Where it sits (``(7FE0,0010)`` or a nested path).
        declared_length: The value length in bytes, or ``None`` for an encapsulated (undefined-length)
            value or a JSON form that does not state one.
        fragments: For an encapsulated value, how many item fragments were stepped over.
        offset: Byte offset of the element header in the Part 10 stream, when known.
        value_span: ``(start, end)`` byte range of the skipped value, when known — excised from the
            material the analysis hashes.
        json_form: For DICOM JSON, whether it was a ``BulkDataURI`` or ``InlineBinary``.
    """

    tag: int
    vr: str
    path: str
    declared_length: Optional[int] = None
    fragments: Optional[int] = None
    offset: Optional[int] = None
    value_span: Optional[Tuple[int, int]] = None
    json_form: Optional[str] = None


@dataclass(frozen=True)
class DicomElement:
    """One attribute as written.

    Attributes:
        tag: The 32-bit tag.
        vr: The VR as written (explicit VR, JSON ``vr``) or as implied (implicit VR).
        path: Display path (``(0040,A730)[1]/(0040,A043)`` or a JSON pointer).
        value_form: One of the ``VALUE_*`` constants.
        values: Decoded values, as text — payload, for the analysis only.
        value_length: Value length in bytes (Part 10) or characters (JSON); ``None`` when undefined.
        offset: Byte offset of the element header (Part 10).
        header_length: Header size in bytes (Part 10).
        items: Sequence items (``SQ``, or ``UN`` holding an implicit-VR sequence).
        pixel: The pixel-data skip record, for an image-content element.
        vr_explicit: Whether the VR was written in the source (``False`` under implicit VR).
    """

    tag: int
    vr: str
    path: str
    value_form: str
    values: Tuple[str, ...] = ()
    value_length: Optional[int] = 0
    offset: Optional[int] = None
    header_length: Optional[int] = None
    items: Tuple["DicomItem", ...] = ()
    pixel: Optional[PixelDataSkip] = None
    vr_explicit: bool = True

    @property
    def multiplicity(self) -> int:
        """How many values the element carried (the number of items for a sequence)."""
        if self.value_form == VALUE_SEQUENCE:
            return len(self.items)
        return len(self.values)


@dataclass(frozen=True)
class DicomItem:
    """One sequence item.

    Attributes:
        elements: The item's elements, in source order.
        path: Display path of the item (``(0040,A730)[0]``).
        offset: Byte offset of the item header (Part 10).
        length: Item length in bytes, or ``None`` when undefined (delimited).
    """

    elements: Tuple[DicomElement, ...]
    path: str
    offset: Optional[int] = None
    length: Optional[int] = None

    def element(self, tag: int) -> Optional[DicomElement]:
        """The element with ``tag``, if the item has one."""
        return next((element for element in self.elements if element.tag == tag), None)

    def first_value(self, tag: int) -> Optional[str]:
        """The first value of ``tag``, stripped, if present and non-empty."""
        element = self.element(tag)
        if element is None or not element.values:
            return None
        return element.values[0].strip() or None


@dataclass(frozen=True)
class DicomDataset(DicomItem):
    """One dataset — an instance, or a query/retrieve result.

    Attributes:
        form: :data:`FORM_PART10` or :data:`FORM_JSON`.
        label: The member path or upload name it came from.
        file_meta: The Part 10 file meta group (``0002,xxxx``), empty for JSON.
        transfer_syntax: The transfer syntax UID (Part 10 only).
        transfer_syntax_name: Its registry name.
        deflated: Whether the dataset was a deflate stream (offsets are then into the inflated bytes).
        pixel_data: Every pixel-data value stepped over, nested ones included, in source order.
    """

    form: str = FORM_JSON
    label: Optional[str] = None
    file_meta: Tuple[DicomElement, ...] = ()
    transfer_syntax: Optional[str] = None
    transfer_syntax_name: Optional[str] = None
    deflated: bool = False
    pixel_data: Tuple[PixelDataSkip, ...] = ()

    def meta_value(self, tag: int) -> Optional[str]:
        """The first value of a file meta element, if present."""
        element = next((e for e in self.file_meta if e.tag == tag), None)
        if element is None or not element.values:
            return None
        return element.values[0].strip() or None


@dataclass(frozen=True)
class DicomDocument:
    """One upload's datasets.

    Attributes:
        datasets: Every dataset, root first.
        form: The form of the root dataset.
        source: The material the analysis hashes — the JSON text, or the Part 10 bytes with every
            pixel-data value excised.
        fileset_root: The fileset root path, for an archive upload.
        skipped_members: ``(path, reason)`` for fileset members that were not read as DICOM.
    """

    datasets: Tuple[DicomDataset, ...]
    form: str
    source: Union[str, bytes]
    fileset_root: Optional[str] = None
    skipped_members: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def all_pixel_data(self) -> Iterator[Tuple[DicomDataset, PixelDataSkip]]:
        """Every pixel-data skip, with the dataset it belongs to."""
        for dataset in self.datasets:
            for skip in dataset.pixel_data:
                yield dataset, skip
