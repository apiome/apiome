/**
 * Tests for the offline demo responder used by the Studio chatbot
 * (#258, #259, #260).
 *
 * Covers:
 *   - The "no context" baseline behaviour designers see in isolated previews
 *   - The context-aware grounding wired up in #259 — project / version
 *     mention, canvas selection acknowledgement, and reuse of existing
 *     class / property names inside the sample OpenAPI spec
 *   - The multi-turn behaviour wired up in #260 — refining the previous
 *     spec, handling clarification questions, "make it more like X"
 *     comparisons, and re-rolls
 */

import {
  buildClassDraftRefinementUserMessage,
  parseClassDefinitionFromAssistantMarkdown,
} from '../../src/app/ade/studio/components/chatbot/assistant-action-detection';
import { createDemoChatResponder } from '../../src/app/ade/studio/components/chatbot/demo-responder';
import { detectOpenApiSpecs } from '../../src/app/ade/studio/components/chatbot/openapi-detection';
import {
  EMPTY_CHAT_STUDIO_CONTEXT,
  type ChatStudioContext,
} from '../../src/app/ade/studio/components/chatbot/chat-context';
import type { ChatMessage } from '../../src/app/ade/studio/components/chatbot/types';

const richContext: ChatStudioContext = {
  project: { id: 'proj-1', name: 'Acme Catalog' },
  version: { id: 'ver-1', label: 'v2.0.0' },
  classes: [
    { id: 'cls-cart', name: 'Cart', description: 'Shopping cart' },
    { id: 'cls-product', name: 'Product', description: 'Catalog item' },
  ],
  properties: [
    { id: 'prop-sku', name: 'sku', type: 'string', description: 'Stock keeping unit' },
    { id: 'prop-qty', name: 'quantity', type: 'integer', description: 'Units in cart' },
  ],
  selectedClassIds: ['cls-cart'],
};

