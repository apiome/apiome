/**
 * Unit tests for the Project-vs-Catalog publishability predicate (MFI-23.8, #4017).
 *
 * This predicate gates every Publish affordance on the shared versions screen: a catalog item
 * (`publishable = false`, MFI-23.1) is never a publish candidate, while ordinary projects — and any
 * payload that omits the flag — remain publishable. REST enforces the same rule server-side.
 */
import { isProjectPublishable } from '../src/app/utils/catalog-publishable';

describe('isProjectPublishable', () => {
  it('treats an explicit publishable=true project as publishable', () => {
    expect(isProjectPublishable({ publishable: true })).toBe(true);
  });

  it('withholds publish for a catalog item (publishable=false)', () => {
    expect(isProjectPublishable({ publishable: false })).toBe(false);
  });

  it('treats a project with no publishable flag as publishable (back-compat)', () => {
    expect(isProjectPublishable({})).toBe(true);
  });

  it('treats a null publishable flag as publishable', () => {
    expect(isProjectPublishable({ publishable: null })).toBe(true);
  });

  it('treats an unresolved project (undefined/null) as publishable', () => {
    expect(isProjectPublishable(undefined)).toBe(true);
    expect(isProjectPublishable(null)).toBe(true);
  });

  it('only an explicit false withholds publish — not other falsy-looking inputs', () => {
    // The guard is strict `=== false`, so a present-but-true flag never blocks.
    expect(isProjectPublishable({ publishable: true })).toBe(true);
  });
});
