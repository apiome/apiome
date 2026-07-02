import {
  parseJsonSchemaObjectText,
  buildPropertyItemFromAiSeedForm,
} from '../../lib/property-item-utils';

describe('parseJsonSchemaObjectText', () => {
  it('accepts a valid object', () => {
    const r = parseJsonSchemaObjectText('{"type":"string","format":"email"}');
    expect(r).toEqual({
      ok: true,
      schema: { type: 'string', format: 'email' },
    });
  });

  it('rejects empty', () => {
    const r = parseJsonSchemaObjectText('   ');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/empty/i);
  });

  it('rejects invalid JSON', () => {
    const r = parseJsonSchemaObjectText('{');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/valid JSON/i);
  });

  it('rejects arrays', () => {
    const r = parseJsonSchemaObjectText('[1,2]');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/object/i);
  });

  it('rejects null', () => {
    const r = parseJsonSchemaObjectText('null');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/object/i);
  });
});

describe('buildPropertyItemFromAiSeedForm', () => {
  it('merges schema with id and name', () => {
    const r = buildPropertyItemFromAiSeedForm({
      name: 'emailAddr',
      description: 'Primary',
      schemaText: '{"type":"string","format":"email"}',
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.item.id).toBe('__ai_seed__');
      expect(r.item.name).toBe('emailAddr');
      expect(r.item.description).toBe('Primary');
      expect(r.item.type).toBe('string');
      expect(r.item.format).toBe('email');
    }
  });

  it('requires non-empty name', () => {
    const r = buildPropertyItemFromAiSeedForm({
      name: '  ',
      description: '',
      schemaText: '{}',
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/name/i);
  });

  it('omits description when blank', () => {
    const r = buildPropertyItemFromAiSeedForm({
      name: 'x',
      description: '  ',
      schemaText: '{"type":"integer"}',
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.item.description).toBeUndefined();
    }
  });

  it('blank description overrides description in schema JSON', () => {
    const r = buildPropertyItemFromAiSeedForm({
      name: 'y',
      description: '  ',
      schemaText: '{"type":"string","description":"from schema"}',
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.item.description).toBeUndefined();
    }
  });
});
