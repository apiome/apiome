/**
 * The workspace the documentation site's Members and Roles screenshots show (DOCS-1.9, #5626).
 *
 * `tests/members-hive-redesign.test.tsx` and `tests/roles-hive-redesign.test.tsx` render their
 * screens against this data in their "docs fixtures" blocks, and dump the result into
 * `e2e/fixtures/hive-a11y/` for `apiome-docs/screens.json`. One module so the two pages show
 * the same people in the same roles.
 *
 * The instant is the docs capture clock (`apiome-docs/scripts/screenshots.ts`), so relative
 * times ("2 hours ago") read the same on every regeneration.
 */

/** "Now" for every docs dump: 15 June 2026, 09:30 UTC. */
export const DOCS_NOW = Date.parse('2026-06-15T09:30:00Z');

/** The viewer — the session mocked in the members suite is `u-ada`. */
export const DOCS_VIEWER_ID = 'u-ada';

/** Every resource of the permission matrix, in its order. */
const RESOURCES = [
  'projects',
  'versions',
  'classes',
  'properties',
  'paths',
  'types',
  'imports',
  'members',
  'api_keys',
  'billing',
  'lint_findings',
  'verification_targets',
  'verification_evidence',
  'consumer_contracts',
] as const;

/** The spec-authoring resources an Editor writes to. */
const AUTHORING = ['projects', 'versions', 'classes', 'properties', 'paths', 'types', 'imports'];

/**
 * Grant some actions on some resources.
 *
 * @param resources The resources.
 * @param actions The actions granted on each.
 * @returns The `{resource, action}` cells, as `GET /api/access/roles` returns them.
 */
function grant(
  resources: readonly string[],
  actions: readonly string[]
): { resource: string; action: string }[] {
  return resources.flatMap((resource) => actions.map((action) => ({ resource, action })));
}

/** Northwind's roles: the four built-ins and two custom roles. */
export const DOCS_ROLES = [
  {
    id: 'role-owner',
    slug: 'owner',
    name: 'Owner',
    description: 'Full control of the workspace, including billing.',
    is_builtin: true,
    member_count: 1,
    permissions: grant(RESOURCES, ['view', 'create', 'edit', 'delete', 'publish']),
  },
  {
    id: 'role-admin',
    slug: 'admin',
    name: 'Admin',
    description: 'Manages members, keys and every specification.',
    is_builtin: true,
    member_count: 1,
    permissions: grant(
      RESOURCES.filter((resource) => resource !== 'billing'),
      ['view', 'create', 'edit', 'delete', 'publish']
    ),
  },
  {
    id: 'role-editor',
    slug: 'editor',
    name: 'Editor',
    description: 'Writes and lints specifications; cannot publish.',
    is_builtin: true,
    member_count: 3,
    permissions: [
      ...grant(RESOURCES, ['view']),
      ...grant([...AUTHORING, 'lint_findings'], ['create', 'edit']),
    ],
  },
  {
    id: 'role-viewer',
    slug: 'viewer',
    name: 'Viewer',
    description: 'Reads everything, changes nothing.',
    is_builtin: true,
    member_count: 2,
    permissions: grant(RESOURCES, ['view']),
  },
  {
    id: 'role-release-manager',
    slug: 'release-manager',
    name: 'Release manager',
    description: 'Cuts, publishes and sunsets versions; reviews lint waivers.',
    is_builtin: false,
    member_count: 1,
    permissions: [
      ...grant(RESOURCES, ['view']),
      ...grant(['versions'], ['create', 'edit', 'publish']),
      ...grant(['lint_findings'], ['edit']),
      ...grant(['verification_evidence', 'consumer_contracts'], ['create', 'edit']),
    ],
  },
  {
    id: 'role-partner-reviewer',
    slug: 'partner-reviewer',
    name: 'Partner reviewer',
    description: 'Outside reviewers: read specifications and their lint findings.',
    is_builtin: false,
    member_count: 0,
    permissions: grant(['projects', 'versions', 'lint_findings'], ['view']),
  },
];

/**
 * One member row.
 *
 * @param fields What differs from an active, role-less row.
 * @returns The row as `GET /api/access/members` returns it.
 */
function member(fields: {
  user_id: string;
  name: string;
  email: string;
  role: string;
  status?: 'active' | 'pending' | 'suspended';
  joined_at: string;
  member_since?: string;
  last_active?: string | null;
  two_factor_enabled?: boolean;
}) {
  const role = DOCS_ROLES.find((entry) => entry.slug === fields.role);
  if (!role) throw new Error(`No docs role ${fields.role}`);
  return {
    user_id: fields.user_id,
    name: fields.name,
    email: fields.email,
    status: fields.status ?? 'active',
    joined_at: fields.joined_at,
    member_since: fields.member_since ?? fields.joined_at,
    last_active: fields.last_active ?? null,
    two_factor_enabled: fields.two_factor_enabled ?? false,
    role_id: role.id,
    role_name: role.name,
    role_slug: role.slug,
    is_admin: role.slug === 'owner' || role.slug === 'admin',
  };
}

