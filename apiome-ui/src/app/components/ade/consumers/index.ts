/**
 * The consumer contract registry's components and model — CTG-4.1 (#4479).
 *
 * One import site for the Consumers screen, matching the other `components/ade/*` barrels.
 */

export { default as ConsumersTable } from './ConsumersTable';
export type { ConsumersTableProps } from './ConsumersTable';

export {
  default as ConsumerFormDialog,
  EMPTY_CONSUMER_DRAFT,
  draftFromConsumer,
} from './ConsumerFormDialog';
export type {
  ConsumerDraft,
  ConsumerFormDialogProps,
  ConsumerFormMode,
} from './ConsumerFormDialog';

export { default as PactImportDialog } from './PactImportDialog';
export type { PactImportDialogProps, PactImportOutcome } from './PactImportDialog';

export { default as SurfacePickerDialog } from './SurfacePickerDialog';
export type { SurfacePickerDialogProps } from './SurfacePickerDialog';

export { default as ConsumerSurfaceDrawer } from './ConsumerSurfaceDrawer';
export type { ConsumerSurfaceDrawerProps } from './ConsumerSurfaceDrawer';

export * from './consumersModel';
