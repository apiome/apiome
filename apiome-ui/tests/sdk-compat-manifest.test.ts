/**
 * The generator compatibility manifest view model — SGD-2.1 (#4735).
 *
 * Runs against apiome-rest's golden manifest (`apiome-rest/tests/golden/sdk_compat_manifest/widgets.json`),
 * the same file the REST builder test pins and the CLI test renders, so the dashboard and
 * `apiome sdk compatibility` provably read one document.
 */

import * as fs from 'fs';
import * as path from 'path';

import {
  artifactLabel,
  coverageLabel,
  isComplete,
  semverSummary,
  severityCounts,
  sortedFindings,
  type SdkCompatManifest,
} from '@lib/sdk-compat-manifest';

const GOLDEN = path.resolve(__dirname, '..', '..', 'apiome-rest', 'tests', 'golden', 'sdk_compat_manifest', 'widgets.json');
const MANIFEST = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as SdkCompatManifest;

describe('sdk compatibility manifest view model', () => {
  it('reads the golden manifest the REST builder and the CLI share', () => {
    expect(MANIFEST.schema_version).toBe('apiome.sdk.compat-manifest/v1');
    expect(MANIFEST.artifacts.map((a) => a.id)).toEqual([
      'snippets-ts', 'snippets-python', 'snippets-curl', 'go-client',
      'server-fastapi', 'server-express', 'terraform-provider', 'mcp-server',
    ]);
  });

  it('lists every finding, most severe first, each with an action', () => {
    const findings = sortedFindings(MANIFEST);
    expect(findings).toHaveLength(MANIFEST.findings_count);
    expect(findings.every((f) => f.action.length > 0 && f.reason.length > 0)).toBe(true);
    const ranks = findings.map((f) => ['error', 'warning', 'info'].indexOf(f.severity));
    expect([...ranks].sort((a, b) => a - b)).toEqual(ranks);
  });

  it('counts findings by severity', () => {
    const counts = severityCounts(MANIFEST);
    expect(counts.error + counts.warning + counts.info).toBe(MANIFEST.findings_count);
  });

  it('labels artifacts and coverage', () => {
    expect(artifactLabel('go-client')).toBe('Go client');
    expect(artifactLabel('something-new')).toBe('something-new');
    const go = MANIFEST.artifacts.find((a) => a.id === 'go-client')!;
    expect(coverageLabel(go)).toBe(`${go.coverage.operations} of ${go.coverage.of} operations`);
    expect(isComplete(go)).toBe(go.coverage.operations >= go.coverage.of);
    expect(coverageLabel({ included: false, coverage: { operations: 0, of: 3 } })).toBe('Not generated');
    expect(coverageLabel({ included: true, coverage: { operations: 1, of: 1 } })).toBe('1 of 1 operation');
  });

  it('summarises semver', () => {
    expect(semverSummary(MANIFEST.semver)).toBe(
      'Non-breaking since 0.9.0: needs a minor bump; the labels declare major — consistent.',
    );
    expect(semverSummary({ classification: 'unknown' })).toMatch(/^Unknown/);
    expect(semverSummary({ classification: 'breaking', baseline_version: '1.0.0', required_bump: 'major', declared_bump: 'minor', consistent: false })).toMatch(/inconsistent\.$/);
  });
});
