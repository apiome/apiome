import {
  normalizeAiSchemaImprovementApplyAction,
  normalizeEstimatedOverallScoreDelta,
  parseAiSchemaImprovementSuggestionsResponse,
} from '../../lib/ai-schema-improvement-suggestions';

describe('parseAiSchemaImprovementSuggestionsResponse', () => {
  it('parses a valid fenced JSON payload', () => {
    const md = `intro\n\n\`\`\`json\n{"thinking":"t","summary":"s","suggestions":[{"title":"Add docs","detail":"Fill descriptions","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":3}]}\n\`\`\``;
    const p = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(p).not.toBeNull();
    expect(p!.suggestions).toHaveLength(1);
    expect(p!.suggestions[0].title).toBe('Add docs');
    expect(p!.suggestions[0].category).toBe('documentation');
    expect(p!.suggestions[0].effort).toBe('quick_win');
    expect(p!.suggestions[0].estimatedOverallScoreDelta).toBe(3);
  });

  it('uses last json fence when multiple exist', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"a","detail":"d","category":"other","effort":"moderate"}]}\n```\n\n```json\n{"thinking":"","summary":"","suggestions":[{"title":"b","detail":"d2","category":"naming","effort":"moderate"}]}\n```';
    const p = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(p?.suggestions[0].title).toBe('b');
  });

  it('returns null when suggestions empty', () => {
    const md = "```json\n{\"thinking\":\"x\",\"summary\":\"y\",\"suggestions\":[]}\n```";
    expect(parseAiSchemaImprovementSuggestionsResponse(md)).toBeNull();
  });

  it('skips rows missing title or detail', () => {
    const md =
      "```json\n{\"thinking\":\"\",\"summary\":\"\",\"suggestions\":[{\"title\":\"\",\"detail\":\"x\",\"category\":\"other\"},{\"title\":\"ok\",\"detail\":\"\",\"category\":\"other\"},{\"title\":\"good\",\"detail\":\"body\",\"category\":\"api\"}]}\n```";
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions).toEqual([{ title: 'good', detail: 'body', category: 'api', effort: 'moderate' }]);
  });

  it('normalizes unknown category to other', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"x","detail":"y","category":"not-a-real-category"}]}\n```';
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].category).toBe('other');
  });

  it('defaults missing effort to moderate', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"x","detail":"y","category":"documentation"}]}\n```';
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].effort).toBe('moderate');
  });

  it('sorts suggestions so quick_win rows come first (stable within tier)', () => {
    const md = `\`\`\`json
{"thinking":"","summary":"","suggestions":[
  {"title":"big","detail":"d","category":"structure","effort":"substantial"},
  {"title":"fast","detail":"d","category":"documentation","effort":"quick_win"},
  {"title":"mid","detail":"d","category":"naming","effort":"moderate"},
  {"title":"also fast","detail":"d","category":"documentation","effort":"quick_win"}
]}
\`\`\``;
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions.map((s) => s.title)).toEqual(['fast', 'also fast', 'mid', 'big']);
  });

  it('normalizes effort aliases', () => {
    const md = `\`\`\`json
{"thinking":"","summary":"","suggestions":[
  {"title":"a","detail":"d","category":"other","effort":"Quick-Win"},
  {"title":"b","detail":"d","category":"other","effort":"LARGE"}
]}
\`\`\``;
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].effort).toBe('quick_win');
    expect(r?.suggestions[1].effort).toBe('substantial');
  });

  it('normalizes spaced effort variants (e.g. "quick win" with a space)', () => {
    const md = `\`\`\`json
{"thinking":"","summary":"","suggestions":[
  {"title":"a","detail":"d","category":"other","effort":"quick win"},
  {"title":"b","detail":"d","category":"other","effort":"Quick Win"},
  {"title":"c","detail":"d","category":"other","effort":"QUICK WIN"}
]}
\`\`\``;
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].effort).toBe('quick_win');
    expect(r?.suggestions[1].effort).toBe('quick_win');
    expect(r?.suggestions[2].effort).toBe('quick_win');
  });

  it('returns null when no json fence', () => {
    expect(parseAiSchemaImprovementSuggestionsResponse('no fence')).toBeNull();
  });

  it('omits estimatedOverallScoreDelta when not provided', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"x","detail":"y","category":"documentation","effort":"quick_win"}]}\n```';
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].estimatedOverallScoreDelta).toBeUndefined();
  });

  it('parses estimatedOverallScoreDelta from numeric strings and clamps', () => {
    const md = `\`\`\`json
{"thinking":"","summary":"","suggestions":[
  {"title":"a","detail":"d","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":"4"},
  {"title":"b","detail":"d","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":99},
  {"title":"c","detail":"d","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":-40}
]}
\`\`\``;
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions.map((s) => s.estimatedOverallScoreDelta)).toEqual([4, 25, -25]);
  });

  it('parses optional apply set_class_description', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"Doc Order","detail":"Add text","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":2,"apply":{"type":"set_class_description","className":"Order","description":"Represents a customer order."}}]}\n```';
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].apply).toEqual({
      type: 'set_class_description',
      className: 'Order',
      description: 'Represents a customer order.',
    });
  });

  it('parses optional apply set_property_description', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"Prop","detail":"d","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":1,"apply":{"type":"set_property_description","className":"User","propertyName":"email","description":"Primary contact email."}}]}\n```';
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].apply).toEqual({
      type: 'set_property_description',
      className: 'User',
      propertyName: 'email',
      description: 'Primary contact email.',
    });
  });

  it('omits invalid apply payloads', () => {
    const md =
      '```json\n{"thinking":"","summary":"","suggestions":[{"title":"x","detail":"y","category":"documentation","effort":"quick_win","estimatedOverallScoreDelta":1,"apply":{"type":"unknown","className":"A","description":"b"}}]}\n```';
    const r = parseAiSchemaImprovementSuggestionsResponse(md);
    expect(r?.suggestions[0].apply).toBeUndefined();
  });
});

describe('normalizeAiSchemaImprovementApplyAction', () => {
  it('returns undefined for malformed payloads', () => {
    expect(normalizeAiSchemaImprovementApplyAction(null)).toBeUndefined();
    expect(normalizeAiSchemaImprovementApplyAction({ type: 'set_class_description' })).toBeUndefined();
  });

  it('clamps long descriptions', () => {
    const long = 'x'.repeat(9000);
    const a = normalizeAiSchemaImprovementApplyAction({
      type: 'set_class_description',
      className: 'Z',
      description: long,
    });
    expect(a?.type).toBe('set_class_description');
    if (a?.type === 'set_class_description') {
      expect(a.description.length).toBe(8000);
    }
  });
});

describe('normalizeEstimatedOverallScoreDelta', () => {
  it('returns undefined for non-finite input', () => {
    expect(normalizeEstimatedOverallScoreDelta(undefined)).toBeUndefined();
    expect(normalizeEstimatedOverallScoreDelta('')).toBeUndefined();
    expect(normalizeEstimatedOverallScoreDelta('x')).toBeUndefined();
  });
});
