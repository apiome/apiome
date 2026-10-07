/**
 * The guide set, and the search over it (HIVE-4.9, #5303).
 *
 * Authority: `docs/mockups/foundations/help.html` — *"Search the guide… e.g. publish a
 * version, import RAML, MCP trust posture"* — and the guide pages of the documentation site
 * (`apiome-docs/docs/`, DOCS-1.2 #5619), which this file is the machine-readable index of.
 *
 * ### Why the guides are listed here rather than read from disk
 *
 * The guide is a separate site built from `apiome-docs/docs/`, not a route this app serves. Reading the
 * directory at request time would need the docs tree inside the runtime image, which the
 * production `Dockerfile` does not ship, so a deployed instance would answer every search
 * with nothing. A listing compiled into the bundle searches instantly, works offline, and
 * costs one line per guide.
 *
 * The obvious failure mode of a hand-kept listing is drift — a guide is added and the search
 * never learns about it. `tests/help-catalog.test.ts` reads the real `apiome-docs/docs` tree
 * and fails when a file is missing from {@link GUIDE_ENTRIES} or names a page that no longer
 * exists, so the listing cannot silently fall behind the directory it describes.
 *
 * ### What a search matches
 *
 * Title, summary and keywords, so a reader who types the *task* ("publish", "gate a PR")
 * lands on the guide even when the title is phrased as a question. Every term has to match
 * something — narrowing a search by adding a word is the behaviour a search box promises —
 * and a title hit outranks a summary hit, which outranks a keyword hit.
 */

import { FORMAT_COUNTS } from '@/app/generated/formatCounts';
import { buildDocsHref } from '@/app/utils/docsLinks';

/**
 * Which of the two Help sections a guide is listed under.
 *
 * `spine` is the end-to-end path a specification travels — import, edit, lint, cut, publish,
 * browse, export. `reference` is everything consulted rather than followed.
 */
export type GuideSection = 'spine' | 'reference';

/** Human-readable headings for the two sections, used above grouped results. */
export const GUIDE_SECTION_LABELS: Readonly<Record<GuideSection, string>> = {
  spine: 'How do I…?',
  reference: 'References & quick-starts',
};

/** One page of the written guide set. */
export interface GuideEntry {
  /** Stable id: the React key, the test handle, and the file's basename. */
  id: string;
  /** The page's title, as its `h1` reads. */
  title: string;
  /** One line about what the page answers. Shown under the title in a result row. */
  summary: string;
  /** Repository-relative path of the page's source, e.g. `apiome-docs/docs/bring-in/import-a-spec.md`. */
  page: string;
  /** Which table of the guide index the page sits in. */
  section: GuideSection;
  /**
   * Words a reader might search for that the title and summary do not contain — the format
   * names, the product vocabulary, the synonyms. Never a repeat of the title: a term already
   * in the title scores higher through the title, and a duplicate would only inflate it.
   */
  keywords: readonly string[];
}

/**
 * Every guide page on the documentation site: the spine first, then the references.
 *
 * The index itself is the last entry rather than the first: a reader searching for a task
 * wants the page that answers it, and "the whole guide" is what they fall back to.
 */
