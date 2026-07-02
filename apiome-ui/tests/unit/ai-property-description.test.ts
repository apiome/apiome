import {
  normalizeGeneratedPropertyDescription,
  summarizeStoredPropertyData,
  draftPropertySchemaFromDialogForm,
  buildClassDescriptionAiPayload,
  parseGeneratedOperationDocs,
  parseGeneratedPropertyExample,
} from '../../lib/ai-property-description';
import type { PropertyFormData } from '../../src/app/components/ade/studio/PropertyFormFields';

describe('ai-property-description (#619)', () => {
  it('normalizeGeneratedPropertyDescription strips fences and markdown noise', () => {
    expect(normalizeGeneratedPropertyDescription('')).toBe('');
    expect(normalizeGeneratedPropertyDescription('  hello world  ')).toBe('hello world');
    expect(
      normalizeGeneratedPropertyDescription('```\nThe customer email.\n```'),
    ).toBe('The customer email.');
    expect(normalizeGeneratedPropertyDescription('First para.\n\nSecond ignored.')).toBe('First para.');
  });

  it('summarizeStoredPropertyData keeps schema semantics', () => {
    expect(summarizeStoredPropertyData(null)).toEqual({});
    const s = summarizeStoredPropertyData({
      type: 'string',
      format: 'email',
      description: 'x'.repeat(5000),
      extra: { nested: true },
    });
    expect(s.type).toBe('string');
    expect(s.format).toBe('email');
    expect(s.description).toHaveLength(320);
  });

  it('draftPropertySchemaFromDialogForm reflects array and nullable', () => {
    const formData: PropertyFormData = {
      nullable: true,
      format: 'uuid',
      minItems: '1',
      maxItems: '10',
    };
    const doc = draftPropertySchemaFromDialogForm({
      propertyType: 'string',
      propertyIsArray: true,
      formData,
      seedProperty: null,
    });
    expect(doc.type).toEqual(['array', 'null']);
    expect(doc.items).toEqual({ type: 'string', format: 'uuid' });
    expect(doc.minItems).toBe(1);
    expect(doc.maxItems).toBe(10);
  });

  it('draftPropertySchemaFromDialogForm handles $ref', () => {
    const formData: PropertyFormData = {};
    expect(
      draftPropertySchemaFromDialogForm({
        propertyType: '$ref',
        propertyIsArray: false,
        formData,
        seedProperty: { $ref: '#/components/schemas/Order' },
      }).$ref,
    ).toBe('#/components/schemas/Order');
    const arr = draftPropertySchemaFromDialogForm({
      propertyType: '$ref',
      propertyIsArray: true,
      formData,
      seedProperty: { items: { $ref: '#/components/schemas/LineItem' } },
    });
    expect(arr.type).toBe('array');
    expect((arr.items as { $ref?: string }).$ref).toBe('#/components/schemas/LineItem');
  });

  it('buildClassDescriptionAiPayload summarizes members and composition (#620)', () => {
    const payload = buildClassDescriptionAiPayload({
      members: [
        {
          name: 'email',
          description: 'Primary contact',
          data: JSON.stringify({ type: 'string', format: 'email' }),
        },
      ],
      composition: { allOf: ['Auditable'] },
    });
    expect(payload.composition).toEqual({ allOf: ['Auditable'] });
    const email = payload.properties as Record<string, { memberDescription?: string; schema: Record<string, unknown> }>;
    expect(email.email.memberDescription).toBe('Primary contact');
    expect(email.email.schema.format).toBe('email');
  });

  it('parseGeneratedOperationDocs reads fenced JSON (#621)', () => {
    expect(parseGeneratedOperationDocs('')).toBeNull();
    expect(
      parseGeneratedOperationDocs(
        '```json\n{"summary":"List users","description":"Returns **users**."}\n```',
      ),
    ).toEqual({ summary: 'List users', description: 'Returns **users**.' });
    expect(parseGeneratedOperationDocs('{"summary":"x","description":"y"}')).toEqual({
      summary: 'x',
      description: 'y',
    });
    expect(parseGeneratedOperationDocs('not json')).toBeNull();
  });

  it('parseGeneratedOperationDocs requires both summary and description to be non-empty (#621)', () => {
    // missing summary key
    expect(parseGeneratedOperationDocs('{"description":"Some description."}')).toBeNull();
    // missing description key
    expect(parseGeneratedOperationDocs('{"summary":"Some summary."}')).toBeNull();
    // empty summary string
    expect(parseGeneratedOperationDocs('{"summary":"","description":"Some description."}')).toBeNull();
    // empty description string (whitespace only)
    expect(parseGeneratedOperationDocs('{"summary":"Some summary.","description":"   "}')).toBeNull();
    // both non-empty — must succeed
    expect(
      parseGeneratedOperationDocs('{"summary":"Get user","description":"Returns a user by ID."}'),
    ).toEqual({ summary: 'Get user', description: 'Returns a user by ID.' });
  });

  it('parseGeneratedOperationDocs tolerates preamble/trailing text and uppercase JSON fence tag (#621)', () => {
    // preamble before the fence
    expect(
      parseGeneratedOperationDocs(
        'Here is the result:\n```json\n{"summary":"Create order","description":"Creates a new order."}\n```',
      ),
    ).toEqual({ summary: 'Create order', description: 'Creates a new order.' });
    // trailing text after the fence
    expect(
      parseGeneratedOperationDocs(
        '```json\n{"summary":"Delete item","description":"Removes the item."}\n```\nLet me know if you need changes.',
      ),
    ).toEqual({ summary: 'Delete item', description: 'Removes the item.' });
    // uppercase JSON fence tag
    expect(
      parseGeneratedOperationDocs(
        '```JSON\n{"summary":"Update record","description":"Updates the record."}\n```',
      ),
    ).toEqual({ summary: 'Update record', description: 'Updates the record.' });
  });

  it('parseGeneratedPropertyExample reads fenced JSON (#622)', () => {
    expect(parseGeneratedPropertyExample('')).toBeNull();
    expect(
      parseGeneratedPropertyExample('```json\n{"example":"user@example.com"}\n```'),
    ).toEqual({ value: 'user@example.com' });
    expect(parseGeneratedPropertyExample('{"example":42}')).toEqual({ value: 42 });
    expect(parseGeneratedPropertyExample('{"example":null}')).toEqual({ value: null });
    expect(parseGeneratedPropertyExample('not json')).toBeNull();
    expect(parseGeneratedPropertyExample('{"wrong":1}')).toBeNull();
  });
});
