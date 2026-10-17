'use client';

/**
 * "How the catalog works" (HIVE-11.6, #5602).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 1 and its `#about-catalog`
 * overlay. The Catalog used to open with two standing blocks — the non-publishable banner and
 * the Supported import formats card — that together cost ≈ 145 px on every visit. Both now
 * live here, one click away, so nothing they said is lost:
 *
 * - the explainer's **three points** (stored as-is · not publishable until converted ·
 *   OpenAPI and Swagger go to Projects);
 * - the **supported-formats list**: the formats this deployment can import, as the same
 *   identity-hued pills the list uses, the first {@link CATALOG_ABOUT_PILL_LIMIT} drawn and the
 *   rest counted as "+n more", and a link to the Supported formats guide for the full table.
 *
 * Opened from three places — the page header's ghost link, the first-visit callout's
 * **Learn more**, and the Import wizard's step 1 ("Which formats can I import?") — none of
 * which is a Radix `Dialog.Trigger`, so the element focused when it opened is remembered and
 * focused again when it closes (the same rule `ui/ModalFrame` follows).
 *
 * ### Which formats count as importable
 *
 * The server registry decides (FMT-1.2, #5413): a format is importable when
 * `GET /api/import/sources` reports its adapter, with the local registry's `importable` flag
 * as the fallback while the read is in flight or if it fails. A registered adapter whose
 * toolchain is missing in this runtime (gRPC without `buf`) is **not** counted as importable
 * here and is named as unavailable instead. The registry is read only while the dialog is open.
 */

import * as React from 'react';
import Link from 'next/link';
import { BookOpen, FileInput, FolderKanban, Library, Route } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormatPill } from '@/app/components/ui/catalog/FormatPill';
import { partitionCatalogFormats } from '@/app/utils/catalog-format-support';
import { catalogAdapterForFormat } from '@/app/utils/catalog-import-formats';
import { buildDocsHref } from '@/app/utils/docsLinks';
import type { CatalogFormat } from '@/app/utils/catalog-format-registry';

import { useCatalogImportAvailability } from '../dashboard/catalog/useCatalogImportAvailability';

/** How many format pills the dialog draws before counting the rest as "+n more". */
export const CATALOG_ABOUT_PILL_LIMIT = 11;

/** The Supported formats guide on the docs site — the full table, with a page per format. */
export const SUPPORTED_FORMATS_GUIDE_HREF = buildDocsHref(
  'apiome-docs/docs/bring-in/supported-formats.md'
);

/** The counts the formats heading states. */
export interface CatalogFormatCounts {
  /** Formats this deployment can import right now. */
  importable: number;
  /** Formats whose adapter is registered but cannot run in this runtime. */
  unavailable: number;
  /** Formats the registry recognises but has no adapter for yet. */
  recognized: number;
}

/**
 * The line beside the formats heading: `44 importable · 1 unavailable here · 4 recognized`.
 *
 * A zero is left out rather than printed, except for the importable count, which is the
 * answer to the question the heading asks.
 *
 * @param counts See {@link CatalogFormatCounts}.
 * @returns The sentence.
 */
export function catalogFormatCountsLine(counts: CatalogFormatCounts): string {
  const parts = [`${counts.importable} importable`];
  if (counts.unavailable > 0) parts.push(`${counts.unavailable} unavailable here`);
  if (counts.recognized > 0) parts.push(`${counts.recognized} recognized`);
  return parts.join(' · ');
}

/** One of the explainer's three points. */
interface AboutPoint {
  /** React key and test hook. */
  id: string;
  /** The leading glyph. */
  icon: React.ReactNode;
  /** The glyph tile's tint — a modifier of `.cat-about__glyph`. */
  tone: 'accent' | 'ok' | 'neutral';
  /** The point, in one line. */
  title: string;
  /** The sentence under it. */
  body: React.ReactNode;
}

/** The three points of the explainer, in the mockup's order. */
const ABOUT_POINTS: readonly AboutPoint[] = [
  {
    id: 'stored',
    icon: <FileInput aria-hidden />,
    tone: 'accent',
    title: 'Catalog items are stored as-is',
    body: (
      <>
        gRPC, GraphQL, AsyncAPI, OData, WSDL, Avro, RAML, Smithy, TypeSpec, API Blueprint and
        many more are kept in their original format, versioned, diffed and linted like Projects.
      </>
    ),
  },
  {
    id: 'convert',
    icon: <Route aria-hidden />,
    tone: 'ok',
    title: 'They are not publishable until converted',
    body: (
      <>
        The one path to a publishable spec is <strong>Convert to OpenAPI</strong>, with a fidelity
        preview before you commit.
      </>
    ),
  },
  {
    id: 'projects',
    icon: <FolderKanban aria-hidden />,
    tone: 'neutral',
    title: 'OpenAPI and Swagger go to Projects',
    body: (
      <>
        Importing one of those never creates a catalog item — it lands in{' '}
        <Link href="/ade/dashboard/projects" className="cat-note__link">
          Projects
        </Link>{' '}
        directly.
      </>
    ),
  },
];

