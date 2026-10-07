'use client';

/**
 * The supporting primitives — the rest of `components/ui` (HIVE-10.5, #5341).
 *
 * `HiveGallery` follows the sections of `docs/mockups/foundations/design-system.html`, and the
 * mockup does not draw every component the app ships: the catalog pills, the stepper, the
 * disclosure, the markdown renderer, the legacy modal frame, toasts, the table and grid
 * skeletons, and the live region. They are here so the `/design-system` route shows every
 * primitive, which `tests/design-system-gallery.test.ts` enforces.
 */

import * as React from 'react';
import { ChevronDown } from 'lucide-react';

import {
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Input,
  Label,
  LiveRegion,
  SkeletonCardGrid,
  SkeletonTableRows,
  Stepper,
} from '@/app/components/ui';
import { FormatTraitPills } from '@/app/components/ui/catalog/FormatTraitPills';
import { ProtocolPill } from '@/app/components/ui/catalog/ProtocolPill';
import { SourceBadge } from '@/app/components/ui/catalog/SourceBadge';
import { Markdown } from '@/app/components/ui/Markdown';
import { ModalFrame, ModalFrameClose, ModalFrameTitle } from '@/app/components/ui/ModalFrame';
import { toast } from '@/app/components/ui/toast';
import {
  resolveCatalogFormat,
  type CatalogFormat,
  type CatalogSourceKind,
} from '@/app/utils/catalog-format-registry';

import { Demo, Section, SpecimenLabel } from './GallerySection';

/** One protocol per registry hue, plus an unknown one to show the neutral fallback. */
const GALLERY_PROTOCOLS: readonly string[] = [
  'rest',
  'rpc',
  'event',
  'graph',
  'dataschema',
  'agent',
  'soap',
];

/** Every source kind, with the label a real catalog item would carry. */
const GALLERY_SOURCES: readonly { kind: CatalogSourceKind; label: string | null }[] = [
  { kind: 'file', label: 'payments-api.yaml' },
  { kind: 'url', label: 'api.example.com' },
  { kind: 'paste', label: null },
  { kind: 'discovery', label: null },
];

/** Formats whose traits differ, so every data-type / origin pairing shape is visible. */
const GALLERY_TRAIT_FORMATS: readonly CatalogFormat[] = ['openapi', 'grpc', 'protobuf', 'thrift']
  .map((id) => resolveCatalogFormat(id))
  .filter((format): format is CatalogFormat => format !== undefined);

/** The steps of the first-tenant wizard, the stepper's first production use. */
const GALLERY_STEPS = [
  { id: 'workspace', label: 'Workspace' },
  { id: 'members', label: 'Members' },
  { id: 'project', label: 'First project' },
  { id: 'done', label: 'Done' },
] as const;

/** A short document that exercises the markdown renderer's headings, lists, code and table. */
const GALLERY_MARKDOWN = [
  '### Breaking changes',
  '',
  'Two operations changed shape since **v2.3.0**:',
  '',
  '- `GET /payments/{id}` drops the `legacy_ref` field.',
  '- `POST /refunds` now requires `reason`.',
  '',
  '| Operation | Change |',
  '| --- | --- |',
  '| `GET /payments/{id}` | Field removed |',
  '| `POST /refunds` | Field required |',
].join('\n');

/** The messages the live-region specimen cycles through. */
const LIVE_MESSAGES: readonly string[] = ['Saving…', 'Saved', 'Import running: step 3 of 8'];

/**
 * The supporting primitives, one titled section each.
 *
 * @returns The sections.
 */
