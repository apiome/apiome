/**
 * Fixtures for the primitive reference gallery (UXE-1.3).
 *
 * The gallery, the component tests and the Playwright visual-regression spec
 * all read from here. Sharing one fixture set is what makes the acceptance
 * criterion checkable: "light, dark, high-contrast and reduced-motion
 * references pass" means *these* references, rendered identically in each run,
 * rather than three screens that happen to look similar.
 *
 * Values are deterministic — fixed ids, fixed timestamps, no randomness — so a
 * screenshot diff reports a styling change and never a data change.
 */

import type { AuthoringCommandAction } from './actions';
import type { AuthoringAnalyticsSeries } from './analytics';
import type { AuthoringCheck } from './checks';
import type { AuthoringTreeNode } from './content-tree';
import type { AuthoringImpactSheet } from './impact';
import type { AuthoringProgressPhase } from './progress';
import type { AuthoringProposal, AuthoringProposalStatus } from './proposals';

/** A grounded, pending proposal with a valid example. */
export const REFERENCE_PROPOSAL: AuthoringProposal = {
  id: 'prop-1',
  title: 'Description for GET /pets/{petId}',
  body: 'Returns a single pet by its identifier. Responds 404 when no pet matches.',
  status: 'pending',
  provenance: {
    model: 'claude-opus-4-8',
    policy: 'Grounded-only',
    generatedAt: '2026-07-19T14:02:00Z',
  },
  currentBody: 'Gets a pet.',
  exampleValidation: { status: 'valid' },
  citations: [
    {
      id: 'cite-1',
      label: 'GET /pets/{petId}',
      kind: 'operation',
      stableKey: 'op:get:/pets/{petId}',
      sourcePointer: 'paths./pets/{petId}.get',
      excerpt: 'responses: 200 -> Pet, 404 -> Error',
    },
    {
      id: 'cite-2',
      label: 'Pet',
      kind: 'type',
      stableKey: 'type:Pet',
      sourcePointer: 'components.schemas.Pet',
    },
  ],
};

/** An ungrounded proposal whose example fails validation — the warning case. */
export const REFERENCE_RISKY_PROPOSAL: AuthoringProposal = {
  id: 'prop-2',
  title: 'Example payload for POST /pets',
  body: '{ "name": "Rex", "tag": 7 }',
  status: 'pending',
  provenance: {
    model: 'claude-opus-4-8',
    policy: 'Unrestricted',
    generatedAt: '2026-07-19T14:04:00Z',
  },
  exampleValidation: { status: 'invalid', message: 'tag must be a string.' },
  citations: [],
};

/** Every proposal status, so the gallery can render the full lifecycle. */
export const REFERENCE_PROPOSAL_STATUSES: readonly AuthoringProposalStatus[] = [
  'pending',
  'accepted',
  'edited',
  'rejected',
  'superseded',
] as const;

/** A mixed check run: one required failure, one advisory, one still running. */
export const REFERENCE_CHECKS: readonly AuthoringCheck[] = [
  { id: 'chk-lint', label: 'Contract lint', status: 'passed', blocking: true },
  {
    id: 'chk-links',
    label: 'Link check',
    status: 'failed',
    detail: '3 links unreachable',
    blocking: false,
    href: '/ade/authoring/releases',
  },
  { id: 'chk-a11y', label: 'Portal accessibility', status: 'running', blocking: true },
  { id: 'chk-graphql', label: 'GraphQL validation', status: 'skipped', blocking: false },
];

/** A settled, fully passing run. */
export const REFERENCE_PASSING_CHECKS: readonly AuthoringCheck[] = [
  { id: 'chk-lint', label: 'Contract lint', status: 'passed', blocking: true },
  { id: 'chk-links', label: 'Link check', status: 'passed', blocking: false },
];

/** A settled run with a required failure, which blocks confirmation. */
export const REFERENCE_BLOCKING_CHECKS: readonly AuthoringCheck[] = [
  {
    id: 'chk-lint',
    label: 'Contract lint',
    status: 'failed',
    detail: '2 operations missing responses',
    blocking: true,
  },
  { id: 'chk-links', label: 'Link check', status: 'passed', blocking: false },
];

