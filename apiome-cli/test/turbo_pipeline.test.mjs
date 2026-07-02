import assert from "node:assert";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const pkgRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(pkgRoot, "..");
const turboDryRunOptions = {
  encoding: "utf8",
  env: { ...process.env, FORCE_COLOR: "0" },
  maxBuffer: 16 * 1024 * 1024,
};

/**
 * `turbo run … --dry=json` may print a banner before the JSON object and a
 * trailing summary after it. Extract the first top-level JSON object.
 *
 * @param {string} raw
 * @returns {unknown}
 */
function parseTurboDryJson(raw) {
  const trimmed = raw.trim();
  const start = trimmed.indexOf("{");
  assert.notStrictEqual(start, -1, "expected JSON object in turbo output");

  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < trimmed.length; i++) {
    const c = trimmed[i];
    if (inString) {
      if (escape) {
        escape = false;
      } else if (c === "\\") {
        escape = true;
      } else if (c === '"') {
        inString = false;
      }
      continue;
    }
    if (c === '"') {
      inString = true;
      continue;
    }
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) {
        return JSON.parse(trimmed.slice(start, i + 1));
      }
    }
  }
  assert.fail("unbalanced JSON in turbo output");
}

test("root turbo.json defines cli:* tasks with expected caching and dependencies", () => {
  const turbo = JSON.parse(readFileSync(join(repoRoot, "turbo.json"), "utf8"));
  const { tasks } = turbo;
  assert.strictEqual(tasks["cli:build"].cache, false);
  assert.deepStrictEqual(tasks["cli:build"].dependsOn, ["^cli:build"]);
  assert.strictEqual(tasks["cli:test"].cache, true);
  assert.deepStrictEqual(tasks["cli:test"].dependsOn, ["cli:build"]);
  assert.strictEqual(tasks["cli:lint"].cache, true);
  assert.deepStrictEqual(tasks["cli:lint"].dependsOn, ["cli:build"]);
});

test("root package.json delegates cli:* scripts to turbo", () => {
  const pkg = JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8"));
  for (const name of ["cli:build", "cli:test", "cli:lint"]) {
    assert.strictEqual(pkg.scripts[name], `turbo run ${name}`);
  }
});

test("@apiome/cli package.json defines cli:* scripts for turborepo", () => {
  const pkg = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf8"));
  assert.match(pkg.scripts["install:py"], /uv venv/);
  assert.match(pkg.scripts["cli:build"], /install:py/);
  assert.match(pkg.scripts["cli:build"], /apiome-cli build complete/);
  assert.match(pkg.scripts["cli:test"], /pytest tests\//);
  assert.match(pkg.scripts["cli:lint"], /ruff check src\/ tests\//);
});

test("turbo dry-run includes cli:* tasks for @apiome/cli", () => {
  const result = spawnSync(
    "yarn",
    ["turbo", "run", "cli:build", "cli:test", "cli:lint", "--filter=@apiome/cli", "--dry=json"],
    {
      cwd: repoRoot,
      ...turboDryRunOptions,
    },
  );
  assert.strictEqual(result.status, 0, `${result.stderr ?? ""}${result.stdout ?? ""}`);
  const doc = /** @type {{ tasks: { taskId: string; task: string }[] }} */ (
    parseTurboDryJson(`${result.stdout ?? ""}${result.stderr ?? ""}`)
  );
  const taskNames = new Set(doc.tasks.map((t) => t.task));
  assert.ok(taskNames.has("cli:build"));
  assert.ok(taskNames.has("cli:test"));
  assert.ok(taskNames.has("cli:lint"));
  const taskIds = new Set(doc.tasks.map((t) => t.taskId));
  assert.ok(taskIds.has("@apiome/cli#cli:build"));
  assert.ok(taskIds.has("@apiome/cli#cli:test"));
  assert.ok(taskIds.has("@apiome/cli#cli:lint"));

  const testDry = spawnSync(
    "yarn",
    ["turbo", "run", "cli:test", "--filter=@apiome/cli", "--dry=json"],
    {
      cwd: repoRoot,
      ...turboDryRunOptions,
    },
  );
  assert.strictEqual(testDry.status, 0, `${testDry.stderr ?? ""}${testDry.stdout ?? ""}`);
  const testDoc = /** @type {{ tasks: { task: string; dependencies: string[] }[] }} */ (
    parseTurboDryJson(`${testDry.stdout ?? ""}${testDry.stderr ?? ""}`)
  );
  const testTask = testDoc.tasks.find((t) => t.task === "cli:test");
  assert.ok(testTask);
  assert.ok(
    testTask.dependencies.some((d) => d.endsWith("#cli:build")),
    "cli:test should depend on cli:build",
  );

  const lintDry = spawnSync(
    "yarn",
    ["turbo", "run", "cli:lint", "--filter=@apiome/cli", "--dry=json"],
    {
      cwd: repoRoot,
      ...turboDryRunOptions,
    },
  );
  assert.strictEqual(lintDry.status, 0, `${lintDry.stderr ?? ""}${lintDry.stdout ?? ""}`);
  const lintDoc = /** @type {{ tasks: { task: string; dependencies: string[] }[] }} */ (
    parseTurboDryJson(`${lintDry.stdout ?? ""}${lintDry.stderr ?? ""}`)
  );
  const lintTask = lintDoc.tasks.find((t) => t.task === "cli:lint");
  assert.ok(lintTask);
  assert.ok(
    lintTask.dependencies.some((d) => d.endsWith("#cli:build")),
    "cli:lint should depend on cli:build",
  );
});
