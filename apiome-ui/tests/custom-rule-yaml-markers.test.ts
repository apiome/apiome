import { pointerToYamlRange, parseValidationDetail } from '../src/app/ade/dashboard/style-guides/customRuleYamlMarkers';

describe('pointerToYamlRange', () => {
  const yaml = `rules:
  servers-use-https:
    description: Every server URL uses https.
    severity: error
    given: "$.servers[*].url"
    then:
      function: pattern
      functionOptions:
        match: '('
`;

  it('resolves a nested pointer to the offending key line', () => {
    const range = pointerToYamlRange('rules.servers-use-https.then.functionOptions.match', yaml);
    expect(range.startLine).toBe(9);
    expect(yaml.split('\n')[range.startLine - 1]).toContain('match:');
  });

  it('falls back to the document start for unknown pointers', () => {
    const range = pointerToYamlRange('rules.unknown.field', yaml);
    expect(range.startLine).toBe(1);
  });
});

describe('parseValidationDetail', () => {
  it('extracts message and pointer from a FastAPI detail object', () => {
    expect(
      parseValidationDetail({ message: 'bad regex', pointer: 'rules.x.then.functionOptions.match' }),
    ).toEqual({
      message: 'bad regex',
      pointer: 'rules.x.then.functionOptions.match',
    });
  });
});
