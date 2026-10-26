"""RAML resource types and traits — MFI-15.2 (#3800).

RAML 1.0 reuses resource and method shapes through **resource types** (applied to a resource
with ``type:``) and **traits** (applied to a resource or method with ``is:``), both
parameterized with ``<<name>>`` placeholders. The canonical model holds the *resolved*
resources: every method with the parameters, headers, bodies and responses its resource type
and traits contribute.

AMF (MFI-15.1, :mod:`app.raml_amf`) already returns that resolved model, but it drops the
record of *which* resource type and traits shaped an operation. This module serves both
parse paths with one walk over the root document's YAML:

* :func:`resolve_resource_types_and_traits` returns the root with every resource type and
  trait merged into its resources and methods (what the YAML reader, used when AMF is not
  available, needs), plus the provenance of each operation;
* the AMF mapper uses only the provenance.

Merging follows the RAML 1.0 rules: a value the resource or method declares wins over one
it inherits; maps merge key by key; a resource-type method written ``get?`` applies only
when the resource declares ``get``. When two traits set the same key, the one listed first
wins. Resource types and traits declared in a ``uses`` library are not visible here (the
YAML reader refuses sets with libraries, and AMF resolves them itself); their names are
still recorded.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import yaml

__all__ = [
    "MAX_EXPANDED_NODES",
    "AppliedReuse",
    "RamlReuseTooLargeError",
    "IncludeAsText",
    "applied_reuse_from_text",
    "declared_names",
    "pluralize",
    "resolve_resource_types_and_traits",
    "singularize",
]

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_PLACEHOLDER_RE = re.compile(r"<<\s*([A-Za-z_][\w-]*)\s*((?:\|\s*![A-Za-z]+\s*)*)>>")
_FUNCTION_RE = re.compile(r"!([A-Za-z]+)")
#: Keys of a resource type / trait that describe the declaration itself, not what it adds.
_DECLARATION_ONLY_KEYS = frozenset({"usage", "type", "is"})

#: Most YAML nodes resolving one document may produce. YAML anchors let a small document
#: name the same subtree many times; copying resource types and traits into every method
#: would expand that, so a document past this is refused rather than resolved.
MAX_EXPANDED_NODES = 200_000


class RamlReuseTooLargeError(ValueError):
    """Raised when applying resource types and traits would produce too large a document."""


class IncludeAsText(yaml.SafeLoader):
    """A YAML loader that reads ``!include x`` as the plain string ``x`` (for scanning only)."""


IncludeAsText.add_constructor("!include", lambda loader, node: loader.construct_scalar(node))


@dataclass(frozen=True)
class AppliedReuse:
    """Which resource type and traits shaped one operation.

    Attributes:
        resource_type: The resource type applied to the operation's resource, as written
            (``collection``, ``lib.collection``); ``None`` when there is none.
        traits: The traits applied to the operation, in precedence order: the method's own
            ``is``, then the resource's, then those its resource type adds (on the method,
            then on the whole resource).
    """

    resource_type: Optional[str] = None
    traits: Tuple[str, ...] = ()


# ===========================================================================
# Parameter functions (<<name | !pluralize>>)
# ===========================================================================


def pluralize(word: str) -> str:
    """The English plural of ``word`` (the RAML ``!pluralize`` function).

    Args:
        word: A singular noun.

    Returns:
        ``Book`` → ``Books``, ``category`` → ``categories``, ``box`` → ``boxes``.
    """
    lower = word.lower()
    if re.search(r"[^aeiou]y$", lower):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", lower):
        return word + "es"
    return word + "s"


def singularize(word: str) -> str:
    """The English singular of ``word`` (the RAML ``!singularize`` function).

    Args:
        word: A plural noun.

    Returns:
        ``books`` → ``book``, ``categories`` → ``category``, ``boxes`` → ``box``.
    """
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if re.search(r"(s|x|z|ch|sh)es$", lower):
        return word[:-2]
    if lower.endswith("s") and not lower.endswith("ss"):
        return word[:-1]
    return word


def _words(value: str) -> List[str]:
    """``value`` split into words on case changes, ``_``, ``-`` and spaces."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [w for w in re.split(r"[\s_\-]+", spaced) if w]


