import { describe, it, expect } from '@jest/globals';
import {
  isDesignerStudioNavActive,
  isPathsStudioNavActive,
} from '../../lib/ade-studio-nav';

describe('ade-studio-nav active states', () => {
  it('Designer: root studio and editor, not Paths', () => {
    expect(isDesignerStudioNavActive('/ade/studio')).toBe(true);
    expect(isDesignerStudioNavActive('/ade/studio/editor')).toBe(true);
    expect(isDesignerStudioNavActive('/ade/studio/code')).toBe(true);
    expect(isDesignerStudioNavActive('/ade/studio/paths')).toBe(false);
    expect(isDesignerStudioNavActive('/ade/studio/paths/foo')).toBe(false);
  });

  it('Paths: paths route only', () => {
    expect(isPathsStudioNavActive('/ade/studio/paths')).toBe(true);
    expect(isPathsStudioNavActive('/ade/studio/paths/')).toBe(true);
    expect(isPathsStudioNavActive('/ade/studio/editor')).toBe(false);
    expect(isPathsStudioNavActive('/ade/studio')).toBe(false);
  });
});
