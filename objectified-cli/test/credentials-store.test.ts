import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

const tempDirs: string[] = [];

function makeTempVaultDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-vault-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) fs.rmSync(dir, { force: true, recursive: true });
  delete process.env.OBJECTIFIED_CLI_CREDENTIAL_BACKEND;
  delete process.env.OBJECTIFIED_CLI_CREDENTIAL_VAULT_DIR;
  delete process.env.OBJECTIFIED_CLI_CREDENTIAL_DISABLE_FILE_FALLBACK;
  delete process.env.OBJECTIFIED_CLI_CREDENTIAL_VAULT_RESET;
  vi.resetModules();
  vi.doUnmock("keytar");
});

describe("CLI credential store", () => {
  it("stores only oauth tokens in the memory backend", async () => {
    process.env.OBJECTIFIED_CLI_CREDENTIAL_BACKEND = "memory";
    const { loadCliOAuthCredentials, resetMemoryCredentialBackend, saveCliOAuthCredentials } =
      await import("../src/lib/credentials/store.js");

    resetMemoryCredentialBackend();
    const bundleWithDisplayEmail: Parameters<typeof saveCliOAuthCredentials>[1] & {
      displayEmail: string;
    } = {
      accessToken: "access",
      refreshToken: "refresh",
      displayEmail: "user@example.com",
    };
    await saveCliOAuthCredentials("default", bundleWithDisplayEmail);

    await expect(loadCliOAuthCredentials("default")).resolves.toEqual({
      accessToken: "access",
      refreshToken: "refresh",
    });
  });

  it("stores API keys in the memory backend (#3195)", async () => {
    process.env.OBJECTIFIED_CLI_CREDENTIAL_BACKEND = "memory";
    const { loadCliStoredAuth, resetMemoryCredentialBackend, saveCliApiKeyCredentials } =
      await import("../src/lib/credentials/store.js");

    resetMemoryCredentialBackend();
    await saveCliApiKeyCredentials("default", "sk_live_unit_test_12345");

    await expect(loadCliStoredAuth("default")).resolves.toEqual({
      kind: "api_key",
      apiKey: "sk_live_unit_test_12345",
    });
  });

  it("wraps keytar load failures with an actionable error when file fallback is disabled", async () => {
    process.env.OBJECTIFIED_CLI_CREDENTIAL_DISABLE_FILE_FALLBACK = "1";
    vi.doMock("keytar", () => {
      throw new Error("libsecret missing");
    });

    const { saveCliOAuthCredentials } = await import("../src/lib/credentials/store.js");

    await expect(
      saveCliOAuthCredentials("default", {
        accessToken: "access",
        refreshToken: "refresh",
      }),
    ).rejects.toMatchObject({
      name: "ObjectifiedCliError",
      message: expect.stringContaining("OS keychain is unavailable for CLI credentials"),
      hint: expect.stringMatching(/libsecret|memory|FILE_FALLBACK/),
    });
  });

  it("persists OAuth in encrypted file vault when keytar is unavailable (#3197)", async () => {
    const dir = makeTempVaultDir();
    process.env.OBJECTIFIED_CLI_CREDENTIAL_VAULT_DIR = dir;
    vi.doMock("keytar", () => {
      throw new Error("no native keychain");
    });

    const {
      deleteCliOAuthCredentials,
      loadCliStoredAuth,
      resetFileBackendWarningForTests,
      saveCliOAuthCredentials,
    } = await import("../src/lib/credentials/store.js");
    resetFileBackendWarningForTests();

    await saveCliOAuthCredentials("default", {
      accessToken: "access-one",
      refreshToken: "refresh-one",
      tenantSlug: "acme",
    });
    await expect(loadCliStoredAuth("default")).resolves.toEqual({
      kind: "oauth",
      accessToken: "access-one",
      refreshToken: "refresh-one",
    });

    const enc = path.join(dir, "credentials.enc");
    expect(fs.existsSync(enc)).toBe(true);
    if (process.platform !== "win32") {
      expect(fs.statSync(enc).mode & 0o777).toBe(0o600);
      const passPath = path.join(dir, ".cli-credential-passphrase");
      expect(fs.existsSync(passPath)).toBe(true);
      expect(fs.statSync(passPath).mode & 0o777).toBe(0o600);
    }

    await saveCliOAuthCredentials("staging", {
      accessToken: "access-two",
      refreshToken: "refresh-two",
    });
    await expect(loadCliStoredAuth("default")).resolves.toMatchObject({
      accessToken: "access-one",
    });
    await expect(loadCliStoredAuth("staging")).resolves.toMatchObject({
      accessToken: "access-two",
    });

    await deleteCliOAuthCredentials("default");
    await expect(loadCliStoredAuth("default")).resolves.toBeNull();
    await expect(loadCliStoredAuth("staging")).resolves.toMatchObject({
      accessToken: "access-two",
    });

    await deleteCliOAuthCredentials("staging");
    expect(fs.existsSync(enc)).toBe(false);
    expect(fs.existsSync(path.join(dir, ".cli-credential-passphrase"))).toBe(false);
  });

  it("cleans file-vault credentials on logout even when fallback is disabled", async () => {
    const dir = makeTempVaultDir();
    process.env.OBJECTIFIED_CLI_CREDENTIAL_VAULT_DIR = dir;
    vi.doMock("keytar", () => {
      const noNative = async () => Promise.reject(new Error("no native keychain"));
      return {
        default: {
          deletePassword: noNative,
          getPassword: noNative,
          setPassword: noNative,
        },
      };
    });

    const { deleteCliOAuthCredentials, saveCliOAuthCredentials } = await import(
      "../src/lib/credentials/store.js"
    );

    await saveCliOAuthCredentials("default", {
      accessToken: "access-one",
      refreshToken: "refresh-one",
    });

    process.env.OBJECTIFIED_CLI_CREDENTIAL_DISABLE_FILE_FALLBACK = "1";
    await expect(deleteCliOAuthCredentials("default")).rejects.toMatchObject({
      name: "ObjectifiedCliError",
      message: expect.stringContaining("Could not delete CLI credentials from OS keychain"),
    });
    expect(fs.existsSync(path.join(dir, "credentials.enc"))).toBe(false);
    expect(fs.existsSync(path.join(dir, ".cli-credential-passphrase"))).toBe(false);
  });
});
