import {
  mcpEndpointNoteAuthorLabel,
  mcpEndpointNoteFromPayload,
  mcpEndpointNoteWasEdited,
  mcpEndpointNotesFromPayload,
} from '../src/app/components/ade/dashboard/mcp/mcpEndpointNotesUi';

describe('mcpEndpointNotesUi', () => {
  const sample = {
    id: 'note-1',
    endpointId: 'ep-1',
    body: 'Prefer staging.',
    createdBy: 'user-1',
    createdByName: 'Ada',
    createdByEmail: 'ada@example.com',
    updatedBy: null,
    updatedByName: null,
    updatedByEmail: null,
    createdAt: '2026-07-07T12:00:00Z',
    updatedAt: '2026-07-07T12:00:00Z',
  };

  it('parses one note from the REST payload', () => {
    const note = mcpEndpointNoteFromPayload(sample);
    expect(note?.body).toBe('Prefer staging.');
    expect(note?.createdByName).toBe('Ada');
  });

  it('parses list envelopes', () => {
    const notes = mcpEndpointNotesFromPayload({ notes: [sample] });
    expect(notes).toHaveLength(1);
  });

  it('builds author labels', () => {
    const note = mcpEndpointNoteFromPayload(sample)!;
    expect(mcpEndpointNoteAuthorLabel(note)).toContain('Ada');
  });

  it('detects edited notes', () => {
    const note = mcpEndpointNoteFromPayload({
      ...sample,
      updatedBy: 'user-2',
      updatedAt: '2026-07-08T12:00:00Z',
    })!;
    expect(mcpEndpointNoteWasEdited(note)).toBe(true);
  });
});
