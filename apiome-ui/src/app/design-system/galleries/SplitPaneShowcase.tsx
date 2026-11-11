'use client';

/**
 * The §Split pane specimen of the gallery (SUX-3.4, apiome#6754).
 *
 * Two layouts: a form beside a preview (the shape Slate's editors use: 360 px, 280–520, the form
 * collapsible) and three panes (tree, canvas, inspector). Each handle drags, and with focus takes
 * ←/→, Shift+←/→, Home, End and — on a collapsible pane — Enter. The two-pane copy persists its
 * width under `apiome:split-pane:design-system-split-pane`, so a reload keeps it. The preview is
 * an `<iframe>` whose counter shows it is never reloaded by a resize. The docs screenshot
 * `design-system-split-pane` is taken of this block.
 */

import * as React from 'react';

import { FormField, Input, SplitPane, type SplitPaneConfig } from '@/app/components/ui';

import { SpecimenLabel } from './GallerySection';

const TWO_PANES: SplitPaneConfig[] = [
  { id: 'form', label: 'Form', defaultSize: 360, minSize: 280, maxSize: 520, collapsible: true },
  { id: 'preview', label: 'Preview' },
];

const THREE_PANES: SplitPaneConfig[] = [
  { id: 'tree', label: 'Structure', defaultSize: 240, minSize: 200, maxSize: 360, collapsible: true },
  { id: 'canvas', label: 'Canvas' },
  { id: 'inspector', label: 'Inspector', defaultSize: 288, minSize: 240, maxSize: 400, collapsible: true },
];

/** A static page for the preview frame: it stamps the time it loaded, so a reload would show. */
const PREVIEW_HTML =
  '<!doctype html><html><body style="font:14px system-ui;margin:16px;color:#333">' +
  '<h1 style="font-size:18px;margin:0 0 8px">Preview</h1>' +
  '<p>Loaded at <span id="t"></span>. Resize the panes: this time does not change.</p>' +
  '<script>document.getElementById("t").textContent=new Date().toLocaleTimeString()</script>' +
  '</body></html>';

/**
 * The split-pane specimen.
 *
 * @returns The two layouts.
 */
export function SplitPaneShowcase() {
  const [title, setTitle] = React.useState('Payments API');
  return (
    <div className="flex flex-col gap-6" data-testid="design-system-split-pane">
      <div className="flex flex-col gap-2">
        <SpecimenLabel>Form beside a preview · width kept after a reload</SpecimenLabel>
        <SplitPane
          aria-label="Form and preview"
          storageKey="design-system-split-pane"
          panes={TWO_PANES}
          className="h-72 overflow-hidden rounded-lg border border-border"
        >
          <div className="flex flex-col gap-4 p-4">
            <FormField label="Site title" htmlFor="ds-split-title">
              <Input id="ds-split-title" value={title} onChange={(event) => setTitle(event.target.value)} />
            </FormField>
            <p className="hive-quiet">Drag the line, or focus it and use the arrow keys.</p>
          </div>
          <iframe
            title="Split pane preview"
            sandbox="allow-scripts"
            srcDoc={PREVIEW_HTML}
            className="block h-full w-full border-0 bg-surface"
          />
        </SplitPane>
      </div>
      <div className="flex flex-col gap-2">
        <SpecimenLabel>Three panes · both sides collapse</SpecimenLabel>
        <SplitPane
          aria-label="Tree, canvas and inspector"
          panes={THREE_PANES}
          className="h-56 overflow-hidden rounded-lg border border-border"
        >
          <div className="p-4 text-sm text-fg-muted">Structure</div>
          <div className="flex h-full items-center justify-center bg-subtle text-sm text-fg-muted">Canvas</div>
          <div className="p-4 text-sm text-fg-muted">Inspector</div>
        </SplitPane>
      </div>
    </div>
  );
}
