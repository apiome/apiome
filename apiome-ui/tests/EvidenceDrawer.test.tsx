/**
 * EvidenceDrawer — the export evidence drawer (EFP-2.3, #4815).
 *
 * Covers the ticket's acceptance criteria at the component level:
 *  1. A non-preserved outcome shows its cause category, distinction line, reason code,
 *     reviewed explanation, and the emitter's outcome text.
 *  2. The five cause categories render distinguishable labels.
 *  3. The destination documentation link is version-disclosing, accessibly named, and opens
 *     safely (new tab, noopener); an unsafe link renders the truthful fallback note instead.
 *  4. Safe remediation: a format limit offers "Choose a different target", an option
 *     exclusion offers "Change export options" — each only when the surface wired the
 *     callback — and callbacks fire on click.
 *  5. Registry remediation guidance and manifest provenance (emitter/registry versions)
 *     render when available; the drawer degrades gracefully without them.
 *  6. Source-native `[redacted]` placeholders pass through untouched.
 */

import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { EvidenceDrawer } from '../src/app/components/ade/dashboard/export/EvidenceDrawer';
import type {
  ProjectionReasonCode,
  ReasonExplanation,
} from '../src/app/components/ade/dashboard/export/capabilityRegistry';
import type { ProjectionManifestSummary } from '../src/app/components/ade/dashboard/export/exportFidelityPreview';
import type {
  ProjectionEvidenceRow,
  ProjectionViewEntry,
} from '../src/app/components/ade/dashboard/export/projectionGraph';
import type { ProjectionEdge } from '../src/app/components/ade/dashboard/export/projectionEvidence';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SUMMARY: ProjectionManifestSummary = {
  manifest_hash: 'hash-aaaaaaaaaaaaaaaa',
  target: {
    key: 'openapi',
    emitter_version: '1.4.0',
    registry_version: '2025.07.01',
    apiome_version: '1.9.0',
  },
  status_counts: { dropped: 1 },
  reason_counts: { destination_unsupported: 1 },
  total_constructs: 1,
  node_count: 2,
  edge_count: 1,
  evidence_count: 1,
  is_lossless: false,
  worst_severity: 'critical',
  truncated: false,
};

const REASONS: ReadonlyMap<ProjectionReasonCode, ReasonExplanation> = new Map<
  ProjectionReasonCode,
  ReasonExplanation
>([
  [
    'destination_unsupported',
    {
      reason: 'destination_unsupported',
      category_label: 'Destination limit',
      summary_template: 'The destination format cannot represent {construct}.',
      remediation: 'Choose a destination format that supports this construct, or accept the loss.',
      destination_documentation_applies: true,
    },
  ],
  [
    'option_excluded',
    {
      reason: 'option_excluded',
      category_label: 'Option exclusion',
      summary_template: 'An export option excluded {construct}.',
      remediation: 'Change the export option and preview again to include it.',
      destination_documentation_applies: false,
    },
  ],
]);

/** Build a row entry around one outcome edge, mirroring `buildEvidenceRows` output. */
function rowEntry(
  edge: Partial<ProjectionEdge> = {},
  row: Partial<ProjectionEvidenceRow> = {},
): ProjectionViewEntry {
  const fullEdge: ProjectionEdge = {
    id: 'e1',
    relation: 'projects',
    source: 'c1',
    target: null,
    status: 'dropped',
    severity: 'critical',
    reason: 'destination_unsupported',
    detail: 'Subscriptions cannot be represented.',
    explanation: 'The destination format cannot represent Sub.onUserCreated.',
    documentation: {
      specification: 'OpenAPI Specification',
      version: '3.1',
      url: 'https://spec.openapis.org/oas/v3.1.0',
      anchor: null,
      documentation_unavailable: false,
      note: null,
    },
    ...edge,
  };
  const fullRow: ProjectionEvidenceRow = {
    id: fullEdge.id,
    construct: 'Sub.onUserCreated',
    constructKey: 'Sub.onUserCreated',
    canonicalKind: 'operation',
    status: fullEdge.status,
    severity: fullEdge.severity,
    reason: fullEdge.reason ?? null,
    reasonSummary: 'The destination format cannot represent Sub.onUserCreated.',
    targetLabel: null,
    targetLocation: null,
    sourceLabel: 'onUserCreated',
    sourceLocation: 'schema.graphql:40',
    edge: fullEdge,
    ...row,
  };
  return {
    key: fullRow.id,
    kind: 'row',
    status: fullRow.status,
    severity: fullRow.severity,
    lane: 'omitted',
    label: fullRow.construct,
    row: fullRow,
  };
}

