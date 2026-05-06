import {
  buildClassDraftRefinementUserMessage,
  CLASS_DRAFT_REFINE_HEADING,
  detectChatQuickActions,
  extractFirstJsonOrYamlFenceBody,
  extractSuggestedRelationshipBulletsFromAssistantMarkdown,
  inferJsonSchemaRelationships,
  parseClassDefinitionFromAssistantMarkdown,
  summarizeJsonSchemaProperties,
  userMessageIsClassDraftRefinement,
} from '../../src/app/ade/studio/components/chatbot/assistant-action-detection';

describe('extractFirstJsonOrYamlFenceBody', () => {
  it('prefers JSON over YAML even when YAML appears first', () => {
    const md = [
      'Intro',
      '```yaml',
      'a: 1',
      '```',
      '```json',
      '{"x":1}',
      '```',
    ].join('\n');
    expect(extractFirstJsonOrYamlFenceBody(md)).toBe('{"x":1}');
  });

  it('falls back to yaml when no json fence exists', () => {
    const md = '```yaml\nhello: world\n```';
    expect(extractFirstJsonOrYamlFenceBody(md)).toBe('hello: world');
  });

  it('returns null when there are no json or yaml fences', () => {
    expect(extractFirstJsonOrYamlFenceBody('```ts\nconst x = 1\n```')).toBeNull();
  });
});

describe('detectChatQuickActions', () => {
  it('detects bold-wrapped phrases case-insensitively', () => {
    const md = 'Please review.\n\n**Create this class**\n\n**Add these properties**';
    const kinds = detectChatQuickActions(md).map((a) => a.kind);
    expect(kinds).toContain('create_class');
    expect(kinds).toContain('batch_add_properties');
  });

  it('includes copy when phrase and a json fence are present', () => {
    const md = [
      '**Copy to clipboard**',
      '',
      '```json',
      '{"ok":true}',
      '```',
    ].join('\n');
    const actions = detectChatQuickActions(md);
    const copy = actions.find((a) => a.kind === 'copy_generated_payload');
    expect(copy && copy.kind === 'copy_generated_payload' ? copy.payload : '').toBe('{"ok":true}');
  });

  it('omits copy when the phrase is missing even if json exists', () => {
    const md = '```json\n{}\n```';
    expect(detectChatQuickActions(md).some((a) => a.kind === 'copy_generated_payload')).toBe(false);
  });

  it('dedupes by action kind', () => {
    const md = 'Create this class\n\ncreate this class';
    const kinds = detectChatQuickActions(md).map((a) => a.kind);
    expect(kinds.filter((k) => k === 'create_class').length).toBe(1);
  });

  it('detects open ai property suggestions CTA (#275)', () => {
    const md = 'Here are ideas.\n\n**Open AI property suggestions**';
    expect(detectChatQuickActions(md).some((a) => a.kind === 'open_property_suggestions')).toBe(true);
  });
});

describe('parseClassDefinitionFromAssistantMarkdown', () => {
  it('parses name, description, and schema from the first json fence', () => {
    const md = [
      'Here you go.',
      '',
      '```json',
      JSON.stringify({
        name: 'User',
        description: 'A user',
        schema: { type: 'object', properties: { email: { type: 'string' } } },
      }),
      '```',
    ].join('\n');
    const parsed = parseClassDefinitionFromAssistantMarkdown(md);
    expect(parsed?.name).toBe('User');
    expect(parsed?.description).toBe('A user');
    expect(parsed?.schema).toEqual({ type: 'object', properties: { email: { type: 'string' } } });
  });

  it('returns null when the json block is missing name or schema', () => {
    expect(parseClassDefinitionFromAssistantMarkdown('```json\n{}\n```')).toBeNull();
    expect(parseClassDefinitionFromAssistantMarkdown('no fence')).toBeNull();
  });

  it('parses a jsonc fence (not only json)', () => {
    const md = [
      '```jsonc',
      JSON.stringify({
        name: 'Product',
        description: 'A product',
        schema: { type: 'object' },
      }),
      '```',
    ].join('\n');
    const parsed = parseClassDefinitionFromAssistantMarkdown(md);
    expect(parsed?.name).toBe('Product');
    expect(parsed?.description).toBe('A product');
  });

  it('parses a fence whose closing ``` has no preceding newline', () => {
    // Inline close: the body and ``` run together without a trailing \n
    const payload = JSON.stringify({ name: 'Order', schema: { type: 'object' } });
    const md = '```json\n' + payload + '```';
    const parsed = parseClassDefinitionFromAssistantMarkdown(md);
    expect(parsed?.name).toBe('Order');
  });
});

