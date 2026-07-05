/**
 * Tests for the public export helpers — MFX-7.1 (#3860).
 *
 * Pins the framework-free logic behind the public export dialog: URL building against the
 * anonymous `/v1/browse/.../export/*` surface, target ordering, the tier badge/label mapping,
 * the lossy-export acknowledgement gate, the fidelity warning sentence, and download-filename
 * derivation.
 */

import { describe, expect, it } from 'vitest';
import {
  exportFallbackFilename,
  fidelityWarningMessage,
  filenameFromContentDisposition,
  publicExportDocumentUrl,
  publicExportPreviewUrl,
  publicExportTargetsUrl,
  requiresExportAcknowledgement,
  serializationAcceptHeader,
  sortTargetsForDisplay,
  tierBadgeClass,
  tierLabel,
  type ExportFidelityTier,
  type PublicExportTarget,
} from '../publicExport';

const COORDS = { tenantSlug: 'acme', projectSlug: 'widgets', versionSlug: '1.0.0' };

function target(
  key: string,
  tier: ExportFidelityTier,
  overrides: {
    preserved_percent?: number;
    total?: number;
    dropped?: number;
    approximated?: number;
    synthesized?: number;
    available?: boolean;
    label?: string;
  } = {}
): PublicExportTarget {
  const preserved_percent = overrides.preserved_percent ?? (tier === 'lossless' ? 100 : 50);
  return {
    descriptor: {
      key,
      format: `${key}-1`,
      label: overrides.label ?? key.toUpperCase(),
      description: `${key} description`,
      icon: 'file',
      paradigm: 'rest',
      multi_file: false,
      needs_toolchain: false,
      available: overrides.available ?? true,
      unavailable_reason: overrides.available === false ? 'toolchain missing' : null,
    },
    capability_profile: {},
    options_schema: {},
    default_options: {},
    fidelity: {
      tier,
      preserved_percent,
      total: overrides.total ?? 10,
      preserved: Math.round(((overrides.total ?? 10) * preserved_percent) / 100),
      dropped: overrides.dropped ?? 0,
      approximated: overrides.approximated ?? 0,
      synthesized: overrides.synthesized ?? 0,
    },
  };
}

describe('URL builders', () => {
  it('builds the public targets URL from the slug coordinates', () => {
    expect(publicExportTargetsUrl('http://localhost:8000/v1', COORDS)).toBe(
      'http://localhost:8000/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/export/targets'
    );
  });

  it('builds the public document URL from the slug coordinates', () => {
    expect(publicExportDocumentUrl('http://localhost:8000/v1', COORDS)).toBe(
      'http://localhost:8000/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/export/document'
    );
  });

  it('builds the public preview URL from the slug coordinates', () => {
    expect(publicExportPreviewUrl('http://localhost:8000/v1', COORDS)).toBe(
      'http://localhost:8000/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/export/preview'
    );
  });

  it('URL-encodes slug segments', () => {
    const url = publicExportTargetsUrl('http://localhost:8000/v1', {
      tenantSlug: 'acme co',
      projectSlug: 'widgets/v2',
      versionSlug: '1.0.0+build',
    });
    expect(url).toBe(
      'http://localhost:8000/v1/browse/tenants/acme%20co/projects/widgets%2Fv2/versions/1.0.0%2Bbuild/export/targets'
    );
  });
});

describe('serializationAcceptHeader', () => {
  it('maps json and yaml to their media types', () => {
    expect(serializationAcceptHeader('json')).toBe('application/json');
    expect(serializationAcceptHeader('yaml')).toBe('application/yaml');
  });
});

