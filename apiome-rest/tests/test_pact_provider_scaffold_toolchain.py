"""Provider test scaffolding: each file compiles in its language — PFX-8.19 (#7316).

Part of the nightly REST suite (``apiome-rest-test.yml``). Each language is checked with its own
toolchain when it is installed, and skipped (saying what is missing) when it is not:

==============  =============================================================================
``python``      ``compile()`` — always; importing it as well when ``APIOME_PACT_PYTHON_DIR``
                holds pact-python 2 (``pip install --target``).
``typescript``  Full ``tsc --noEmit`` against ``@pact-foundation/pact`` when
                ``APIOME_PACT_JS_DIR`` names a ``node_modules`` holding it (and ``typescript``);
                otherwise a syntax check with the repository's own ``typescript`` package.
``go``          ``gofmt -e`` (syntax) when ``go`` is on ``PATH``; ``go vet`` as well when
                ``APIOME_PACT_GO_DIR`` names a module that requires pact-go v2.
``java``        ``javac`` when ``APIOME_PACT_JVM_CLASSPATH`` holds the pact-jvm JUnit 5 jars.
==============  =============================================================================

Every file is generated from the same hostile state name (quotes, newlines, comment closers,
non-ASCII), so a check also proves the name cannot break out of its string literal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.pact_provider_scaffold import ScaffoldState, scaffold_provider_test

_STATES = [
    ScaffoldState(name="an invoice exists", params=(("id", 1042),), registered=True),
    ScaffoldState(name='x"); //\n*/ \\ `${boom}` é 😀', params=(("q", 'a"b'),)),
    ScaffoldState(name="class", params=()),
]
_REPO = Path(__file__).resolve().parents[2]


def _file(language: str, directory: Path) -> Path:
    scaffold = scaffold_provider_test("Billing Service", language, _STATES, pacts=1)
    path = directory / scaffold.file_name
    path.write_text(scaffold.content, encoding="utf-8")
    return path


def _run(args: list, cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"{' '.join(map(str, args))}\n{result.stdout}\n{result.stderr}"


def test_the_python_file_compiles(tmp_path: Path) -> None:
    path = _file("python", tmp_path)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    pact_python = os.environ.get("APIOME_PACT_PYTHON_DIR")
    if pact_python:
        script = (
            "import sys, importlib, inspect; sys.path[:0] = [sys.argv[1], sys.argv[2]];"
            "module = importlib.import_module(sys.argv[3]);"
            "assert set(module.STATE_HANDLERS) == set(module.EXAMPLE_PARAMETERS);"
            "module.handle_state_change({'state': 'an invoice exists', 'params': {'id': 1}, 'action': 'setup'})"
        )
        _run([sys.executable, "-I", "-c", script, pact_python, str(tmp_path), path.stem], tmp_path)


def test_the_typescript_file_type_checks(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    path = _file("typescript", tmp_path)
    pact_js = os.environ.get("APIOME_PACT_JS_DIR")
    if pact_js:
        modules = Path(pact_js)
        (tmp_path / "globals.d.ts").write_text(
            "declare const process: { env: Record<string, string | undefined> };\n"
            "declare function describe(name: string, run: () => void): void;\n"
            "declare function it(name: string, run: () => Promise<unknown>): void;\n",
            encoding="utf-8",
        )
        (tmp_path / "node_modules").symlink_to(modules)
        tsc = modules / "typescript" / "bin" / "tsc"
        _run(
            [
                node,
                str(tsc),
                "--noEmit",
                "--strict",
                "--skipLibCheck",
                "--types",
                "",
                "--moduleResolution",
                "bundler",
                "--esModuleInterop",
                "--target",
                "es2022",
                "--module",
                "preserve",
                path.name,
                "globals.d.ts",
            ],
            tmp_path,
        )
        return
    typescript = _REPO / "node_modules" / "typescript"
    if not typescript.exists():
        pytest.skip("no typescript package (set APIOME_PACT_JS_DIR for a full type-check)")
    script = (
        "const ts = require(process.argv[1]);"
        "const text = require('fs').readFileSync(process.argv[2], 'utf8');"
        "const out = ts.transpileModule(text, { reportDiagnostics: true, compilerOptions: { target: 7 } });"
        "if (out.diagnostics.length) {"
        " console.error(out.diagnostics.map(d => d.messageText).join('\\n')); process.exit(1); }"
    )
    _run([node, "-e", script, str(typescript), str(path)], tmp_path)


def test_the_go_file_is_valid_go(tmp_path: Path) -> None:
    if shutil.which("gofmt") is None:
        pytest.skip("go is not installed")
    path = _file("go", tmp_path)
    _run(["gofmt", "-e", "-l", str(path)], tmp_path)
    module = os.environ.get("APIOME_PACT_GO_DIR")
    if module:
        target = Path(module) / path.name
        shutil.copy(path, target)
        try:
            _run(["go", "vet", "./..."], Path(module))
        finally:
            target.unlink()


def test_the_java_file_compiles(tmp_path: Path) -> None:
    classpath = os.environ.get("APIOME_PACT_JVM_CLASSPATH")
    if shutil.which("javac") is None or not classpath:
        pytest.skip("javac or APIOME_PACT_JVM_CLASSPATH (pact-jvm junit5 jars) is missing")
    path = _file("java", tmp_path)
    _run(["javac", "-proc:none", "-cp", classpath, "-d", str(tmp_path / "out"), str(path)], tmp_path)
