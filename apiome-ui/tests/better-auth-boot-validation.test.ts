/**
 * @jest-environment node
 *
 * Boot-time provider validation parity under the Better Auth engine (OLO-10.9, #5004).
 *
 * OLO-7.2 fails a partially-configured sign-in provider loud at startup (or, in `warn` mode, logs and
 * leaves it disabled) via the Next.js `register()` hook in `src/instrumentation.ts`. That hook is
 * gated only on the Node.js runtime — **never** on `AUTH_ENGINE` — and validates env against the
 * shared `PROVIDER_REGISTRY` that both engines build their provider set from. So the OLO-7.2 boot
 * contract must hold identically when `AUTH_ENGINE=better-auth`.
 *
 * These tests are the OLO-10.9 guardrail that was missing: they drive the real boot hook with the
 * Better Auth engine selected and pin that strict still aborts, warn still degrades, a coherent env
 * still boots clean, and — crucially — that the hook is not engine-gated (next-auth behaves the same).
 * `validateProviderEnv` reads the live `process.env` (the boot hook has no injectable env), so each
 * test scrubs every provider env var first to isolate the case.
 */

import { PROVIDER_REGISTRY } from '../lib/auth/provider-registry';

/** Every required provider env var across the registry — the keys a boot case must control. */
const PROVIDER_ENV_KEYS = Array.from(
  new Set(PROVIDER_REGISTRY.flatMap((provider) => [...provider.requiredEnvKeys]))
);

/** Provider keys plus the switches the boot hook and validation mode read. */
const CONTROLLED_KEYS = [...PROVIDER_ENV_KEYS, 'AUTH_PROVIDER_VALIDATION', 'AUTH_ENGINE', 'NEXT_RUNTIME'];

describe('OLO-7.2 boot validation holds under AUTH_ENGINE=better-auth (OLO-10.9)', () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of CONTROLLED_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
    // The boot hook only runs on the Node.js runtime; select the Better Auth engine for every case
    // (individual tests override AUTH_ENGINE where they assert engine-independence).
    process.env.NEXT_RUNTIME = 'nodejs';
    process.env.AUTH_ENGINE = 'better-auth';
    jest.resetModules();
    // warn mode logs by design; silence it so the suite stays clean while still asserting the call.
    jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterEach(() => {
    for (const key of CONTROLLED_KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
    jest.restoreAllMocks();
  });

  test('strict mode still aborts startup on partial provider config with the Better Auth engine', async () => {
    // github id set, secret missing ⇒ partial config ⇒ strict (default) must refuse to start.
    process.env.GITHUB_ID = 'gh-id';
    const { register } = await import('../src/instrumentation');

    await expect(register()).rejects.toThrow(/Refusing to start/);
  });

  test('warn mode logs and does not throw, engine notwithstanding', async () => {
    process.env.AUTH_PROVIDER_VALIDATION = 'warn';
    process.env.GITLAB_CLIENT_ID = 'gl-id'; // secret missing ⇒ partial

    const { register } = await import('../src/instrumentation');

    await expect(register()).resolves.toBeUndefined();
    expect(console.warn).toHaveBeenCalled();
  });

  test('a coherent env boots cleanly under Better Auth — no throw, no warning', async () => {
    // github fully set, every other provider fully unset ⇒ both are valid deployments.
    process.env.GITHUB_ID = 'gh-id';
    process.env.GITHUB_SECRET = 'gh-secret';

    const { register } = await import('../src/instrumentation');

    await expect(register()).resolves.toBeUndefined();
    expect(console.warn).not.toHaveBeenCalled();
  });

  test('the boot hook is not engine-gated — next-auth aborts on the same partial config', async () => {
    process.env.AUTH_ENGINE = 'next-auth';
    process.env.GITHUB_ID = 'gh-id'; // secret missing ⇒ partial

    const { register } = await import('../src/instrumentation');

    await expect(register()).rejects.toThrow(/Refusing to start/);
  });

  test('the hook is skipped off the Node.js runtime regardless of engine (no validation on the edge)', async () => {
    process.env.NEXT_RUNTIME = 'edge';
    process.env.GITHUB_ID = 'gh-id'; // partial, but the edge runtime must not validate

    const { register } = await import('../src/instrumentation');

    await expect(register()).resolves.toBeUndefined();
  });
});
