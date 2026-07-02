/**
 * Tests for the Studio chat context module (#259).
 *
 * Pins the contract that downstream callers (ChatConversation, demo
 * responder, eventual Ollama transport) rely on:
 *   - Empty / null snapshots short-circuit cleanly
 *   - Project / version / classes / properties / selection all surface
 *   - Caps are honoured so big workspaces don't blow the prompt budget
 *   - `injectChatContext` is a no-op when the context is empty
 */

import {
  buildChatContextPreamble,
  CHAT_CONTEXT_CLASS_CAP,
  CHAT_CONTEXT_DESCRIPTION_CHAR_CAP,
  CHAT_CONTEXT_PROPERTY_CAP,
  CHAT_CONTEXT_SCHEMA_CHAR_CAP,
  CHAT_CONTEXT_SELECTION_CAP,
  EMPTY_CHAT_STUDIO_CONTEXT,
  getSelectedClasses,
  injectChatContext,
  isChatStudioContextEmpty,
  summarizeChatStudioContext,
  type ChatStudioContext,
  type ChatStudioProperty,
} from '../../src/app/ade/studio/components/chatbot/chat-context';

function makeContext(overrides: Partial<ChatStudioContext> = {}): ChatStudioContext {
  return {
    project: { id: 'proj-1', name: 'Acme Catalog' },
    version: { id: 'ver-1', label: 'v1.4.0' },
    classes: [
      { id: 'cls-user', name: 'User', description: 'Authenticated principal', schema: { type: 'object' } },
      { id: 'cls-product', name: 'Product', description: 'Catalog item', schema: { type: 'object' } },
    ],
    properties: [
      { id: 'prop-email', name: 'email', type: 'string', format: 'email', required: true, description: 'Login email' },
      { id: 'prop-id', name: 'id', type: 'string', format: 'uuid' },
    ],
    selectedClassIds: ['cls-user'],
    ...overrides,
  };
}

describe('isChatStudioContextEmpty', () => {
  it('treats null / undefined / empty snapshots as empty', () => {
    expect(isChatStudioContextEmpty(null)).toBe(true);
    expect(isChatStudioContextEmpty(undefined)).toBe(true);
    expect(isChatStudioContextEmpty(EMPTY_CHAT_STUDIO_CONTEXT)).toBe(true);
  });

  it('returns false when any field has data', () => {
    expect(isChatStudioContextEmpty({ ...EMPTY_CHAT_STUDIO_CONTEXT, project: { id: 'p', name: 'P' } })).toBe(false);
    expect(isChatStudioContextEmpty({ ...EMPTY_CHAT_STUDIO_CONTEXT, version: { id: 'v', label: null } })).toBe(false);
    expect(isChatStudioContextEmpty({
      ...EMPTY_CHAT_STUDIO_CONTEXT,
      classes: [{ id: 'c', name: 'X' }],
    })).toBe(false);
    expect(isChatStudioContextEmpty({
      ...EMPTY_CHAT_STUDIO_CONTEXT,
      properties: [{ id: 'p', name: 'q' }],
    })).toBe(false);
    expect(isChatStudioContextEmpty({ ...EMPTY_CHAT_STUDIO_CONTEXT, selectedClassIds: ['x'] })).toBe(false);
  });
});

describe('getSelectedClasses', () => {
  it('returns the matching class objects in selection order', () => {
    const ctx = makeContext({ selectedClassIds: ['cls-product', 'cls-user'] });
    const selected = getSelectedClasses(ctx);
    expect(selected.map((c) => c.id)).toEqual(['cls-product', 'cls-user']);
  });

  it('drops selection IDs that no longer resolve to a class', () => {
    const ctx = makeContext({ selectedClassIds: ['cls-user', 'ghost'] });
    const selected = getSelectedClasses(ctx);
    expect(selected).toHaveLength(1);
    expect(selected[0].id).toBe('cls-user');
  });

  it('returns an empty array when nothing is selected', () => {
    expect(getSelectedClasses(makeContext({ selectedClassIds: [] }))).toEqual([]);
  });
});

describe('summarizeChatStudioContext', () => {
  it('returns an empty string for empty context', () => {
    expect(summarizeChatStudioContext(EMPTY_CHAT_STUDIO_CONTEXT)).toBe('');
  });

  it('mentions project, version, classes, properties, and selection', () => {
    const summary = summarizeChatStudioContext(makeContext());
    expect(summary).toMatch(/Project:.*Acme Catalog/);
    expect(summary).toMatch(/Version:.*v1\.4\.0/);
    expect(summary).toMatch(/Selected on canvas:.*User/);
    expect(summary).toMatch(/Classes \(2\):.*User.*Product/);
    expect(summary).toMatch(/Properties \(2\):.*email.*id/);
  });

  it('includes project domain in the summary when domainCategory is set (#615)', () => {
    const summary = summarizeChatStudioContext(
      makeContext({
        project: { id: 'proj-1', name: 'Acme Catalog', domainCategory: 'ecommerce' },
      }),
    );
    expect(summary).toMatch(/Project domain/);
    expect(summary).toMatch(/E-commerce/);
  });

  it('caps the visible class names with an overflow marker', () => {
    const classes = Array.from({ length: CHAT_CONTEXT_CLASS_CAP + 5 }, (_, i) => ({
      id: `c${i}`,
      name: `C${i}`,
    }));
    const summary = summarizeChatStudioContext(makeContext({ classes, selectedClassIds: [] }));
    expect(summary).toMatch(`Classes (${classes.length})`);
    expect(summary).toMatch('+5 more');
  });
});