export const GUIDE_ENTRIES: readonly GuideEntry[] = [
  {
    id: 'import-a-spec',
    title: 'Import a specification',
    summary:
      `Import any of ${FORMAT_COUNTS.importable} formats — and which of the two importers, Projects or Catalog, handles yours.`,
    page: 'apiome-docs/docs/bring-in/import-a-spec.md',
    section: 'spine',
    keywords: ['upload', 'swagger', 'openapi', 'arazzo', 'json schema', 'job', 'raml', 'postman'],
  },
  {
    id: 'edit-classes-and-properties',
    title: 'Edit classes & properties',
    summary:
      'Shape the data model your published spec exposes — a class becomes a component schema, its properties the fields.',
    page: 'apiome-docs/docs/build/edit-classes-and-properties.md',
    section: 'spine',
    keywords: ['schema', 'component', 'model', 'field', 'attribute', 'type'],
  },
  {
    id: 'edit-paths',
    title: 'Edit paths & operations',
    summary:
      'Author URL templates and their operations — parameters, request bodies and responses — on a specific version.',
    page: 'apiome-docs/docs/build/edit-paths.md',
    section: 'spine',
    keywords: ['endpoint', 'route', 'get', 'post', 'parameter', 'response', 'request body'],
  },
  {
    id: 'lint-and-quality',
    title: 'Lint & check quality',
    summary:
      'The server-side quality score (A–F out of 100) and the itemized findings behind it, so the UI and the CLI always agree.',
    page: 'apiome-docs/docs/build/lint-and-quality.md',
    section: 'spine',
    keywords: ['grade', 'score', 'style guide', 'severity', 'finding', 'governance'],
  },
  {
    id: 'axis-score',
    title: 'Axis score algorithm (clx-axis-v1)',
    summary:
      'How catalog and MCP lint evidence rolls into a multi-axis evaluation, and what each band means.',
    page: 'apiome-docs/docs/build/axis-score.md',
    section: 'spine',
    keywords: ['coverage', 'weighting', 'band', 'evidence', 'grade', 'rollup'],
  },
  {
    id: 'cut-a-version',
    title: 'Cut a version',
    summary:
      'Create a new revision of a project — classes carry over, paths are authored on the new revision.',
    page: 'apiome-docs/docs/ship/cut-a-version.md',
    section: 'spine',
    keywords: ['revision', 'semver', 'branch', 'draft', 'base'],
  },
  {
    id: 'publish-a-version',
    title: 'Publish a version',
    summary:
      'Freeze a version for browse, export and MCP consumers — and the publish gates that refuse one that is not ready.',
    page: 'apiome-docs/docs/ship/publish-a-version.md',
    section: 'spine',
    keywords: ['release', 'gate', 'freeze', 'public', 'private', 'ship'],
  },
  {
    id: 'browse-published-specs',
    title: 'Browse published specs',
    summary:
      'The read surface for published versions: public ones need no authentication, private ones an in-scope API key.',
    page: 'apiome-docs/docs/ship/browse-published-specs.md',
    section: 'spine',
    keywords: ['catalog', 'discover', 'search', 'public', 'api key'],
  },
  {
    id: 'export-a-spec',
    title: 'Export / download a spec',
    summary:
      'Reconstruct the full OpenAPI 3.1, Arazzo or JSON Schema document for a published version, in JSON or YAML.',
    page: 'apiome-docs/docs/ship/export-a-spec.md',
    section: 'spine',
    keywords: ['fetch', 'yaml', 'json', 'bundle', 'artifact', 'save'],
  },
  {
    id: 'export-fidelity',
    title: 'Understand export fidelity',
    summary:
      'What a projection to another format preserves, downgrades or drops — predicted before generation, with reasons.',
    page: 'apiome-docs/docs/ship/export-fidelity.md',
    section: 'spine',
    keywords: [
      'projection',
      'asyncapi',
      'graphql',
      'proto3',
      'avro',
      'lossy',
      'acknowledgement',
      'reason code',
    ],
  },
  {
    id: 'catalog-format-details',
    title: "Read a catalog item's format details",
    summary:
      'Payload analysis for an imported item: X12 envelopes and segments, COBOL copybooks, statuses and redaction.',
    page: 'apiome-docs/docs/bring-in/catalog-format-details.md',
    section: 'spine',
    keywords: ['x12', 'edi', 'cobol', 'copybook', 'redaction', 'payload', 'analysis'],
  },
  {
    id: 'convert-to-openapi',
    title: 'Convert a catalog item to OpenAPI',
    summary:
      'The evidence-first conversion: a deterministic projection map and its reason codes before anything is created.',
    page: 'apiome-docs/docs/bring-in/convert-to-openapi.md',
    section: 'spine',
    keywords: ['projection graph', 'evidence', 'reason code', 'history', 'promote'],
  },
  {
    id: 'supported-formats',
    title: 'Supported formats',
    summary:
      'Every format Apiome imports and exports, generated from the registries — keys, input kinds, versions and extensions.',
    page: 'apiome-docs/docs/bring-in/supported-formats.md',
    section: 'reference',
    keywords: [
      'protobuf',
      'grpc',
      'graphql',
      'asyncapi',
      'thrift',
      'smithy',
      'typespec',
      'wsdl',
      'xsd',
      'odata',
      'edi',
      'x12',
      'hl7',
      'fhir',
      'copybook',
      'matrix',
      'which formats',
    ],
  },
  {
    id: 'api-reference',
    title: 'API reference',
    summary:
      'The REST service publishes its own interactive reference — where it lives, and how to authenticate against it.',
    page: 'apiome-docs/docs/reference/api-reference.md',
    section: 'reference',
    keywords: ['rest', 'swagger ui', 'fastapi', 'endpoint', 'openapi.json', 'token'],
  },
  {
    id: 'cli-quickstart',
    title: 'CLI quick-start',
    summary:
      'Import documents, inspect tenant resources, lint and export specs from the terminal with the apiome CLI.',
    page: 'apiome-docs/docs/reference/cli-quickstart.md',
    section: 'reference',
    keywords: ['command line', 'terminal', 'shell', 'exit code', 'install', 'apiome diff'],
  },
  {
    id: 'mcp-quickstart',
    title: 'MCP setup quick-start',
    summary:
      'Point an MCP host — Claude Desktop, an IDE, automation — at your published specs, read-only.',
    page: 'apiome-docs/docs/reference/mcp-quickstart.md',
    section: 'reference',
    keywords: ['model context protocol', 'claude desktop', 'ide', 'host', 'tool', 'stdio'],
  },
  {
    id: 'keyboard',
    title: 'Using Apiome from the keyboard',
    summary: 'The keyboard path for every primary task, and every shortcut in one table.',
    page: 'apiome-docs/docs/reference/keyboard.md',
    section: 'reference',
    keywords: ['shortcuts', 'hotkeys', 'command palette', 'tab', 'focus', 'no mouse', 'accessibility'],
  },
  {
    id: 'accessibility',
    title: 'Accessibility in Apiome',
    summary: 'The WCAG 2.2 AA contract, how the CI axe gate checks it, and the screen-reader checklist.',
    page: 'apiome-docs/docs/reference/accessibility.md',
    section: 'reference',
    keywords: ['a11y', 'wcag', 'axe', 'screen reader', 'contrast', 'high contrast', 'voiceover', 'nvda'],
  },
  {
    id: 'content-voice',
    title: 'Content & voice',
    summary: 'How empty, loading, error and gated states read, and the per-route checklist.',
    page: 'apiome-docs/docs/reference/content-voice.md',
    section: 'reference',
    keywords: ['copy', 'empty state', 'error message', 'loading', 'tone', 'writing', 'microcopy'],
  },
  {
    id: 'ci-diff-gate',
    title: 'CI contract gate (GitHub Action)',
    summary:
      'Gate pull requests when an OpenAPI change breaks a published version, with one sticky PR comment.',
    page: 'apiome-docs/docs/reference/ci-diff-gate.md',
    section: 'reference',
    keywords: ['github actions', 'pipeline', 'breaking change', 'diff', 'pull request', 'workflow'],
  },
  {
    id: 'ci-gitlab-bitbucket',
    title: 'CI contract gate on GitLab & Bitbucket',
    summary:
      'The same diff gate as a copy-paste GitLab CI or Bitbucket Pipelines job, run from the container image.',
    page: 'apiome-docs/docs/reference/ci-gitlab-bitbucket.md',
    section: 'reference',
    keywords: ['merge request', 'pipeline', 'container', 'docker', 'recipe'],
  },
  {
    id: 'lint-rules',
    title: 'Built-in lint rules',
    summary:
      'Reference for every rule in the catalog: stable ids, default severities and the rationale behind each one.',
    page: 'apiome-docs/docs/build/lint-rules.md',
    section: 'reference',
    keywords: ['rule id', 'severity', 'naming', 'catalog', 'registry'],
  },
  {
    id: 'custom-rules',
    title: 'Custom lint rules',
    summary:
      'Author organization-specific rules in a YAML dialect that is a strict subset of Spectral.',
    page: 'apiome-docs/docs/build/custom-rules.md',
    section: 'reference',
    keywords: ['spectral', 'dsl', 'yaml', 'organization', 'standard', 'validate'],
  },
  {
    id: 'spectral-import',
    title: 'Import a Spectral ruleset',
    summary:
      'Translate an existing .spectral.yaml into built-in and custom rules instead of re-authoring it.',
    page: 'apiome-docs/docs/bring-in/spectral-import.md',
    section: 'reference',
    keywords: ['stoplight', 'redocly', 'migrate', 'yaml', 'convert'],
  },
  {
    id: 'schematron-import',
    title: 'Import a Schematron rule set',
    summary:
      'Turn a .sch rule set into a governance style guide: one rule per assertion, with a reason for every assertion that cannot be scored.',
    page: 'apiome-docs/docs/bring-in/schematron-import.md',
    section: 'reference',
    keywords: ['.sch', 'xml', 'peppol', 'ubl', 'assert', 'xpath', 'governance', 'iso 19757'],
  },
  {
    id: 'style-guide-revisions',
    title: 'Style-guide revisions & governance audit',
    summary:
      'Every edit appends an immutable revision, so a lint score always names what the guide contained at the time.',
    page: 'apiome-docs/docs/govern/style-guide-revisions.md',
    section: 'reference',
    keywords: ['history', 'immutable', 'compliance', 'pinned', 'trail'],
  },
  {
    id: 'mcp-conformance-rules',
    title: 'MCP conformance rules',
    summary: 'The conformance catalog, each rule citing the MCP specification reference it enforces.',
    page: 'apiome-docs/docs/govern/mcp-conformance-rules.md',
    section: 'reference',
    keywords: ['specification', 'blocking', 'model context protocol', 'compliance'],
  },
  {
    id: 'mcp-surface-lint-rules',
    title: 'MCP surface lint rules',
    summary: 'What is checked about an MCP surface itself — tools, descriptions and transparency fields.',
    page: 'apiome-docs/docs/govern/mcp-surface-lint-rules.md',
    section: 'reference',
    keywords: ['tool', 'transparency', 'model context protocol', 'description'],
  },
  {
    id: 'mcp-trust-posture-rules',
    title: 'MCP trust-posture rules',
    summary: 'Trust-posture checks mapped to the OWASP MCP Top 10, including the blocking ones.',
    page: 'apiome-docs/docs/govern/mcp-trust-posture-rules.md',
    section: 'reference',
    keywords: ['owasp', 'security', 'risk', 'top 10', 'model context protocol'],
  },
  {
    id: 'mock-bundle-format',
    title: 'Portable mock bundle format',
    summary:
      'One JSON document pinning everything the mock runtime needs to serve a version offline.',
    page: 'apiome-docs/docs/ship/mocks/mock-bundle-format.md',
    section: 'reference',
    keywords: ['offline', 'signed', 'digest', 'pinned', 'schema', 'air-gapped'],
  },
  {
    id: 'portable-mock-runtime',
    title: 'Portable mock runtime',
    summary:
      'Serve a mock bundle on a laptop, in CI or inside an air-gapped network with `apiome mock run`.',
    page: 'apiome-docs/docs/ship/mocks/portable-mock-runtime.md',
    section: 'reference',
    keywords: ['mock server', 'image', 'readiness', 'logs', 'conformance', 'docker'],
  },
  {
    id: 'mock-fixture-packs',
    title: 'Mock fixture packs and data lifecycle',
    summary:
      'Versioned seed data with a stable content digest, and the reset that puts a test back where it started.',
    page: 'apiome-docs/docs/ship/mocks/mock-fixture-packs.md',
    section: 'reference',
    keywords: ['seed', 'stateful', 'reset', 'session', 'deterministic'],
  },
  {
    id: 'one-mock-engine',
    title: 'One mock engine',
    summary:
      'How the two mock implementations became one — what moved, and how a stored instance config migrates.',
    page: 'apiome-docs/docs/ship/mocks/one-mock-engine.md',
    section: 'reference',
    keywords: ['scenario', 'migration', 'hosted mock', 'resolver'],
  },
  {
    id: 'mock-callbacks',
    title: 'Mock callbacks and webhooks',
    summary:
      'Callbacks the mock sends: allowlisted destinations, schema-checked payloads and deterministic retries.',
    page: 'apiome-docs/docs/ship/mocks/mock-callbacks.md',
    section: 'reference',
    keywords: ['allowlist', 'retry', 'outbound', 'event'],
  },
  {
    id: 'mock-response-correlation',
    title: 'Request-correlated mock responses',
    summary: 'Answer `GET /pets/42` with id 42 — no request header, configured on the version.',
    page: 'apiome-docs/docs/ship/mocks/mock-response-correlation.md',
    section: 'reference',
    keywords: ['template', 'path parameter', 'echo', 'correlation'],
  },
  {
    id: 'mock-response-preview',
    title: 'Mock response preview',
    summary: 'Dry-run a request to see what the mock returns, and which layer produced it.',
    page: 'apiome-docs/docs/ship/mocks/mock-response-preview.md',
    section: 'reference',
    keywords: ['dry run', 'render', 'template', 'scenario'],
  },
  {
    id: 'mock-proxy-capture',
    title: 'Guarded proxy capture and replay',
    summary:
      'Record real upstream traffic into reviewed, redacted fixtures — allowlists, redaction and provenance.',
    page: 'apiome-docs/docs/ship/mocks/mock-proxy-capture.md',
    section: 'reference',
    keywords: ['record', 'upstream', 'redaction', 'fixture', 'mock'],
  },
  {
    id: 'serverless-mock-adapter',
    title: 'Serverless mock adapter',
    summary: 'Run a mock bundle as a Lambda, Cloud Run or Azure function — limits, cold start, preflight.',
    page: 'apiome-docs/docs/ship/mocks/serverless-mock-adapter.md',
    section: 'reference',
    keywords: ['lambda', 'cloud run', 'azure', 'function', 'cold start'],
  },
  {
    id: 'mock-release-attestation',
    title: 'Release-proof mock attestation',
    summary:
      'Bundle digest, runtime, conformance result and fixture digests on a verification run, signed for offline checks.',
    page: 'apiome-docs/docs/ship/mocks/mock-release-attestation.md',
    section: 'reference',
    keywords: ['verification', 'signature', 'dsse', 'provenance', 'digest'],
  },
  {
    id: 'run-locally',
    title: 'Run Apiome locally',
    summary: 'Start the local stack with Docker, load the sample data and sign in.',
    page: 'apiome-docs/docs/getting-started/run-locally.md',
    section: 'spine',
    keywords: ['docker', 'compose', 'seed', 'setup', 'install', 'dev login'],
  },
  {
    id: 'sign-in',
    title: 'Sign in and create an account',
    summary: 'Sign in with single sign-on or email, pass two-factor checks, or create an account.',
    page: 'apiome-docs/docs/getting-started/sign-in.mdx',
    section: 'spine',
    keywords: ['login', 'sso', '2fa', 'two-factor', 'password', 'signup', 'register'],
  },
  {
    id: 'onboarding',
    title: 'Set up your first organization',
    summary: 'The three-step setup that creates your first tenant after you sign in.',
    page: 'apiome-docs/docs/getting-started/onboarding.mdx',
    section: 'spine',
    keywords: ['tenant', 'workspace', 'onboarding', 'slug', 'free plan'],
  },
  {
    id: 'launcher-and-home',
    title: 'The launcher and Home',
    summary: 'What the launcher and Home show: the checklist, statistics, quick actions and what needs attention.',
    page: 'apiome-docs/docs/getting-started/launcher-and-home.mdx',
    section: 'spine',
    keywords: ['dashboard', 'checklist', 'overview', 'quick actions', 'needs attention'],
  },
  {
    id: 'first-project',
    title: 'Import your first project',
    summary: 'Bring an existing OpenAPI file in with the import wizard, step by step.',
    page: 'apiome-docs/docs/getting-started/first-project.mdx',
    section: 'spine',
    keywords: ['wizard', 'upload', 'openapi', 'petstore', 'getting started'],
  },
  {
    id: 'versions-and-publishing',
    title: 'Version and publish',
    summary: 'Cut a version of a project and publish it, private or public, through the publish gates.',
    page: 'apiome-docs/docs/getting-started/versions-and-publishing.mdx',
    section: 'spine',
    keywords: ['release', 'visibility', 'gates', 'force publish', 'new version'],
  },
  {
    id: 'browse-and-export',
    title: 'Browse and export',
    summary: 'Find published versions, share their URL, and export another format in the Export studio.',
    page: 'apiome-docs/docs/getting-started/browse-and-export.mdx',
    section: 'spine',
    keywords: ['published', 'swagger ui', 'download', 'export studio', 'convert'],
  },
  {
    id: 'connect-an-mcp-host',
    title: 'Connect an MCP host',
    summary: 'Create an MCP API key and point Claude Desktop, an IDE or an agent at your published specs.',
    page: 'apiome-docs/docs/getting-started/connect-an-mcp-host.mdx',
    section: 'spine',
    keywords: ['claude', 'agent', 'model context protocol', 'mcp key', 'ide'],
  },
  {
    id: 'keyboard-and-preferences',
    title: 'Keyboard and preferences',
    summary: 'Change the theme, font size and density, and move around Apiome from the keyboard.',
    page: 'apiome-docs/docs/getting-started/keyboard-and-preferences.mdx',
    section: 'spine',
    keywords: ['theme', 'dark mode', 'density', 'font size', 'shortcuts', 'command palette'],
  },
  {
    id: 'projects',
    title: 'Projects',
    summary: 'Every API in your workspace as cards or a table: create, edit, delete, restore, consumers.',
    page: 'apiome-docs/docs/build/projects.mdx',
    section: 'reference',
    keywords: ['new project', 'cards', 'table', 'delete', 'undelete', 'consumers'],
  },
  {
    id: 'versions',
    title: 'Versions',
    summary: "A project's version timeline, the mock switch, and the Changes, Test bench, Discussion and Repository tabs.",
    page: 'apiome-docs/docs/build/versions.mdx',
    section: 'reference',
    keywords: ['timeline', 'mock', 'test bench', 'discussion', 'repository', 'changelog'],
  },
  {
    id: 'version-dialogs',
    title: 'Version dialogs',
    summary: 'New version, Edit, Publish, Schedule sunset, Compare and Export — and the git-like features that are switched off.',
    page: 'apiome-docs/docs/build/version-dialogs.mdx',
    section: 'reference',
    keywords: ['new version', 'sunset', 'compare', 'export', 'gitlike', 'merge', 'fork', 'tag'],
  },
  {
    id: 'primitives-and-types',
    title: 'Primitives and types',
    summary: 'The JSON Schema type registry: create and import types, namespaces, the $ref resolver and settings.',
    page: 'apiome-docs/docs/build/primitives-and-types.mdx',
    section: 'reference',
    keywords: ['json schema', 'registry', 'namespace', 'resolver', '$ref', 'import'],
  },
  {
    id: 'studio',
    title: 'Studio',
    summary: 'Where classes, paths and code are edited — the Designer app, and the /ade/studio routes.',
    page: 'apiome-docs/docs/build/studio.mdx',
    section: 'reference',
    keywords: ['designer', 'editor', 'paths editor', 'classes'],
  },
  {
    id: 'catalog',
    title: 'Catalog',
    summary: 'Imports in formats other than OpenAPI: find items, read their tabs, convert one to OpenAPI.',
    page: 'apiome-docs/docs/bring-in/catalog.mdx',
    section: 'reference',
    keywords: ['graphql', 'asyncapi', 'grpc', 'catalog item', 'convert', 'fidelity'],
  },
  {
    id: 'import-wizard',
    title: 'Import wizard',
    summary: 'Every import source step by step — file, URL, paste, Git, SwaggerHub, Postman — with sample files.',
    page: 'apiome-docs/docs/bring-in/import-wizard.mdx',
    section: 'reference',
    keywords: ['upload', 'url', 'clipboard', 'git', 'swaggerhub', 'postman', 'sample files'],
  },
  {
    id: 'repositories',
    title: 'Repositories',
    summary: 'Register Git repositories, find the specs in them, import in bulk, quotas and the webhook allowlist.',
    page: 'apiome-docs/docs/bring-in/repositories.mdx',
    section: 'reference',
    keywords: ['github', 'gitlab', 'bitbucket', 'discovered specs', 'webhook', 'quota', 'bulk import'],
  },
  {
    id: 'mcp-servers',
    title: 'MCP servers',
    summary: 'Catalog MCP servers, discover their tools, grade them, and compare them.',
    page: 'apiome-docs/docs/bring-in/mcp-servers.mdx',
    section: 'reference',
    keywords: ['model context protocol', 'add mcp server', 'endpoint', 'capability directory', 'analytics'],
  },
  {
    id: 'agent-access',
    title: 'Agent access',
    summary: 'Expose published operations to AI agents as MCP tools, issue agent keys, and watch usage.',
    page: 'apiome-docs/docs/bring-in/agent-access.mdx',
    section: 'reference',
    keywords: ['toolset', 'agent key', 'ai', 'claude', 'tools'],
  },
  {
    id: 'published',
    title: 'Published',
    summary: 'Published versions: visibility, access URLs, private keys, and the hosted mock with scenarios.',
    page: 'apiome-docs/docs/ship/published.mdx',
    section: 'reference',
    keywords: ['visibility', 'public', 'private', 'access url', 'api key', 'hosted mock', 'scenarios'],
  },
  {
    id: 'sunset-timeline',
    title: 'Sunset timeline',
    summary: 'When each deprecated version reaches end of life, how to schedule it, and the CSV export.',
    page: 'apiome-docs/docs/ship/sunset-timeline.mdx',
    section: 'reference',
    keywords: ['deprecation', 'end of life', 'eol', 'successor', 'csv'],
  },
  {
    id: 'export-studio',
    title: 'Export studio',
    summary: 'Source, target, options, verify, generate — convert a version and see what survives.',
    page: 'apiome-docs/docs/ship/export-studio.mdx',
    section: 'reference',
    keywords: ['convert', 'fidelity', 'lossy', 'types-only', 'verify', 'export job'],
  },
  {
    id: 'sdk-settings',
    title: 'SDK settings',
    summary: 'Name and brand generated SDK packages, and offer a public Get SDK download.',
    page: 'apiome-docs/docs/ship/sdk-settings.mdx',
    section: 'reference',
    keywords: ['npm', 'pypi', 'go module', 'licence header', 'user agent', 'get sdk'],
  },
  {
    id: 'mock-try-out',
    title: 'Mock try-out',
    summary: 'Preview a mock response, call the hosted mock, or test-drive an exported file.',
    page: 'apiome-docs/docs/ship/mock-try-out.mdx',
    section: 'reference',
    keywords: ['try it', 'preview', 'test drive', 'x-mock-scenario'],
  },
  {
    id: 'style-guides',
    title: 'Style guides',
    summary: 'Choose the rules specs are scored against, assign guides, and set quality and verification policies.',
    page: 'apiome-docs/docs/govern/style-guides.mdx',
    section: 'reference',
    keywords: ['rule catalog', 'custom rules', 'tenant default', 'assign', 'quality policy', 'severity'],
  },
  {
    id: 'lint-posture',
    title: 'Lint posture',
    summary: 'Triage lint findings across the workspace: filter, acknowledge, request and approve waivers, assign owners.',
    page: 'apiome-docs/docs/govern/lint-posture.mdx',
    section: 'reference',
    keywords: ['findings', 'waiver', 'acknowledge', 'false positive', 'saved view', 'owner', 'trends'],
  },
  {
    id: 'access-audit',
    title: 'Access audit',
    summary: 'The append-only ledger of access and permission changes, its hash chain, and the CSV export.',
    page: 'apiome-docs/docs/govern/access-audit.mdx',
    section: 'reference',
    keywords: ['ledger', 'hash chain', 'csv', 'role changes', 'permissions', 'soc 2'],
  },
  {
    id: 'reviews',
    title: 'Reviews and the approval gate',
    summary: 'Review a draft version, approve or request changes, and require approvals before publishing.',
    page: 'apiome-docs/docs/govern/reviews.mdx',
    section: 'reference',
    keywords: ['approve', 'request changes', 'reviewer', 'round', 'force publish'],
  },
  {
    id: 'docs-image',
    title: 'Host the documentation site',
    summary: 'Serve this guide next to your Apiome installation from the apiome-docs Docker image.',
    page: 'apiome-docs/docs/admin/docs-image.mdx',
    section: 'reference',
    keywords: ['docker', 'self-host', 'nginx', 'docs image'],
  },
  {
    id: 'contribute-to-the-docs',
    title: 'Contribute to the docs',
    summary: 'Write a docs page, add a screenshot to the manifest, and pass the docs gate.',
    page: 'apiome-docs/docs/admin/contribute-to-the-docs.mdx',
    section: 'reference',
    keywords: ['screenshot', 'docusaurus', 'manifest', 'playwright', 'documentation', 'writing'],
  },
  {
    id: 'README',
    title: 'User guide index',
    summary: 'The documentation site home, grouped by job: build, bring in, ship, govern and reference.',
    page: 'apiome-docs/docs/getting-started/index.mdx',
    section: 'reference',
    keywords: ['contents', 'overview', 'all guides', 'documentation', 'spine'],
  },
] as const;