/** Northwind's nine seats: seven people, one suspended contractor, and two open invitations. */
export const DOCS_MEMBERS = [
  member({
    user_id: DOCS_VIEWER_ID,
    name: 'Priya Raman',
    email: 'priya.raman@northwind.io',
    role: 'owner',
    joined_at: '2025-01-12T10:00:00Z',
    last_active: '2026-06-15T09:12:00Z',
    two_factor_enabled: true,
  }),
  member({
    user_id: 'u-marcus',
    name: 'Marcus Lee',
    email: 'marcus.lee@northwind.io',
    role: 'admin',
    joined_at: '2025-02-03T14:20:00Z',
    last_active: '2026-06-15T07:05:00Z',
    two_factor_enabled: true,
  }),
  member({
    user_id: 'u-sam',
    name: 'Sam Okafor',
    email: 'sam.okafor@northwind.io',
    role: 'release-manager',
    joined_at: '2025-04-22T09:00:00Z',
    last_active: '2026-06-14T16:40:00Z',
    two_factor_enabled: true,
  }),
  member({
    user_id: 'u-elena',
    name: 'Elena Vasquez',
    email: 'elena.vasquez@northwind.io',
    role: 'editor',
    joined_at: '2025-06-09T11:30:00Z',
    last_active: '2026-06-12T13:15:00Z',
  }),
  member({
    user_id: 'u-tomas',
    name: 'Tomas Berg',
    email: 'tomas.berg@northwind.io',
    role: 'editor',
    joined_at: '2025-09-15T08:45:00Z',
    last_active: '2026-06-03T10:00:00Z',
    two_factor_enabled: true,
  }),
  member({
    user_id: 'u-hana',
    name: 'Hana Sato',
    email: 'hana.sato@northwind.io',
    role: 'viewer',
    joined_at: '2026-01-20T15:00:00Z',
    last_active: '2026-05-28T09:20:00Z',
  }),
  member({
    user_id: 'u-jordan',
    name: 'Jordan Blake',
    email: 'contractor.jb@partner.dev',
    role: 'editor',
    status: 'suspended',
    joined_at: '2025-11-03T09:00:00Z',
    member_since: '2026-05-22T17:44:00Z',
    last_active: '2026-05-22T16:02:00Z',
  }),
  member({
    user_id: 'u-dmitri',
    name: '',
    email: 'dmitri.ivanov@northwind.io',
    role: 'editor',
    status: 'pending',
    joined_at: '2026-06-11T14:30:00Z',
  }),
  member({
    user_id: 'u-aiko',
    name: '',
    email: 'aiko.mori@northwind.io',
    role: 'viewer',
    status: 'pending',
    joined_at: '2026-06-13T10:05:00Z',
  }),
];

/** Seat usage the licence reports: every member, suspended and invited ones included. */
export const DOCS_SEATS = { used: DOCS_MEMBERS.length, max: 10 };

/** The access ledger, newest first — what the member drawer narrows to one person. */
export const DOCS_AUDIT = [
  {
    id: 'evt-9f1c2a07',
    actor_id: DOCS_VIEWER_ID,
    actor_label: 'priya.raman@northwind.io',
    action: 'role.assigned',
    target: 'u-sam',
    source: 'web',
    created_at: '2026-06-14T08:14:00Z',
  },
  {
    id: 'evt-6c8f97d4',
    actor_id: DOCS_VIEWER_ID,
    actor_label: 'priya.raman@northwind.io',
    action: 'member.invited',
    target: 'aiko.mori@northwind.io',
    source: 'web',
    created_at: '2026-06-13T10:05:00Z',
  },
  {
    id: 'evt-5a1d0c33',
    actor_id: 'u-sam',
    actor_label: 'sam.okafor@northwind.io',
    action: 'api_key.created',
    target: 'ci-publisher',
    source: 'web',
    created_at: '2026-06-10T15:22:00Z',
  },
  {
    id: 'evt-4a6d75b2',
    actor_id: DOCS_VIEWER_ID,
    actor_label: 'priya.raman@northwind.io',
    action: 'role.created',
    target: 'Release manager',
    source: 'web',
    created_at: '2026-04-21T10:12:00Z',
  },
  {
    id: 'evt-2f0e9a41',
    actor_id: 'u-marcus',
    actor_label: 'marcus.lee@northwind.io',
    action: 'member.joined',
    target: 'u-sam',
    source: 'web',
    created_at: '2025-04-22T09:00:00Z',
  },
];
