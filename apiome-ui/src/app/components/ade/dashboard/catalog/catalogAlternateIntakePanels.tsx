/**
 * The catalog importer's alternate intake panels, by capability kind (MFI-26.5, #4098).
 *
 * A format that can be brought in some other way than File / URL / Clipboard — a live
 * introspection, a reflection crawl, a registry — declares an `alternate_intake` on
 * `GET /v1/import/sources`. The wizard draws its source card from that record
 * (`alternateIntakeTiles`) only when this registry has a panel for the record's `kind`, so a server
 * can never surface a card that leads nowhere.
 *
 * The registry is keyed by **capability**, not by format: one `introspection` panel would serve
 * every format that declares that kind. It is empty today because no format declares an alternate
 * intake yet — the import pipeline does not run any adapter's live discovery. Adding one is:
 *
 *   1. the server sets `ImportSource.alternate_intake` once its pipeline runs that intake;
 *   2. a panel component for the kind is registered here.
 *
 * No change to the dialog itself is needed.
 */

import type { ComponentType } from 'react';
import type { ImportSourceDescriptor } from '../importSourceCatalog';

/** What the wizard hands an alternate intake panel. */
export interface CatalogAlternateIntakePanelProps {
  /** The registry descriptor of the format whose card was chosen. */
  source: ImportSourceDescriptor;
}

/** Capability kind → the panel that runs it. Empty until a format declares an alternate intake. */
export const CATALOG_ALTERNATE_INTAKE_PANELS: Readonly<
  Record<string, ComponentType<CatalogAlternateIntakePanelProps>>
> = {};

/** The capability kinds a panel is registered for — what `alternateIntakeTiles` gates on. */
export const CATALOG_ALTERNATE_INTAKE_KINDS: ReadonlySet<string> = new Set(
  Object.keys(CATALOG_ALTERNATE_INTAKE_PANELS),
);