/** How many results the search shows at once. */
export const GUIDE_RESULT_LIMIT = 8;

/**
 * The shortest query that searches.
 *
 * One character matches most of the set, which is a wall of rows rather than an answer; two
 * is the point at which the result list says something.
 */
export const GUIDE_QUERY_MIN_LENGTH = 2;

/** Where a guide is read. */
export function guideHref(entry: GuideEntry): string {
  return buildDocsHref(entry.page);
}

/** What a term matching a given field is worth. Title beats summary beats keyword. */
const FIELD_WEIGHT = { title: 6, summary: 2, keyword: 3 } as const;

/** Extra credit for a term that starts the title — "impo" should reach *Import a spec* first. */
const TITLE_PREFIX_BONUS = 4;

/**
 * Split a query into the terms every result has to satisfy.
 *
 * @param query What the reader typed.
 * @returns Lower-cased, non-empty terms; empty when the query is too short to search.
 */
function queryTerms(query: string): string[] {
  const trimmed = query.trim().toLowerCase();
  if (trimmed.length < GUIDE_QUERY_MIN_LENGTH) return [];
  return trimmed.split(/\s+/).filter(Boolean);
}

/**
 * Score one guide against one term.
 *
 * @param entry The guide.
 * @param term A lower-cased search term.
 * @returns The term's contribution, or `0` when the guide does not match it at all.
 */
