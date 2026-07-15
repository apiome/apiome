/**
 * projectionParityIssues — cross-surface projection-evidence parity (EFP-1.3, #4812).
 *
 * The UI leg of the projection contract corpus: the fidelity envelope every export
 * surface relays (preview, verify, job result) must tell one story across its report
 * counts, coarse summary, and projection status/reason counts — and the UI must reject
 * unknown reason codes rather than render them.
 *
 * The clean fixture (`fixtures/projectionParityEnvelope.json`) is a checked-in copy of
 * the apiome-rest corpus golden `parity_envelope_graphql.json` (rich source → GraphQL
 * SDL), so this checker is exercised over the exact envelope bytes the REST corpus
 * produced — the same fixture apiome-cli's parity tests consume. Regenerate all copies
 * together when the contract changes (`UPDATE_PROJECTION_GOLDENS=1` in apiome-rest,
 * then re-copy).
 */

import { readFileSync } from 'fs';
import { join } from 'path';

import { isKnownReasonCode } from '../src/app/components/ade/dashboard/export/capabilityRegistry';
import {
  projectionParityIssues,
  type ExportFidelityEnvelope,
} from '../src/app/components/ade/dashboard/export/exportFidelityPreview';

const FIXTURE = JSON.parse(
  readFileSync(join(__dirname, 'fixtures', 'projectionParityEnvelope.json'), 'utf-8'),
);

/** A deep copy of the shared parity fixture, safe to tamper per-test. */
function envelope(): ExportFidelityEnvelope {
  return JSON.parse(JSON.stringify(FIXTURE)) as ExportFidelityEnvelope;
}

describe('shared REST corpus fixture', () => {
  it('passes the parity checker byte-for-byte', () => {
    expect(projectionParityIssues(envelope())).toEqual([]);
  });

  it('carries only canonical reason codes', () => {
    for (const code of Object.keys(envelope().projection!.reason_counts)) {
      expect(isKnownReasonCode(code)).toBe(true);
    }
  });

  it('is a lossy envelope with real evidence (the fixture proves something)', () => {
    const fixture = envelope();
    expect(fixture.projection!.is_lossless).toBe(false);
    expect(fixture.projection!.evidence_count).toBeGreaterThan(0);
    expect(fixture.projection!.manifest_hash).toBeTruthy();
  });
});

describe('missing blocks degrade explicitly', () => {
  it('reports a pre-projection (older server) envelope as exactly one missing-block issue', () => {
    const preProjection = envelope();
    delete preProjection.projection;
    expect(projectionParityIssues(preProjection)).toEqual([
      'envelope is missing its projection summary block (EFP-1.1)',
    ]);
  });

  it('reports missing report/summary blocks', () => {
    const bare = {} as ExportFidelityEnvelope;
    expect(projectionParityIssues(bare)).toEqual(['envelope is missing its report/summary blocks']);
  });
});

describe('each tampering is detected', () => {
  const cases: Array<[string, (e: ExportFidelityEnvelope) => void, string]> = [
    [
      'report kind count drift',
      (e) => {
        e.report.kind_counts['drop'] = 99;
      },
      "kind_counts['drop']",
    ],
    [
      'summary dropped drift',
      (e) => {
        (e.summary as Record<string, unknown>)['dropped'] = 99;
      },
      'summary dropped=99',
    ],
    [
      'summary total drift',
      (e) => {
        (e.summary as Record<string, unknown>)['total'] = 99;
      },
      'summary total=99',
    ],
    [
      'projection status count drift',
      (e) => {
        e.projection!.status_counts['retained'] = 99;
      },
      'disagrees with projection',
    ],
    [
      'unknown reason code',
      (e) => {
        e.projection!.reason_counts['destination_broken'] = 1;
      },
      'unknown reason code',
    ],
    [
      'false lossless claim',
      (e) => {
        e.projection!.is_lossless = true;
      },
      'is_lossless',
    ],
    [
      'missing snapshot id',
      (e) => {
        e.projection!.manifest_hash = '';
      },
      'manifest_hash',
    ],
  ];

  it.each(cases)('%s', (_name, tamper, expectedFragment) => {
    const tampered = envelope();
    tamper(tampered);
    const issues = projectionParityIssues(tampered);
    expect(issues.length).toBeGreaterThan(0);
    expect(issues.some((issue) => issue.includes(expectedFragment))).toBe(true);
  });
});
