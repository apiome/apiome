"""Find route handlers that would run blocking database work on the event loop (DBP-1.4, #7187).

FastAPI runs a plain ``def`` route handler on a worker thread and an ``async def`` one on the
event loop. The database layer is synchronous, so a query made directly inside an ``async def``
handler stalls every other request in the process until it returns. This module reads the route
modules' source (it never imports them) and reports two things:

``awaitless``
    An ``async def`` handler that never awaits. It gains nothing from the event loop, so it must
    be a plain ``def``.

``db-on-loop``
    An ``async def`` handler that, outside a thread hop, calls ``db.<method>(...)``, passes the
    ``db`` handle to a call, or calls a synchronous function of the same module (or one nested in
    the handler) that reaches ``db``. Wrap the call: ``await run_in_threadpool(fn, *args)``.

A thread hop is a call to ``run_in_threadpool``, ``asyncio.to_thread`` or ``run_in_executor``;
everything in its arguments counts as off the loop.

The check is deliberately shallow: it does not follow calls into other modules. A handler that
only calls helpers imported from elsewhere should simply be a plain ``def``, which the
``awaitless`` rule already enforces for every handler that has nothing to await.

``tests/test_event_loop_db_lint.py`` runs it over ``src/app`` and holds the allowlist.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set

#: Decorator attributes that register an HTTP route (``@router.get(...)``, ``@app.post(...)``).
ROUTE_DECORATORS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "api_route"})
#: Calls whose arguments run on a worker thread.
THREAD_HOPS = frozenset({"run_in_threadpool", "to_thread", "run_in_executor"})
#: The module-level database handle route modules import.
DB_NAME = "db"

AWAITLESS = "awaitless"
DB_ON_LOOP = "db-on-loop"

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_ASYNC_SYNTAX = (ast.Await, ast.AsyncFor, ast.AsyncWith, ast.Yield, ast.YieldFrom)


@dataclass(frozen=True)
class Violation:
    """One handler line that breaks a rule.

    Attributes:
        file: File name of the route module.
        handler: Name of the route handler.
        line: 1-based line of the offending code (the ``async def`` line for ``awaitless``).
        rule: ``awaitless`` or ``db-on-loop``.
        detail: What was found, for the failure message.
    """

    file: str
    handler: str
    line: int
    rule: str
    detail: str

    @property
    def key(self) -> str:
        """The allowlist key: ``<file>::<handler>::<rule>``."""
        return f"{self.file}::{self.handler}::{self.rule}"

    def __str__(self) -> str:
        return f"{self.file}:{self.line} {self.handler} [{self.rule}] {self.detail}"


def _call_name(call: ast.Call) -> Optional[str]:
    """The called name: ``f`` for ``f(...)`` and ``attr`` for ``x.attr(...)``."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_db(node: ast.AST) -> bool:
    """Whether ``node`` is the bare ``db`` name."""
    return isinstance(node, ast.Name) and node.id == DB_NAME


def is_route_handler(fn: ast.AST) -> bool:
    """Whether a function definition carries a route decorator such as ``@router.get(...)``."""
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for decorator in fn.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in ROUTE_DECORATORS:
            return True
    return False


def _own_nodes(fn: ast.AST) -> Iterator[ast.AST]:
    """Every node of a function's body, not descending into nested functions or lambdas."""
    stack: List[ast.AST] = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _FUNCTIONS):
            stack.extend(ast.iter_child_nodes(node))


def uses_event_loop(fn: ast.AsyncFunctionDef) -> bool:
    """Whether an ``async def`` awaits, iterates or enters anything asynchronous, or yields."""
    for node in _own_nodes(fn):
        if isinstance(node, _ASYNC_SYNTAX):
            return True
        if isinstance(node, ast.comprehension) and node.is_async:
            return True
    return False


def _db_reaching(functions: Dict[str, ast.AST]) -> Set[str]:
    """Names of the synchronous functions that reach ``db``, directly or through each other.

    Args:
        functions: Synchronous functions by name (one module's top level, or a handler's nested ones).

    Returns:
        The names whose body mentions ``db`` or calls another name in the result.
    """
    reaching = {name for name, fn in functions.items() if any(_is_db(node) for node in ast.walk(fn))}
    changed = True
    while changed:
        changed = False
        for name, fn in functions.items():
            if name in reaching:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in reaching:
                    reaching.add(name)
                    changed = True
                    break
    return reaching


def _db_on_loop(fn: ast.AsyncFunctionDef, file: str, helpers: Set[str]) -> List[Violation]:
    """The ``db-on-loop`` violations of one async handler.

    Args:
        fn: The handler.
        file: Its module's file name.
        helpers: Synchronous functions callable by bare name from the handler that reach ``db``.
    """
    found: List[Violation] = []

    def report(node: ast.AST, detail: str) -> None:
        found.append(Violation(file, fn.name, node.lineno, DB_ON_LOOP, detail))

    def visit(node: ast.AST) -> None:
        if isinstance(node, _FUNCTIONS):
            return  # A nested function runs where it is called; calls to it are checked by name.
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in THREAD_HOPS:
                return  # Everything inside the hop runs on a worker thread.
            func = node.func
            if isinstance(func, ast.Attribute) and _is_db(func.value):
                report(node, f"calls db.{func.attr}(...)")
                for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                    visit(argument)
                return
            elif isinstance(func, ast.Name) and func.id in helpers:
                report(node, f"calls {func.id}(...), which reaches db")
            elif any(_is_db(arg) for arg in node.args) or any(_is_db(kw.value) for kw in node.keywords):
                report(node, f"passes db to {name or 'a call'}(...)")
        elif isinstance(node, ast.Attribute) and _is_db(node.value):
            report(node, f"reads db.{node.attr}")
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in fn.body:
        visit(statement)
    return found


def check_source(source: str, file: str) -> List[Violation]:
    """Check one module's source.

    Args:
        source: The module's Python source.
        file: The file name to report.

    Returns:
        Its violations, in source order.
    """
    tree = ast.parse(source)
    module_functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    module_helpers = _db_reaching(module_functions)
    found: List[Violation] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef) or not is_route_handler(fn):
            continue
        if not uses_event_loop(fn):
            found.append(Violation(file, fn.name, fn.lineno, AWAITLESS, "async def without an await; make it def"))
            continue
        nested = {node.name: node for node in _own_nodes(fn) if isinstance(node, ast.FunctionDef)}
        found.extend(_db_on_loop(fn, file, module_helpers | _db_reaching(nested)))
    return sorted(found, key=lambda violation: violation.line)


def check_paths(paths: Iterable[Path]) -> List[Violation]:
    """Check several modules.

    Args:
        paths: Python files to read.

    Returns:
        Every violation, ordered by file then line.
    """
    found: List[Violation] = []
    for path in sorted(paths):
        found.extend(check_source(path.read_text(encoding="utf-8"), path.name))
    return found


def route_module_paths(app_dir: Path) -> List[Path]:
    """Every Python module under the service package (route handlers live in many of them)."""
    return sorted(path for path in app_dir.rglob("*.py") if "__pycache__" not in path.parts)
