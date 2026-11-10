/**
 * Class strings shared by the System settings cards (sign-up policy and sign-in providers), so
 * their fields and buttons stay identical.
 */

/** Shared classes for the card text inputs. */
export const INPUT_CLASSES =
  'w-full rounded-md border border-border-strong bg-surface px-3 py-1.5 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50';

/** Shared classes for secondary (outline) buttons. */
export const SECONDARY_BUTTON_CLASSES =
  'inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-surface px-3 py-1.5 text-sm font-medium text-fg-muted transition-colors hover:bg-subtle disabled:cursor-not-allowed disabled:opacity-50';

/** Shared classes for the primary (save) button. */
export const PRIMARY_BUTTON_CLASSES =
  'inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-fg-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50';

/** Shared classes for the small slate status chip ("Env-derived", "using .env fallback"). */
export const NEUTRAL_CHIP_CLASSES =
  'inline-flex items-center rounded-full border border-border-strong bg-subtle px-2 py-0.5 text-2xs font-medium text-fg-muted';
