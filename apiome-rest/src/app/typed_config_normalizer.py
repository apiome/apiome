"""CUE, Pkl and Dhall → canonical model normalizers — FMT-8.5 (#5466).

Each typed configuration reader (:mod:`app.cue_parser`, :mod:`app.pkl_parser`,
:mod:`app.dhall_parser`) hands over a :class:`~app.typed_config_common.TypedConfigDocument`
whose schema is a JSON Schema document — one ``$defs`` entry per definition, class, type alias or
record type. This module is the shared second half: it reuses the JSON Schema translator FMT-8.2
built (:func:`app.zod_normalizer.translate_schema`, in this reader's dialect) and the FMT-8.1
model builder, so a CUE definition, a Pkl class, a Dhall record type, a Zod schema and a
TypeScript interface of the same shape produce the same records, enums, unions and names.

Two projection rules are specific to typed configuration:

* a definition written as ``allOf: [{$ref: Base}, {…own fields…}]`` — a CUE embedding, a Pkl
  subclass — is modelled as a record that *extends* its bases, so inherited fields come first;
* declared limits use the reader's vocabulary and land in
  ``extras[<language>]['capability_limits']``, beside the root file, the files read, the
  definitions exported and the concrete values the tool validated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from .cue_parser import CUE_FORMAT
from .cue_parser import LIMIT_DETAILS as CUE_LIMIT_DETAILS
from .dhall_parser import DHALL_FORMAT
from .dhall_parser import LIMIT_DETAILS as DHALL_LIMIT_DETAILS
from .normalizer import Keys, Normalizer, normalize_ordering
from .pkl_parser import LIMIT_DETAILS as PKL_LIMIT_DETAILS
from .pkl_parser import PKL_FORMAT
from .typed_config_common import TypedConfigDocument, model_limit_aliases
from .typescript_types_normalizer import _limits_payload, _Model
from .typescript_types_parser import LimitRecorder, TsDocument
from .zod_normalizer import JsonSchemaDialect, translate_schema

__all__ = [
    "CueNormalizer",
    "DhallNormalizer",
    "PklNormalizer",
    "TypedConfigNormalizer",
    "dialect_for",
    "to_declarations",
]

#: Each language's limit vocabulary, keyed by format.
_VOCABULARIES: Dict[str, Dict[str, str]] = {
    CUE_FORMAT: CUE_LIMIT_DETAILS,
    PKL_FORMAT: PKL_LIMIT_DETAILS,
    DHALL_FORMAT: DHALL_LIMIT_DETAILS,
}


def dialect_for(language: str) -> JsonSchemaDialect:
    """The JSON Schema dialect a typed-config projection is written in.

    Declarations are ids ``<language>#<Name>``; the readers write no vendor keywords (their
    limits are recorded on the document, not the nodes), and a closed record — every CUE
    definition, Pkl class and Dhall record type is closed — records no unknown-key extra.
    """
    return JsonSchemaDialect(
        id_prefix=f"{language}#",
        limits_keyword=f"x-{language}-limits",
        unsupported_keyword=f"x-{language}-unsupported",
        type_keyword=f"x-{language}-type",
        unknown_keys_extra=None,
    )


def _extension(schema: Any) -> Optional[Dict[str, Any]]:
    """Split ``allOf: [{$ref}…, {object}]`` into bases and own shape, or ``None``.

    Returns:
        ``{"refs": [ref schemas], "own": object schema}`` when every member is a ``$ref`` except
        at most one object shape; ``None`` for any other schema.
    """
    if not isinstance(schema, dict) or not isinstance(schema.get("allOf"), list):
        return None
    refs: List[Dict[str, Any]] = []
    own: Dict[str, Any] = {"type": "object", "properties": {}}
    for member in schema["allOf"]:
        if isinstance(member, dict) and set(member) == {"$ref"}:
            refs.append(member)
        elif isinstance(member, dict) and member.get("type") == "object" and own["properties"] == {}:
            own = member
        else:
            return None
    return {"refs": refs, "own": own} if refs else None


def to_declarations(document: TypedConfigDocument) -> List[Dict[str, Any]]:
    """Translate every ``$defs`` entry into a declaration the FMT-8.1 model builder reads.

    The root's own definitions are exported, in declaration order; a definition another file
    contributes follows, unexported — modelled only because something points at it.

    Args:
        document: The reader's projection.

    Returns:
        The declarations: ``interface`` for an extension (``allOf`` of bases and fields),
        ``alias`` for everything else.
    """
    dialect = dialect_for(document.language)
    definitions = document.definitions
    order = list(document.exports) + [n for n in definitions if n not in document.exports]
    declarations: List[Dict[str, Any]] = []
    for name in order:
        schema = definitions.get(name)
        if schema is None:
            continue
        description = schema.get("description") if isinstance(schema, dict) else None
        declaration: Dict[str, Any] = {
            "id": f"{dialect.id_prefix}{name}",
            "name": name,
            "module": document.root,
            "line": None,
            "exported": name in document.exports,
            "doc": description if isinstance(description, str) else None,
            "deprecated": False,
            "typeParameters": [],
            "mergedDeclarations": 1,
        }
        extension = _extension(schema)
        if extension is not None:
            own = translate_schema(extension["own"], dialect)
            declaration.update(
                kind="interface",
                properties=own.get("properties") or [],
                indexSignatures=own.get("indexSignatures") or [],
                unsupported=[],
                extends=[translate_schema(ref, dialect) for ref in extension["refs"]],
            )
        else:
            declaration.update(kind="alias", type=translate_schema(schema, dialect))
        declarations.append(declaration)
    return declarations


class TypedConfigNormalizer(Normalizer):
    """Normalize a typed configuration projection into a :class:`CanonicalApi`.

    Subclasses set :attr:`format`; the extras key and the limit vocabulary follow from it.
    """

    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.typed_config_common.TypedConfigDocument` to the canonical model.

        Args:
            source: The parsed document (its ``language`` must be this normalizer's format).
            include_raw: Whether to keep the sources and the JSON Schema projection on ``raw``.

        Returns:
            The canonical model: one ``data_schema`` API holding every root definition and every
            definition they reach.

        Raises:
            ValueError: When ``source`` is not a document of this normalizer's language.
        """
        if not isinstance(source, TypedConfigDocument) or source.language != self.format:
            raise ValueError(
                f"{self.format} source must be a TypedConfigDocument read by the {self.format} "
                "reader"
            )

        declarations = to_declarations(source)
        projection = TsDocument(
            root=source.root,
            files=source.files,
            typescript_version="",
            declarations=tuple(declarations),
            sources={},
        )
        limits = LimitRecorder(
            details=_VOCABULARIES[self.format], aliases=model_limit_aliases(self.format)
        )
        for construct, location in source.limits:
            limits.record(construct, location=location)
        model = _Model(projection, limits)
        exported = projection.exported()
        for declaration in exported:
            model.reserve(declaration["name"])
        for declaration in exported:
            model.declare_exported(declaration)

        name = source.identity or (source.exports[0] if source.exports else self.format.upper())
        record: Dict[str, Any] = {
            "root_file": source.root,
            "files": list(source.files),
            "exports": list(source.exports),
            "instances": list(source.instances),
            "capability_limits": _limits_payload(limits.limits()),
        }
        if Keys.type(name) in model.types:
            record["root_type"] = Keys.type(name)

        raw: Optional[Dict[str, Any]] = None
        if include_raw:
            raw = {self.format: dict(source.sources), "json_schema": source.schema}

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name),
            title=name,
            types=list(model.types.values()),
            raw=raw,
            extras={self.format: record},
        )
        return normalize_ordering(api)


class CueNormalizer(TypedConfigNormalizer, register=True):
    """Normalize a CUE package's definitions (FMT-8.5)."""

    format = CUE_FORMAT


class PklNormalizer(TypedConfigNormalizer, register=True):
    """Normalize a Pkl module's classes and type aliases (FMT-8.5)."""

    format = PKL_FORMAT


class DhallNormalizer(TypedConfigNormalizer, register=True):
    """Normalize a Dhall expression's record and union types (FMT-8.5)."""

    format = DHALL_FORMAT
