import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assertWritableConfigKey,
  defaultConfigDirectory,
  defaultConfigFilePath,
  ensureDefaultConfigFile,
  loadTomlConfigFile,
  resolveConfigFilePath,
  splitDottedKey,
} from "../src/lib/config.js";
import { CliError } from "../src/lib/errors.js";

describe("config path resolution (#3188)", () => {
  const homedir = () => "/home/testuser";

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("uses OBJECTIFIED_CONFIG when set", () => {
    vi.stubEnv("OBJECTIFIED_CONFIG", "/custom/objectified.toml");
    expect(resolveConfigFilePath(undefined, process.env, homedir)).toBe("/custom/objectified.toml");
  });

  it("expands ~/ in OBJECTIFIED_CONFIG", () => {
    vi.stubEnv("OBJECTIFIED_CONFIG", "~/foo/config.toml");
    expect(resolveConfigFilePath(undefined, process.env, homedir)).toBe(
      "/home/testuser/foo/config.toml",
    );
  });

  it("prefers --config flag over OBJECTIFIED_CONFIG", () => {
    vi.stubEnv("OBJECTIFIED_CONFIG", "/env.toml");
    expect(resolveConfigFilePath("/flag.toml", process.env, homedir)).toBe("/flag.toml");
  });

  it("on Linux uses XDG_CONFIG_HOME/objectified (env-paths)", () => {
    vi.stubEnv("XDG_CONFIG_HOME", "/xdg-config");
    const spy = vi.spyOn(process, "platform", "get").mockReturnValue("linux");
    expect(defaultConfigDirectory(process.env, homedir)).toBe("/xdg-config/objectified");
    expect(defaultConfigFilePath(process.env, homedir)).toBe("/xdg-config/objectified/config.toml");
    spy.mockRestore();
  });

  it("on macOS uses ~/.config/objectified when XDG_CONFIG_HOME is unset", () => {
    const spy = vi.spyOn(process, "platform", "get").mockReturnValue("darwin");
    expect(defaultConfigDirectory({}, homedir)).toBe("/home/testuser/.config/objectified");
    spy.mockRestore();
  });

  it("on macOS respects XDG_CONFIG_HOME", () => {
    const spy = vi.spyOn(process, "platform", "get").mockReturnValue("darwin");
    expect(defaultConfigDirectory({ XDG_CONFIG_HOME: "/xdg" }, homedir)).toBe("/xdg/objectified");
    spy.mockRestore();
  });

  it("on Windows uses APPDATA\\\\Objectified\\\\config.toml", () => {
    const spy = vi.spyOn(process, "platform", "get").mockReturnValue("win32");
    vi.stubEnv("APPDATA", "C:\\Users\\Me\\AppData\\Roaming");
    expect(defaultConfigDirectory(process.env, () => "C:\\Users\\Me")).toBe(
      "C:\\Users\\Me\\AppData\\Roaming\\Objectified",
    );
    expect(resolveConfigFilePath(undefined, process.env, () => "C:\\Users\\Me")).toBe(
      "C:\\Users\\Me\\AppData\\Roaming\\Objectified\\config.toml",
    );
    spy.mockRestore();
  });

  it("creates default config with mode 0600 on Unix", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-mode-"));
    const cfg = path.join(dir, "config.toml");
    await ensureDefaultConfigFile(cfg);
    const stat = fs.statSync(cfg);
    if (process.platform !== "win32") {
      expect((stat.mode & 0o777).toString(8)).toBe("600");
    }
  });

  it("ensureDefaultConfigFile: skips creation when file already exists", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-exists-"));
    const cfg = path.join(dir, "config.toml");
    fs.writeFileSync(cfg, "default_profile = \"default\"\n");
    await ensureDefaultConfigFile(cfg); // should not throw
    expect(fs.readFileSync(cfg, "utf8")).toBe("default_profile = \"default\"\n");
  });

  it("ensureDefaultConfigFile: throws CliError when path is a directory", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-dir-"));
    const asDir = path.join(dir, "config.toml");
    fs.mkdirSync(asDir);
    await expect(ensureDefaultConfigFile(asDir)).rejects.toThrow(CliError);
  });
});

describe("loadTomlConfigFile (#3188)", () => {
  it("throws CliError on invalid TOML", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-parse-"));
    const cfg = path.join(dir, "bad.toml");
    fs.writeFileSync(cfg, "this is not valid toml = = =\n");
    expect(() => loadTomlConfigFile(cfg)).toThrow(CliError);
  });

  it("CliError on parse failure has exit code 11", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-parse-"));
    const cfg = path.join(dir, "bad.toml");
    fs.writeFileSync(cfg, "[[broken\n");
    let err: unknown;
    try {
      loadTomlConfigFile(cfg);
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(CliError);
    expect((err as CliError).exitCode).toBe(11);
  });
});

describe("splitDottedKey (#3188)", () => {
  it("rejects keys with consecutive dots", () => {
    expect(() => splitDottedKey("profile..prod")).toThrow(CliError);
  });

  it("rejects keys with a trailing dot", () => {
    expect(() => splitDottedKey("profile.")).toThrow(CliError);
  });

  it("rejects keys with a leading dot", () => {
    expect(() => splitDottedKey(".profile.prod")).toThrow(CliError);
  });

  it("accepts a valid dotted key", () => {
    expect(splitDottedKey("profile.staging.base_url")).toEqual(["profile", "staging", "base_url"]);
  });

  it("rejects an empty key", () => {
    expect(() => splitDottedKey("")).toThrow(CliError);
  });
});

describe("assertWritableConfigKey (#3188)", () => {
  const shouldBlock = [
    "api_key",
    "api-key",
    "apiKey",
    "apikey",
    "secrets.api_key",
    "access_token",
    "accessToken",
    "refresh_token",
    "refreshToken",
    "profile.prod.token",
    "password",
    "secret",
    "credential",
    "private_key",
    "privateKey",
  ];

  for (const key of shouldBlock) {
    it(`blocks secret key: ${key}`, () => {
      expect(() => assertWritableConfigKey(key)).toThrow(CliError);
    });
  }

  it("allows legitimate config keys", () => {
    expect(() => assertWritableConfigKey("profile.staging.base_url")).not.toThrow();
    expect(() => assertWritableConfigKey("profile.staging.tenant_slug")).not.toThrow();
    expect(() => assertWritableConfigKey("default_profile")).not.toThrow();
    expect(() => assertWritableConfigKey("default.api_key")).not.toThrow();
    expect(() => assertWritableConfigKey("profile.staging.api_key")).not.toThrow();
    expect(() => assertWritableConfigKey("profile.staging.api-key")).not.toThrow();
  });
});
