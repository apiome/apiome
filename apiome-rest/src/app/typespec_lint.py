"""TypeSpec lint pack — MFI-14.3 (#3796).

A compiled TypeSpec project (MFI-14.1) is normalized through its emitted OpenAPI, so the API it
describes is linted like any OpenAPI one. What the TypeSpec compiler itself says about the
*source* would otherwise be lost: every compile runs the bundled libraries' built-in linter
rulesets (:data:`app.typespec_config.BUILTIN_LINTER_RULESETS`), and its warnings — the compiler's
own (``deprecated``), the libraries' and the linter rules'
(``@typespec/http/op-reference-container-route``) — are recorded on the catalog item
(``extras["typespec_diagnostics"]``, :mod:`app.typespec_compile`). This pack, registered under the
``typespec`` format key, reports them:

* **typespec.compiler-diagnostic** (warning) — one finding per diagnostic, at
  ``tsp:<file>:<line>:<column>`` (``tsp:`` for one with no location), the message prefixed with the
  diagnostic code so it can be looked up in the TypeSpec docs.

A single ``.tsp`` file read by the built-in reader is not compiled, so it has no diagnostics.
A compile *error* refuses the import (``INPUT_SEMANTIC_INVALID``), so only warnings reach here.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack

__all__ = ["TypeSpecRulePack"]


def _path(diagnostic: Mapping[str, Any]) -> str:
    """``tsp:<file>:<line>:<column>`` for a located diagnostic, ``tsp:`` otherwise."""
    file = diagnostic.get("file")
    if not file:
        return "tsp:"
    return f"tsp:{file}:{diagnostic.get('line')}:{diagnostic.get('column')}"


def _check_compiler_diagnostics(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """One finding per recorded compile diagnostic, plus one for any the import did not list."""
    diagnostics = api.extras.get("typespec_diagnostics") or []
    for diagnostic in diagnostics:
        if isinstance(diagnostic, Mapping):
            yield _path(diagnostic), f"{diagnostic.get('code', '')}: {diagnostic.get('message', '')}"
    total = api.extras.get("typespec_diagnostic_count")
    if isinstance(total, int) and total > len(diagnostics):
        yield "tsp:", f"{total - len(diagnostics)} more TypeSpec compiler diagnostic(s) not listed."


class TypeSpecRulePack(RulePack, register=True):
    """Native rules for TypeSpec artifacts (see the module docstring)."""

    format = "typespec"
    pack_id = "typespec"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="typespec.compiler-diagnostic",
            category="structure",
            severity="warning",
            description=(
                "A TypeSpec project should compile without warnings from the compiler or its built-in linter rules."
            ),
            check=_check_compiler_diagnostics,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the TypeSpec native rules."""
        return list(self._RULES)
