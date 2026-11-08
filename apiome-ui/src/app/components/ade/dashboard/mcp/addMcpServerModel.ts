/**
 * The Add MCP server dialog's steps and footer — pure, so the whole table is unit-tested.
 *
 * Adding an MCP server used to borrow the Import specification wizard, which carried that
 * wizard's stepper (Source → Analyze → Preview → Import → Done), its tab row of every spec source
 * and its *Recent import jobs* drawer — none of which apply to an MCP server. The dialog now has
 * its own three stops, **Connect → Discover → Done**, and reuses only the wizard's frame
 * (`ImportWizardChrome`). A registry import goes straight from Connect to Done: its first sync
 * runs while **Import servers →** is pressed.
 */

import type { ImportFooter } from '../../import/importWizardModel';

/** Where the dialog is. */
export type AddMcpServerStep = 'connect' | 'discover' | 'done';

/** The stepper's stops, in order. */
export const ADD_MCP_SERVER_STEPS: ReadonlyArray<{ id: AddMcpServerStep; label: string }> = [
  { id: 'connect', label: 'Connect' },
  { id: 'discover', label: 'Discover' },
  { id: 'done', label: 'Done' },
];

/** The dialog's fixed copy. */
export const ADD_MCP_SERVER_COPY = {
  title: 'Add an MCP server',
  description:
    'Connect to a Model Context Protocol server. Apiome discovers its tools, resources and prompts, lints and grades them, and catalogs the server as version 1.',
  stepsLabel: 'Add MCP server progress',
} as const;

/** What the dialog needs to know to choose its footer. */
export interface AddMcpServerFooterState {
  step: AddMcpServerStep;
  /** The form validates. */
  ready: boolean;
  /** Registration (or the registry's first sync) is in flight. */
  submitting: boolean;
  /** The form imports a whole registry rather than one server. */
  registry: boolean;
  /** The discovery scan reached a terminal state. */
  scanComplete: boolean;
  /** That terminal state was a success. */
  scanSucceeded: boolean;
}

/**
 * The footer for a state.
 *
 * - **Connect:** *Cancel*, and *Discover →* (*Import servers →* for a registry) once the form
 *   validates; both read as in progress while the request runs.
 * - **Discover:** Back is disabled while the scan runs. A failed scan offers *Discard* (which
 *   deletes the server) and *Add this server anyway*; a successful one offers *Continue*.
 * - **Done:** *← Back*, *Close* and *Done*.
 *
 * @param state See {@link AddMcpServerFooterState}.
 * @returns The four footer slots; `null` for a slot the step does not fill.
 */
export function addMcpServerFooterFor(state: AddMcpServerFooterState): ImportFooter {
  const { step, ready, submitting, registry, scanComplete, scanSucceeded } = state;

  if (step === 'connect') {
    const idle = registry ? 'Import servers →' : 'Discover →';
    const busy = registry ? 'Importing servers…' : 'Starting…';
    return {
      back: null,
      cancel: { label: 'Cancel', disabled: false },
      primary: { label: submitting ? busy : idle, disabled: submitting || !ready },
      keepAnyway: null,
    };
  }

  if (step === 'discover') {
    if (scanComplete && !scanSucceeded) {
      return {
        back: { label: '← Back', disabled: false },
        cancel: { label: 'Discard', disabled: false },
        primary: null,
        keepAnyway: { label: 'Add this server anyway', disabled: false },
      };
    }
    return {
      back: { label: '← Back', disabled: !scanComplete },
      cancel: { label: 'Cancel', disabled: false },
      primary: scanComplete ? { label: 'Continue', disabled: false } : null,
      keepAnyway: null,
    };
  }

  return {
    back: { label: '← Back', disabled: false },
    cancel: { label: 'Close', disabled: false },
    primary: { label: 'Done', disabled: false },
    keepAnyway: null,
  };
}
