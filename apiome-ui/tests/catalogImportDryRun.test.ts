/**
 * The catalog import Dry run's pure rules (MFI-26.4, #4097): the footer button, the shared
 * pre-flight request, and the prediction built from a pre-flight report.
 */

import { describe, expect, it } from '@jest/globals';

import { catalogImportDryRunFor } from '../src/app/components/ade/import/importWizardModel';
import { buildCatalogPreflightRequest, type PreflightReport } from '../src/app/utils/import-preflight';
import {
  describeDryRunCounts,
  predictCatalogImport,
} from '../src/app/components/ade/dashboard/catalog/catalogImportDryRun';

const IDENTITY = { name: 'Orders API', slug: 'orders-api' };

/** A completed pre-flight report for a GraphQL schema; `overrides` swap fields under test. */
function report(overrides: Partial<PreflightReport> = {}): PreflightReport {
  return {
    ok: true,
    detection: { adapter_key: 'graphql', matched: true, importable: true },
    routing: {
      target: 'catalog',
      publishable: false,
      reason: 'GraphQL imports are stored in the catalog unconverted.',
    },
    paradigm: 'graphql',
    format: 'graphql',
    counts: { services: 1, operations: 4, types: 12, channels: 0 },
    fingerprint: 'abcdef0123456789abcdef',
    lint: { score: 87.6, grade: 'B' },
    policy: {
      verdict: 'pass',
      blocking: false,
      source: 'default',
      reason: '',
      threshold_score: null,
      allow_override: true,
    } as PreflightReport['policy'],
    ...overrides,
  };
}

describe('catalogImportDryRunFor', () => {
  const base = {
    step: 'options' as const,
    storing: false,
    writesCatalogItem: true,
    canCommit: true,
    running: false,
  };

  it('offers Dry run on the Options step', () => {
    expect(catalogImportDryRunFor(base)).toEqual({ label: 'Dry run', disabled: false, reason: null });
  });

  it.each(['source', 'detect', 'quality', 'import'] as const)('is not drawn on the %s step', (step) => {
    expect(catalogImportDryRunFor({ ...base, step })).toBeNull();
  });

  it('is not drawn when the step writes no catalog item (JSON Schema → Types)', () => {
    expect(catalogImportDryRunFor({ ...base, writesCatalogItem: false })).toBeNull();
  });

  it('is refused, with a reason, while one runs, while committing, or when the commit could not run', () => {
    expect(catalogImportDryRunFor({ ...base, running: true })).toEqual({
      label: 'Running dry run…',
      disabled: true,
      reason: 'A dry run is already running.',
    });
    expect(catalogImportDryRunFor({ ...base, storing: true })).toMatchObject({
      disabled: true,
      reason: 'The import is already running.',
    });
    expect(catalogImportDryRunFor({ ...base, canCommit: false })).toMatchObject({
      disabled: true,
      reason: 'This format cannot be imported in this deployment.',
    });
    expect(
      catalogImportDryRunFor({ ...base, canCommit: false, unavailableReason: 'protoc is not installed.' })
        ?.reason,
    ).toBe('protoc is not installed.');
  });
});

describe('buildCatalogPreflightRequest', () => {
  it('targets the catalog and forwards the URL only for URL intake', () => {
    expect(
      buildCatalogPreflightRequest({
        documentBase64: 'eA==',
        sourceKind: 'graphql',
        label: 'https://example.com/schema.graphql',
        inputKind: 'url',
        archiveRoot: null,
        url: 'https://example.com/schema.graphql',
      }),
    ).toEqual({
      document_base64: 'eA==',
      source_kind: 'graphql',
      filename: 'https://example.com/schema.graphql',
      url: 'https://example.com/schema.graphql',
      input_kind: 'url',
      archive_root: undefined,
      import_target: 'catalog',
    });

    const paste = buildCatalogPreflightRequest({
      documentBase64: 'eA==',
      sourceKind: null,
      label: '',
      inputKind: 'fileset',
      archiveRoot: 'protos/api.proto',
      url: 'ignored',
    });
    expect(paste.url).toBeUndefined();
    expect(paste.source_kind).toBeUndefined();
    expect(paste.filename).toBeUndefined();
    expect(paste.archive_root).toBe('protos/api.proto');
  });
});

describe('predictCatalogImport', () => {
  it('predicts the format, destination, identity, contents and fingerprint', () => {
    const prediction = predictCatalogImport(report(), IDENTITY);
    expect(prediction.ok).toBe(true);
    expect(prediction.formatLabel).toBe('GraphQL');
    expect(prediction.destination).toBe('catalog');
    expect(prediction.destinationLabel).toMatch(/Catalog item/);
    expect(prediction.reason).toMatch(/stored in the catalog/);
    expect(prediction.routesElsewhere).toBe(false);
    expect(prediction.identity).toEqual(IDENTITY);
    expect(prediction.counts).toEqual({ services: 1, operations: 4, types: 12, channels: 0 });
    expect(prediction.lint).toEqual({ score: 87.6, grade: 'B' });
    expect(prediction.fingerprint).toBe('abcdef0123456789abcdef');
    expect(prediction.error).toBeNull();
  });

  it('flags a route other than the catalog', () => {
    const prediction = predictCatalogImport(
      report({ routing: { target: 'project', reason: 'OpenAPI creates a Project.' } }),
      IDENTITY,
    );
    expect(prediction.destination).toBe('project');
    expect(prediction.destinationLabel).toBe('Project (publishable)');
    expect(prediction.routesElsewhere).toBe(true);
  });

  it('carries the importer error and remediation when the import would fail', () => {
    const prediction = predictCatalogImport(
      report({
        ok: false,
        routing: null,
        paradigm: null,
        format: null,
        counts: undefined,
        lint: null,
        fingerprint: null,
        error: {
          code: 'PARSE_ERROR',
          category: 'intake',
          message: 'Syntax error at line 3.',
          remediation: 'Fix the schema and try again.',
          retriable: false,
        },
      }),
      IDENTITY,
    );
    expect(prediction.ok).toBe(false);
    expect(prediction.destination).toBeNull();
    expect(prediction.formatLabel).toBe('GraphQL'); // falls back to the adapter that ran
    expect(prediction.counts).toEqual({ services: 0, operations: 0, types: 0, channels: 0 });
    expect(prediction.lint).toBeNull();
    expect(prediction.error).toEqual({
      message: 'Syntax error at line 3.',
      remediation: 'Fix the schema and try again.',
    });
  });

  it('still explains a failure that arrived without an error payload', () => {
    const prediction = predictCatalogImport(report({ ok: false, error: null }), IDENTITY);
    expect(prediction.error?.message).toMatch(/could not read/);
  });

  it('ignores an unknown routing target', () => {
    const prediction = predictCatalogImport(report({ routing: { target: 'elsewhere' } }), IDENTITY);
    expect(prediction.destination).toBeNull();
    expect(prediction.routesElsewhere).toBe(false);
  });
});

describe('describeDryRunCounts', () => {
  it('names only the non-zero counts, singular or plural', () => {
    expect(describeDryRunCounts({ services: 1, operations: 4, types: 0, channels: 2 })).toBe(
      '1 service · 4 operations · 2 channels',
    );
    expect(describeDryRunCounts({ services: 0, operations: 0, types: 0, channels: 0 })).toBe(
      'No entities',
    );
  });
});
