"""Only :mod:`app.rendered_documents` renders a revision's OpenAPI document — COA-5.14 (#7090).

Every REST feature used to call the generator itself, so each read of a revision queried all of
its classes, properties and paths. They now read through the rendered document cache
(:func:`app.rendered_documents.rendered_document`, most of them by way of
:func:`app.compatibility_engine.openapi_for_revision` or
:func:`app.rendered_documents.revision_openapi`). This test keeps it that way. It reads the code
of every module under ``src/app`` and fails when:

* a module other than the generator and the cache names ``generate_openapi_spec`` in code (an
  import, a call, or a reference; a docstring or comment is not code);
* a ``render_uncached`` call has no ``reason=`` naming one of the declared reasons, or is not one
  of the call sites in :data:`UNCACHED_RENDERS`;
* a module not in :data:`BUILD_LIVE_SPEC_CALLERS` calls ``build_live_spec``, the render behind
  the cache.

The canonical model has the same rule, kept by the last two tests: a stored revision's model is
rebuilt only by :func:`app.catalog_conversion.build_conversion_source`, which reads the captured
source through :mod:`app.revision_source` and parses it through the per-digest model cache.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path
from typing import Dict, List, Set, Tuple

import app.rendered_documents as rendered

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"

GENERATOR = "generate_openapi_spec"

#: The two modules that may name the generator: the generator, and the cache that owns rendering.
GENERATOR_MODULES = {"openapi_generator.py", "rendered_documents.py"}

#: Every ``render_uncached`` call site: ``(module, enclosing function, reason constant)``. Each
#: renders a state that no stored revision has, so the cache has no key for it.
UNCACHED_RENDERS: Set[Tuple[str, str, str]] = {
    # The bulk-upgrade preview reads a revision as it would be with other pins (DCW-3.4).
    ("compatibility_engine.py", "openapi_for_revision", "REASON_COMPONENT_PINS_OVERRIDE"),
    # The materialization preview renders the revision without its pins, then materializes them.
    ("component_library_routes.py", "materialization_preview", "REASON_COMPONENT_PINS_OVERRIDE"),
    # A source apply predicts the document its reviewed change will produce, before writing it.
    ("source_change_apply.py", "regenerate_document", "REASON_SOURCE_APPLY"),
    # A source apply reads the current rows on its transaction's cursor, under the row lock.
    ("database.py", "_cursor_current_merged_document", "REASON_SOURCE_APPLY"),
}

#: Modules that call ``build_live_spec`` (the render behind the cache) and why.
BUILD_LIVE_SPEC_CALLERS: Dict[str, str] = {
    "rendered_documents.py": "the cache's own renders and the direct render of revision_openapi",
    "compatibility_engine.py": "openapi_for_revision when the cache cannot serve the revision",
    "versions_routes.py": "a freeze, which needs the class, property and path counts too",
    "url_import_refresh_sweep.py": "the divergence guard's content identity, which names no project",
}


@functools.lru_cache(maxsize=None)
def _tree(name: str) -> ast.Module:
    return ast.parse((APP_DIR / name).read_text(encoding="utf-8"), filename=name)


def _modules() -> List[str]:
    return sorted(path.name for path in APP_DIR.glob("*.py"))


def _names(tree: ast.AST, wanted: str) -> List[int]:
    """Line numbers where ``wanted`` appears in code: a name, an attribute or an import."""
    lines: List[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == wanted:
            lines.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == wanted:
            lines.append(node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.extend(node.lineno for alias in node.names if alias.name.split(".")[-1] == wanted)
    return lines


def _calls(tree: ast.AST, wanted: str) -> List[Tuple[str, ast.Call]]:
    """Every call of ``wanted`` in a module, with the name of the function it is written in."""
    found: List[Tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if isinstance(child, ast.Call):
                target = child.func
                name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
                if name == wanted:
                    found.append((scope, child))
            visit(child, inner)

    visit(tree, "<module>")
    return found


def test_only_the_generator_and_the_cache_name_the_generator() -> None:
    offenders = {
        name: lines
        for name in _modules()
        if name not in GENERATOR_MODULES and (lines := _names(_tree(name), GENERATOR))
    }
    assert offenders == {}, (
        "These modules call the OpenAPI generator directly. Read a stored revision with "
        "rendered_documents.revision_openapi (or openapi_for_revision); render a state that is "
        f"not stored with rendered_documents.render_uncached(reason=…): {offenders}"
    )


def test_every_uncached_render_names_a_declared_reason_and_is_a_known_call_site() -> None:
    declared = {name for name in dir(rendered) if name.startswith("REASON_")}
    assert {getattr(rendered, name) for name in declared} == set(rendered.UNCACHED_REASONS)

    seen: Set[Tuple[str, str, str]] = set()
    for name in _modules():
        for scope, call in _calls(_tree(name), "render_uncached"):
            reasons = [keyword.value for keyword in call.keywords if keyword.arg == "reason"]
            assert len(reasons) == 1, f"{name}:{call.lineno} render_uncached needs reason=…"
            reason = reasons[0]
            assert isinstance(reason, ast.Name) and reason.id in declared, (
                f"{name}:{call.lineno} reason must be one of {sorted(declared)}"
            )
            seen.add((name, scope, reason.id))
    assert seen == UNCACHED_RENDERS, (
        "render_uncached call sites changed. A stored revision is read through the cache; add a "
        "call site here only for a state that is not stored."
    )


def test_the_uncached_reasons_are_the_two_hypothetical_states() -> None:
    assert set(rendered.UNCACHED_REASONS) == {"component-pins-override", "source-apply"}


def test_only_known_modules_call_the_render_behind_the_cache() -> None:
    callers = {name for name in _modules() if _calls(_tree(name), "build_live_spec")}
    assert callers == set(BUILD_LIVE_SPEC_CALLERS), (
        "build_live_spec renders without the cache. Use rendered_documents.revision_openapi to "
        "read a stored revision."
    )


def test_a_stored_revisions_canonical_model_is_rebuilt_in_one_place() -> None:
    """``build_conversion_source`` is the only caller of the parse, and the parse is cached."""
    conversion = _tree("catalog_conversion.py")
    parse_callers = {scope for scope, _call in _calls(conversion, "_normalized_model")}
    assert parse_callers == {"build_conversion_source"}
    assert [scope for scope, _call in _calls(conversion, "canonical_model_cache")] == ["_normalized_model"]
    assert [scope for scope, _call in _calls(conversion, "resolve_source_payload")] == ["build_conversion_source"]
    elsewhere = [
        name
        for name in _modules()
        if name != "catalog_conversion.py" and _names(_tree(name), "_normalized_model")
    ]
    assert elsewhere == []


def test_canonical_model_for_revision_reads_the_source_through_the_store() -> None:
    modes = _tree("compatibility_modes.py")
    assert [scope for scope, _call in _calls(modes, "build_conversion_source")] == ["canonical_model_for_revision"]
    assert [scope for scope, _call in _calls(modes, "attach_revision_source")] == ["canonical_model_for_revision"]
