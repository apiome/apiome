/**
 * Tests for the multi-turn conversation history helpers (#260).
 *
 * Pins the intent classifier, refinement-op extraction, prompt-injection
 * preamble, and the spec mutation pipeline so regressions show up loudly
 * before they reach the chat surface.
 */

import {
  applyRefinementsToSpec,
  buildConversationHistoryPreamble,
  CHAT_HISTORY_EXCERPT_CHAR_CAP,
  CHAT_HISTORY_TURN_CAP,
  summarizeConversationHistory,
  type ChatRefinementOp,
} from '../../src/app/ade/studio/components/chatbot/conversation-history';
import type { ChatMessage } from '../../src/app/ade/studio/components/chatbot/types';

function user(content: string, id = `u-${content.slice(0, 8)}`): ChatMessage {
  return { id, role: 'user', content };
}

function assistant(content: string, id = `a-${content.slice(0, 8)}`): ChatMessage {
  return { id, role: 'assistant', content };
}

const SAMPLE_SPEC_REPLY = [
  'Here is the spec:',
  '',
  '```json',
  JSON.stringify({
    openapi: '3.1.0',
    info: { title: 'Catalog', version: '0.1.0' },
    components: {
      schemas: {
        Product: {
          type: 'object',
          properties: {
            id: { type: 'string', format: 'uuid' },
            name: { type: 'string' },
            priceCents: { type: 'integer' },
          },
          required: ['id'],
        },
      },
    },
  }),
  '```',
].join('\n');

describe('summarizeConversationHistory', () => {
  it('classifies the first turn when there is no prior assistant reply', () => {
    const summary = summarizeConversationHistory([user('Sketch a User class')], 'Sketch a User class');
    expect(summary.intent).toBe('first-turn');
    expect(summary.userTurnCount).toBe(1);
    expect(summary.assistantTurnCount).toBe(0);
    expect(summary.lastAssistantSpec).toBeNull();
    expect(summary.refinementOps).toEqual([]);
  });

  it('treats unrelated follow-ups as standalone when no other pattern matches', () => {
    const messages: ChatMessage[] = [user('hi'), assistant('hello there'), user('sketch a wholly new schema')];
    const summary = summarizeConversationHistory(messages, 'sketch a wholly new schema');
    expect(summary.intent).toBe('standalone');
    expect(summary.userTurnCount).toBe(2);
    expect(summary.assistantTurnCount).toBe(1);
  });

  it('skips pending and empty assistant messages when counting prior replies', () => {
    const messages: ChatMessage[] = [
      user('first'),
      { id: 'pending', role: 'assistant', content: '', pending: true },
      user('follow up'),
    ];
    const summary = summarizeConversationHistory(messages, 'follow up');
    expect(summary.assistantTurnCount).toBe(0);
    expect(summary.intent).toBe('first-turn');
  });

  it('detects clarification questions about the previous reply', () => {
    const messages: ChatMessage[] = [user('q'), assistant('a long answer'), user('What does that mean?')];
    const summary = summarizeConversationHistory(messages, 'What does that mean?');
    expect(summary.intent).toBe('clarification');
  });

  it('detects iteration intent for "actually" / "instead" prompts', () => {
    const messages: ChatMessage[] = [user('q'), assistant('first try'), user('actually, try again with fewer fields')];
    const summary = summarizeConversationHistory(messages, 'actually, try again with fewer fields');
    expect(summary.intent).toBe('iteration');
  });

  it('detects "more like X" comparison prompts and captures the subject', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('Make it more like Stripe Charges')];
    const summary = summarizeConversationHistory(
      messages,
      'Make it more like Stripe Charges',
    );
    expect(summary.intent).toBe('comparison');
    expect(summary.comparisonSubject).toBe('Stripe Charges');
  });

  it('detects refine-spec intent when a prior spec exists and refinement words appear', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('refine that please')];
    const summary = summarizeConversationHistory(messages, 'refine that please');
    expect(summary.intent).toBe('refine-spec');
    expect(summary.lastAssistantSpec).not.toBeNull();
  });

  it('returns standalone (not refine-spec) when refinement words appear but no spec is present', () => {
    const messages: ChatMessage[] = [user('q'), assistant('plain text reply'), user('refine that please')];
    const summary = summarizeConversationHistory(messages, 'refine that please');
    expect(summary.intent).toBe('standalone');
    expect(summary.lastAssistantSpec).toBeNull();
  });

  it('extracts add / remove / require / rename ops from the prompt', () => {
    const prompt = 'add a phone field of type string, remove priceCents, make name required, rename id to productId';
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user(prompt)];
    const summary = summarizeConversationHistory(
      messages,
      prompt,
    );
    expect(summary.intent).toBe('refine-spec');
    expect(summary.refinementOps).toEqual<ChatRefinementOp[]>([
      { kind: 'add-property', name: 'phone', type: 'string' },
      { kind: 'remove-property', name: 'priceCents' },
      { kind: 'require-property', name: 'name' },
      { kind: 'rename-property', from: 'id', to: 'productId' },
    ]);
  });

  it('parses concise add-property phrasing like "add timestamps integer"', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('add createdAt integer')];
    const summary = summarizeConversationHistory(messages, 'add createdAt integer');
    expect(summary.refinementOps).toContainEqual({
      kind: 'add-property',
      name: 'createdAt',
      type: 'integer',
    });
  });

  it('builds excerpts capped to the most recent turns and trims long text', () => {
    const long = 'word '.repeat(120);
    const messages: ChatMessage[] = [];
    for (let i = 0; i < CHAT_HISTORY_TURN_CAP + 4; i += 1) {
      messages.push(user(`u-${i}`, `u-${i}`));
      messages.push(assistant(`a-${i}-${long}`, `a-${i}`));
    }
    messages.push(user('next')); // mirror production: include the current user turn.
    const summary = summarizeConversationHistory(messages, 'next');
    expect(summary.recentExcerpts.length).toBeLessThanOrEqual(CHAT_HISTORY_TURN_CAP);
    for (const e of summary.recentExcerpts) {
      expect(e.content.length).toBeLessThanOrEqual(CHAT_HISTORY_EXCERPT_CHAR_CAP);
    }
  });

  it('replaces fenced code blocks in excerpts with a placeholder', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('next')];
    const summary = summarizeConversationHistory(messages, 'next');
    const last = summary.recentExcerpts[summary.recentExcerpts.length - 1];
    expect(last.content).toContain('[code block omitted]');
    expect(last.content).not.toContain('```');
  });
});

