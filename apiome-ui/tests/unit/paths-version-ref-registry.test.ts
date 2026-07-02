import { describe, it, expect } from '@jest/globals';
import { createPathsVersionRefRegistry } from '../../lib/utils/paths-version-ref-registry';

describe('paths-version-ref-registry', () => {
  it('builds refs from class ids without embedding schema JSON', () => {
    const reg = createPathsVersionRefRegistry([{ id: 'a1', name: 'Pet' }]);
    expect(reg.refForClassId('a1')).toBe('#/components/schemas/Pet');
    expect(reg.refForClassId('missing')).toBeNull();
  });

  it('detects orphan class ids', () => {
    const reg = createPathsVersionRefRegistry([{ id: 'x', name: 'X' }]);
    expect(reg.isOrphanClassId('x')).toBe(false);
    expect(reg.isOrphanClassId('y')).toBe(true);
    expect(reg.isOrphanClassId(null)).toBe(false);
  });

  it('finds broken component schema refs in nested JSON', () => {
    const reg = createPathsVersionRefRegistry([{ id: '1', name: 'User' }]);
    const body = {
      a: { $ref: '#/components/schemas/User' },
      b: { $ref: '#/components/schemas/Gone' },
    };
    const broken = reg.findBrokenComponentSchemaRefs(body);
    expect(broken.some((x) => x.ref === '#/components/schemas/Gone')).toBe(true);
    expect(broken.some((x) => x.ref === '#/components/schemas/User')).toBe(false);
  });
});
