/**
 * TS ⇄ Python registry mirror test (OLO-9.1, #4984).
 *
 * The sign-in provider registry is duplicated across languages: the canonical TypeScript registry
 * (`lib/auth/provider-registry.ts`) and its server-side projection in Python
 * (`apiome-rest/src/app/auth_provider_registry.py`). REST cannot import TypeScript, so drift between
 * the two is a real risk — a provider added on one side but not the other silently breaks completeness
 * checks or enablement.
 *
 * The guard is a single source-of-truth snapshot committed at `scripts/auth_providers/registry.json`.
 * This test asserts the TypeScript registry serializes to that snapshot; the mirror on the Python side
 * (`test_auth_provider_registry.py::test_registry_mirrors_canonical_snapshot`) asserts the same for the
 * Python registry. Either registry drifting from the snapshot turns one suite red.
 *
 * Follows the golden-path contract precedent (`tests/contract/rest-golden-path-contract.test.ts`).
 */
import * as fs from 'fs';
import * as path from 'path';
import { PROVIDER_REGISTRY, ProviderDescriptor } from '../lib/auth/provider-registry';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SNAPSHOT_PATH = path.join(REPO_ROOT, 'scripts', 'auth_providers', 'registry.json');

/** One provider in the language-neutral snapshot shape (snake_case, matching the JSON). */
interface SnapshotProvider {
  id: string;
  label: string;
  status: string;
  required_fields: { field: string; kind: string; env_key: string }[];
}

/** Project a live TS descriptor into the neutral snapshot shape. */
function toSnapshot(descriptor: ProviderDescriptor): SnapshotProvider {
  return {
    id: descriptor.id,
    label: descriptor.label,
    status: descriptor.status,
    required_fields: descriptor.requiredFields.map((f) => ({
      field: f.field,
      kind: f.kind,
      env_key: f.envKey,
    })),
  };
}

describe('provider registry mirror (TS ⇄ canonical snapshot)', () => {
  const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, 'utf8')) as {
    providers: SnapshotProvider[];
  };

  it('the TypeScript registry matches the canonical snapshot exactly', () => {
    expect(PROVIDER_REGISTRY.map(toSnapshot)).toEqual(snapshot.providers);
  });

  it('every descriptor derives requiredEnvKeys from its requiredFields', () => {
    for (const descriptor of PROVIDER_REGISTRY) {
      expect(descriptor.requiredEnvKeys).toEqual(descriptor.requiredFields.map((f) => f.envKey));
    }
  });
});
