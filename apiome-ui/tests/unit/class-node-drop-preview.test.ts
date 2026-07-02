import { getDropPreviewPropertyType } from '@/app/components/ade/studio/ClassNode';

describe('ClassNode ghost drop preview type', () => {
  it('renders array reference type labels', () => {
    expect(
      getDropPreviewPropertyType({
        data: {
          type: 'array',
          items: { $ref: '#/components/schemas/Address' },
        },
      })
    ).toBe('Address[]');
  });

  it('renders direct ref labels', () => {
    expect(
      getDropPreviewPropertyType({
        data: { $ref: '#/components/schemas/User' },
      })
    ).toBe('User');
  });

  it('renders array reference labels from top-level payload shape', () => {
    expect(
      getDropPreviewPropertyType({
        type: 'array',
        items: { $ref: '#/components/schemas/OrderLine' },
      } as any)
    ).toBe('OrderLine[]');
  });

  it('renders direct ref labels from top-level payload shape', () => {
    expect(
      getDropPreviewPropertyType({
        $ref: '#/components/schemas/Account',
      } as any)
    ).toBe('Account');
  });

  it('falls back to primitive/base type', () => {
    expect(
      getDropPreviewPropertyType({
        data: { type: ['string', 'null'] },
      })
    ).toBe('string');
  });

  it('normalizes nullable array item type labels', () => {
    expect(
      getDropPreviewPropertyType({
        data: {
          type: 'array',
          items: { type: ['string', 'null'] },
        },
      })
    ).toBe('string[]');
  });

  it('handles malformed string data payloads without throwing', () => {
    expect(
      getDropPreviewPropertyType({
        type: 'number',
        data: '{"type":"array","items":',
      })
    ).toBe('number');
  });
});