describe('buildChatContextPreamble', () => {
  it('returns an empty string when there is no context to share', () => {
    expect(buildChatContextPreamble(EMPTY_CHAT_STUDIO_CONTEXT)).toBe('');
  });

  it('adds domain-aware best practices to the preamble when tips apply (#615)', () => {
    const preamble = buildChatContextPreamble(
      makeContext({
        project: { id: 'proj-1', name: 'Acme Catalog', domainCategory: 'saas' },
      }),
    );
    expect(preamble).toMatch(/Domain-aware best practices/);
    expect(preamble).toMatch(/tenant isolation/i);
  });

  it('includes a schema preview for selected classes only', () => {
    const ctx = makeContext({
      classes: [
        { id: 'cls-user', name: 'User', schema: { type: 'object', properties: { email: { type: 'string' } } } },
        { id: 'cls-product', name: 'Product', schema: { type: 'object' } },
      ],
      selectedClassIds: ['cls-user'],
    });
    const preamble = buildChatContextPreamble(ctx);
    expect(preamble).toMatch(/Selected on canvas/);
    expect(preamble).toMatch(/`User`/);
    // Schema preview only attached to the *selected* class to keep payload tight.
    expect(preamble).toMatch(/schema:.*"email".*"string"/);
    expect(preamble.split('schema:').length - 1).toBe(1);
  });

  it('truncates long schemas to the schema cap', () => {
    const longSchema = { type: 'object', description: 'x'.repeat(CHAT_CONTEXT_SCHEMA_CHAR_CAP * 2) };
    const ctx = makeContext({
      classes: [{ id: 'cls-x', name: 'X', schema: longSchema }],
      selectedClassIds: ['cls-x'],
    });
    const preamble = buildChatContextPreamble(ctx);
    const schemaLine = preamble.split('\n').find((line) => line.includes('schema:'));
    expect(schemaLine).toBeDefined();
    expect(schemaLine!.length).toBeLessThanOrEqual(CHAT_CONTEXT_SCHEMA_CHAR_CAP + 'schema:  '.length + 4);
    expect(schemaLine).toMatch(/…$/);
  });

  it('truncates long descriptions on properties and classes', () => {
    const longDesc = 'word '.repeat(CHAT_CONTEXT_DESCRIPTION_CHAR_CAP);
    const prop: ChatStudioProperty = {
      id: 'p',
      name: 'bio',
      type: 'string',
      description: longDesc,
    };
    const preamble = buildChatContextPreamble(makeContext({ properties: [prop], selectedClassIds: [] }));
    const propLine = preamble.split('\n').find((line) => line.startsWith('- `bio`'));
    expect(propLine).toBeDefined();
    expect(propLine!.length).toBeLessThan(longDesc.length);
    expect(propLine).toMatch(/…/);
  });

  it('caps the class and property lists with overflow markers', () => {
    const classes = Array.from({ length: CHAT_CONTEXT_CLASS_CAP + 3 }, (_, i) => ({ id: `c${i}`, name: `C${i}` }));
    const properties = Array.from({ length: CHAT_CONTEXT_PROPERTY_CAP + 2 }, (_, i) => ({ id: `p${i}`, name: `p${i}` }));
    const preamble = buildChatContextPreamble({
      ...EMPTY_CHAT_STUDIO_CONTEXT,
      project: { id: 'p', name: 'P' },
      classes,
      properties,
    });
    expect(preamble).toMatch(`and ${classes.length - CHAT_CONTEXT_CLASS_CAP} more classes not shown`);
    expect(preamble).toMatch(`and ${properties.length - CHAT_CONTEXT_PROPERTY_CAP} more properties not shown`);
  });

  it('caps the selected class list with an overflow line', () => {
    const classes = Array.from({ length: CHAT_CONTEXT_SELECTION_CAP + 4 }, (_, i) => ({
      id: `c${i}`,
      name: `C${i}`,
    }));
    const selectedClassIds = classes.map((c) => c.id);
    const preamble = buildChatContextPreamble({
      ...EMPTY_CHAT_STUDIO_CONTEXT,
      classes,
      selectedClassIds,
    });
    expect(preamble).toMatch(`and ${selectedClassIds.length - CHAT_CONTEXT_SELECTION_CAP} more selected`);
  });
});

describe('injectChatContext', () => {
  it('returns the prompt unchanged when context is empty', () => {
    expect(injectChatContext('hello', null)).toBe('hello');
    expect(injectChatContext('hello', undefined)).toBe('hello');
    expect(injectChatContext('hello', EMPTY_CHAT_STUDIO_CONTEXT)).toBe('hello');
  });

  it('prepends the preamble and a divider before the user prompt', () => {
    const out = injectChatContext('Sketch a Cart class', makeContext());
    expect(out.startsWith('### Current Studio context')).toBe(true);
    expect(out).toMatch(/### User request\nSketch a Cart class$/);
  });
});
