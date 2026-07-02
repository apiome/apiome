import { markersForParsedText } from '../../src/app/ade/studio/paths/lib/paths-code-markers';

describe('paths-code-markers', () => {
  it('returns no markers for valid JSON', () => {
    expect(markersForParsedText('{"a":1}', 'json')).toEqual([]);
  });

  it('returns a marker for invalid JSON', () => {
    const m = markersForParsedText('{', 'json');
    expect(m).toHaveLength(1);
    expect(m[0].message).toBeDefined();
  });

  it('returns no markers for valid YAML', () => {
    expect(markersForParsedText('a: 1\n', 'yaml')).toEqual([]);
  });

  it('returns a marker for invalid YAML', () => {
    const m = markersForParsedText('a: [', 'yaml');
    expect(m.length).toBeGreaterThanOrEqual(1);
  });
});
