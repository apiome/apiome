/**
 * Unit tests for source-format checks helpers (CLX-2.4 / #4854).
 */

import {
  capabilityForSourceFormat,
  outcomeChipClass,
  parseLintEvidenceCoverage,
  scannerLabel,
} from '@/app/utils/source-format-checks';

describe('parseLintEvidenceCoverage', () => {
  it('normalizes camelCase and snake_case coverage rows', () => {
    const entries = parseLintEvidenceCoverage({
      coverage: [
        {
          scannerId: 'apiome.native-lint',
          outcome: 'passed',
          coverage: { state: 'full' },
        },
        {
          scanner_id: 'buf.lint',
          outcome: 'not_run',
          coverage: { state: 'none' },
        },
      ],
    });
    expect(entries).toHaveLength(2);
    expect(entries[0].scannerId).toBe('apiome.native-lint');
    expect(entries[1].scannerId).toBe('buf.lint');
    expect(entries[1].outcome).toBe('not_run');
  });

  it('returns empty for malformed payloads', () => {
    expect(parseLintEvidenceCoverage(null)).toEqual([]);
    expect(parseLintEvidenceCoverage({ coverage: 'nope' })).toEqual([]);
  });
});

describe('capabilityForSourceFormat', () => {
  const formats = [
    {
      format: 'smithy',
      mode: 'unsupported',
      relatedIssues: ['https://github.com/apiome/apiome/issues/3810'],
    },
    { format: 'protobuf', mode: 'native', adaptedScanners: ['buf.lint'] },
  ];

  it('matches aliases like grpc → protobuf', () => {
    expect(capabilityForSourceFormat(formats, 'grpc')?.format).toBe('protobuf');
  });

  it('returns unsupported smithy with linked issues', () => {
    const cap = capabilityForSourceFormat(formats, 'smithy');
    expect(cap?.mode).toBe('unsupported');
    expect(cap?.relatedIssues?.[0]).toContain('3810');
  });
});

describe('presentation helpers', () => {
  it('labels known scanners', () => {
    expect(scannerLabel('graphql.eslint')).toBe('GraphQL ESLint');
    expect(scannerLabel('custom.tool')).toBe('custom.tool');
  });

  it('returns token classes for outcomes', () => {
    expect(outcomeChipClass('passed')).toContain('emerald');
    expect(outcomeChipClass('unavailable')).toContain('rose');
    expect(outcomeChipClass('not_run')).toContain('gray');
  });
});
