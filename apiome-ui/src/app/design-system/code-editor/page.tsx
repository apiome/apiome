'use client';

/**
 * Code editor — live showcase gallery (#6274).
 *
 * A data-free route at `/design-system/code-editor` that renders the real Hive-themed Monaco
 * editor (`useHiveMonacoTheme`, through the Export studio's `ReadOnlyCodeViewer`) over the real
 * stylesheet, with no session and no database behind it.
 *
 * It exists for the accessibility gate. Monaco paints its text in its own colours, which only a
 * browser running axe can measure, and before #6274 no gated page rendered a Hive editor at all —
 * the `/design-system` primitives use the stock `light` / `vs-dark` viewers — so the theme's light
 * keys, strings and line numbers fell under 4.5:1 unseen. `e2e/hive-code-editor-a11y.spec.ts`
 * opens this page in the three gate themes, waits for Monaco to paint, and runs axe over it.
 *
 * The specimens are written to exercise every syntax role the theme names: YAML and JSON keys,
 * strings, numbers, literals, comments and anchors, and enough lines to fill the gutter.
 *
 * Sibling galleries: `/design-system` (the primitives), `/design-system/page-header`.
 */

import * as React from 'react';
import { Badge } from '@/app/components/ui';
import { ReadOnlyCodeViewer } from '@/app/components/ade/dashboard/export/ReadOnlyCodeViewer';
import PreferenceAxes from '../PreferenceAxes';

/** A YAML specimen: comments, keys, strings, numbers, booleans, an anchor and its alias. */
const YAML_SPECIMEN = `# Orders API — a specimen for the Hive editor theme
openapi: 3.1.0
info:
  title: Orders API
  version: "2.4.0"
x-defaults: &defaults
  retries: 3
  timeout: 2.5
  cached: true
paths:
  /orders/{orderId}:
    get:
      operationId: getOrder
      summary: Fetch one order
      x-policy: *defaults
      responses:
        "200":
          description: The order
`;

/** A JSON specimen: property keys, string and number values, literals and nesting. */
const JSON_SPECIMEN = `{
  "$id": "https://example.com/schemas/order.json",
  "type": "object",
  "required": ["id", "total"],
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "total": { "type": "number", "minimum": 0, "multipleOf": 0.01 },
    "paid": { "type": "boolean", "default": false },
    "note": { "type": ["string", "null"] }
  }
}
`;

/** Props for {@link Specimen}. */
interface SpecimenProps {
  /** `data-testid` of the card, which the e2e suite drives. */
  id: string;
  /** What this specimen shows. */
  title: string;
  /** Why it is here. */
  note: string;
  /** The editor. */
  children: React.ReactNode;
}

/**
 * One captioned specimen.
 *
 * @param props See {@link SpecimenProps}.
 * @returns The card.
 */
function Specimen({ id, title, note, children }: SpecimenProps) {
  return (
    <section data-testid={id} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-fg">{title}</h2>
        <p className="max-w-[72ch] text-sm text-fg-muted">{note}</p>
      </div>
      {children}
    </section>
  );
}

/**
 * The code-editor gallery.
 *
 * @returns The page.
 */
export default function CodeEditorGalleryPage() {
  return (
    <main className="mx-auto flex max-w-[75rem] flex-col gap-8 p-[var(--page-pad)]">
      <header className="flex flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-[-0.02em] text-fg">
          Code editor <Badge variant="honey" size="lg">#6274</Badge>
        </h1>
        <p className="max-w-[72ch] text-sm text-fg-muted">
          The Hive Monaco theme on the inset well. Every syntax colour and the line numbers are
          painted in ink that reads at 4.5:1 in every theme — switch the theme below to check.
        </p>
        <PreferenceAxes />
      </header>

      <Specimen
        id="specimen-yaml"
        title="YAML"
        note="Keys in honey ink, strings in green ink, numbers and literals in violet ink, an anchor and its alias, and comments in muted italic."
      >
        <ReadOnlyCodeViewer
          value={YAML_SPECIMEN}
          language="yaml"
          theme="hive"
          height={360}
          documentLabel="YAML specimen"
          editorTestId="hive-editor-yaml"
        />
      </Specimen>

      <Specimen
        id="specimen-json"
        title="JSON"
        note="Property keys, string and number values, and the true / false / null literals."
      >
        <ReadOnlyCodeViewer
          value={JSON_SPECIMEN}
          language="json"
          theme="hive"
          height={260}
          documentLabel="JSON specimen"
          editorTestId="hive-editor-json"
        />
      </Specimen>
    </main>
  );
}
