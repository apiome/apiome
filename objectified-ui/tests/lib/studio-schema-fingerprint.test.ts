import type { ChatStudioContext } from '@/app/ade/studio/components/chatbot/chat-context';
import {
  canonicalStudioSchemaState,
  computeStudioSchemaFingerprint,
} from '../../lib/studio-schema-fingerprint';

function baseCtx(overrides: Partial<ChatStudioContext> = {}): ChatStudioContext {
  return {
    project: { id: 'p1', name: 'P' },
    version: { id: 'v1', label: '1.0' },
    classes: [{ id: 'c1', name: 'User', schema: { type: 'object', properties: { id: { type: 'string' } } } }],
    properties: [{ id: 'pr1', name: 'email', type: 'string', format: 'email', required: true, description: null }],
    selectedClassIds: [],
    ...overrides,
  };
}

describe('canonicalStudioSchemaState', () => {
  it('sorts classes and properties by id', () => {
    const ctx = baseCtx({
      classes: [
        { id: 'z', name: 'Z', schema: null },
        { id: 'a', name: 'A', schema: null },
      ],
      properties: [
        { id: 'p2', name: 'b', type: 'string', format: null, required: null, description: null },
        { id: 'p1', name: 'a', type: 'integer', format: null, required: null, description: null },
      ],
    });
    const canon = canonicalStudioSchemaState(ctx) as { classes: { id: string }[]; properties: { id: string }[] };
    expect(canon.classes.map((c) => c.id)).toEqual(['a', 'z']);
    expect(canon.properties.map((p) => p.id)).toEqual(['p1', 'p2']);
  });

  it('omits selection from canonical state', () => {
    const a = canonicalStudioSchemaState(baseCtx({ selectedClassIds: ['c1'] }));
    const b = canonicalStudioSchemaState(baseCtx({ selectedClassIds: [] }));
    expect(a).toEqual(b);
  });
});

describe('computeStudioSchemaFingerprint', () => {
  it('returns stable hex across calls for the same context', async () => {
    const ctx = baseCtx();
    const h1 = await computeStudioSchemaFingerprint(ctx);
    const h2 = await computeStudioSchemaFingerprint(ctx);
    expect(h1).toBe(h2);
    expect(h1).toMatch(/^[0-9a-f]{64}$/);
  });

  it('changes when a class schema changes', async () => {
    const before = await computeStudioSchemaFingerprint(baseCtx());
    const after = await computeStudioSchemaFingerprint(
      baseCtx({
        classes: [
          {
            id: 'c1',
            name: 'User',
            schema: { type: 'object', properties: { id: { type: 'string' }, extra: { type: 'number' } } },
          },
        ],
      }),
    );
    expect(before).not.toBe(after);
  });

  it('changes when a property field changes', async () => {
    const before = await computeStudioSchemaFingerprint(baseCtx());
    const after = await computeStudioSchemaFingerprint(
      baseCtx({
        properties: [
          {
            id: 'pr1',
            name: 'email',
            type: 'string',
            format: 'email',
            required: false,
            description: 'User email address',
          },
        ],
      }),
    );
    expect(before).not.toBe(after);
  });
});