export function SupportingGallery() {
  const [modalOpen, setModalOpen] = React.useState(false);
  const [liveIndex, setLiveIndex] = React.useState<number | null>(null);
  const liveMessage = liveIndex === null ? null : LIVE_MESSAGES[liveIndex];

  return (
    <div className="flex flex-col gap-6">
      <Section
        id="catalog-pills"
        title="Catalog pills"
        description="Protocol, source and format-trait pills from the catalog list and detail."
      >
        <SpecimenLabel>Protocol — registry hues, then an unknown protocol</SpecimenLabel>
        <Demo>
          {GALLERY_PROTOCOLS.map((protocol) => (
            <ProtocolPill key={protocol} protocol={protocol} />
          ))}
        </Demo>
        <SpecimenLabel>Source — one per input kind</SpecimenLabel>
        <Demo>
          {GALLERY_SOURCES.map((source) => (
            <SourceBadge key={source.kind} kind={source.kind} label={source.label} />
          ))}
        </Demo>
        <SpecimenLabel>Format traits — data type, then typical source</SpecimenLabel>
        <Demo>
          {GALLERY_TRAIT_FORMATS.map((format) => (
            <FormatTraitPills key={format.id} format={format} />
          ))}
        </Demo>
      </Section>

      <Section
        id="structure"
        title="Labels, steps & disclosure"
        description="A field label, the wizard stepper, and a collapsible section."
      >
        <Demo className="!flex-col !items-start">
          <Label htmlFor="ds-label-specimen">Project name</Label>
          <Input id="ds-label-specimen" placeholder="e.g. Payments API" />
        </Demo>
        <SpecimenLabel>Stepper — in progress, filled, complete</SpecimenLabel>
        <Demo className="!flex-col !items-stretch gap-4">
          <Stepper aria-label="Setup progress" steps={GALLERY_STEPS} current="members" />
          <Stepper aria-label="Setup progress, filled" steps={GALLERY_STEPS} current="project" fill />
          <Stepper aria-label="Setup complete" steps={GALLERY_STEPS} complete />
        </Demo>
        <SpecimenLabel>Collapsible</SpecimenLabel>
        <Demo className="!flex-col !items-start">
          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm">
                <ChevronDown aria-hidden />
                Advanced options
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2 text-sm text-fg-muted">
              Mock latency, response seeds and the export target live here.
            </CollapsibleContent>
          </Collapsible>
        </Demo>
      </Section>

      <Section
        id="markdown"
        title="Markdown"
        description="The shared markdown renderer, in its compact variant and with its fallback."
      >
        <Demo className="!block">
          <Markdown variant="compact">{GALLERY_MARKDOWN}</Markdown>
        </Demo>
        <Demo>
          <Markdown fallback={<span className="text-sm text-fg-muted">No release notes yet.</span>}>
            {''}
          </Markdown>
        </Demo>
      </Section>

      <Section
        id="modals-toasts"
        title="Legacy modal & toasts"
        description="The accessible frame for pre-Hive modals, and the four toast tones."
      >
        <Demo>
          <Button variant="outline" onClick={() => setModalOpen(true)}>
            Open legacy modal
          </Button>
          <ModalFrame
            open={modalOpen}
            onClose={() => setModalOpen(false)}
            overlayClassName="hive-overlay fixed inset-0 z-[9998] flex items-center justify-center bg-overlay p-4"
            className="flex w-full max-w-md flex-col gap-3 rounded-lg bg-surface p-6 shadow-lg"
          >
            <ModalFrameTitle className="text-lg font-semibold text-fg">Legacy modal</ModalFrameTitle>
            <p className="text-sm text-fg-muted">
              Focus is trapped here and returns to the button when this closes.
            </p>
            <ModalFrameClose asChild>
              <Button variant="primary" className="self-end">
                Close
              </Button>
            </ModalFrameClose>
          </ModalFrame>
        </Demo>
        <SpecimenLabel>Toasts — raised through the app toast</SpecimenLabel>
        <Demo>
          <Button variant="outline" onClick={() => toast.success('Version published')}>
            Success toast
          </Button>
          <Button variant="outline" onClick={() => toast.error('Could not publish the version')}>
            Error toast
          </Button>
          <Button variant="outline" onClick={() => toast.warning('Mock quota at 90%')}>
            Warning toast
          </Button>
          <Button variant="outline" onClick={() => toast.info('Import queued')}>
            Info toast
          </Button>
        </Demo>
      </Section>

      <Section
        id="loading-shapes"
        title="Loading shapes"
        description="The card-grid and table-row skeletons, sized like the content they replace."
      >
        <Demo className="!block">
          <SkeletonCardGrid count={3} />
        </Demo>
        <Demo className="!block">
          <table className="w-full text-sm">
            <caption className="sr-only">Loading table rows</caption>
            <SkeletonTableRows rows={3} columns={['40%', '6rem', '20%', '4rem']} cellClassName="px-4 py-3" />
          </table>
        </Demo>
      </Section>

      <Section
        id="live-region"
        title="Live region"
        description="The hidden announcer for save state and async jobs. Its message is echoed here."
      >
        <Demo>
          <Button
            variant="outline"
            onClick={() =>
              setLiveIndex((index) => (index === null ? 0 : (index + 1) % LIVE_MESSAGES.length))
            }
          >
            Announce next status
          </Button>
          <span className="text-sm text-fg-muted" data-testid="live-region-echo">
            {liveMessage ?? 'Silent'}
          </span>
          <LiveRegion message={liveMessage} data-testid="live-region-specimen" />
        </Demo>
      </Section>
    </div>
  );
}