describe('createDemoChatResponder', () => {
  const responder = createDemoChatResponder();

  it('returns an OpenAPI spec when the prompt mentions a spec keyword', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'Generate an OpenAPI spec for me',
      isRegenerate: false,
    });
    expect(reply).toMatch(/```json/);
    expect(detectOpenApiSpecs(reply)).toHaveLength(1);
    expect(reply).toMatch(/\*\*Improvement suggestions\*\*/);
    expect(reply).toMatch(/pagination/i);
  });

  it('returns an OpenAPI spec for a plain-language description without spec keywords (#267)', async () => {
    const reply = await responder({
      messages: [],
      prompt:
        'I need a blog platform with posts, authors, and comments where each comment references a post',
      isRegenerate: false,
    });
    expect(reply).toMatch(/```json/);
    expect(detectOpenApiSpecs(reply)).toHaveLength(1);
    expect(reply).toMatch(/Import OpenAPI spec/);
  });

  it('returns a generic onboarding reply for unrelated prompts', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'tell me a joke',
      isRegenerate: false,
    });
    expect(reply).toMatch(/Markdown/);
    expect(detectOpenApiSpecs(reply)).toHaveLength(0);
  });

  it('refines an embedded class skeleton draft heuristically (#532)', async () => {
    const draftMd = [
      '```json',
      JSON.stringify({
        name: 'User',
        description: '',
        schema: {
          type: 'object',
          properties: {
            email: { type: 'string' },
            password: { type: 'string' },
          },
        },
      }),
      '```',
    ].join('\n');
    const parsed = parseClassDefinitionFromAssistantMarkdown(draftMd);
    expect(parsed).not.toBeNull();
    const prompt = buildClassDraftRefinementUserMessage(parsed!, 'Add a phone number field');
    const reply = await responder({
      messages: [{ id: 'u1', role: 'user', content: prompt }],
      prompt,
      isRegenerate: false,
    });
    expect(reply).toContain('phoneNumber');
    expect(reply).toMatch(/\*\*Improvement suggestions\*\*/);
    const out = parseClassDefinitionFromAssistantMarkdown(reply);
    expect(out).not.toBeNull();
    const props = (out!.schema as { properties?: Record<string, unknown> }).properties ?? {};
    expect(props.phoneNumber).toBeDefined();
  });

  it('annotates the reply when the user regenerates', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'tell me a joke',
      isRegenerate: true,
    });
    expect(reply).toMatch(/Regenerated/);
  });

  it('treats an empty studio context the same as no context', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'tell me a joke',
      isRegenerate: false,
      studioContext: EMPTY_CHAT_STUDIO_CONTEXT,
    });
    expect(reply).not.toMatch(/Acme Catalog/);
    expect(reply).not.toMatch(/v2\.0\.0/);
  });

  it('mentions the project, version, and selection when context is present', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'tell me a joke',
      isRegenerate: false,
      studioContext: richContext,
    });
    expect(reply).toMatch(/Acme Catalog/);
    expect(reply).toMatch(/v2\.0\.0/);
    expect(reply).toMatch(/Cart/);
  });

  it('prepends domain best-practice tips in improvement suggestions when domainCategory is set (#615)', async () => {
    const ctx: ChatStudioContext = {
      ...richContext,
      project: { id: 'proj-1', name: 'Acme Catalog', domainCategory: 'ecommerce' },
    };
    const reply = await responder({
      messages: [],
      prompt: 'Generate an OpenAPI spec for me',
      isRegenerate: false,
      studioContext: ctx,
    });
    const idxInventory = reply.toLowerCase().indexOf('inventory tracking');
    const idxPagination = reply.toLowerCase().indexOf('pagination');
    expect(idxInventory).toBeGreaterThan(-1);
    expect(idxPagination).toBeGreaterThan(-1);
    expect(idxInventory).toBeLessThan(idxPagination);
  });

  it('embeds the project name and reusable properties in the sample OpenAPI spec', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'sketch a schema for me',
      isRegenerate: false,
      studioContext: richContext,
    });
    const specs = detectOpenApiSpecs(reply);
    expect(specs).toHaveLength(1);
    const spec = specs[0].spec as {
      info: { title: string; version: string };
      components: { schemas: Record<string, { properties: Record<string, unknown> }> };
    };
    expect(spec.info.title).toMatch(/Acme Catalog/);
    expect(spec.info.version).toBe('v2.0.0');
    // The selected class wins as the schema name; reusable properties are inlined.
    const schemaName = Object.keys(spec.components.schemas)[0];
    expect(schemaName).toBe('Cart');
    const props = spec.components.schemas[schemaName].properties;
    expect(props).toHaveProperty('sku');
    expect(props).toHaveProperty('quantity');
  });

  it('falls back to the canonical sample spec when no context is supplied', async () => {
    const reply = await responder({
      messages: [],
      prompt: 'openapi please',
      isRegenerate: false,
    });
    const specs = detectOpenApiSpecs(reply);
    expect(specs).toHaveLength(1);
    const spec = specs[0].spec as {
      info: { title: string };
      components: { schemas: Record<string, unknown> };
    };
    expect(spec.info.title).toBe('Sample Catalog API');
    expect(Object.keys(spec.components.schemas)).toContain('Product');
  });

  describe('multi-turn behaviour (#260)', () => {
    async function getInitialSpecReply(): Promise<string> {
      return responder({
        messages: [],
        prompt: 'Generate an OpenAPI spec for me',
        isRegenerate: false,
      });
    }

    function turnsAfter(initialReply: string, prompt: string): ChatMessage[] {
      return [
        { id: 'u1', role: 'user', content: 'Generate an OpenAPI spec for me' },
        { id: 'a1', role: 'assistant', content: initialReply },
        { id: 'u2', role: 'user', content: prompt },
      ]; // mirror production: messages includes the latest user turn as well.
    }

    it('refines the previously-generated spec when the user asks to add a property', async () => {
      const initial = await getInitialSpecReply();
      const initialSpecs = detectOpenApiSpecs(initial);
      const initialSchemaName = Object.keys(
        (initialSpecs[0].spec as { components: { schemas: Record<string, unknown> } })
          .components.schemas,
      )[0];

      const refinement = await responder({
        messages: turnsAfter(initial, 'add a phone field of type string'),
        prompt: 'add a phone field of type string',
        isRegenerate: false,
      });
      expect(refinement).toMatch(/Updated the previous schema/);
      expect(refinement).toMatch(/added `phone`/);
      expect(refinement).toMatch(/\*\*Improvement suggestions\*\*/);
      const refinedSpecs = detectOpenApiSpecs(refinement);
      expect(refinedSpecs).toHaveLength(1);
      const refinedSchema = (refinedSpecs[0].spec as {
        components: { schemas: Record<string, { properties: Record<string, { type: string }> }> };
      }).components.schemas[initialSchemaName];
      expect(refinedSchema.properties.phone).toEqual({
        type: 'string',
        description: 'Added in follow-up: phone.',
      });
      // The original properties are preserved by the deep clone.
      expect(refinedSchema.properties.id).toBeDefined();
      expect(refinedSchema.properties.name).toBeDefined();
    });

    it('removes a property and prunes the required list when asked', async () => {
      const initial = await getInitialSpecReply();
      const refinement = await responder({
        messages: turnsAfter(initial, 'remove priceCents'),
        prompt: 'remove priceCents',
        isRegenerate: false,
      });
      expect(refinement).toMatch(/removed `priceCents`/);
      const spec = detectOpenApiSpecs(refinement)[0].spec as {
        components: { schemas: Record<string, { properties: Record<string, unknown> }> };
      };
      const schema = Object.values(spec.components.schemas)[0];
      expect(schema.properties.priceCents).toBeUndefined();
    });

    it('marks a property required when the follow-up uses "make X required"', async () => {
      const initial = await getInitialSpecReply();
      const refinement = await responder({
        messages: turnsAfter(initial, 'make name required'),
        prompt: 'make name required',
        isRegenerate: false,
      });
      const spec = detectOpenApiSpecs(refinement)[0].spec as {
        components: { schemas: Record<string, { required: string[] }> };
      };
      const schema = Object.values(spec.components.schemas)[0];
      expect(schema.required).toContain('name');
    });

    it('answers clarification questions without re-shipping a spec', async () => {
      const initial = await getInitialSpecReply();
      const reply = await responder({
        messages: turnsAfter(initial, 'What does priceCents represent?'),
        prompt: 'What does priceCents represent?',
        isRegenerate: false,
      });
      expect(reply).toMatch(/Happy to clarify/);
      expect(reply).toMatch(/turn 2/);
      expect(detectOpenApiSpecs(reply)).toHaveLength(0);
    });

    it('reframes the spec when the user asks for "more like X"', async () => {
      const initial = await getInitialSpecReply();
      const reply = await responder({
        messages: turnsAfter(initial, 'Make it more like Stripe Charges'),
        prompt: 'Make it more like Stripe Charges',
        isRegenerate: false,
      });
      expect(reply).toMatch(/lean more like \*\*Stripe Charges\*\*/);
      const spec = detectOpenApiSpecs(reply)[0].spec as {
        info: { title: string; description: string };
      };
      expect(spec.info.title).toMatch(/Stripe Charges/);
      expect(spec.info.description).toMatch(/Stripe Charges/);
    });

    it('flags multi-turn standalone prompts with a continuation note', async () => {
      const initial = await getInitialSpecReply();
      const reply = await responder({
        messages: turnsAfter(initial, 'tell me a joke'),
        prompt: 'tell me a joke',
        isRegenerate: false,
      });
      expect(reply).toMatch(/Continuing the thread — turn 2/);
    });
  });
});
