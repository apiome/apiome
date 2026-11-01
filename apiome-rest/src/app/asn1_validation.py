"""Validate an emitted ASN.1 module with asn1tools — MFX-27.3 (#4165).

The export gate (MFX-5.1, :func:`app.export_validation.validate_emitted_artifact`) checks the module the way an
ASN.1 toolchain would — compile-validation gates delivery:

1. **parse + compile** — ``asn1tools`` (pure Python, no external toolchain) parses the module and compiles
   it, resolving every type reference. A syntax error is ``asn1.parse`` (with its line and column); a
   module that parses but does not compile — a reference to an undefined type, a bad constraint — is
   ``asn1.compile``;
2. **one module** — the export writes exactly one module (``asn1.module-count``);
3. **type inventory** — the module's type assignments are exactly the ones the emit plan wrote for the
   source model (:func:`app.asn1_emitter.asn1_type_plan`): a planned type that is missing is
   ``asn1.missing-type``, an assignment the plan does not name is ``asn1.unexpected-type``.

A rejected module fails the export job with ``EMITTED_ARTIFACT_INVALID`` and these findings.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .canonical_model import CanonicalApi
from .emitter import EmitResult

__all__ = ["check_emitted_asn1"]

#: asn1tools reports a syntax error as ``Invalid ASN.1 syntax at line L, column C: …``.
_LOCATION = re.compile(r"at line (\d+), column (\d+)")


def _problem(rule: str, message: str, file: str, *, line: Optional[int] = None,
             column: Optional[int] = None) -> Dict[str, Any]:
    return {"rule": rule, "message": message, "file": file, "line": line, "column": column}


def _parse_problem(file: str, exc: Exception) -> Dict[str, Any]:
    """An ``asn1.parse`` problem, located when asn1tools names the line and column."""
    message = str(exc)
    match = _LOCATION.search(message)
    line, column = (int(match.group(1)), int(match.group(2))) if match else (None, None)
    return _problem("asn1.parse", f"The ASN.1 module does not parse: {message}", file, line=line, column=column)


def _inventory_problems(file: str, modules: Dict[str, Any], plan: List[str]) -> List[Dict[str, Any]]:
    """The module-count and type-inventory problems of a parsed module set against the emit plan."""
    if len(modules) != 1:
        return [_problem("asn1.module-count", f"The export must write one ASN.1 module; it wrote {len(modules)} "
                         f"({', '.join(sorted(modules)) or 'none'}).", file)]
    (module_name, module), = modules.items()
    written = list((module.get("types") or {}).keys())
    problems = [
        _problem("asn1.missing-type", f"Type {name!r} of the emit plan is not assigned in module {module_name!r}.",
                 file)
        for name in plan if name not in written
    ]
    problems += [
        _problem("asn1.unexpected-type", f"Module {module_name!r} assigns {name!r}, which the emit plan does not "
                 "name.", file)
        for name in written if name not in plan
    ]
    return problems


def check_emitted_asn1(emit_result: EmitResult, api: CanonicalApi) -> List[Dict[str, Any]]:
    """Parse, compile and inventory every emitted ASN.1 module.

    Args:
        emit_result: The ASN.1 emitter's output (one ``.asn1`` module).
        api: The source model the module was written from; its emit plan is the expected type inventory.

    Returns:
        The problems, each a dict with ``rule``, ``message``, ``file`` and (for a parse error) ``line`` /
        ``column``; empty when every module compiles and assigns exactly the planned types.
    """
    import asn1tools

    from .asn1_emitter import asn1_type_plan

    if not emit_result.files:
        return [_problem("asn1.module-count", "The ASN.1 export wrote no module.", "")]
    plan = asn1_type_plan(api)
    problems: List[Dict[str, Any]] = []
    for emitted in emit_result.files:
        text = str(emitted.content)
        try:
            modules = asn1tools.parse_string(text)
        except asn1tools.ParseError as exc:
            problems.append(_parse_problem(emitted.path, exc))
            continue
        # The inventory is read before compiling: compile_dict resolves the parsed set in place.
        inventory = _inventory_problems(emitted.path, modules, plan)
        try:
            asn1tools.compile_dict(modules)
        except Exception as exc:  # noqa: BLE001 — any compiler failure is "does not compile", never a crash
            problems.append(_problem("asn1.compile", f"The ASN.1 module does not compile: {exc}", emitted.path))
            continue
        problems += inventory
    return problems
