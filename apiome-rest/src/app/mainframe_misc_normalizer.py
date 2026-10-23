"""VSAM / CICS BMS → canonical model normalizers — FMT-11.3 (#5484).

Both sub-formats of the ``mainframe-misc`` family normalize onto the **data_schema** paradigm.

**VSAM** (:class:`VsamIdcamsNormalizer`, format ``vsam-idcams``):

.. code-block:: text

    DEFINE CLUSTER NAME(A.B.KSDS) KEYS(10 0)  → RECORD  vsam.A_B_KSDS
                                                 field  PRIMARY_KEY  bytes, length 10 at offset 0
    DEFINE AIX RELATE(A.B.KSDS) KEYS(8 40)    → field  ALTERNATE_KEY_<last qualifier>  on that record
    DEFINE PATH PATHENTRY(<aix>)              → the alternate key's ``paths``
    LINEAR / DEFINE GDG / REPRO …             → declared limits (no record structure to model)

A cluster gives the record's *envelope*: organisation, record size (``fixed`` when the average and
maximum agree), key positions and storage parameters — kept in ``extras['vsam_idcams']``. It never
gives the record's fields, so every record carries the ``vsam.record_layout`` limit pointing at the
copybook that does. Keys are ``bytes`` fields whose ``min_length`` / ``max_length`` are the key
length; their offset is declared metadata.

**BMS** (:class:`CicsBmsNormalizer`, format ``cics-bms``):

.. code-block:: text

    DFHMSD CUSTSET                → identity / namespace CUSTSET
    DFHMDI CUSTMAP SIZE=(24,80)   → RECORD   CUSTSET.CUSTMAP
    CUSTID DFHMDF POS=(3,17) …    → field    CUSTID — row 3, column 17, 10 characters
    (unlabelled DFHMDF)           → a literal, kept in the map's extras, not a field
    OCCURS=8                      → a list of exactly 8

A field's type comes from its input picture (``PICIN``), else its output picture (``PICOUT``):
``9`` / ``S9`` pictures are ``integer``, with ``V`` / ``P`` ``decimal``; an alphanumeric or edited
picture (``ZZ,ZZ9.99``) and a field with no picture are ``string`` with ``max_length`` = ``LENGTH``.
Position, length, pictures and attributes — protection, numeric-only, intensity, initial cursor,
modified-data tag, colour, highlight, validation — are **declared metadata** in
``extras['cics_bms']``, never inferred semantics. A symbolic map read beside the mapset names each
field's ``L`` / ``F`` / ``A`` / ``I`` / ``O`` entries; read alone it gives the records without
screen positions.

Declared limits are counted in ``extras[<format extras key>]['capability_limits']``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from .cics_bms_parser import FORMAT_KEY as BMS_FORMAT_KEY
from .cics_bms_parser import BmsDocument, BmsField, BmsMap, BmsMapset, SymbolicField, SymbolicMap
from .mainframe_misc_common import FAMILY_KEY, sanitize_identifier
from .normalizer import Keys, Normalizer, normalize_ordering
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder
from .vsam_idcams_parser import FORMAT_KEY as VSAM_FORMAT_KEY
from .vsam_idcams_parser import VsamAlternateIndex, VsamCluster, VsamDocument

__all__ = [
    "BMS_EXTRAS_KEY",
    "BMS_LIMIT_DETAILS",
    "BMS_PARTIAL_LIMITS",
    "CicsBmsNormalizer",
    "VSAM_EXTRAS_KEY",
    "VSAM_LIMIT_DETAILS",
    "VSAM_PARTIAL_LIMITS",
    "VsamIdcamsNormalizer",
    "picture_scalar",
]

#: Root extras key of the VSAM projection record (also used on its types and fields).
VSAM_EXTRAS_KEY = "vsam_idcams"
#: Root extras key of the BMS projection record (also used on its types and fields).
BMS_EXTRAS_KEY = "cics_bms"

#: The namespace VSAM record types are keyed under.
VSAM_NAMESPACE = "vsam"

#: The VSAM declared-limit vocabulary (stable keys → reviewed sentence).
VSAM_LIMIT_DETAILS: Dict[str, str] = {
    "vsam.record_layout": (
        "A cluster definition describes the record's envelope — organisation, record size and key "
        "positions — and never its fields. The record keeps only its keys; import the COBOL "
        "copybook or PL/I declaration the programs use for the field layout."
    ),
    "vsam.linear_dataset": (
        "A LINEAR (LDS) cluster has no record structure at all — its layout is entirely in the "
        "application — so no record is modelled for it."
    ),
    "vsam.generation_data_group": (
        "A generation data group is a container of like files and carries no record structure; it "
        "is listed in extras['vsam_idcams']['gdgs'] and not modelled."
    ),
    "vsam.utility_command": (
        "A utility command (REPRO, BLDINDEX, DELETE, LISTCAT, SET …) or a non-VSAM DEFINE describes "
        "what is done to a file, not its record; it is listed in extras['vsam_idcams']['commands'] "
        "and not modelled."
    ),
    "vsam.listcat_statistics": (
        "A LISTCAT section other than ASSOCIATIONS and ATTRIBUTES (HISTORY, STATISTICS, ALLOCATION, "
        "VOLUME) is catalog bookkeeping and activity counters, not record structure; it is not read."
    ),
    "vsam.unlisted_alternate_index": (
        "The listing names an alternate index as associated with the cluster but does not list the "
        "index itself, so its key position is unknown and no alternate key is modelled."
    ),
}
#: Limits whose construct is still modelled, with only a detail lost.
VSAM_PARTIAL_LIMITS = frozenset({"vsam.record_layout"})

#: The BMS declared-limit vocabulary (stable keys → reviewed sentence).
BMS_LIMIT_DETAILS: Dict[str, str] = {
    "bms.literal_field": (
        "An unlabelled DFHMDF is screen text (a title, a prompt, function-key help), not data; it is "
        "kept in the map's extras['cics_bms']['literals'] and not modelled as a field."
    ),
    "bms.edited_picture": (
        "An edited output picture (Z, comma, period, sign, currency or CR / DB insertion) formats a "
        "number for display; the field is projected to a string and the picture kept in "
        "extras['cics_bms']['picout']."
    ),
    "bms.occurs_layout": (
        "An OCCURS field is a list of its occurrence count; the screen positions of the occurrences "
        "after the first are not modelled."
    ),
    "bms.symbolic_map_positions": (
        "A symbolic-map copybook read without its mapset gives the record the program uses but no "
        "screen positions; import the mapset source beside it to place the fields."
    ),
    "bms.symbolic_map_mismatch": (
        "The symbolic map read beside the mapset does not match a field of the map (missing, extra, "
        "or of a different length) — the copybook was generated from another version of the "
        "mapset. The mapset's field is kept; regenerate the copybook."
    ),
}
#: Limits whose construct is still modelled, with only a detail lost.
BMS_PARTIAL_LIMITS = frozenset(
    {"bms.edited_picture", "bms.occurs_layout", "bms.symbolic_map_positions", "bms.symbolic_map_mismatch"}
)

#: ``ATTRB`` values → the attribute they set.
_PROTECTION = {"ASKIP": "autoskip", "PROT": "protected", "UNPROT": "unprotected"}
_INTENSITY = {"BRT": "bright", "NORM": "normal", "DRK": "dark"}
#: Operands copied verbatim into a field's declared metadata.
_FIELD_OPERANDS = ("COLOR", "HILIGHT", "VALIDN", "JUSTIFY", "PS", "OUTLINE", "SOSI", "TRANSP", "CASE")
#: Operands a mapset / map passes down to its fields as defaults.
_INHERITED_OPERANDS = ("COLOR", "HILIGHT")

_EDIT_SYMBOLS = re.compile(r"[Z*,.+\-B0/$]|CR|DB")


def picture_scalar(picture: Optional[str]) -> Tuple[str, bool]:
    """The canonical scalar of a COBOL / BMS picture.

    Args:
        picture: The picture string (``X(10)``, ``9(7)V99``, ``ZZZ,ZZ9.99-``), or ``None``.

    Returns:
        ``(scalar, edited)`` — ``integer`` for ``9`` / ``S9`` pictures, ``decimal`` when they carry
        an assumed decimal point (``V``) or scaling (``P``), else ``string``; ``edited`` is true for
        an edited numeric picture, which is display text and projected to ``string``.
    """
    if not picture:
        return "string", False
    expanded = re.sub(r"\((\d+)\)", "", picture.upper())
    if re.search(r"[XAGN]", expanded):
        return "string", False
    if _EDIT_SYMBOLS.search(expanded):
        return "string", "9" in expanded or "Z" in expanded
    if re.fullmatch(r"S?[9VP]+", expanded):
        return ("decimal" if re.search(r"[VP]", expanded) else "integer"), False
    return "string", False


def _record_ref(scalar: str, occurs: Optional[int], length: Optional[int]) -> Tuple[TypeRef, Optional[Constraints]]:
    """The reference and constraints of a ``scalar`` field, a list of ``occurs`` when repeated."""
    max_length = length if scalar == "string" else None
    element = TypeRef(name=scalar, nullable=False)
    if occurs:
        extras = {"item_max_length": max_length} if max_length is not None else {}
        return TypeRef(item=element, nullable=False), Constraints(min_items=occurs, max_items=occurs, extras=extras)
    if max_length is not None:
        return element, Constraints(max_length=max_length)
    return element, None


# ===========================================================================
# VSAM
# ===========================================================================


def _vsam_type_name(dataset: str) -> str:
    return sanitize_identifier(dataset)


def _record_size_payload(size: Optional[Tuple[int, int]]) -> Optional[Dict[str, Any]]:
    if size is None:
        return None
    return {"average": size[0], "maximum": size[1], "fixed": size[0] == size[1]}


def _alternate_key_names(indexes: List[VsamAlternateIndex]) -> Dict[str, str]:
    """AIX name → field name: ``ALTERNATE_KEY_<last qualifier>``, the whole name when that repeats."""
    last = [aix.name.rsplit(".", 1)[-1] for aix in indexes]
    names: Dict[str, str] = {}
    for aix, qualifier in zip(indexes, last):
        suffix = qualifier if last.count(qualifier) == 1 else aix.name
        names[aix.name] = f"ALTERNATE_KEY_{sanitize_identifier(suffix)}"
    return names


def _vsam_description(cluster: VsamCluster) -> str:
    parts = [f"VSAM {cluster.organisation} {cluster.name}"]
    if cluster.record_size:
        average, maximum = cluster.record_size
        parts.append(
            f"fixed {maximum}-byte records"
            if average == maximum
            else f"records of {average} bytes on average, at most {maximum}"
        )
    else:
        parts.append("record size not declared")
    if cluster.key:
        parts.append(f"primary key {cluster.key.length} bytes at offset {cluster.key.offset}")
    return (
        "; ".join(parts) + ". The cluster definition gives the record's envelope, not its fields: import the copybook "
        "for the field layout."
    )


def _vsam_record(document: VsamDocument, cluster: VsamCluster, limits: LimitRecorder) -> Type:
    """One cluster's record type: its keys as fields, its envelope as declared metadata."""
    type_key = Keys.type(_vsam_type_name(cluster.name), VSAM_NAMESPACE)
    keys: List[Tuple[int, str, CanonicalField]] = []
    if cluster.key:
        keys.append(
            (
                cluster.key.offset,
                "PRIMARY_KEY",
                CanonicalField(
                    key=Keys.field(type_key, "PRIMARY_KEY"),
                    name="PRIMARY_KEY",
                    type=TypeRef(name="bytes", nullable=False),
                    constraints=Constraints(min_length=cluster.key.length, max_length=cluster.key.length),
                    description=(
                        f"Primary key: {cluster.key.length} bytes at offset {cluster.key.offset} of the record."
                    ),
                    extras={
                        VSAM_EXTRAS_KEY: {
                            "role": "primary",
                            "offset": cluster.key.offset,
                            "length": cluster.key.length,
                            "unique": True,
                        }
                    },
                ),
            )
        )
    indexes = [aix for aix in document.alternate_indexes if aix.relate == cluster.name]
    names = _alternate_key_names(indexes)
    for aix in indexes:
        paths = [path.name for path in document.paths if path.entry == aix.name]
        name = names[aix.name]
        keys.append(
            (
                aix.key.offset,
                name,
                CanonicalField(
                    key=Keys.field(type_key, name),
                    name=name,
                    type=TypeRef(name="bytes", nullable=False),
                    constraints=Constraints(min_length=aix.key.length, max_length=aix.key.length),
                    description=(
                        f"Alternate key ({'unique' if aix.unique else 'non-unique'}) of index {aix.name}: "
                        f"{aix.key.length} bytes at offset {aix.key.offset} of the record."
                    ),
                    extras={
                        VSAM_EXTRAS_KEY: {
                            "role": "alternate",
                            "offset": aix.key.offset,
                            "length": aix.key.length,
                            "unique": aix.unique,
                            "index": aix.name,
                            "upgrade": aix.upgrade,
                            "paths": paths,
                            **({"indexRecordSize": _record_size_payload(aix.record_size)} if aix.record_size else {}),
                            **({"storage": aix.storage} if aix.storage else {}),
                        }
                    },
                ),
            )
        )
    keys.sort(key=lambda item: (item[0], item[1]))
    fields = [item[2].model_copy(update={"field_number": number}) for number, item in enumerate(keys, start=1)]
    location = cluster.name
    limits.record("vsam.record_layout", location=location)
    for association in cluster.associations:
        if not any(aix.name == association for aix in indexes):
            limits.record("vsam.unlisted_alternate_index", location=association)
    metadata: Dict[str, Any] = {
        "dataset": cluster.name,
        "organisation": cluster.organisation,
        "organisationDeclared": cluster.organisation_declared,
        "origin": cluster.origin,
        **({"recordSize": _record_size_payload(cluster.record_size)} if cluster.record_size else {}),
        **(
            {"shareOptions": {"crossRegion": cluster.share_options[0], "crossSystem": cluster.share_options[1]}}
            if cluster.share_options
            else {}
        ),
        **(
            {"freeSpace": {"controlInterval": cluster.free_space[0], "controlArea": cluster.free_space[1]}}
            if cluster.free_space
            else {}
        ),
        **({"controlIntervalSize": cluster.ci_size} if cluster.ci_size else {}),
        **({"dataComponent": cluster.data_name} if cluster.data_name else {}),
        **({"indexComponent": cluster.index_name} if cluster.index_name else {}),
        **({"flags": list(cluster.flags)} if cluster.flags else {}),
        **({"storage": cluster.storage} if cluster.storage else {}),
        **(
            {"paths": [p.name for p in document.paths if p.entry == cluster.name]}
            if any(p.entry == cluster.name for p in document.paths)
            else {}
        ),
        **({"associations": list(cluster.associations)} if cluster.associations else {}),
        **({"file": cluster.path} if cluster.path else {}),
    }
    return Type(
        key=type_key,
        name=_vsam_type_name(cluster.name),
        kind=TypeKind.RECORD,
        namespace=VSAM_NAMESPACE,
        description=_vsam_description(cluster),
        fields=fields,
        extras={VSAM_EXTRAS_KEY: metadata},
    )


