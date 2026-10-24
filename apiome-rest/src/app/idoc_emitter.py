"""SAP IDoc emitter: canonical model → IDoc XML — FMT-6.2 (#5446).

The inverse of :class:`app.idoc_normalizer.IdocNormalizer`. The canonical model's types are the
structure: the root record type is the basic type, each segment type its own record type, and the
fields that reference segment types are the hierarchy. The values come from the ``idoc_segments``
template the importer recorded, so an imported IDoc is written back as the document it was:

.. code-block:: xml

    <ORDERS05>
      <IDOC BEGIN="1">
        <EDI_DC40 SEGMENT="1"> … the control record from idoc_control … </EDI_DC40>
        <E1EDK01 SEGMENT="1"> <CURCY>EUR</CURCY> … </E1EDK01>
      </IDOC>
    </ORDERS05>

A segment type the template has no occurrence of (one added after import) is written as an empty
skeleton occurrence — two when it is a list, so a re-import reads it as one — and recorded as an
inferred loss. A model with no IDoc control record (one not imported from an IDoc) is refused: an
IDoc without ``EDI_DC40`` identifies nothing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Union
from xml.sax.saxutils import escape

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

__all__ = ["IdocEmitOptions", "IdocEmitter", "IdocFidelityRulePack", "validate_idoc_xml"]

_TYPES_ONLY = "only data schemas are exported"
_XML_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class IdocFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for IDoc export: types only."""

    target_label = "SAP IDoc"

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY}; the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


class IdocEmitOptions(EmitOptions):
    """Per-target options for :class:`IdocEmitter`."""

    include_comments: bool = Field(
        default=False,
        description="IDoc XML carries no comments; kept for SPI parity.",
    )


class IdocEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as SAP IDoc XML."""

    #: Only a same-format import carries these (RC6-H4, #6211).
    required_source_extras = ("idoc_control",)

    key = "idoc"
    format = "idoc"
    label = "SAP IDoc"
    description = "Export as SAP IDoc XML (.xml) from the catalog schema and its control record."
    icon = "file-text"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = IdocEmitOptions

    OUTPUT_MEDIA_TYPE = "application/xml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=False,
            nullability=False,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return IdocFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[IdocEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        writer = _IdocWriter(api)
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path, content=content, media_type=self.OUTPUT_MEDIA_TYPE
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


def _segment_name(item: CanonicalField, segment_types: Dict[str, Type]) -> Optional[str]:
    """The segment type a field refers to, or ``None`` for a scalar field."""
    reference = item.type.item.name if item.type.item is not None else item.type.name
    target = segment_types.get(reference or "")
    return target.name if target is not None else None


class _IdocWriter:
    """Writes one IDoc XML document."""

    def __init__(self, api: CanonicalApi) -> None:
        self._api = api
        self._templated: set = set()
        self._skeletons: set = set()
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key: Dict[str, Type] = {item.key: item for item in api.types}
        self._types_by_name: Dict[str, Type] = {item.name: item for item in api.types}
        basic = str(api.extras.get("idoc_basic_type") or "")
        self.output_path = f"{re.sub(r'[^A-Za-z0-9_-]+', '-', basic).strip('-') or 'idoc'}.xml"

    def render(self) -> str:
        control = self._api.extras.get("idoc_control")
        basic = self._api.extras.get("idoc_basic_type")
        if not isinstance(control, dict) or not control:
            raise ValueError("IDoc export requires `idoc_control` extras from import")
        if not isinstance(basic, str) or basic not in self._types_by_name:
            raise ValueError("IDoc export requires the basic-type record type named by `idoc_basic_type`")
        if not _XML_NAME_RE.match(basic):
            raise ValueError(f"IDoc basic type {basic!r} is not a valid XML element name")
        templates = self._api.extras.get("idoc_segments")
        self._templated = _template_names(templates if isinstance(templates, list) else [])
        self._skeletons: set = set()
        lines: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>', f"<{basic}>", '  <IDOC BEGIN="1">']
        lines.append('    <EDI_DC40 SEGMENT="1">')
        for name, value in control.items():
            lines.append(f"      {self._element(str(name), str(value))}")
        lines.append("    </EDI_DC40>")
        self._children(
            self._types_by_name[basic], templates if isinstance(templates, list) else [], lines, 2
        )
        lines.extend(["  </IDOC>", f"</{basic}>"])

        if any(item.description for type_ in self._api.types for item in type_.fields):
            self.losses.record(
                LossKind.NA,
                "field-descriptions",
                "IDoc XML carries field values, not the segment definition's field descriptions",
            )
        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA, "services-dropped", "IDoc export is types-only; services are omitted"
            )
        self.tracker.record(self._api.identity.name or "idoc", Provenance.SOURCE)
        return "\n".join(lines) + "\n"

    def _element(self, name: str, value: str) -> str:
        if not _XML_NAME_RE.match(name):
            raise ValueError(f"IDoc field {name!r} is not a valid XML element name")
        return f"<{name}>{escape(value)}</{name}>" if value else f"<{name}/>"

    def _children(
        self, owner: Type, templates: Sequence[Any], lines: List[str], depth: int
    ) -> None:
        """Write ``owner``'s child segments: template occurrences first, then skeletons."""
        children = {
            name: item
            for item in owner.fields
            if (name := _segment_name(item, self._types_by_key)) is not None
        }
        covered = set()
        for template in templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or "")
            segment_type = self._types_by_name.get(name)
            if segment_type is None or name not in children:
                continue
            covered.add(name)
            self._segment(segment_type, template, lines, depth)
        for name, item in children.items():
            # A segment type with an occurrence anywhere in the template is simply absent under this
            # parent; only a type the template never holds gets a skeleton, and only once.
            if name in covered or name in self._templated or name in self._skeletons:
                continue
            self._skeletons.add(name)
            occurrences = 2 if item.type.item is not None else 1
            self.losses.record(
                LossKind.INFERRED,
                f"{owner.name}.{name}",
                f"segment {name} has no imported occurrence; written as {occurrences} empty "
                "skeleton occurrence(s)",
            )
            for _ in range(occurrences):
                self._segment(self._types_by_name[name], None, lines, depth)

    def _segment(
        self, segment_type: Type, template: Optional[Dict[str, Any]], lines: List[str], depth: int
    ) -> None:
        """Write one segment occurrence: its fields, then its children."""
        pad = "  " * depth
        lines.append(f'{pad}<{segment_type.name} SEGMENT="1">')
        if template is not None:
            values = [
                (str(pair[0]), str(pair[1]))
                for pair in template.get("fields") or []
                if isinstance(pair, (list, tuple)) and len(pair) == 2
            ]
        else:
            values = [
                (item.name, "")
                for item in segment_type.fields
                if _segment_name(item, self._types_by_key) is None
            ]
        for name, value in values:
            lines.append(f"{pad}  {self._element(name, value)}")
        self._children(
            segment_type, (template or {}).get("children") or [], lines, depth + 1
        )
        lines.append(f"{pad}</{segment_type.name}>")


def _template_names(templates: Sequence[Any]) -> set:
    """Every segment name that occurs anywhere in an ``idoc_segments`` template."""
    names: set = set()
    for template in templates:
        if isinstance(template, dict):
            names.add(str(template.get("name") or ""))
            names |= _template_names(template.get("children") or [])
    return names


def validate_idoc_xml(content: str) -> None:
    """Validate emitted IDoc XML by reading it back with the IDoc parser.

    Raises:
        ValueError: When the document is not an IDoc the importer can read.
    """
    from .idoc_parser import FORM_XML, IdocParseError, parse_idoc

    try:
        parsed = parse_idoc(content)
    except IdocParseError as exc:
        raise ValueError(str(exc)) from exc
    if parsed.form != FORM_XML:
        raise ValueError("IDoc export must be IDoc XML")