function renderDrawer(
  entry: ProjectionViewEntry,
  props: Partial<React.ComponentProps<typeof EvidenceDrawer>> = {},
) {
  return render(
    <EvidenceDrawer
      entry={entry}
      summary={SUMMARY}
      reasons={REASONS}
      onClose={jest.fn()}
      {...props}
    />,
  );
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1/2. Cause category + explanation + outcome text
// ---------------------------------------------------------------------------

describe('EvidenceDrawer — cause category and explanations (EFP-2.3 AC 1–2)', () => {
  it('shows the category chip, distinction, reason code, explanation, and outcome text', () => {
    renderDrawer(rowEntry());

    expect(screen.getByTestId('projection-detail-category')).toHaveTextContent('Format limit');
    expect(screen.getByTestId('projection-detail-distinction')).toHaveTextContent(
      /destination format cannot represent/i,
    );
    const detail = screen.getByTestId('projection-detail');
    expect(detail).toHaveTextContent('destination_unsupported');
    expect(detail).toHaveTextContent('The destination format cannot represent Sub.onUserCreated.');
    // The emitter's outcome text is distinct evidence and shows alongside the explanation.
    expect(screen.getByTestId('projection-detail-outcome')).toHaveTextContent(
      'Subscriptions cannot be represented.',
    );
    expect(detail).toHaveTextContent('Dropped');
    expect(detail).toHaveTextContent('critical');
  });

  it('does not repeat the outcome text when it matches the explanation', () => {
    renderDrawer(rowEntry({ detail: 'Same sentence.', explanation: 'Same sentence.' }));
    expect(screen.queryByTestId('projection-detail-outcome')).not.toBeInTheDocument();
  });

  it.each([
    ['destination_unsupported', 'Format limit'],
    ['emitter_unsupported', 'Emitter gap'],
    ['target_tool_unavailable', 'Emitter gap'],
    ['source_incomplete', 'Source incomplete'],
    ['source_parse_limit', 'Source incomplete'],
    ['option_excluded', 'Excluded by option'],
    ['security_redacted', 'Redacted'],
  ])('labels a %s outcome with the %s category', (reason, label) => {
    renderDrawer(rowEntry({ reason, documentation: null }));
    expect(screen.getByTestId('projection-detail-category')).toHaveTextContent(label);
  });

  it('shows no category chip for an unknown reason code (never guesses)', () => {
    renderDrawer(rowEntry({ reason: 'made_up_reason', documentation: null }));
    expect(screen.queryByTestId('projection-detail-category')).not.toBeInTheDocument();
    expect(screen.queryByTestId('projection-detail-distinction')).not.toBeInTheDocument();
  });

  it('shows source and destination locations, passing a [redacted] placeholder through', () => {
    renderDrawer(
      rowEntry(
        {},
        { sourceLabel: '[redacted]', sourceLocation: '[redacted]', targetLocation: '/paths/~1pets' },
      ),
    );
    const detail = screen.getByTestId('projection-detail');
    expect(detail).toHaveTextContent('In the destination: /paths/~1pets');
    expect(detail).toHaveTextContent('[redacted]');
  });
});

// ---------------------------------------------------------------------------
// 3. Documentation link safety + accessibility
// ---------------------------------------------------------------------------

describe('EvidenceDrawer — destination documentation link (EFP-2.3 AC 3)', () => {
  it('renders a version-disclosing, accessibly named link that opens safely in a new tab', () => {
    renderDrawer(rowEntry());

    const link = screen.getByTestId('projection-detail-doc');
    expect(link).toHaveTextContent('OpenAPI Specification (3.1)');
    expect(link).toHaveAttribute('href', 'https://spec.openapis.org/oas/v3.1.0');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link.getAttribute('aria-label')).toMatch(/spec\.openapis\.org.*opens in a new tab/i);
  });

  it('withholds an off-allowlist link and renders the truthful fallback note instead', () => {
    renderDrawer(
      rowEntry({
        documentation: {
          specification: 'Evil Spec',
          version: '1.0',
          url: 'https://evil.example.com/spec',
          anchor: null,
          documentation_unavailable: false,
          note: null,
        },
      }),
    );
    expect(screen.queryByTestId('projection-detail-doc')).not.toBeInTheDocument();
    expect(screen.getByTestId('projection-detail-doc-note')).toHaveTextContent(
      /failed the host allowlist and was withheld/i,
    );
  });

  it('renders the documentation-unavailable note without inventing a link', () => {
    renderDrawer(
      rowEntry({
        documentation: {
          specification: null,
          version: null,
          url: null,
          anchor: null,
          documentation_unavailable: true,
          note: 'No stable public specification exists for this destination.',
        },
      }),
    );
    expect(screen.queryByTestId('projection-detail-doc')).not.toBeInTheDocument();
    expect(screen.getByTestId('projection-detail-doc-note')).toHaveTextContent(
      'No stable public specification exists for this destination.',
    );
  });
});

