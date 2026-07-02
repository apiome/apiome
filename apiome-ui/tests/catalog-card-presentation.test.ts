/**
 * Unit tests for the catalog presentation helper `catalogItemGrade` (MFI-24.4, #4084).
 *
 * The Grade column derives its letter from the item's captured `qualityGrade` when present, else
 * from the numeric `qualityScore` via the shared score→letter bands, else `null`. This keeps the
 * Grade column consistent with the `grade` sort (which orders on `qualityGrade`).
 */
import { catalogItemGrade } from '../src/app/utils/catalog-card-presentation';

describe('catalogItemGrade', () => {
  it('prefers the captured qualityGrade verbatim (trimmed) when present', () => {
    expect(catalogItemGrade({ qualityGrade: 'A', qualityScore: 12 })).toBe('A');
    expect(catalogItemGrade({ qualityGrade: '  B  ', qualityScore: null })).toBe('B');
  });

  it('derives the letter from qualityScore when no grade is captured', () => {
    expect(catalogItemGrade({ qualityScore: 95 })).toBe('A');
    expect(catalogItemGrade({ qualityScore: 72 })).toBe('B');
    expect(catalogItemGrade({ qualityScore: 55 })).toBe('C');
    expect(catalogItemGrade({ qualityScore: 42 })).toBe('D');
    expect(catalogItemGrade({ qualityScore: 10 })).toBe('F');
  });

  it('returns null when neither a grade nor a numeric score is known', () => {
    expect(catalogItemGrade({})).toBeNull();
    expect(catalogItemGrade({ qualityGrade: '   ', qualityScore: null })).toBeNull();
    expect(catalogItemGrade({ qualityScore: NaN })).toBeNull();
  });
});