describe('sortTargetsForDisplay', () => {
  it('orders lossless before lossy before types-only', () => {
    const sorted = sortTargetsForDisplay([
      target('avro', 'types-only'),
      target('asyncapi', 'lossy'),
      target('openapi', 'lossless'),
    ]);
    expect(sorted.map((t) => t.descriptor.key)).toEqual(['openapi', 'asyncapi', 'avro']);
  });

  it('pushes unavailable targets to the end regardless of fidelity', () => {
    const sorted = sortTargetsForDisplay([
      target('tsp', 'lossless', { available: false }),
      target('asyncapi', 'lossy'),
    ]);
    expect(sorted.map((t) => t.descriptor.key)).toEqual(['asyncapi', 'tsp']);
  });

  it('breaks fidelity ties by preserved percent, then label', () => {
    const sorted = sortTargetsForDisplay([
      target('b-target', 'lossy', { preserved_percent: 40, label: 'Beta' }),
      target('a-target', 'lossy', { preserved_percent: 40, label: 'Alpha' }),
      target('c-target', 'lossy', { preserved_percent: 80, label: 'Gamma' }),
    ]);
    expect(sorted.map((t) => t.descriptor.label)).toEqual(['Gamma', 'Alpha', 'Beta']);
  });

  it('does not mutate the input array', () => {
    const input = [target('avro', 'types-only'), target('openapi', 'lossless')];
    sortTargetsForDisplay(input);
    expect(input[0].descriptor.key).toBe('avro');
  });
});

describe('tier presentation', () => {
  it('labels every tier with the ADE wording', () => {
    expect(tierLabel('lossless')).toBe('Full fidelity');
    expect(tierLabel('lossy')).toBe('May lose fidelity');
    expect(tierLabel('types-only')).toBe('Types only');
  });

  it('maps tiers to emerald/amber/rose badge classes with dark variants', () => {
    expect(tierBadgeClass('lossless')).toContain('emerald');
    expect(tierBadgeClass('lossy')).toContain('amber');
    expect(tierBadgeClass('types-only')).toContain('rose');
    expect(tierBadgeClass('lossless')).toContain('dark:');
  });
});

describe('requiresExportAcknowledgement', () => {
  it('gates every tier short of lossless', () => {
    expect(requiresExportAcknowledgement('lossless')).toBe(false);
    expect(requiresExportAcknowledgement('lossy')).toBe(true);
    expect(requiresExportAcknowledgement('types-only')).toBe(true);
  });
});

describe('fidelityWarningMessage', () => {
  it('is empty for a lossless target', () => {
    expect(fidelityWarningMessage(target('openapi', 'lossless'))).toBe('');
  });

  it('describes a lossy export with its loss counts and preserved percent', () => {
    const message = fidelityWarningMessage(
      target('asyncapi', 'lossy', {
        preserved_percent: 70,
        total: 10,
        dropped: 2,
        approximated: 1,
      })
    );
    expect(message).toContain('ASYNCAPI');
    expect(message).toContain('may lose fidelity');
    expect(message).toContain('70% of 10 source constructs are preserved');
    expect(message).toContain('2 dropped');
    expect(message).toContain('1 approximated');
  });

  it('calls out that a types-only target drops operations', () => {
    const message = fidelityWarningMessage(
      target('avro', 'types-only', { preserved_percent: 50, total: 4, dropped: 2 })
    );
    expect(message).toContain('keeps only the type definitions');
    expect(message).toContain('operations are not carried over');
  });

  it('omits the loss breakdown when no counts are present', () => {
    const message = fidelityWarningMessage(
      target('asyncapi', 'lossy', { preserved_percent: 90, total: 10 })
    );
    expect(message).not.toContain('(');
  });
});

describe('download filenames', () => {
  it('extracts a quoted filename from Content-Disposition', () => {
    expect(
      filenameFromContentDisposition('attachment; filename="asyncapi.yaml"', 'fallback.json')
    ).toBe('asyncapi.yaml');
  });

  it('extracts an unquoted filename', () => {
    expect(
      filenameFromContentDisposition('attachment; filename=openapi.json', 'fallback.json')
    ).toBe('openapi.json');
  });

  it('falls back when the header is missing or nameless', () => {
    expect(filenameFromContentDisposition(null, 'fallback.json')).toBe('fallback.json');
    expect(filenameFromContentDisposition('attachment', 'fallback.json')).toBe('fallback.json');
  });

  it('builds a stable fallback name from the coordinates and target', () => {
    expect(exportFallbackFilename(COORDS, 'asyncapi', 'yaml')).toBe(
      'widgets-1.0.0-asyncapi.yaml'
    );
    expect(exportFallbackFilename(COORDS, 'openapi', 'json')).toBe('widgets-1.0.0-openapi.json');
  });
});