function scoreTerm(entry: GuideEntry, term: string): number {
  let score = 0;

  const title = entry.title.toLowerCase();
  if (title.includes(term)) {
    score += FIELD_WEIGHT.title;
    if (title.startsWith(term)) score += TITLE_PREFIX_BONUS;
  }

  if (entry.summary.toLowerCase().includes(term)) score += FIELD_WEIGHT.summary;

  // The id is the file name, so `mcp-quickstart` finds the page a reader saw in a URL.
  if (entry.id.toLowerCase().includes(term)) score += FIELD_WEIGHT.keyword;

  if (entry.keywords.some((keyword) => keyword.toLowerCase().includes(term))) {
    score += FIELD_WEIGHT.keyword;
  }

  return score;
}

/**
 * Search the guide set.
 *
 * Every term has to match something — a second word narrows the result list rather than
 * widening it — and results are ranked by total score, ties broken by the catalog's own
 * order so the same query always returns the same list.
 *
 * @param query What the reader typed. Shorter than {@link GUIDE_QUERY_MIN_LENGTH} returns
 *   nothing, which is how the page knows to show its cards instead of a result list.
 * @param entries The set to search. Defaults to {@link GUIDE_ENTRIES}; a test passes its own.
 * @returns At most {@link GUIDE_RESULT_LIMIT} guides, best match first.
 */
export function searchGuides(
  query: string,
  entries: readonly GuideEntry[] = GUIDE_ENTRIES
): readonly GuideEntry[] {
  const terms = queryTerms(query);
  if (terms.length === 0) return [];

  const scored: Array<{ entry: GuideEntry; score: number; order: number }> = [];

  entries.forEach((entry, order) => {
    let total = 0;
    for (const term of terms) {
      const score = scoreTerm(entry, term);
      // One unmatched term disqualifies the guide: adding a word must never widen the list.
      if (score === 0) return;
      total += score;
    }
    scored.push({ entry, score: total, order });
  });

  return scored
    .sort((a, b) => b.score - a.score || a.order - b.order)
    .slice(0, GUIDE_RESULT_LIMIT)
    .map((result) => result.entry);
}