/** A three-level content tree covering every node decoration. */
export const REFERENCE_TREE: readonly AuthoringTreeNode[] = [
  {
    id: 'guides',
    label: 'Guides',
    icon: 'FolderOpen',
    children: [
      {
        id: 'guide-start',
        label: 'Getting started',
        kind: 'Guide',
        icon: 'FileText',
        tone: 'success',
        statusLabel: 'Documented',
      },
      {
        id: 'guide-auth',
        label: 'Authentication',
        kind: 'Guide',
        icon: 'FileText',
        tone: 'warning',
        statusLabel: 'Stale',
      },
    ],
  },
  {
    id: 'pets',
    label: '/pets',
    kind: 'Path',
    children: [
      {
        id: 'pets-get',
        label: 'GET /pets',
        kind: 'Operation',
        tone: 'success',
        statusLabel: 'Documented',
      },
      {
        id: 'pets-post',
        label: 'POST /pets',
        kind: 'Operation',
        tone: 'danger',
        statusLabel: 'Missing',
        children: [
          { id: 'pets-post-201', label: '201 Created', kind: 'Response' },
          { id: 'pets-post-400', label: '400 Bad Request', kind: 'Response' },
        ],
      },
    ],
  },
];

/** A build mid-flight: two phases done, one active with live detail. */
export const REFERENCE_PHASES: readonly AuthoringProgressPhase[] = [
  { id: 'resolve', label: 'Resolving sources', status: 'complete' },
  { id: 'validate', label: 'Validating contracts', status: 'complete' },
  { id: 'render', label: 'Rendering pages', detail: '482 of 640 pages', status: 'active' },
  { id: 'upload', label: 'Uploading assets', status: 'pending' },
  { id: 'activate', label: 'Activating edge release', status: 'pending' },
] as const;

/** A build that failed partway, so the failure state has a reference too. */
export const REFERENCE_FAILED_PHASES: readonly AuthoringProgressPhase[] = [
  { id: 'resolve', label: 'Resolving sources', status: 'complete' },
  {
    id: 'validate',
    label: 'Validating contracts',
    detail: 'Unresolved $ref in components.schemas.Pet',
    status: 'failed',
  },
  { id: 'render', label: 'Rendering pages', status: 'pending' },
] as const;

/** A routine promotion: reversible, and its checks pass. */
export const REFERENCE_PROMOTE_SHEET: AuthoringImpactSheet = {
  action: 'promote',
  severity: 'notable',
  target: 'r-4821',
  environment: 'production',
  policy: 'Production promotions are recorded in the tenant audit log.',
  checks: REFERENCE_PASSING_CHECKS,
  effects: [
    {
      id: 'eff-domain',
      label: 'docs.example.com',
      detail: 'Serves release r-4821 instead of r-4820.',
      tone: 'info',
      scope: '640 pages',
    },
    {
      id: 'eff-cache',
      label: 'Edge cache',
      detail: 'Invalidated for changed pages only.',
      tone: 'neutral',
      scope: '128 pages',
    },
  ],
};

/** An irreversible purge, which demands the target be typed out. */
export const REFERENCE_PURGE_SHEET: AuthoringImpactSheet = {
  action: 'purge',
  severity: 'irreversible',
  target: 'docs.example.com',
  environment: 'production',
  confirmationPhrase: 'docs.example.com',
  policy: 'Purging removes every cached object. Origin load will spike until the cache refills.',
  checks: REFERENCE_PASSING_CHECKS,
  effects: [
    {
      id: 'eff-purge',
      label: 'Global edge cache',
      detail: 'Every cached object is discarded in all regions.',
      tone: 'danger',
      scope: '640 pages, 12 regions',
    },
  ],
};

/** Before/after text for the diff reference. */
export const REFERENCE_DIFF = {
  before: 'Gets a pet.\nReturns the pet.\nErrors are not documented.',
  after: 'Returns a single pet by its identifier.\nReturns the pet.\nResponds 404 when no pet matches.',
} as const;

/** A series above the privacy threshold, with a clear upward trend. */
export const REFERENCE_SERIES: AuthoringAnalyticsSeries = {
  id: 'views',
  label: 'Page views',
  unit: 'views',
  points: [
    { label: '2026-07-13', value: 120 },
    { label: '2026-07-14', value: 180 },
    { label: '2026-07-15', value: 240 },
    { label: '2026-07-16', value: 310 },
    { label: '2026-07-17', value: 295 },
  ],
};

/** A series that exists but is too sparse to show — the `threshold` state. */
export const REFERENCE_SPARSE_SERIES: AuthoringAnalyticsSeries = {
  id: 'feedback',
  label: 'Page feedback',
  unit: 'responses',
  points: [
    { label: '2026-07-16', value: 1 },
    { label: '2026-07-17', value: 2 },
  ],
};

/** Bulk actions for the selection bar reference. */
export const REFERENCE_BULK_ACTIONS: readonly AuthoringCommandAction[] = [
  { id: 'regenerate', label: 'Regenerate', icon: 'RefreshCw', variant: 'secondary' },
  { id: 'request-review', label: 'Request review', icon: 'UserCheck', variant: 'primary' },
  {
    id: 'export',
    label: 'Export',
    icon: 'FileText',
    variant: 'ghost',
    disabledReason: 'Export needs the hosted plan.',
  },
];
