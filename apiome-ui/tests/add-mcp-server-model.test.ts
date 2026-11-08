/**
 * The Add MCP server dialog's footer table (`addMcpServerFooterFor`) and its steps.
 */

import {
  ADD_MCP_SERVER_STEPS,
  addMcpServerFooterFor,
  type AddMcpServerFooterState,
} from '@/app/components/ade/dashboard/mcp/addMcpServerModel';

function state(overrides: Partial<AddMcpServerFooterState> = {}): AddMcpServerFooterState {
  return {
    step: 'connect',
    ready: true,
    submitting: false,
    registry: false,
    scanComplete: false,
    scanSucceeded: false,
    ...overrides,
  };
}

describe('the Add MCP server steps', () => {
  it('are Connect, Discover and Done', () => {
    expect(ADD_MCP_SERVER_STEPS.map((s) => s.label)).toEqual(['Connect', 'Discover', 'Done']);
  });
});

describe('the Connect footer', () => {
  it('offers Discover → with no Back, gated on the form', () => {
    expect(addMcpServerFooterFor(state())).toEqual({
      back: null,
      cancel: { label: 'Cancel', disabled: false },
      primary: { label: 'Discover →', disabled: false },
      keepAnyway: null,
    });
    expect(addMcpServerFooterFor(state({ ready: false })).primary).toEqual({ label: 'Discover →', disabled: true });
  });

  it('says Starting… while the server is being registered', () => {
    expect(addMcpServerFooterFor(state({ submitting: true })).primary).toEqual({ label: 'Starting…', disabled: true });
  });

  it('says Import servers → for a registry, and Importing servers… while it syncs', () => {
    expect(addMcpServerFooterFor(state({ registry: true })).primary).toEqual({
      label: 'Import servers →',
      disabled: false,
    });
    expect(addMcpServerFooterFor(state({ registry: true, submitting: true })).primary).toEqual({
      label: 'Importing servers…',
      disabled: true,
    });
  });
});

describe('the Discover footer', () => {
  it('holds Back and offers nothing forward while the scan runs', () => {
    const footer = addMcpServerFooterFor(state({ step: 'discover' }));
    expect(footer.back).toEqual({ label: '← Back', disabled: true });
    expect(footer.cancel.label).toBe('Cancel');
    expect(footer.primary).toBeNull();
    expect(footer.keepAnyway).toBeNull();
  });

  it('offers Continue once the scan succeeds', () => {
    const footer = addMcpServerFooterFor(state({ step: 'discover', scanComplete: true, scanSucceeded: true }));
    expect(footer.back).toEqual({ label: '← Back', disabled: false });
    expect(footer.primary).toEqual({ label: 'Continue', disabled: false });
    expect(footer.keepAnyway).toBeNull();
  });

  it('turns a failed scan’s dismiss verb into Discard, with a deliberate way to keep the server', () => {
    const footer = addMcpServerFooterFor(state({ step: 'discover', scanComplete: true, scanSucceeded: false }));
    expect(footer.cancel.label).toBe('Discard');
    expect(footer.keepAnyway).toEqual({ label: 'Add this server anyway', disabled: false });
    expect(footer.primary).toBeNull();
    expect(footer.back).toEqual({ label: '← Back', disabled: false });
  });
});

describe('the Done footer', () => {
  it('closes with Done, Close or Back', () => {
    expect(addMcpServerFooterFor(state({ step: 'done' }))).toEqual({
      back: { label: '← Back', disabled: false },
      cancel: { label: 'Close', disabled: false },
      primary: { label: 'Done', disabled: false },
      keepAnyway: null,
    });
  });
});