describe('buildConversationHistoryPreamble', () => {
  it('returns an empty string for the first turn', () => {
    const summary = summarizeConversationHistory([user('hello')], 'hello');
    expect(buildConversationHistoryPreamble(summary)).toBe('');
  });

  it('mentions turn counters and intent when refining a spec', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('add a phone field')];
    const summary = summarizeConversationHistory(messages, 'add a phone field');
    const preamble = buildConversationHistoryPreamble(summary);
    expect(preamble).toMatch(/Turn 2 of an ongoing thread/);
    expect(preamble).toMatch(/refinement of the last generated schema/i);
    expect(preamble).toMatch(/Add property `phone`/);
  });

  it('mentions the comparison subject when present', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('Make it more like FHIR Patient')];
    const summary = summarizeConversationHistory(messages, 'Make it more like FHIR Patient');
    const preamble = buildConversationHistoryPreamble(summary);
    expect(preamble).toMatch(/look more like: FHIR Patient/);
  });

  it('describes clarification intent without inventing schema edits', () => {
    const messages: ChatMessage[] = [user('q'), assistant(SAMPLE_SPEC_REPLY), user('What does priceCents mean?')];
    const summary = summarizeConversationHistory(messages, 'What does priceCents mean?');
    const preamble = buildConversationHistoryPreamble(summary);
    expect(preamble).toMatch(/clarifying question/);
    expect(preamble).not.toMatch(/Detected schema edits/);
  });
});

