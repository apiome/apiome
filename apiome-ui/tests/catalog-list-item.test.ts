import { normalizeCatalogListItem } from '@/app/utils/catalog-list-item';

describe('normalizeCatalogListItem', () => {
  it('maps snake_case provenance fields to camelCase', () => {
    const item = normalizeCatalogListItem({
      id: 'cat-1',
      name: 'Orders',
      slug: 'orders',
      enabled: true,
      deleted_at: null,
      source_format: 'protobuf',
      format_metadata: { inputKind: 'file' },
      quality_score: 80,
      quality_grade: 'B',
      versions_count: 2,
    });

    expect(item.sourceFormat).toBe('protobuf');
    expect(item.formatMetadata).toEqual({ inputKind: 'file' });
    expect(item.qualityScore).toBe(80);
    expect(item.qualityGrade).toBe('B');
    expect(item.versionsCount).toBe(2);
  });
});