// ---------------------------------------------------------------------------
// 4/5. Remediation + provenance
// ---------------------------------------------------------------------------

describe('EvidenceDrawer — safe remediation and provenance (EFP-2.3 AC 4)', () => {
  it('offers the target change for a format limit and fires the callback', () => {
    const onChangeTarget = jest.fn();
    renderDrawer(rowEntry(), { onChangeTarget });

    const remediation = screen.getByTestId('projection-detail-remediation');
    expect(remediation).toHaveTextContent(
      'Choose a destination format that supports this construct, or accept the loss.',
    );
    fireEvent.click(within(remediation).getByTestId('projection-detail-action-change-target'));
    expect(onChangeTarget).toHaveBeenCalledTimes(1);
  });

  it('offers the options change for an option exclusion and fires the callback', () => {
    const onChangeOptions = jest.fn();
    renderDrawer(
      rowEntry({ reason: 'option_excluded', severity: 'info', documentation: null }),
      { onChangeOptions },
    );
    fireEvent.click(screen.getByTestId('projection-detail-action-change-options'));
    expect(onChangeOptions).toHaveBeenCalledTimes(1);
  });

  it('offers no action button when the surface wired no callback', () => {
    renderDrawer(rowEntry());
    expect(screen.queryByTestId('projection-detail-action-change-target')).not.toBeInTheDocument();
    // The reviewed registry guidance still shows — remediation text is not gated on actions.
    expect(screen.getByTestId('projection-detail-remediation')).toBeInTheDocument();
  });

  it('offers no action for causes fixed outside this export', () => {
    renderDrawer(rowEntry({ reason: 'source_incomplete', documentation: null }), {
      onChangeTarget: jest.fn(),
      onChangeOptions: jest.fn(),
    });
    expect(screen.queryByTestId('projection-detail-action-change-target')).not.toBeInTheDocument();
    expect(screen.queryByTestId('projection-detail-action-change-options')).not.toBeInTheDocument();
  });

  it('prints the emitter/registry/apiome version provenance from the manifest summary', () => {
    renderDrawer(rowEntry());
    expect(screen.getByTestId('projection-detail-provenance')).toHaveTextContent(
      'Evidence produced by emitter v1.4.0 · registry v2025.07.01 · apiome v1.9.0.',
    );
  });

  it('degrades gracefully without a summary or registry data', () => {
    renderDrawer(rowEntry(), { summary: null, reasons: new Map() });
    expect(screen.queryByTestId('projection-detail-provenance')).not.toBeInTheDocument();
    // The category, explanation, and documentation still render from the edge itself.
    expect(screen.getByTestId('projection-detail-category')).toHaveTextContent('Format limit');
    expect(screen.getByTestId('projection-detail-doc')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Aggregate + close
// ---------------------------------------------------------------------------

describe('EvidenceDrawer — aggregate entries and closing', () => {
  it('explains an aggregate entry instead of row evidence', () => {
    const entry: ProjectionViewEntry = {
      key: 'aggregate:retained',
      kind: 'aggregate',
      status: 'retained',
      severity: 'info',
      lane: 'target',
      label: '60 constructs',
      members: [],
    };
    renderDrawer(entry);
    expect(screen.getByTestId('projection-detail')).toHaveTextContent(/aggregated for readability/i);
    expect(screen.queryByTestId('projection-detail-category')).not.toBeInTheDocument();
  });

  it('fires onClose from the close button', () => {
    const onClose = jest.fn();
    renderDrawer(rowEntry(), { onClose });
    fireEvent.click(screen.getByTestId('projection-detail-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