describe('applyRefinementsToSpec', () => {
  const baseSpec = (): Record<string, unknown> => ({
    openapi: '3.1.0',
    info: { title: 'Catalog', version: '0.1.0' },
    components: {
      schemas: {
        Product: {
          type: 'object',
          properties: {
            id: { type: 'string' },
            name: { type: 'string' },
            priceCents: { type: 'integer' },
          },
          required: ['id'],
        },
      },
    },
  });

  it('returns a clone — never mutates the input spec', () => {
    const input = baseSpec();
    const before = JSON.stringify(input);
    applyRefinementsToSpec(input, [{ kind: 'remove-property', name: 'name' }]);
    expect(JSON.stringify(input)).toBe(before);
  });

  it('adds a property with the requested type', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'add-property', name: 'phone', type: 'string' },
    ]) as { components: { schemas: { Product: { properties: Record<string, { type: string }> } } } };
    expect(out.components.schemas.Product.properties.phone.type).toBe('string');
  });

  it('infers schema from property name when type is omitted (#277)', () => {
    const ops: ChatRefinementOp[] = [
      { kind: 'add-property', name: 'email' },
      { kind: 'add-property', name: 'createdAt' },
      { kind: 'add-property', name: 'age' },
      { kind: 'add-property', name: 'price' },
      { kind: 'add-property', name: 'isActive' },
      { kind: 'add-property', name: 'notes' },
    ];
    const out = applyRefinementsToSpec(baseSpec(), ops) as {
      components: { schemas: { Product: { properties: Record<string, Record<string, unknown>> } } };
    };
    const p = out.components.schemas.Product.properties;
    expect(p.email).toMatchObject({
      type: 'string',
      format: 'email',
      maxLength: 254,
    });
    expect(p.createdAt).toMatchObject({ type: 'string', format: 'date-time' });
    expect(p.age).toMatchObject({ type: 'integer', minimum: 0, maximum: 150 });
    expect(p.price).toMatchObject({ type: 'number', minimum: 0 });
    expect(p.isActive).toMatchObject({ type: 'boolean' });
    expect(p.notes).toMatchObject({ type: 'string', maxLength: 10000 });
    expect(p.notes.format).toBeUndefined();
  });

  it('matches inference case-insensitively on property name (#277)', () => {
    const out = applyRefinementsToSpec(baseSpec(), [{ kind: 'add-property', name: 'Email' }]) as {
      components: { schemas: { Product: { properties: Record<string, { type: string; format?: string }> } } };
    };
    expect(out.components.schemas.Product.properties.Email).toMatchObject({
      type: 'string',
      format: 'email',
    });
  });

  it('does not override an explicit type with name inference (#277)', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'add-property', name: 'createdAt', type: 'integer' },
    ]) as {
      components: { schemas: { Product: { properties: Record<string, Record<string, unknown>> } } };
    };
    const pr = out.components.schemas.Product.properties.createdAt;
    expect(pr.type).toBe('integer');
    expect(pr.format).toBeUndefined();
  });

  it('updates the type of an existing property when add is requested with a type', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'add-property', name: 'priceCents', type: 'number' },
    ]) as { components: { schemas: { Product: { properties: Record<string, { type: string }> } } } };
    expect(out.components.schemas.Product.properties.priceCents.type).toBe('number');
  });

  it('clears stale inferred constraints when an explicit type is provided for an existing property (#277)', () => {
    // First, add createdAt without a type so inference kicks in (gives string + format: date-time).
    const step1 = applyRefinementsToSpec(baseSpec(), [{ kind: 'add-property', name: 'createdAt' }]) as {
      components: { schemas: { Product: { properties: Record<string, Record<string, unknown>> } } };
    };
    expect(step1.components.schemas.Product.properties.createdAt).toMatchObject({
      type: 'string',
      format: 'date-time',
    });

    // Now re-add with an explicit type — format must be cleared to avoid contradictory schema.
    const step2 = applyRefinementsToSpec(step1, [{ kind: 'add-property', name: 'createdAt', type: 'integer' }]) as {
      components: { schemas: { Product: { properties: Record<string, Record<string, unknown>> } } };
    };
    const prop = step2.components.schemas.Product.properties.createdAt;
    expect(prop.type).toBe('integer');
    expect(prop.format).toBeUndefined();
    expect(prop.minimum).toBeUndefined();
  });

  it('removes a property and prunes required entries', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'remove-property', name: 'id' },
    ]) as { components: { schemas: { Product: { properties: Record<string, unknown>; required?: string[] } } } };
    expect(out.components.schemas.Product.properties.id).toBeUndefined();
    expect(out.components.schemas.Product.required).toBeUndefined();
  });

  it('marks an existing property as required without duplicating it', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'require-property', name: 'name' },
      { kind: 'require-property', name: 'name' },
    ]) as { components: { schemas: { Product: { required: string[] } } } };
    expect(out.components.schemas.Product.required).toEqual(['id', 'name']);
  });

  it('creates a placeholder property when require is asked for an unknown name', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'require-property', name: 'tenantId' },
    ]) as { components: { schemas: { Product: { properties: Record<string, { type: string }>; required: string[] } } } };
    expect(out.components.schemas.Product.properties.tenantId.type).toBe('string');
    expect(out.components.schemas.Product.required).toContain('tenantId');
  });

  it('infers constraint hints for common names (#278)', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'add-property', name: 'password' },
      { kind: 'add-property', name: 'percentage' },
      { kind: 'add-property', name: 'slug' },
      { kind: 'add-property', name: 'latitude' },
    ]) as {
      components: { schemas: { Product: { properties: Record<string, Record<string, unknown>> } } };
    };
    const pr = out.components.schemas.Product.properties;
    expect(pr.password).toMatchObject({ minLength: 8, maxLength: 256 });
    expect(pr.percentage).toMatchObject({ minimum: 0, maximum: 100 });
    expect(pr.slug).toMatchObject({ pattern: '^[a-z0-9]+(?:-[a-z0-9]+)*$' });
    expect(pr.latitude).toMatchObject({ minimum: -90, maximum: 90 });
  });

  it('adds id with uuid constraints and marks it required when inferred (#278)', () => {
    const spec: Record<string, unknown> = {
      openapi: '3.1.0',
      info: { title: 'x', version: '0.1.0' },
      components: {
        schemas: {
          Widget: {
            type: 'object',
            properties: {},
          },
        },
      },
    };
    const out = applyRefinementsToSpec(spec, [{ kind: 'add-property', name: 'id' }]) as {
      components: {
        schemas: {
          Widget: {
            properties: Record<string, Record<string, unknown>>;
            required?: string[];
          };
        };
      };
    };
    expect(out.components.schemas.Widget.properties.id).toMatchObject({
      type: 'string',
      format: 'uuid',
    });
    expect(out.components.schemas.Widget.required).toContain('id');
  });

  it('infers schema when require-property adds a missing known name (#277)', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'require-property', name: 'isActive' },
    ]) as {
      components: { schemas: { Product: { properties: Record<string, Record<string, unknown>>; required: string[] } } };
    };
    expect(out.components.schemas.Product.properties.isActive).toMatchObject({ type: 'boolean' });
    expect(out.components.schemas.Product.required).toContain('isActive');
  });

  it('renames a property and updates the required list', () => {
    const out = applyRefinementsToSpec(baseSpec(), [
      { kind: 'rename-property', from: 'id', to: 'productId' },
    ]) as { components: { schemas: { Product: { properties: Record<string, unknown>; required: string[] } } } };
    expect(out.components.schemas.Product.properties.productId).toBeDefined();
    expect(out.components.schemas.Product.properties.id).toBeUndefined();
    expect(out.components.schemas.Product.required).toContain('productId');
  });

  it('returns the clone untouched when the spec has no schemas', () => {
    const spec = { openapi: '3.1.0', info: { title: 'x', version: '0.1.0' } };
    const out = applyRefinementsToSpec(spec, [{ kind: 'remove-property', name: 'x' }]);
    expect(out).toEqual(spec);
    expect(out).not.toBe(spec);
  });
});