describe('extractSuggestedRelationshipBulletsFromAssistantMarkdown', () => {
  it('returns bullets under **Suggested relationships** before the json fence', () => {
    const md = [
      '**Suggested relationships**',
      '- lineItems — one-to-many LineItem',
      '* customer — many-to-one Customer',
      '',
      '```json',
      '{"name":"Order","schema":{"type":"object","properties":{}}}',
      '```',
    ].join('\n');
    expect(extractSuggestedRelationshipBulletsFromAssistantMarkdown(md)).toEqual([
      'lineItems — one-to-many LineItem',
      'customer — many-to-one Customer',
    ]);
  });

  it('returns empty when the heading is missing', () => {
    expect(extractSuggestedRelationshipBulletsFromAssistantMarkdown('**Suggested properties**\n- a — string\n')).toEqual(
      [],
    );
  });

  it('does not treat json fence content as bullets', () => {
    const md = [
      '**Suggested relationships**',
      '',
      '```json',
      '{"x":1}',
      '```',
    ].join('\n');
    expect(extractSuggestedRelationshipBulletsFromAssistantMarkdown(md)).toEqual([]);
  });
});

describe('inferJsonSchemaRelationships', () => {
  it('returns empty when there are no refs', () => {
    expect(inferJsonSchemaRelationships({ type: 'object', properties: { name: { type: 'string' } } })).toEqual([]);
  });

  it('detects property $ref and array items $ref', () => {
    const schema = {
      type: 'object',
      properties: {
        owner: { $ref: '#/components/schemas/User' },
        tags: { type: 'array', items: { type: 'string' } },
        items: { type: 'array', items: { $ref: '#/components/schemas/LineItem' } },
      },
    };
    expect(inferJsonSchemaRelationships(schema)).toEqual([
      { property: 'owner', detail: 'references User' },
      { property: 'items', detail: 'collection of LineItem' },
    ]);
  });

  it('does not throw when items is null (malformed/partial schema)', () => {
    const schema = {
      type: 'object',
      properties: {
        tags: { type: 'array', items: null },
        owner: { $ref: '#/components/schemas/User' },
      },
    };
    expect(() => inferJsonSchemaRelationships(schema)).not.toThrow();
    expect(inferJsonSchemaRelationships(schema)).toEqual([{ property: 'owner', detail: 'references User' }]);
  });
});

describe('summarizeJsonSchemaProperties', () => {
  it('returns empty when properties are missing', () => {
    expect(summarizeJsonSchemaProperties(null)).toEqual([]);
    expect(summarizeJsonSchemaProperties({ type: 'object' })).toEqual([]);
  });

  it('labels primitives, refs, arrays, and compositions', () => {
    const schema = {
      type: 'object',
      properties: {
        email: { type: 'string', format: 'email' },
        userId: { $ref: '#/components/schemas/User' },
        tags: { type: 'array', items: { type: 'string' } },
        role: { oneOf: [{ type: 'string' }, { type: 'null' }] },
      },
    };
    const rows = summarizeJsonSchemaProperties(schema);
    expect(rows).toEqual([
      { name: 'email', suggestedType: 'string' },
      { name: 'userId', suggestedType: 'ref (User)' },
      { name: 'tags', suggestedType: 'array<string>' },
      { name: 'role', suggestedType: 'oneOf(2)' },
    ]);
  });

  it('handles union type keyword arrays', () => {
    const schema = {
      properties: {
        id: { type: ['string', 'number'] },
      },
    };
    expect(summarizeJsonSchemaProperties(schema)).toEqual([{ name: 'id', suggestedType: 'string | number' }]);
  });

  it('preserves nested array type rather than collapsing to plain array', () => {
    const schema = {
      properties: {
        matrix: { type: 'array', items: { type: 'array', items: { type: 'number' } } },
        tags: { type: 'array', items: { type: 'array' } },
      },
    };
    const rows = summarizeJsonSchemaProperties(schema);
    expect(rows).toEqual([
      { name: 'matrix', suggestedType: 'array<array<number>>' },
      { name: 'tags', suggestedType: 'array<array>' },
    ]);
  });
});

describe('class draft refinement (#532)', () => {
  it('buildClassDraftRefinementUserMessage embeds draft json and instructions', () => {
    const parsed = parseClassDefinitionFromAssistantMarkdown(
      [
        '```json',
        JSON.stringify({
          name: 'User',
          description: 'A user',
          schema: { type: 'object', properties: { email: { type: 'string' } } },
        }),
        '```',
      ].join('\n'),
    );
    expect(parsed).not.toBeNull();
    const msg = buildClassDraftRefinementUserMessage(parsed!, 'Make email required');
    expect(msg).toContain(CLASS_DRAFT_REFINE_HEADING);
    expect(msg).toContain('Make email required');
    expect(msg).toContain('Current definition:');
    expect(msg).toContain('"email"');
  });

  it('userMessageIsClassDraftRefinement detects structured refinement turns', () => {
    const parsed = parseClassDefinitionFromAssistantMarkdown(
      ['```json', JSON.stringify({ name: 'X', schema: { type: 'object', properties: {} } }), '```'].join('\n'),
    );
    expect(parsed).not.toBeNull();
    const msg = buildClassDraftRefinementUserMessage(parsed!, ' tweak ');
    expect(userMessageIsClassDraftRefinement('plain text')).toBe(false);
    expect(userMessageIsClassDraftRefinement(msg)).toBe(true);
  });
});