_FUNCTIONS = {
    "singularize": singularize,
    "pluralize": pluralize,
    "uppercase": str.upper,
    "lowercase": str.lower,
    "lowercamelcase": lambda v: "".join(
        w.lower() if i == 0 else w.capitalize() for i, w in enumerate(_words(v))
    ),
    "uppercamelcase": lambda v: "".join(w.capitalize() for w in _words(v)),
    "lowerunderscorecase": lambda v: "_".join(w.lower() for w in _words(v)),
    "upperunderscorecase": lambda v: "_".join(w.upper() for w in _words(v)),
    "lowerhyphencase": lambda v: "-".join(w.lower() for w in _words(v)),
    "upperhyphencase": lambda v: "-".join(w.upper() for w in _words(v)),
}


def _substitute_text(text: str, params: Mapping[str, str]) -> str:
    """Replace every ``<<name | !fn ...>>`` in ``text`` whose ``name`` is in ``params``.

    A placeholder naming an unknown parameter is left as written; an unknown function is
    skipped.
    """

    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        value = params[name]
        for function in _FUNCTION_RE.findall(match.group(2) or ""):
            transform = _FUNCTIONS.get(function.lower())
            if transform:
                value = transform(value)
        return value

    return _PLACEHOLDER_RE.sub(_replace, text)


# ===========================================================================
# References (``type: collection`` / ``type: {collection: {item: Book}}``)
# ===========================================================================


def _reference(value: Any) -> Tuple[Optional[str], Dict[str, str]]:
    """A ``type`` / ``is`` entry as ``(name, parameters)``; ``(None, {})`` when unusable."""
    if isinstance(value, str) and value.strip():
        return value.strip(), {}
    if isinstance(value, Mapping) and len(value) == 1:
        name, params = next(iter(value.items()))
        if isinstance(name, str):
            given = params if isinstance(params, Mapping) else {}
            return name.strip(), {str(k): _param_text(v) for k, v in given.items()}
    return None, {}


def _param_text(value: Any) -> str:
    """A parameter value as the text a placeholder is replaced with."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _entries(value: Any) -> List[Any]:
    """An ``is`` value (one entry or a list) as a list of entries."""
    return list(value) if isinstance(value, list) else [value] if value is not None else []


def _references(value: Any) -> List[Tuple[str, Dict[str, str]]]:
    """An ``is`` value (one entry or a list) as ``[(name, parameters), ...]``."""
    refs = []
    for entry in _entries(value):
        name, params = _reference(entry)
        if name:
            refs.append((name, params))
    return refs


def _resource_path_name(path: str) -> str:
    """The rightmost path segment that is not a URI parameter (``/books/{isbn}`` → ``books``)."""
    for segment in reversed([s for s in path.split("/") if s]):
        if not (segment.startswith("{") and segment.endswith("}")):
            return segment
    return ""


# ===========================================================================
# Merging
# ===========================================================================


def _merge_missing(target: Dict[str, Any], source: Mapping[str, Any]) -> None:
    """Merge ``source`` into ``target`` without overriding what ``target`` declares.

    Maps merge key by key, recursively; any other value ``target`` already has is kept.
    """
    for key, value in source.items():
        if key not in target or target[key] is None:
            target[key] = copy.deepcopy(value)
        elif isinstance(target[key], dict) and isinstance(value, Mapping):
            _merge_missing(target[key], value)


def _optional_method(key: Any) -> Tuple[Optional[str], bool]:
    """``(method, optional)`` for a resource-type key (``get`` / ``get?``), else ``(None, False)``."""
    if not isinstance(key, str):
        return None, False
    name = key[:-1] if key.endswith("?") else key
    if name.lower() in _HTTP_METHODS:
        return name.lower(), key.endswith("?")
    return None, False


def declared_names(root: Mapping[str, Any], key: str) -> Tuple[str, ...]:
    """The names a root declares under ``key`` (``traits`` / ``resourceTypes``), in order.

    RAML 0.8 writes them as a list of one-entry maps; RAML 1.0 as a map.

    Args:
        root: The root document.
        key: ``traits`` or ``resourceTypes``.

    Returns:
        The declared names.
    """
    return tuple(_declarations(root, key))


def _declarations(root: Mapping[str, Any], key: str) -> Dict[str, Mapping[str, Any]]:
    """Name → body for the root's ``traits`` / ``resourceTypes`` (map or 0.8 list form)."""
    block = root.get(key)
    entries: List[Tuple[Any, Any]] = []
    if isinstance(block, Mapping):
        entries = list(block.items())
    elif isinstance(block, list):
        entries = [item for entry in block if isinstance(entry, Mapping) for item in entry.items()]
    return {
        str(name): (body if isinstance(body, Mapping) else {})
        for name, body in entries
        if isinstance(name, str)
    }


