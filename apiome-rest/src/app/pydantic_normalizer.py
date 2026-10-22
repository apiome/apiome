"""Pydantic models → canonical model normalizer — FMT-8.4 (#5465).

:mod:`app.pydantic_parser` reads a module of models *statically* and produces the neutral AST
FMT-8.1's TypeScript extractor emits — models as interfaces (inheritance as ``extends``, generics
as type parameters), enums as enums, union aliases as aliases, and ``Field`` constraints attached
as JSON Schema keywords. This normalizer feeds that AST through the shared FMT-8.1 model builder,
so a Pydantic model, a Zod schema and a TypeScript interface of the same shape produce the same
records, unions and names, and constraints become canonical constraints through
:func:`app.normalizer.coerce_constraints`.

Declared limits use the Pydantic vocabulary (:data:`app.pydantic_parser.LIMIT_DETAILS`) and land
in ``extras['pydantic']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from .normalizer import Keys, Normalizer, normalize_ordering
from .pydantic_parser import PydanticDocument, pydantic_limit_recorder
from .typescript_types_normalizer import _limits_payload, _Model
from .typescript_types_parser import TsDocument

__all__ = ["PYDANTIC_EXTRAS_KEY", "PYDANTIC_FORMAT", "PydanticNormalizer"]

#: The format key the normalizer registers under.
PYDANTIC_FORMAT = "pydantic"

#: The key the projection record sits under in ``CanonicalApi.extras``.
PYDANTIC_EXTRAS_KEY = "pydantic"


def _identity_name(document: PydanticDocument) -> str:
    """The root module's first model, else its first declaration (never the filename)."""
    exported = document.exported()
    own = [d for d in exported if d.get("module") == document.root] or exported
    for declaration in own:
        if declaration.get("kind") == "interface":
            return str(declaration["name"])
    return str(own[0]["name"]) if own else "PydanticModels"


class PydanticNormalizer(Normalizer, register=True):
    """Normalize statically-read Pydantic models into a :class:`CanonicalApi`."""

    format = PYDANTIC_FORMAT
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.pydantic_parser.PydanticDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep the module sources on ``raw``.

        Returns:
            The canonical model: one ``data_schema`` API holding every model the root module
            defines or re-exports, and every model and enum they reach.

        Raises:
            ValueError: When ``source`` is not a :class:`PydanticDocument`.
        """
        if not isinstance(source, PydanticDocument):
            raise ValueError(
                "Pydantic source must be a PydanticDocument (see app.pydantic_parser.parse_pydantic)"
            )
        projection = TsDocument(
            root=source.root,
            files=source.files,
            typescript_version="",
            declarations=source.declarations,
            sources={},
        )
        limits = pydantic_limit_recorder()
        for construct, location in source.module_limits:
            limits.record(construct, location=location)
        model = _Model(projection, limits)
        exported = projection.exported()
        for declaration in exported:
            model.reserve(declaration["name"])
        for declaration in exported:
            model.declare_exported(declaration)
        model.report_uninstantiated(exported)

        name = _identity_name(source)
        pydantic: Dict[str, Any] = {
            "root_module": source.root,
            "modules": list(source.files),
            "exports": [d["name"] for d in exported],
            "capability_limits": _limits_payload(limits.limits()),
        }
        if Keys.type(name) in model.types:
            pydantic["root_type"] = Keys.type(name)
        raw: Optional[Dict[str, Any]] = {"pydantic": dict(source.sources)} if include_raw else None
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name),
            title=name,
            types=list(model.types.values()),
            raw=raw,
            extras={PYDANTIC_EXTRAS_KEY: pydantic},
        )
        return normalize_ordering(api)