class VsamIdcamsNormalizer(Normalizer, register=True):
    """Normalize a parsed IDCAMS / LISTCAT document (:class:`~app.vsam_idcams_parser.VsamDocument`)."""

    format = VSAM_FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.vsam_idcams_parser.VsamDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            One ``RECORD`` per cluster with a record structure.

        Raises:
            ValueError: When ``source`` is not a :class:`VsamDocument`.
        """
        if not isinstance(source, VsamDocument):
            raise ValueError("VSAM source must be a VsamDocument (see app.vsam_idcams_parser)")
        limits = LimitRecorder(details=VSAM_LIMIT_DETAILS)
        types: List[Type] = []
        for cluster in source.clusters:
            if cluster.organisation == "LDS":
                limits.record("vsam.linear_dataset", location=cluster.name)
                continue
            types.append(_vsam_record(source, cluster, limits))
        for gdg in source.gdgs:
            limits.record("vsam.generation_data_group", location=gdg.name)
        for command in source.commands:
            limits.record("vsam.utility_command", location=command.verb)
        for section, entry in source.dropped_sections:
            limits.record("vsam.listcat_statistics", location=f"{entry} {section}")
        primary = next(c for c in source.clusters if c.organisation != "LDS")
        record: Dict[str, Any] = {
            "family": FAMILY_KEY,
            "input": "fileset" if source.is_fileset else "file",
            "files": sorted(source.sources),
            "clusters": [{"name": c.name, "organisation": c.organisation} for c in source.clusters],
            "alternateIndexes": [{"name": a.name, "relate": a.relate} for a in source.alternate_indexes],
            "paths": [{"name": p.name, "entry": p.entry, "update": p.update} for p in source.paths],
            "gdgs": [
                {"name": g.name, **({"limit": g.limit} if g.limit is not None else {}), "flags": list(g.flags)}
                for g in source.gdgs
            ],
            "commands": [{"verb": c.verb, "datasets": list(c.datasets)} for c in source.commands],
            "capability_limits": _limits_payload(limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=primary.name, namespace=VSAM_NAMESPACE),
            title=primary.name,
            description=(
                f"VSAM catalog definitions: {len(types)} record envelope(s). Field layouts are not part "
                "of IDCAMS; import the copybook for them."
            ),
            types=types,
            raw={"files": [{"path": p, "text": t} for p, t in sorted(source.sources.items())]} if include_raw else None,
            extras={VSAM_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)


# ===========================================================================
# BMS
# ===========================================================================


def _attribute_payload(item: BmsField) -> Dict[str, Any]:
    """Decode ``ATTRB`` into declared attributes; BMS's defaults are ``(ASKIP,NORM)``."""
    written = set(item.attributes)
    protection = next((_PROTECTION[a] for a in item.attributes if a in _PROTECTION), "autoskip")
    intensity = next((_INTENSITY[a] for a in item.attributes if a in _INTENSITY), "normal")
    return {
        "protection": protection,
        "numeric": "NUM" in written,
        "intensity": intensity,
        "initialCursor": "IC" in written,
        "modifiedDataTag": "FSET" in written,
        "declared": list(item.attributes),
    }


