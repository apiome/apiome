import {
  COMMIT_EXTERNAL_REF_MAX_CHARS,
  extractBreakingHintsFromChangelog,
  validateVersionNotesClient,
} from '../lib/version-notes';

describe('version-notes', () => {
  it('validateVersionNotesClient requires non-empty revision note', () => {
    expect(validateVersionNotesClient('', '')).toEqual({
      ok: false,
      error: 'Revision note is required',
    });
    expect(validateVersionNotesClient('  ', 'x').ok).toBe(false);
  });

  it('validateVersionNotesClient accepts note with optional empty changelog', () => {
    expect(validateVersionNotesClient('Ship v2', '')).toEqual({ ok: true });
  });

  it('COMMIT_EXTERNAL_REF_MAX_CHARS matches REST author/ref limit (#2564)', () => {
    expect(COMMIT_EXTERNAL_REF_MAX_CHARS).toBe(500);
  });

  it('extractBreakingHintsFromChangelog finds breaking bullets', () => {
    const md = `- breaking: renamed id field\n- doc: readme\n* Breaking: API path`;
    expect(extractBreakingHintsFromChangelog(md)).toEqual([
      '- breaking: renamed id field',
      '* Breaking: API path',
    ]);
  });
});
