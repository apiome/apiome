/**
 * Unit tests for the catalog convert-to-OpenAPI back-link helpers (MFI-23.11, #4020).
 *
 * These pin the pure presentation logic behind the "Converted → {project}" state the Catalog card,
 * table and detail render: the project href, the friendly label (name → slug → short id), the
 * live-vs-deleted link decision, and the convert-vs-re-convert action label.
 */
import {
  convertActionLabel,
  convertedProjectHref,
  convertedProjectLabel,
  isConvertedLinkLive,
  type CatalogConversion,
} from '../src/app/utils/catalog-conversion';

function makeConversion(overrides: Partial<CatalogConversion> = {}): CatalogConversion {
  return {
    projectId: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    projectName: 'Acme OpenAPI',
    projectSlug: 'acme-openapi',
    projectDeleted: false,
    versionId: '1.0.0',
    versionRecordId: 'ver-1',
    reconverted: false,
    convertedAt: '2026-03-01T00:00:00.000Z',
    fidelityGrade: 'B',
    fidelityTier: 'medium',
    ...overrides,
  };
}

describe('convertedProjectHref', () => {
  it('links to the converted project’s versions screen with an encoded id', () => {
    const href = convertedProjectHref(makeConversion({ projectId: 'a b/c' }));
    expect(href).toBe('/ade/dashboard/versions?projectId=a%20b%2Fc');
  });
});

describe('convertedProjectLabel', () => {
  it('prefers the project name', () => {
    expect(convertedProjectLabel(makeConversion())).toBe('Acme OpenAPI');
  });

  it('falls back to the slug when the name is missing', () => {
    expect(convertedProjectLabel(makeConversion({ projectName: null }))).toBe('acme-openapi');
  });

  it('falls back to a shortened id when name and slug are missing', () => {
    const label = convertedProjectLabel(
      makeConversion({ projectName: null, projectSlug: null, projectId: 'abcdef0123456789' }),
    );
    expect(label).toBe('project abcdef01');
  });

  it('ignores whitespace-only name/slug', () => {
    expect(convertedProjectLabel(makeConversion({ projectName: '   ', projectSlug: 'acme-openapi' }))).toBe(
      'acme-openapi',
    );
  });
});

describe('isConvertedLinkLive', () => {
  it('is true for a converted, non-deleted target', () => {
    expect(isConvertedLinkLive(makeConversion())).toBe(true);
  });

  it('is false when the target project was deleted', () => {
    expect(isConvertedLinkLive(makeConversion({ projectDeleted: true }))).toBe(false);
  });

  it('is false for a null/undefined conversion', () => {
    expect(isConvertedLinkLive(null)).toBe(false);
    expect(isConvertedLinkLive(undefined)).toBe(false);
  });
});

describe('convertActionLabel', () => {
  it('reads "Convert to OpenAPI" for an unconverted item', () => {
    expect(convertActionLabel(null)).toBe('Convert to OpenAPI');
    expect(convertActionLabel(undefined)).toBe('Convert to OpenAPI');
  });

  it('reads "Re-convert to OpenAPI" once the item has been converted', () => {
    expect(convertActionLabel(makeConversion())).toBe('Re-convert to OpenAPI');
  });
});