def _operand_payload(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _effective_defaults(mapset: BmsMapset, bms_map: BmsMap) -> Dict[str, Any]:
    """Operands a map inherits from its mapset (``COLOR``, ``HILIGHT``), the map's own winning."""
    defaults: Dict[str, Any] = {}
    for owner in (mapset.operands, bms_map.operands):
        for name in _INHERITED_OPERANDS:
            if name in owner:
                defaults[name.lower()] = _operand_payload(owner[name])
    return defaults


def _field_metadata(item: BmsField, defaults: Dict[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "position": {"row": item.row, "column": item.column},
        "length": item.length,
        "attributes": _attribute_payload(item),
    }
    if item.picin:
        metadata["picin"] = item.picin
    if item.picout:
        metadata["picout"] = item.picout
    if item.initial is not None:
        metadata["initial"] = item.initial
    if item.occurs:
        metadata["occurs"] = item.occurs
    if item.group:
        metadata["group"] = item.group
    for name in _FIELD_OPERANDS:
        if name in item.operands:
            metadata[name.lower()] = _operand_payload(item.operands[name])
    inherited = {name: value for name, value in defaults.items() if name not in metadata}
    if inherited:
        metadata["inherited"] = inherited
    return metadata


def _field_description(item: BmsField) -> str:
    attributes = _attribute_payload(item)
    plural = "s" if item.length != 1 else ""
    text = f"Row {item.row}, column {item.column}; {item.length} character{plural}; {attributes['protection']}"
    if attributes["numeric"]:
        text += ", numeric"
    if attributes["intensity"] != "normal":
        text += f", {attributes['intensity']}"
    if attributes["initialCursor"]:
        text += ", initial cursor"
    if item.occurs:
        text += f"; repeated {item.occurs} times"
    return text + "."


def _symbolic_payload(symbolic: SymbolicField) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"entries": dict(symbolic.entries)}
    if symbolic.input_picture:
        payload["inputPicture"] = symbolic.input_picture
    if symbolic.output_picture:
        payload["outputPicture"] = symbolic.output_picture
    return payload


def _picture_length(picture: Optional[str]) -> Optional[int]:
    """The character length of a simple picture (``X(10)`` → 10, ``XXX`` → 3); ``None`` otherwise."""
    if not picture:
        return None
    total = 0
    for symbol, count in re.findall(r"([A-Z9])(?:\((\d+)\))?", picture.upper()):
        total += int(count) if count else 1
    return total if re.fullmatch(r"(?:[XA9](?:\(\d+\))?)+", picture.upper()) else None


def _bms_field(
    type_key: str,
    item: BmsField,
    number: int,
    defaults: Dict[str, Any],
    symbolic: Optional[SymbolicMap],
    limits: LimitRecorder,
) -> CanonicalField:
    assert item.name is not None
    location = f"{type_key}.{item.name}"
    picture = item.picin or item.picout
    scalar, edited = picture_scalar(picture)
    if edited or picture_scalar(item.picout)[1]:
        limits.record("bms.edited_picture", location=location)
    if item.occurs:
        limits.record("bms.occurs_layout", location=location)
    type_ref, constraints = _record_ref(scalar, item.occurs, item.length)
    metadata = _field_metadata(item, defaults)
    if symbolic is not None:
        entry = symbolic.field(item.name)
        input_length = _picture_length(entry.input_picture) if entry else None
        if entry is None or (input_length is not None and input_length != item.length):
            limits.record("bms.symbolic_map_mismatch", location=location)
        if entry is not None:
            metadata["symbolic"] = _symbolic_payload(entry)
    return CanonicalField(
        key=Keys.field(type_key, item.name),
        name=item.name,
        type=type_ref,
        field_number=number,
        constraints=constraints,
        description=_field_description(item),
        extras={BMS_EXTRAS_KEY: metadata},
    )


def _bms_map_type(mapset: BmsMapset, bms_map: BmsMap, limits: LimitRecorder) -> Type:
    type_key = Keys.type(bms_map.name, mapset.name)
    defaults = _effective_defaults(mapset, bms_map)
    ordered = sorted(bms_map.named_fields, key=lambda f: (f.row, f.column))
    fields = [
        _bms_field(type_key, item, number, defaults, bms_map.symbolic, limits)
        for number, item in enumerate(ordered, start=1)
    ]
    literals = [
        {
            "position": {"row": item.row, "column": item.column},
            "length": item.length,
            **({"initial": item.initial} if item.initial is not None else {}),
        }
        for item in bms_map.fields
        if not item.name
    ]
    for _ in literals:
        limits.record("bms.literal_field", location=type_key)
    if bms_map.symbolic is not None:
        known = {item.name for item in bms_map.named_fields}
        for extra in bms_map.symbolic.fields:
            if extra.name not in known:
                limits.record("bms.symbolic_map_mismatch", location=f"{type_key}.{extra.name}")
    metadata: Dict[str, Any] = {
        "mapset": mapset.name,
        "size": {"rows": bms_map.rows, "columns": bms_map.columns},
        "sizeDeclared": bms_map.size_declared,
        **{name.lower(): _operand_payload(value) for name, value in bms_map.operands.items()},
        "literals": literals,
        **({"file": mapset.path} if mapset.path else {}),
    }
    if bms_map.symbolic is not None:
        metadata["symbolicMap"] = {
            "inputRecord": bms_map.symbolic.input_record,
            **({"outputRecord": bms_map.symbolic.output_record} if bms_map.symbolic.output_record else {}),
            **({"file": bms_map.symbolic.path} if bms_map.symbolic.path else {}),
        }
    return Type(
        key=type_key,
        name=bms_map.name,
        kind=TypeKind.RECORD,
        namespace=mapset.name,
        description=(
            f"BMS map {bms_map.name} of mapset {mapset.name}: a {bms_map.rows}×{bms_map.columns} screen "
            f"with {len(fields)} named field(s)."
        ),
        fields=fields,
        extras={BMS_EXTRAS_KEY: metadata},
    )


def _symbolic_type(symbolic: SymbolicMap, limits: LimitRecorder) -> Type:
    """A record from a symbolic map read without its mapset: no positions."""
    type_key = Keys.type(symbolic.name, None)
    fields: List[CanonicalField] = []
    for number, entry in enumerate(symbolic.fields, start=1):
        location = f"{type_key}.{entry.name}"
        limits.record("bms.symbolic_map_positions", location=location)
        scalar, _ = picture_scalar(entry.input_picture)
        if picture_scalar(entry.output_picture)[1]:
            limits.record("bms.edited_picture", location=location)
        type_ref, constraints = _record_ref(scalar, entry.occurs, _picture_length(entry.input_picture))
        fields.append(
            CanonicalField(
                key=Keys.field(type_key, entry.name),
                name=entry.name,
                type=type_ref,
                field_number=number,
                constraints=constraints,
                description=f"Symbolic-map field {entry.name}; its screen position is in the mapset source.",
                extras={
                    BMS_EXTRAS_KEY: {
                        "symbolic": _symbolic_payload(entry),
                        **({"occurs": entry.occurs} if entry.occurs else {}),
                    }
                },
            )
        )
    return Type(
        key=type_key,
        name=symbolic.name,
        kind=TypeKind.RECORD,
        description=f"BMS symbolic map {symbolic.input_record}: the record the program uses for map {symbolic.name}.",
        fields=fields,
        extras={
            BMS_EXTRAS_KEY: {
                "symbolicMap": {
                    "inputRecord": symbolic.input_record,
                    **({"outputRecord": symbolic.output_record} if symbolic.output_record else {}),
                    **({"file": symbolic.path} if symbolic.path else {}),
                }
            }
        },
    )


class CicsBmsNormalizer(Normalizer, register=True):
    """Normalize a parsed BMS document (:class:`~app.cics_bms_parser.BmsDocument`)."""

    format = BMS_FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.cics_bms_parser.BmsDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            One ``RECORD`` per map (and per unpaired symbolic map).

        Raises:
            ValueError: When ``source`` is not a :class:`BmsDocument`.
        """
        if not isinstance(source, BmsDocument):
            raise ValueError("BMS source must be a BmsDocument (see app.cics_bms_parser)")
        limits = LimitRecorder(details=BMS_LIMIT_DETAILS)
        types: List[Type] = []
        for mapset in source.mapsets:
            types.extend(_bms_map_type(mapset, bms_map, limits) for bms_map in mapset.maps)
        types.extend(_symbolic_type(symbolic, limits) for symbolic in source.symbolic_maps)
        name = source.mapsets[0].name if source.mapsets else source.symbolic_maps[0].name
        record: Dict[str, Any] = {
            "family": FAMILY_KEY,
            "input": "fileset" if source.is_fileset else "file",
            "files": sorted(source.sources),
            "mapsets": [
                {
                    "name": mapset.name,
                    "maps": [m.name for m in mapset.maps],
                    "operands": {k.lower(): _operand_payload(v) for k, v in mapset.operands.items()},
                }
                for mapset in source.mapsets
            ],
            "symbolicMaps": [s.input_record for s in source.symbolic_maps]
            + [m.symbolic.input_record for s in source.mapsets for m in s.maps if m.symbolic is not None],
            "capability_limits": _limits_payload(limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name, namespace=name),
            title=name,
            description=(
                f"CICS BMS screens: {len(types)} map(s). Field positions, pictures and attributes are "
                "declared metadata; the screen says nothing about validation or business meaning."
            ),
            types=types,
            raw={"files": [{"path": p, "text": t} for p, t in sorted(source.sources.items())]} if include_raw else None,
            extras={BMS_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
