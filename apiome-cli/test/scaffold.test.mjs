import assert from "node:assert";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const mustExist = (relative) => {
  const path = join(root, relative);
  assert.ok(existsSync(path), `expected ${relative} to exist`);
};

test("package.json uses @apiome/cli", () => {
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  assert.strictEqual(pkg.name, "@apiome/cli");
});

test("run.sh documents usage and forwards to apiome or interactive mode", () => {
  const raw = readFileSync(join(root, "run.sh"), "utf8");
  assert.match(raw, /Usage:/);
  assert.match(raw, /apiome_cli\.run_interactive/);
  assert.match(raw, /exec "\$CLI" "\$@"/);
});

test("package.json defines turborepo scripts", () => {
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  const scripts = pkg.scripts ?? {};
  for (const name of [
    "install:py",
    "build",
    "cli:build",
    "test",
    "cli:test",
    "lint",
    "cli:lint",
    "run",
  ]) {
    assert.ok(scripts[name], `expected scripts.${name} to be defined`);
  }
  assert.match(scripts.test, /pytest tests\//);
  assert.match(scripts.lint, /ruff check src\/ tests\//);
  assert.match(scripts["cli:build"], /install:py/);
  assert.match(scripts["cli:build"], /apiome-cli build complete/);
});

test("pyproject.toml requires Python >= 3.12", () => {
  const raw = readFileSync(join(root, "pyproject.toml"), "utf8");
  assert.match(raw, /requires-python\s*=\s*">=3\.12"/);
});

test("pyproject.toml declares CLI stack dependencies", () => {
  const raw = readFileSync(join(root, "pyproject.toml"), "utf8");
  for (const dep of [
    "typer[all]>=",
    "httpx>=",
    "pydantic-settings>=",
    "py-yaml12>=",
    "jsonschema>=",
    "openapi-spec-validator>=",
  ]) {
    assert.ok(raw.includes(dep), `expected pyproject.toml to include ${dep}`);
  }
});

test("pyproject.toml declares CLI dev dependencies", () => {
  const raw = readFileSync(join(root, "pyproject.toml"), "utf8");
  for (const dep of ["pytest>=", "pytest-httpx>=", "ruff>="]) {
    assert.ok(raw.includes(dep), `expected pyproject.toml to include ${dep}`);
  }
});

test("pyproject.toml registers apiome console script", () => {
  const raw = readFileSync(join(root, "pyproject.toml"), "utf8");
  assert.match(raw, /apiome\s*=\s*"apiome_cli\.main:run"/);
});

test("installed apiome --version prints package version", () => {
  const script = join(root, ".venv", "bin", "apiome");
  assert.ok(existsSync(script), "expected .venv/bin/apiome after uv sync");
  const initPy = readFileSync(
    join(root, "src", "apiome_cli", "__init__.py"),
    "utf8",
  );
  const match = initPy.match(/__version__\s*=\s*"([^"]+)"/);
  assert.ok(match, "expected __version__ in apiome_cli/__init__.py");
  const result = spawnSync(script, ["--version"], { encoding: "utf8" });
  assert.strictEqual(result.status, 0, result.stderr || result.stdout);
  assert.strictEqual(result.stdout.trim(), `apiome ${match[1]}`);
});

test("uv.lock is committed for reproducible installs", () => {
  mustExist("uv.lock");
});

test("expected CLI scaffold paths exist", () => {
  for (const rel of [
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "package.json",
    "src/apiome_cli/__init__.py",
    "run.sh",
    "src/apiome_cli/run_interactive.py",
    "src/apiome_cli/main.py",
    "src/apiome_cli/config.py",
    "src/apiome_cli/client/__init__.py",
    "src/apiome_cli/commands/__init__.py",
    "src/apiome_cli/import_/__init__.py",
    "src/apiome_cli/import_/openapi.py",
    "src/apiome_cli/import_/detect.py",
    "src/apiome_cli/import_/json_schema.py",
    "src/apiome_cli/extract/__init__.py",
    "src/apiome_cli/extract/openapi_info.py",
    "tests/test_scaffold.py",
  ]) {
    mustExist(rel);
  }
});

test(".gitignore excludes required patterns", () => {
  const gitignore = readFileSync(join(root, ".gitignore"), "utf8");
  for (const line of [".env", "__pycache__/", ".venv/", "*.pyc", "dist/"]) {
    assert.ok(
      gitignore.split("\n").some((entry) => entry.trim() === line),
      `expected .gitignore to contain ${line}`,
    );
  }
});

test("README documents install, configuration, and examples", () => {
  const raw = readFileSync(join(root, "README.md"), "utf8");
  assert.match(raw, /## Install/i);
  assert.match(raw, /## Configuration/i);
  assert.match(raw, /## Examples/i);
  assert.match(raw, /APIOME_BASE_URL/);
  assert.match(raw, /config\.toml/);
  assert.match(raw, /apiome projects list/);
  assert.match(raw, /apiome repos list/);
  assert.match(raw, /apiome repos add --url/);
  assert.match(raw, /apiome repos scan/);
  assert.match(raw, /apiome repos files/);
  assert.match(raw, /apiome repos inspect/);
  assert.match(raw, /apiome repos import/);
  assert.match(raw, /apiome repos imports/);
  assert.match(raw, /apiome import openapi/);
  assert.match(raw, /apiome import arazzo/);
  assert.match(raw, /apiome paths list/);
  assert.match(raw, /apiome operations show/);
  assert.match(raw, /apiome workflows list/);
  assert.match(raw, /import → inspect → export/);
});

test("AGENTS.md documents layout, clig.dev, and REST contract", () => {
  const raw = readFileSync(join(root, "AGENTS.md"), "utf8");
  assert.match(raw, /## Layout/i);
  assert.match(raw, /clig\.dev/i);
  assert.match(raw, /apiome-rest\/openapi\.yaml/);
  assert.match(raw, /yarn cli:test/);
});

test("main.py bootstraps Typer application", () => {
  const raw = readFileSync(
    join(root, "src/apiome_cli/main.py"),
    "utf8",
  );
  assert.match(raw, /app\s*=\s*typer\.Typer/);
  assert.match(raw, /no_args_is_help=False/);
  assert.match(raw, /help_option_names.*-h.*--help/);
});
