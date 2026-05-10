import { describe, expect, it } from "vitest";

import {
  assertProfileExists,
  buildObjectifiedContext,
  configLayerForProfile,
  listAvailableProfileNames,
  resolveAllowColor,
  resolveApiKey,
  resolveEffectiveProfile,
  resolveJson,
  resolveTenantSlug,
  resolveVerbose,
} from "../src/lib/cli-context.js";
import { parseTomlConfig } from "../src/lib/config.js";
import { DEFAULT_BASE_URL } from "../src/lib/constants.js";
import { CliError } from "../src/lib/errors.js";

function docFromToml(): ReturnType<typeof parseTomlConfig> {
  return parseTomlConfig(`
[default]
base_url = "https://cfg-default.example"

[profile.prod]
base_url = "https://cfg-prod.example"

[profile.staging]
base_url = "https://cfg-staging.example"
`);
}

describe("cli-context resolution", () => {
  it("resolves base URL: flag > env > profile config > default config > built-in", () => {
    const doc = docFromToml();
    const tty = true;

    expect(
      buildObjectifiedContext({
        flags: { baseUrl: "https://flag.example" },
        env: { OBJECTIFIED_BASE_URL: "https://env.example" },
        stdoutIsTTY: tty,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.baseUrl,
    ).toBe("https://flag.example");

    expect(
      buildObjectifiedContext({
        flags: {},
        env: { OBJECTIFIED_BASE_URL: "https://env.example" },
        stdoutIsTTY: tty,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.baseUrl,
    ).toBe("https://env.example");

    expect(
      buildObjectifiedContext({
        flags: { profile: "prod" },
        env: {},
        stdoutIsTTY: tty,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.baseUrl,
    ).toBe("https://cfg-prod.example");

    expect(
      buildObjectifiedContext({
        flags: {},
        env: {},
        stdoutIsTTY: tty,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.baseUrl,
    ).toBe("https://cfg-default.example");

    expect(() =>
      buildObjectifiedContext({
        flags: { profile: "unknown" },
        env: {},
        stdoutIsTTY: tty,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }),
    ).toThrow(CliError);

    expect(
      buildObjectifiedContext({
        flags: {},
        env: {},
        stdoutIsTTY: tty,
        supportsColorStdout: true,
        configDoc: { default: {}, profiles: {} },
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.baseUrl,
    ).toBe(DEFAULT_BASE_URL);
  });

  it("resolves effective profile: flag > OBJECTIFIED_PROFILE > default_profile > default", () => {
    const doc = parseTomlConfig(`
default_profile = "staging"

[profile.prod]
base_url = "https://prod.example"

[profile.staging]
base_url = "https://staging.example"
`);

    expect(resolveEffectiveProfile(undefined, {}, doc)).toBe("staging");

    expect(resolveEffectiveProfile("prod", {}, doc)).toBe("prod");

    expect(resolveEffectiveProfile(undefined, { OBJECTIFIED_PROFILE: "prod" }, doc)).toBe("prod");

    expect(
      resolveEffectiveProfile(undefined, {}, parseTomlConfig(`[profile.x]\nbase_url="y"`)),
    ).toBe("default");
  });

  it("rejects a missing named profile with a friendly message", () => {
    const doc = parseTomlConfig(`
[profile.prod]
base_url = "https://prod.example"
`);
    expect(() =>
      buildObjectifiedContext({
        flags: { profile: "staging" },
        env: {},
        stdoutIsTTY: true,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/cfg.toml",
      }),
    ).toThrow(CliError);

    try {
      buildObjectifiedContext({
        flags: { profile: "staging" },
        env: {},
        stdoutIsTTY: true,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/cfg.toml",
      });
    } catch (e) {
      expect(e).toBeInstanceOf(CliError);
      expect((e as CliError).message).toMatch(/Profile 'staging' not found/);
      expect((e as CliError).message).toMatch(/Available:/);
      expect((e as CliError).exitCode).toBe(11);
    }
  });

  it("lists available profile names including implicit default", () => {
    const doc = parseTomlConfig(`
[profile.prod]
base_url = "https://x"
`);
    expect(listAvailableProfileNames(doc)).toEqual(["default", "prod"]);
  });

  it("assertProfileExists allows default without profile.default table", () => {
    const doc = parseTomlConfig(`[profile.prod]\nbase_url="https://x"`);
    expect(() => assertProfileExists(doc, "default")).not.toThrow();
    expect(() => assertProfileExists(doc, "prod")).not.toThrow();
    expect(() => assertProfileExists(doc, "nope")).toThrow(CliError);
  });

  it("resolves API key: flag > env > config ([profile] over [default])", () => {
    expect(resolveApiKey("flag-key", { OBJECTIFIED_API_KEY: "env-key" })).toBe("flag-key");
    expect(resolveApiKey(undefined, { OBJECTIFIED_API_KEY: "env-key" })).toBe("env-key");
    expect(resolveApiKey(undefined, {})).toBe(undefined);
    expect(resolveApiKey(undefined, {}, { apiKey: "cfg-key" })).toBe("cfg-key");
    expect(resolveApiKey(undefined, { OBJECTIFIED_API_KEY: "env-key" }, { apiKey: "cfg-key" })).toBe(
      "env-key",
    );

    const doc = parseTomlConfig(`
[default]
api_key = "default-key"

[profile.prod]
api_key = "prod-key"
`);
    const fromProfile = buildObjectifiedContext({
      flags: { profile: "prod" },
      env: {},
      stdoutIsTTY: true,
      supportsColorStdout: true,
      configDoc: doc,
      configPath: "/tmp/fake/objectified/config.toml",
    });
    expect(fromProfile.context.apiKey).toBe("prod-key");
    expect(fromProfile.context.apiKeyFromConfig).toBe(true);

    const fromDefault = buildObjectifiedContext({
      flags: {},
      env: {},
      stdoutIsTTY: true,
      supportsColorStdout: true,
      configDoc: doc,
      configPath: "/tmp/fake/objectified/config.toml",
    });
    expect(fromDefault.context.apiKey).toBe("default-key");
    expect(fromDefault.context.apiKeyFromConfig).toBe(true);

    expect(
      buildObjectifiedContext({
        flags: { profile: "prod", apiKey: "flag" },
        env: {},
        stdoutIsTTY: true,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.apiKey,
    ).toBe("flag");

    expect(
      buildObjectifiedContext({
        flags: { profile: "prod" },
        env: { OBJECTIFIED_API_KEY: "envk" },
        stdoutIsTTY: true,
        supportsColorStdout: true,
        configDoc: doc,
        configPath: "/tmp/fake/objectified/config.toml",
      }).context.apiKey,
    ).toBe("envk");
  });

  it("resolves tenant slug: flag > env > profile overlay > default section", () => {
    const doc = parseTomlConfig(`
[default]
tenant_slug = "tenant-default"

[profile.prod]
tenant_slug = "tenant-prod"
`);
    expect(resolveTenantSlug(undefined, {}, configLayerForProfile(doc, "prod"))).toBe(
      "tenant-prod",
    );
    expect(
      resolveTenantSlug(
        undefined,
        { OBJECTIFIED_TENANT: "env-tenant" },
        configLayerForProfile(doc, "prod"),
      ),
    ).toBe("env-tenant");
    expect(
      resolveTenantSlug(
        "flag-tenant",
        { OBJECTIFIED_TENANT: "env-tenant" },
        configLayerForProfile(doc, "prod"),
      ),
    ).toBe("flag-tenant");
  });

  it("resolves JSON: flag > OBJECTIFIED_JSON > auto when stdout is not a TTY", () => {
    expect(resolveJson(true, {}, true)).toBe(true);
    expect(resolveJson(false, {}, false)).toBe(false);
    expect(resolveJson(undefined, { OBJECTIFIED_JSON: "1" }, true)).toBe(true);
    expect(resolveJson(undefined, {}, false)).toBe(true);
    expect(resolveJson(undefined, {}, true)).toBe(false);
  });

  it("resolves verbose: flag > OBJECTIFIED_VERBOSE", () => {
    expect(resolveVerbose(true, {})).toBe(true);
    expect(resolveVerbose(false, { OBJECTIFIED_VERBOSE: "1" })).toBe(false);
    expect(resolveVerbose(undefined, { OBJECTIFIED_VERBOSE: "1" })).toBe(true);
    expect(resolveVerbose(undefined, {})).toBe(false);
  });

  it("disables color for --no-color, NO_COLOR, or non-TTY; enables with --color", () => {
    expect(resolveAllowColor(false, {}, true, true)).toBe(false);
    expect(resolveAllowColor(true, {}, false, false)).toBe(true);
    expect(resolveAllowColor(undefined, { NO_COLOR: "1" }, true, true)).toBe(false);
    expect(resolveAllowColor(undefined, {}, false, true)).toBe(false);
    expect(resolveAllowColor(undefined, {}, true, false)).toBe(false);
    expect(resolveAllowColor(undefined, {}, true, true)).toBe(true);
  });

  it("surfaces verboseEffective from env when flag omitted", () => {
    const r = buildObjectifiedContext({
      flags: {},
      env: { OBJECTIFIED_VERBOSE: "1" },
      stdoutIsTTY: true,
      supportsColorStdout: true,
      configDoc: { default: {}, profiles: {} },
      configPath: "/tmp/fake/objectified/config.toml",
    });
    expect(r.verboseEffective).toBe(true);
  });
});