/** Props for {@link CatalogAboutDialog}. */
export interface CatalogAboutDialogProps {
  /** Whether the dialog is shown. */
  open: boolean;
  /** Reports a request to open or close it (Escape, the scrim, the close buttons). */
  onOpenChange: (open: boolean) => void;
}

/**
 * Render the dialog.
 *
 * @param props See {@link CatalogAboutDialogProps}.
 * @returns The dialog (nothing is in the DOM while it is closed).
 */
export function CatalogAboutDialog({ open, onOpenChange }: CatalogAboutDialogProps) {
  const availability = useCatalogImportAvailability(open);
  const { importable: registered, recognized } = React.useMemo(
    () => partitionCatalogFormats(availability.registeredKeys),
    [availability.registeredKeys]
  );

  /** Whether a registered format's adapter can run in this deployment. */
  const runnable = React.useCallback(
    (fmt: CatalogFormat) => {
      const adapter = catalogAdapterForFormat(fmt.id);
      return !adapter || availability.isAvailable(adapter.sourceKind);
    },
    [availability]
  );

  const importable = React.useMemo(() => registered.filter(runnable), [registered, runnable]);
  const shown = importable.slice(0, CATALOG_ABOUT_PILL_LIMIT);
  const more = importable.length - shown.length;
  const counts = catalogFormatCountsLine({
    importable: importable.length,
    unavailable: registered.length - importable.length,
    recognized: recognized.length,
  });

  // Radix returns focus only to a `Dialog.Trigger`; this opens from plain buttons.
  const returnFocusTo = React.useRef<HTMLElement | null>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="cat-about"
        data-testid="catalog-about-dialog"
        onOpenAutoFocus={() => {
          // Runs before Radix moves focus in, so this is still the element that opened it.
          const active = document.activeElement;
          returnFocusTo.current = active instanceof HTMLElement ? active : null;
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const target = returnFocusTo.current;
          returnFocusTo.current = null;
          if (target?.isConnected) target.focus();
        }}
      >
        <div className="cat-about__head">
          <span className="cat-about__glyph cat-about__glyph--accent" aria-hidden>
            <Library />
          </span>
          <div className="cat-about__heading">
            <DialogTitle>How the catalog works</DialogTitle>
            <DialogDescription>
              Where catalog items come from, and how one becomes publishable.
            </DialogDescription>
          </div>
        </div>

        <ul className="cat-about__points">
          {ABOUT_POINTS.map((point) => (
            <li key={point.id} className="cat-about__point" data-testid={`catalog-about-${point.id}`}>
              <span
                className={`cat-about__glyph cat-about__glyph--sm cat-about__glyph--${point.tone}`}
                aria-hidden
              >
                {point.icon}
              </span>
              <div className="cat-about__point-text">
                <p className="cat-about__point-title">{point.title}</p>
                <p className="cat-about__point-body">{point.body}</p>
              </div>
            </li>
          ))}
        </ul>

        <section className="cat-about__formats" aria-labelledby="catalog-about-formats-heading">
          <div className="cat-about__formats-head">
            <h3 id="catalog-about-formats-heading" className="cat-about__caps">
              Supported import formats
            </h3>
            <span className="cat-about__counts" data-testid="catalog-about-counts">
              {counts}
            </span>
          </div>
          <div className="cat-about__pills" data-testid="catalog-about-formats">
            {shown.map((fmt) => (
              <FormatPill key={fmt.id} format={fmt.id} />
            ))}
            {more > 0 ? (
              <span className="cat-about__more" data-testid="catalog-about-more">
                +{more} more
              </span>
            ) : null}
          </div>
        </section>

        <DialogFooter>
          <Button variant="ghost" asChild>
            <a href={SUPPORTED_FORMATS_GUIDE_HREF} target="_blank" rel="noopener noreferrer">
              <BookOpen aria-hidden />
              Supported formats guide
              <span className="sr-only"> (opens in new tab)</span>
            </a>
          </Button>
          <DialogClose asChild>
            <Button>Got it</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default CatalogAboutDialog;
