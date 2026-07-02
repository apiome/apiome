import {
  parseAiPropertySuggestionsResponse,
  suggestionPublicExplanation,
  type AiPropertySuggestionsPayload,
} from '../../lib/ai-property-suggestions';

describe('parseAiPropertySuggestionsResponse', () => {
  it('parses the last fenced json block', () => {
    const md = `ignored\n\n\`\`\`json\n{"thinking":"overall","summary":"wrap","suggestions":[{"name":"emailAddress","description":"Primary","schema":{"type":"string","format":"email"},"thinking":"common id","summary":"email"}]}\n\`\`\``;
    const r = parseAiPropertySuggestionsResponse(md);
    expect(r).not.toBeNull();
    const p = r as AiPropertySuggestionsPayload;
    expect(p.thinking).toBe('overall');
    expect(p.summary).toBe('wrap');
    expect(p.suggestions).toHaveLength(1);
    expect(p.suggestions[0].name).toBe('emailAddress');
    expect(p.suggestions[0].schema).toEqual({ type: 'string', format: 'email' });
  });

  it('returns null without a json fence', () => {
    expect(parseAiPropertySuggestionsResponse('plain text')).toBeNull();
  });

  it('returns null when suggestions empty', () => {
    const md = "```json\n{\"thinking\":\"x\",\"summary\":\"y\",\"suggestions\":[]}\n```";
    expect(parseAiPropertySuggestionsResponse(md)).toBeNull();
  });

  it('skips suggestion rows missing name or schema object', () => {
    const md =
      "```json\n{\"thinking\":\"\",\"summary\":\"\",\"suggestions\":[{\"name\":\"\",\"schema\":{\"type\":\"string\"}},{\"name\":\"ok\",\"schema\":{\"type\":\"integer\"}}]}\n```";
    const r = parseAiPropertySuggestionsResponse(md);
    expect(r?.suggestions).toEqual([
      expect.objectContaining({ name: 'ok', schema: { type: 'integer' } }),
    ]);
  });

  it('canonicalPropertyName overrides suggestion names', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"name":"wrong","schema":{"type":"string"}},{"name":"x","schema":{"type":"integer"}}]}\n```';
    const r = parseAiPropertySuggestionsResponse(md, { canonicalPropertyName: 'patientId' });
    expect(r?.suggestions.map((s) => s.name)).toEqual(['patientId', 'patientId']);
  });

  it('parses per-suggestion explanation and rationale', () => {
    const md = `\`\`\`json
{"thinking":"","summary":"","suggestions":[
  {"name":"a","schema":{"type":"string"},"explanation":"From explanation"},
  {"name":"b","schema":{"type":"integer"},"rationale":"From rationale"},
  {"name":"c","schema":{"type":"number"},"thinking":"From thinking"}
]}
\`\`\``;
    const r = parseAiPropertySuggestionsResponse(md);
    expect(r?.suggestions[0].explanation).toBe('From explanation');
    expect(r?.suggestions[1].explanation).toBe('From rationale');
    expect(r?.suggestions[2].explanation).toBeUndefined();
    expect(r?.suggestions[2].thinking).toBe('From thinking');
  });
});

describe('suggestionPublicExplanation', () => {
  it('prefers explanation, then thinking, then description', () => {
    expect(
      suggestionPublicExplanation({
        name: 'x',
        schema: {},
        explanation: 'E',
        thinking: 'T',
        description: 'D',
      }),
    ).toBe('E');
    expect(
      suggestionPublicExplanation({
        name: 'x',
        schema: {},
        thinking: 'T',
        description: 'D',
      }),
    ).toBe('T');
    expect(
      suggestionPublicExplanation({
        name: 'x',
        schema: {},
        description: 'D',
      }),
    ).toBe('D');
    expect(suggestionPublicExplanation({ name: 'x', schema: {} })).toBeUndefined();
  });
});