class _Resolver:
    """One pass over a root document's resources."""

    def __init__(self, root: Mapping[str, Any]) -> None:
        self.resource_types = _declarations(root, "resourceTypes")
        self.traits = _declarations(root, "traits")
        self.applied: Dict[Tuple[str, str], AppliedReuse] = {}
        self.expanded_nodes = 0

    def _substitute(self, node: Any, params: Mapping[str, str]) -> Any:
        """A deep copy of ``node`` with placeholders replaced in every string key and value.

        Raises:
            RamlReuseTooLargeError: When the copies made so far pass :data:`MAX_EXPANDED_NODES`.
        """
        self.expanded_nodes += 1
        if self.expanded_nodes > MAX_EXPANDED_NODES:
            raise RamlReuseTooLargeError(
                f"Applying the RAML resource types and traits would produce more than "
                f"{MAX_EXPANDED_NODES} nodes"
            )
        if isinstance(node, str):
            return _substitute_text(node, params)
        if isinstance(node, Mapping):
            return {
                (_substitute_text(k, params) if isinstance(k, str) else k): self._substitute(v, params)
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [self._substitute(item, params) for item in node]
        return node

    def resolve_resources(self, node: Mapping[str, Any], parent_path: str = "") -> Dict[str, Any]:
        """Resolve every resource under ``node`` (a root or a resource), recursively."""
        resolved = dict(node)
        for key, value in node.items():
            if isinstance(key, str) and key.startswith("/") and isinstance(value, Mapping):
                resolved[key] = self._resolve_resource(value, f"{parent_path}{key}")
        return resolved

    def _resource_type_body(
        self, ref: Any, base_params: Mapping[str, str], seen: Tuple[str, ...]
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """The named resource type with its parameters applied and its own ``type`` merged in.

        Returns:
            ``(name, body)``; the body is empty when the type is not declared in this document.
        """
        name, given = _reference(ref)
        if not name:
            return None, {}
        declared = self.resource_types.get(name)
        if declared is None or name in seen:
            return name, {}
        params = {**base_params, **given}
        body: Dict[str, Any] = {}
        for key, value in declared.items():
            method, _optional = _optional_method(key)
            body[key] = self._substitute(value, {**params, "methodName": method} if method else params)
        if "type" in body:
            # The substituted ``type`` value, so ``type: {base: {item: <<item>>}}`` passes the value on.
            _parent, parent_body = self._resource_type_body(body["type"], base_params, seen + (name,))
            _merge_missing(body, {k: v for k, v in parent_body.items() if k != "type"})
            body["is"] = _entries(body.get("is")) + _entries(parent_body.get("is"))
        return name, body

    def _resolve_resource(self, resource: Mapping[str, Any], path: str) -> Dict[str, Any]:
        """One resource with its resource type and traits merged into its methods."""
        resolved: Dict[str, Any] = copy.deepcopy(dict(resource))
        base_params = {"resourcePath": path, "resourcePathName": _resource_path_name(path)}
        rt_name, rt_body = self._resource_type_body(resource.get("type"), base_params, ())
        resource_traits = _references(resource.get("is"))
        rt_traits = _references(rt_body.get("is"))
        rt_method_traits: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}

        for key, value in rt_body.items():
            method, optional = _optional_method(key)
            if method is None:
                if key not in _DECLARATION_ONLY_KEYS:
                    _merge_missing(resolved, {key: value})
                continue
            if optional and method not in resolved:
                continue
            existing = resolved.get(method)
            target = existing if isinstance(existing, dict) else {}
            inherited = value if isinstance(value, Mapping) else {}
            _merge_missing(target, {k: v for k, v in inherited.items() if k != "is"})
            rt_method_traits[method] = _references(inherited.get("is"))
            resolved[method] = target

        for method in _HTTP_METHODS:
            spec = resolved.get(method)
            if spec is None and method in resource:
                spec = {}
            if not isinstance(spec, dict):
                continue
            traits = self._unique(
                _references(spec.get("is"))
                + resource_traits
                + rt_method_traits.get(method, [])
                + rt_traits
            )
            params = {**base_params, "methodName": method}
            for trait_name, trait_params in traits:
                body = self.traits.get(trait_name)
                if body is not None:
                    applied = self._substitute(body, {**params, **trait_params})
                    _merge_missing(spec, {k: v for k, v in applied.items() if k not in _DECLARATION_ONLY_KEYS})
            spec.pop("is", None)
            resolved[method] = spec
            self.applied[(path, method)] = AppliedReuse(
                resource_type=rt_name, traits=tuple(name for name, _ in traits)
            )
        resolved.pop("type", None)
        resolved.pop("is", None)
        return self.resolve_resources(resolved, path)

    @staticmethod
    def _unique(refs: List[Tuple[str, Dict[str, str]]]) -> List[Tuple[str, Dict[str, str]]]:
        """``refs`` with repeated trait names dropped (the first one is kept)."""
        seen: Set[str] = set()
        unique = []
        for name, params in refs:
            if name not in seen:
                seen.add(name)
                unique.append((name, params))
        return unique


def resolve_resource_types_and_traits(
    root: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[Tuple[str, str], AppliedReuse]]:
    """Merge the root's resource types and traits into its resources and methods.

    Args:
        root: The root document, as loaded from YAML.

    Returns:
        ``(resolved_root, applied)``: a copy of ``root`` in which every resource and method
        carries what its resource type and traits contribute (and no longer has ``type`` /
        ``is``), and ``(full path, method)`` → :class:`AppliedReuse` for every method.

    Raises:
        RamlReuseTooLargeError: When resolving would expand the document past
            :data:`MAX_EXPANDED_NODES` nodes (see that constant).
    """
    resolver = _Resolver(root)
    return resolver.resolve_resources(root), resolver.applied


def applied_reuse_from_text(text: str) -> Dict[Tuple[str, str], AppliedReuse]:
    """The resource type and traits applied to each operation of a RAML root document.

    Used on the AMF path, whose resolved model no longer records them. ``!include`` values
    are read as their paths, so a resource type kept in another file is named but does not
    contribute the traits it applies.

    Args:
        text: The root document's text.

    Returns:
        ``(full path, method)`` → :class:`AppliedReuse`; empty when the text is not a YAML
        mapping or is too large to resolve (AMF has already resolved the model itself).
    """
    try:
        root = yaml.load(text, Loader=IncludeAsText)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError:
        return {}
    if not isinstance(root, Mapping):
        return {}
    try:
        return resolve_resource_types_and_traits(root)[1]
    except RamlReuseTooLargeError:
        return {}
