"""A TypeSpec project's ``tspconfig.yaml`` — MFI-14.5 (#3798).

A TypeSpec project carries a ``tspconfig.yaml`` beside its main file. On import Apiome always
compiles with its own configuration — the ``@typespec/openapi3`` emitter writing one
``openapi.json`` (:data:`app.typespec_compile.OPENAPI_TSPCONFIG`) — and applies only the uploaded
settings that shape the emitted API and are safe to honor:

==================================================  ==========================================
Setting                                             Values
==================================================  ==========================================
``options."@typespec/openapi3".openapi-versions``   ``3.0.0`` / ``3.1.0`` — the first listed
                                                    version only, so one document is emitted
``options."@typespec/openapi3".omit-unreachable-types``  ``true`` / ``false``
``options."@typespec/openapi3".include-x-typespec-name`` ``inline-only`` / ``never``
``options."@typespec/openapi3".safeint-strategy``   ``double-int`` / ``int64``
``warn-as-error``                                   ``true`` / ``false``
==================================================  ==========================================

Everything else is ignored and named, with the reason, on the catalog item: emitter lists and
other emitters' options (only ``@typespec/openapi3`` runs), output locations (``output-dir``,
``emitter-output-dir``, ``output-file``, ``file-type``, ``new-line`` — Apiome reads one JSON
document from its own scratch directory), ``imports`` and ``linter`` (a project's ``.tsp`` files
are its imports, and Apiome enables the bundled libraries' built-in linter rulesets itself —
:data:`BUILTIN_LINTER_RULESETS`, MFI-14.3), ``parameters`` / ``environment-variables`` (no
interpolation is performed), and any value of the wrong type.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from .import_source import ImportSourceError

__all__ = [
    "BUILTIN_LINTER_RULESETS",
    "OPENAPI3_EMITTER",
    "TSPCONFIG_NAMES",
    "TypeSpecConfig",
    "build_tspconfig",
    "find_tspconfig",
    "resolve_tspconfig",
]

#: The emitter Apiome compiles with.
OPENAPI3_EMITTER = "@typespec/openapi3"

#: The built-in ``tsp`` linter rulesets every compile enables (MFI-14.3, #3796): every rule the
#: bundled TypeSpec libraries define (``@typespec/http``'s, at 0.65). Their warnings are recorded
#: on the catalog item and reported by the ``typespec`` lint pack (:mod:`app.typespec_lint`).
BUILTIN_LINTER_RULESETS = ("@typespec/http/all",)

#: File names a project's configuration may have.
TSPCONFIG_NAMES = ("tspconfig.yaml", "tspconfig.yml")

#: ``@typespec/openapi3`` options honored, with their accepted values (``bool`` = true/false).
_OPENAPI3_OPTIONS: Dict[str, Tuple[Any, ...]] = {
    "openapi-versions": ("3.0.0", "3.1.0"),
    "omit-unreachable-types": (bool,),
    "include-x-typespec-name": ("inline-only", "never"),
    "safeint-strategy": ("double-int", "int64"),
}

#: ``@typespec/openapi3`` options Apiome sets itself, and why an uploaded value is ignored.
_OPENAPI3_OWNED = {
    "output-file": "Apiome reads one openapi.json it names itself",
    "file-type": "Apiome reads the document as JSON",
    "new-line": "line endings do not change the API",
    "emitter-output-dir": "output stays in Apiome's scratch directory",
}

#: Top-level keys ignored, and why.
_TOP_LEVEL_IGNORED = {
    "emit": f"only {OPENAPI3_EMITTER} runs on import",
    "output-dir": "output stays in Apiome's scratch directory",
    "imports": "a project's .tsp files are its imports",
    "linter": "Apiome runs the bundled libraries' built-in linter rulesets itself",
    "parameters": "no parameter interpolation is performed",
    "environment-variables": "no environment interpolation is performed",
    "extends": "only the uploaded project's own settings are read",
    "trace": "compiler tracing is not used on import",
}


@dataclass(frozen=True)
class TypeSpecConfig:
    """The outcome of reading an uploaded ``tspconfig.yaml``.

    Attributes:
        path: The configuration's path in the upload.
        applied: The settings honored, as a ``tspconfig`` fragment
            (``{"warn-as-error": True, "options": {"@typespec/openapi3": {...}}}``).
        ignored: One ``"<key>: <reason>"`` line per setting left out, in file order.
    """

    path: str
    applied: Dict[str, Any] = field(default_factory=dict)
    ignored: Tuple[str, ...] = ()


def find_tspconfig(members: Mapping[str, str], root: str) -> Optional[str]:
    """The path of the ``tspconfig.yaml`` (or ``.yml``) beside the root ``.tsp``, if any.

    Args:
        members: The set's members, path → text.
        root: The root document's path.

    Returns:
        The member path, or ``None``.
    """
    folder = posixpath.dirname(root.replace("\\", "/"))
    for name in TSPCONFIG_NAMES:
        candidate = posixpath.join(folder, name) if folder else name
        if candidate in members:
            return candidate
    return None


def _accepts(allowed: Tuple[Any, ...], value: Any) -> bool:
    """Whether ``value`` is one of ``allowed`` (``bool`` in ``allowed`` means any boolean)."""
    if bool in allowed:
        return isinstance(value, bool)
    return isinstance(value, str) and value in allowed


def _resolve_openapi3(options: Any, ignored: List[str]) -> Dict[str, Any]:
    """The honored ``@typespec/openapi3`` options; the rest are recorded in ``ignored``."""
    prefix = f'options."{OPENAPI3_EMITTER}"'
    if not isinstance(options, Mapping):
        ignored.append(f"{prefix}: not a mapping")
        return {}
    applied: Dict[str, Any] = {}
    for key, value in options.items():
        name = str(key)
        if name in _OPENAPI3_OWNED:
            ignored.append(f"{prefix}.{name}: {_OPENAPI3_OWNED[name]}")
            continue
        allowed = _OPENAPI3_OPTIONS.get(name)
        if allowed is None:
            ignored.append(f"{prefix}.{name}: not a setting Apiome applies")
            continue
        if name == "openapi-versions":
            versions = value if isinstance(value, list) else [value]
            valid = [v for v in versions if _accepts(allowed, v)]
            if not valid:
                ignored.append(f"{prefix}.{name}: expected one of {', '.join(allowed)}")
                continue
            applied[name] = [valid[0]]
            if len(versions) > 1:
                ignored.append(f"{prefix}.{name}: only the first version ({valid[0]}) is emitted")
            continue
        if not _accepts(allowed, value):
            expected = "true or false" if bool in allowed else f"one of {', '.join(allowed)}"
            ignored.append(f"{prefix}.{name}: expected {expected}")
            continue
        applied[name] = value
    return applied


def resolve_tspconfig(text: str, *, path: str = "tspconfig.yaml") -> TypeSpecConfig:
    """Read an uploaded ``tspconfig.yaml`` into the settings Apiome honors.

    Args:
        text: The configuration's text.
        path: Its path in the upload (for messages).

    Returns:
        The honored and ignored settings.

    Raises:
        ImportSourceError: ``INPUT_MALFORMED`` when it is not YAML or not a mapping.
    """
    try:
        document = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        raise ImportSourceError(f"{path} is not valid YAML: {exc}", code="INPUT_MALFORMED") from exc
    if document is None:
        document = {}
    if not isinstance(document, Mapping):
        raise ImportSourceError(f"{path} must be a YAML mapping", code="INPUT_MALFORMED")

    applied: Dict[str, Any] = {}
    ignored: List[str] = []
    for key, value in document.items():
        name = str(key)
        if name == "warn-as-error":
            if isinstance(value, bool):
                applied[name] = value
            else:
                ignored.append(f"{name}: expected true or false")
        elif name == "options":
            if not isinstance(value, Mapping):
                ignored.append("options: not a mapping")
                continue
            for emitter, emitter_options in value.items():
                if str(emitter) == OPENAPI3_EMITTER:
                    honored = _resolve_openapi3(emitter_options, ignored)
                    if honored:
                        applied.setdefault("options", {})[OPENAPI3_EMITTER] = honored
                else:
                    ignored.append(f'options."{emitter}": only {OPENAPI3_EMITTER} runs on import')
        elif name in _TOP_LEVEL_IGNORED:
            ignored.append(f"{name}: {_TOP_LEVEL_IGNORED[name]}")
        else:
            ignored.append(f"{name}: not a setting Apiome applies")
    return TypeSpecConfig(path=path, applied=applied, ignored=tuple(ignored))


def build_tspconfig(applied: Optional[Mapping[str, Any]] = None) -> str:
    """Apiome's compile configuration, with an uploaded project's honored settings merged in.

    Args:
        applied: :attr:`TypeSpecConfig.applied` (``None`` for no uploaded configuration).

    Returns:
        ``tspconfig.yaml`` text emitting ``@typespec/openapi3`` to ``openapi.json``, with the
        :data:`BUILTIN_LINTER_RULESETS` enabled.
    """
    applied = dict(applied or {})
    openapi3 = dict((applied.get("options") or {}).get(OPENAPI3_EMITTER) or {})
    openapi3["output-file"] = "openapi.json"
    config: Dict[str, Any] = {"emit": [OPENAPI3_EMITTER], "options": {OPENAPI3_EMITTER: openapi3}}
    if "warn-as-error" in applied:
        config["warn-as-error"] = applied["warn-as-error"]
    config["linter"] = {"extends": list(BUILTIN_LINTER_RULESETS)}
    return yaml.safe_dump(config, sort_keys=False)
