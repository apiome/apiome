/**
 * Source citations (UXE-1.3).
 *
 * Roadmap section 28.1 requires "exact source citations". The formatting
 * helpers below produce a citation's accessible name, so a screen-reader user
 * hears where a generated claim came from without opening the link — and the
 * uncited case is reported as a warning rather than as a tidy blank.
 */

import {
  describeAuthoringCanonicalKind,
  formatAuthoringCitation,
  summarizeAuthoringCitations,
  type AuthoringCanonicalKind,
  type AuthoringCitation,
} from '../../lib/authoring/citations';

const OPERATION: AuthoringCitation = {
  id: 'cite-1',
  label: 'GET /pets/{petId}',
  kind: 'operation',
  stableKey: 'op:get:/pets/{petId}',
  sourcePointer: 'paths./pets/{petId}.get',
};

const ALL_KINDS: AuthoringCanonicalKind[] = [
  'artifact',
  'service',
  'operation',
  'message',
  'channel',
  'type',
  'field',
  'parameter',
  'response',
  'workflow_step',
];

describe('describeAuthoringCanonicalKind', () => {
  it.each(ALL_KINDS)('gives %s a readable name', (kind) => {
    expect(describeAuthoringCanonicalKind(kind)).toBeTruthy();
  });

  it('renders the underscored kind as words', () => {
    expect(describeAuthoringCanonicalKind('workflow_step')).toBe('Workflow step');
  });
});

describe('formatAuthoringCitation', () => {
  it('names the kind, the target and the source pointer', () => {
    expect(formatAuthoringCitation(OPERATION)).toBe(
      'Operation GET /pets/{petId} at paths./pets/{petId}.get'
    );
  });

  it('omits the location clause when there is no native pointer', () => {
    expect(formatAuthoringCitation({ ...OPERATION, sourcePointer: undefined })).toBe(
      'Operation GET /pets/{petId}'
    );
  });
});

describe('summarizeAuthoringCitations', () => {
  it('warns when nothing was cited, rather than reporting an empty list', () => {
    const summary = summarizeAuthoringCitations([]);

    expect(summary).toMatch(/no sources cited/i);
    expect(summary).toMatch(/verify/i);
  });

  it('spells out a single citation in full', () => {
    expect(summarizeAuthoringCitations([OPERATION])).toContain('paths./pets/{petId}.get');
  });

  it('counts rather than enumerates several citations', () => {
    expect(summarizeAuthoringCitations([OPERATION, { ...OPERATION, id: 'cite-2' }])).toBe(
      '2 sources cited.'
    );
  });
});
