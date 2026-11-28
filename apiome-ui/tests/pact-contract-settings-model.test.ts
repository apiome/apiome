/**
 * The Secrets / CI / Agents model — PFX-8.15 (#7312): the proxies' body checks (nothing unknown is
 * forwarded or dropped; a value is never repeated in a refusal), what a secret's row says, the broker
 * address, and the pipeline recipes, which must be the tested sources byte for byte.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import {
  AGENT_KEYS,
  AGENT_SWITCHES,
  COMMIT_KEYS,
  blockers,
  brokerBaseUrl,
  checkSecretCreate,
  checkSecretUpdate,
  checkSwitchesBody,
  inUse,
  usedByText,
  type SecretRecord,
} from '../lib/pact-contract-settings';
import { PACT_CI_RECIPES } from '../lib/pact-ci-recipes.generated';
import fixture from './fixtures/pact-contract-settings.json';

const REPO = path.resolve(__dirname, '..', '..');
const [STAGING, GITHUB, MIGRATED, UNUSED] = fixture.secrets.secrets as SecretRecord[];

describe('the proxies’ body checks', () => {
  it('passes booleans for the named switches only', () => {
    expect(checkSwitchesBody({ bidirectional: true }, COMMIT_KEYS)).toEqual({ ok: true, body: { bidirectional: true } });
    expect(checkSwitchesBody({ check_runs: true }, COMMIT_KEYS)).toEqual({ ok: false, error: 'Unsupported field check_runs.' });
    expect(checkSwitchesBody({ record: 'yes' }, AGENT_KEYS)).toEqual({ ok: false, error: 'record must be true or false.' });
    expect(checkSwitchesBody([], AGENT_KEYS)).toEqual({ ok: false, error: 'Send the switches as a JSON object.' });
  });

  it('checks a new secret without ever repeating its value', () => {
    expect(checkSecretCreate({ name: 'ci_token', value: 'v' })).toEqual({ ok: true, body: { name: 'ci_token', value: 'v' } });
    expect(checkSecretCreate({ name: '9lives', value: 'v' })).toMatchObject({ ok: false });
    expect(checkSecretCreate({ name: 'ci_token', value: '' })).toEqual({ ok: false, error: 'Enter the value.' });
    const long = checkSecretCreate({ name: 'ci_token', value: 'x'.repeat(4097) });
    expect(long).toEqual({ ok: false, error: 'A value is at most 4096 characters.' });
    expect(checkSecretCreate({ name: 'a', value: 'v', scope: 'all' })).toEqual({ ok: false, error: 'Unsupported field scope.' });
  });

  it('refuses a rename and passes a new value', () => {
    expect(checkSecretUpdate({ name: 'other' })).toEqual({ ok: false, error: 'A secret cannot be renamed; create a new one.' });
    expect(checkSecretUpdate({ value: 'v', description: 'd' })).toEqual({ ok: true, body: { value: 'v', description: 'd' } });
    expect(checkSecretUpdate({ value: '' })).toEqual({ ok: false, error: 'Enter the value.' });
  });
});

describe('what a secret row says', () => {
  it('names what uses it, counting the webhooks that are off', () => {
    expect(usedByText(STAGING)).toBe('verification target staging');
    expect(usedByText(GITHUB)).toBe('3 webhooks');
    expect(usedByText(MIGRATED)).toBe('1 webhook (1 off)');
    expect(usedByText(UNUSED)).toBe('Nothing yet');
  });

  it('blocks deleting a secret in use, listing what uses it', () => {
    expect([inUse(GITHUB), inUse(UNUSED)]).toEqual([true, false]);
    expect(blockers(STAGING)).toEqual(['Verification target staging']);
    expect(blockers(GITHUB)[0]).toBe('Webhook “Verify Ledger API”');
  });
});

describe('the CI tab', () => {
  it('builds the broker address from REST’s public base and the workspace', () => {
    expect(brokerBaseUrl('https://api.apiome.dev/v1/', 'acme')).toBe('https://api.apiome.dev/v1/tenants/acme/pact-broker');
  });

  it('shows each recipe exactly as its tested source', () => {
    for (const recipe of PACT_CI_RECIPES.filter((item) => item.id !== 'github')) {
      expect(recipe.text).toBe(fs.readFileSync(path.join(REPO, recipe.source), 'utf8'));
    }
    const guide = fs.readFileSync(path.join(REPO, 'apiome-docs/docs/ship/pact-broker/ci-pact.mdx'), 'utf8');
    const github = PACT_CI_RECIPES.find((item) => item.id === 'github')!;
    expect(guide).toContain(github.text.trimEnd());
    expect(github.text.startsWith('# .github/workflows/pact.yml')).toBe(true);
  });

  it('is regenerated whenever a source changes', () => {
    const script = path.join(__dirname, '..', 'scripts', 'generate-pact-ci-recipes.mjs');
    // Exits 1 (and throws here) while lib/pact-ci-recipes.generated.ts differs from its sources.
    expect(() => execFileSync(process.execPath, [script, '--check'], { stdio: 'pipe' })).not.toThrow();
  });
});

describe('the Agents tab', () => {
  it('says which switches nothing enforces yet', () => {
    expect(AGENT_SWITCHES.filter((spec) => spec.notYet).map((spec) => spec.key)).toEqual(['draft', 'publish']);
  });
});
