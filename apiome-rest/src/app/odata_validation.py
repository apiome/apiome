"""Every check an imported OData document goes through — MFI-11.1 + MFI-11.4.

One entry point, :func:`validate_odata_document`, so the upload, fileset and live-discovery
paths of :class:`~app.odata_import_source.ODataImportSource` validate alike:

1. the OASIS CSDL **JSON schema** (MFI-11.1, :func:`app.odata_csdl_json.with_csdl_validation`);
2. the OASIS CSDL **XML schemas** for a v4 CSDL XML document (MFI-11.4, :mod:`app.odata_csdl_xsd`);
3. **reference and key resolution** for every version (MFI-11.4, :mod:`app.odata_resolution`).

None of them refuses the import: what they find is recorded on the document, carried onto the
catalog item by the normalizer and reported by the ``odata`` lint pack (:mod:`app.odata_lint`).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from .odata_csdl_json import is_csdl_json, with_csdl_validation
from .odata_csdl_xsd import validate_csdl_xml
from .odata_parser import ODataDocument
from .odata_resolution import resolve_odata_document

__all__ = ["validate_odata_document"]


def validate_odata_document(document: ODataDocument, *, source_label: Optional[str] = None) -> ODataDocument:
    """Run the OASIS schema checks and reference / key resolution over a parsed document.

    Args:
        document: A parsed document (``raw`` holds its source text).
        source_label: Label for parse errors.

    Returns:
        The document with its CSDL JSON, schema violations and resolution issues attached.
    """
    document = with_csdl_validation(document, source_label=source_label)
    if not is_csdl_json(document.raw):
        checked = validate_csdl_xml(document.raw, source_label=source_label)
        if checked is not None:
            violations, total = checked
            document = replace(
                document,
                xsd_violations=tuple(v.as_dict() for v in violations),
                xsd_violation_count=total,
            )
    issues, total = resolve_odata_document(document)
    return replace(
        document,
        resolution_issues=tuple(issue.as_dict() for issue in issues),
        resolution_issue_count=total,
    )
