import type { Tone } from "../components/ui/GlassCard";

export type SuiteStatus = "coming-soon" | "early-access" | "beta";

export type SuiteFeature = {
  title: string;
  description: string;
};

export type SuiteUseCase = {
  audience: string;
  scenario: string;
};

export type SuiteScreenshot = {
  src: string;
  alt: string;
  caption: string;
};

export type Suite = {
  /** URL slug under /suite/<slug> */
  slug: string;
  /** Short product name, e.g. "Academy" */
  name: string;
  /** Full marketing name, e.g. "Apiome Academy" */
  fullName: string;
  /** Brand category, e.g. "Learning · Enablement" */
  category: string;
  /** One-line tagline used on cards and the hero */
  tagline: string;
  /** 2–3 sentence summary used on the index card and detail intro */
  summary: string;
  /** Colour tone used by the GlassCard / chip system */
  tone: Tone;
  /** lucide-react icon name (resolved to an icon at render time) */
  icon: string;
  /** Launch status flag */
  status: SuiteStatus;
  /** Cover image (large hero) — `/suite/<slug>-cover.png` */
  cover: string;
  /** Hub / catalogue screenshot — `/suite/<slug>-hub.png` */
  hub: string;
  /** Additional in-product screenshots */
  details: SuiteScreenshot[];
  /** Headline capability list */
  features: SuiteFeature[];
  /** Who benefits and how */
  useCases: SuiteUseCase[];
  /** Enterprise-only differentiators */
  enterprise: string[];
  /** AI integration story */
  ai: {
    headline: string;
    description: string;
    capabilities: string[];
  };
  /** Cross-references to mockup pages (relative names of html files) */
  modules: string[];
  /** Marketing metrics shown on the detail page */
  highlights: { label: string; value: string }[];
};

const detailAlt = (name: string, what: string) => `${name} — ${what}`;

export const SUITES: Suite[] = [
  // ─────────────────────────────────────────────────────────────── Academy
  {
    slug: "academy",
    name: "Academy",
    fullName: "Apiome Academy",
    category: "Learning · Enablement",
    tagline:
      "An LMS purpose-built for API & data teams — turn your platform into a curriculum.",
    summary:
      "Apiome Academy is a full learning platform that ships with your tenant. Author courses, lessons, quizzes, and badges right next to the schemas they describe — and let new engineers ramp on your APIs through guided, gamified paths instead of stale wiki pages.",
    tone: "indigo",
    icon: "GraduationCap",
    status: "coming-soon",
    cover: "/suite/academy-cover.png",
    hub: "/suite/academy-hub.png",
    details: [
      {
        src: "/suite/academy-detail-1.png",
        alt: detailAlt("Academy", "Course catalog"),
        caption: "Filterable course catalog with full-text search and rich sort.",
      },
      {
        src: "/suite/academy-detail-2.png",
        alt: detailAlt("Academy", "Course detail"),
        caption: "Course detail with syllabus, prerequisites, and enrollment CTA.",
      },
      {
        src: "/suite/academy-detail-3.png",
        alt: detailAlt("Academy", "Lesson viewer"),
        caption: "Block-rendered lesson viewer with progress and inline quizzes.",
      },
    ],
    features: [
      { title: "Block-based course authoring", description: "Compose lessons from text, code, video, embeds, and quizzes with live preview." },
      { title: "Rich media library", description: "Upload pipeline with chunked transfers, thumbnail processing, and asset reuse." },
      { title: "Student dashboard", description: "Continue-learning rail, streaks, leaderboards, and AI-generated recommendations." },
      { title: "Quizzes & assessments", description: "Inline quizzes with instant feedback and pass-grade tracking per lesson." },
      { title: "Badges & achievements", description: "Earned and locked badge walls, share-modal, and verifiable credential URLs." },
      { title: "Catalog & discovery", description: "Faceted catalog with curated tracks for new hires, partners, or external developers." },
    ],
    useCases: [
      { audience: "Platform teams", scenario: "Onboard new engineers to a 200-schema domain in days instead of months." },
      { audience: "Developer relations", scenario: "Publish API certification tracks customers must complete to unlock production keys." },
      { audience: "Customer success", scenario: "Bundle role-based learning paths with each enterprise contract." },
    ],
    enterprise: [
      "SSO / SCIM provisioning for cohort enrollment",
      "Per-tenant white-labeling, custom domains, and brand themes",
      "SCORM / xAPI exports for corporate LMS interoperability",
      "Compliance-grade completion reports and certificate issuance",
      "Granular roles: author, reviewer, instructor, learner, admin",
    ],
    ai: {
      headline: "AI co-author for every lesson",
      description:
        "Academy ships with an AI tutor that drafts lessons from your schemas, generates quiz questions from API specs, and recommends what each learner should study next.",
      capabilities: [
        "Draft full courses from a schema or OpenAPI spec",
        "Auto-generate quizzes that test real endpoint behavior",
        "Personalized next-best-lesson recommendations per learner",
        "Inline AI tutor that answers learner questions in context",
      ],
    },
    modules: [
      "catalog",
      "course-detail",
      "course-editor",
      "lesson-viewer",
      "media-library",
      "student-dashboard",
      "badges",
    ],
    highlights: [
      { label: "Lesson formats", value: "12+" },
      { label: "Assessment types", value: "5" },
      { label: "Native formats", value: "MDX · SCORM · xAPI" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Analytics
  {
    slug: "analytics",
    name: "Analytics",
    fullName: "Apiome Analytics",
    category: "Insight · Reporting",
    tagline:
      "Executive-grade analytics across every API, schema, and team in your tenant.",
    summary:
      "Analytics turns operational telemetry into board-room narratives. Track adoption of every endpoint, the health of every schema, and the velocity of every team — then schedule beautiful, branded reports straight to stakeholder inboxes.",
    tone: "blue",
    icon: "BarChart3",
    status: "coming-soon",
    cover: "/suite/analytics-cover.png",
    hub: "/suite/analytics-hub.png",
    details: [
      {
        src: "/suite/analytics-detail-1.png",
        alt: detailAlt("Analytics", "API analytics"),
        caption: "Per-endpoint adoption, latency, error-rate, and consumer breakdown.",
      },
      {
        src: "/suite/analytics-detail-2.png",
        alt: detailAlt("Analytics", "Schema analytics"),
        caption: "Schema usage heatmaps with property-level reach and drift.",
      },
      {
        src: "/suite/analytics-detail-3.png",
        alt: detailAlt("Analytics", "Export center"),
        caption: "Export center with scheduled PDF, CSV, and dashboard delivery.",
      },
    ],
    features: [
      { title: "Executive dashboard", description: "Curated KPIs for adoption, quality, velocity, and cost across the whole tenant." },
      { title: "API analytics", description: "Per-endpoint volume, latency, error class, and consumer cohort breakdowns." },
      { title: "Schema analytics", description: "Field-level usage, drift signals, and unused-property detection." },
      { title: "Team analytics", description: "Velocity, review throughput, and quality-trend indices per team and product." },
      { title: "Export center", description: "Schedule branded PDFs, CSV exports, and dashboards to people, channels, or storage." },
      { title: "Custom reports", description: "Drag-and-drop report builder with templates for QBRs and board reviews." },
    ],
    useCases: [
      { audience: "VP Engineering", scenario: "Run a Monday morning health review without opening 10 tabs." },
      { audience: "Product managers", scenario: "Prove which endpoints actually move the metric you care about." },
      { audience: "Finance", scenario: "Tie API consumption directly to billing & revenue events." },
    ],
    enterprise: [
      "Row-level security across every metric and dimension",
      "SOC 2 / HIPAA compliant data warehouse residency",
      "SLA-backed real-time roll-ups and 13-month retention",
      "BI connectors for Looker, Tableau, Power BI, and Snowflake share",
      "Anomaly alerting with PagerDuty / Opsgenie / webhook routing",
    ],
    ai: {
      headline: "Ask your data anything",
      description:
        "Natural-language analytics turn questions like “which endpoints regressed this week?” into instantly rendered dashboards with citations to the underlying events.",
      capabilities: [
        "Natural-language query bar over every metric and dimension",
        "Automated weekly insight digests with anomaly call-outs",
        "AI-suggested KPIs based on tenant usage patterns",
        "Forecasts with confidence bands for adoption and cost",
      ],
    },
    modules: ["executive-dashboard", "api-analytics", "schema-analytics", "team-analytics", "export-center"],
    highlights: [
      { label: "Pre-built KPIs", value: "60+" },
      { label: "Data freshness", value: "≤ 30s" },
      { label: "Retention", value: "13 months" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Architect
  {
    slug: "architect",
    name: "Architect",
    fullName: "Apiome Architect",
    category: "Architecture · Governance",
    tagline:
      "A living system landscape — every service, schema, and decision in one canvas.",
    summary:
      "Architect maps your entire technology landscape, traces dependencies and data flow, enforces architectural patterns, and keeps ADRs version-controlled next to the systems they govern. Treat your architecture like code — searchable, reviewable, and always current.",
    tone: "violet",
    icon: "LayoutGrid",
    status: "coming-soon",
    cover: "/suite/architect-cover.png",
    hub: "/suite/architect-hub.png",
    details: [
      {
        src: "/suite/architect-detail-1.png",
        alt: detailAlt("Architect", "Data flow"),
        caption: "Cross-system data flow with PII, residency, and consent overlays.",
      },
      {
        src: "/suite/architect-detail-2.png",
        alt: detailAlt("Architect", "Impact analysis"),
        caption: "Blast-radius analysis for any proposed schema or service change.",
      },
      {
        src: "/suite/architect-detail-3.png",
        alt: detailAlt("Architect", "ADR catalog"),
        caption: "Searchable ADR catalog with status, supersession, and reviewers.",
      },
    ],
    features: [
      { title: "System landscape canvas", description: "Auto-layout map of services, datastores, and external integrations." },
      { title: "Dependency analysis", description: "Trace upstream and downstream impact for any schema, path, or service." },
      { title: "Pattern catalog", description: "A library of approved patterns with “use-this / never-use-this” guidance." },
      { title: "Compliance checker", description: "Continuously scan systems against architectural rules and tag drift." },
      { title: "ADR management", description: "Author, review, and supersede Architectural Decision Records inline." },
      { title: "Impact analysis", description: "What-if simulations for major refactors, deprecations, and tenant migrations." },
    ],
    useCases: [
      { audience: "Principal engineers", scenario: "Stop relying on tribal knowledge — query the landscape instead." },
      { audience: "Security teams", scenario: "See exactly which services touch regulated data and where it flows." },
      { audience: "M&A integration", scenario: "Diff two acquired companies' landscapes side-by-side." },
    ],
    enterprise: [
      "Multi-portfolio support across BUs and acquired companies",
      "Policy-as-code enforcement gates wired into CI/CD",
      "Read-only board / regulator views with narrative annotations",
      "Federated landscape sync from Backstage, ServiceNow, and IT4IT sources",
      "Custom diagram exports (C4, ArchiMate, SVG, Confluence sync)",
    ],
    ai: {
      headline: "Architectural reasoning, on tap",
      description:
        "Ask Architect to summarize a domain, propose a refactor, or explain a 12-year-old ADR — every answer is grounded in the live landscape and decision history.",
      capabilities: [
        "Natural-language landscape queries (“who depends on Billing v2?”)",
        "AI-drafted ADRs from chat threads and meeting notes",
        "Pattern conformance scoring with auto-suggested fixes",
        "Refactor planner that proposes safe migration sequences",
      ],
    },
    modules: ["landscape", "data-flow", "impact-analysis", "pattern-catalog", "compliance-checker", "adrs"],
    highlights: [
      { label: "Diagram styles", value: "C4 · ArchiMate · custom" },
      { label: "Pattern templates", value: "40+" },
      { label: "Live drift scans", value: "Continuous" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Automation
  {
    slug: "automation",
    name: "Automation",
    fullName: "Apiome Automation",
    category: "Workflow · Orchestration",
    tagline:
      "Webhooks, scheduled jobs, and CI/CD workflows native to your platform.",
    summary:
      "Automation is the event spine of Apiome — fire webhooks on any platform event, schedule recurring jobs, build approval chains, and connect to GitHub, GitLab, Slack, and your CI/CD pipelines without a third-party iPaaS.",
    tone: "orange",
    icon: "Zap",
    status: "coming-soon",
    cover: "/suite/automation-cover.png",
    hub: "/suite/automation-hub.png",
    details: [
      {
        src: "/suite/automation-detail-1.png",
        alt: detailAlt("Automation", "Webhooks"),
        caption: "Webhook registry with HMAC signing, retries, and per-endpoint stats.",
      },
      {
        src: "/suite/automation-detail-2.png",
        alt: detailAlt("Automation", "Scheduled jobs"),
        caption: "Scheduled jobs with cron, timezone-aware runs, and historical timelines.",
      },
      {
        src: "/suite/automation-detail-3.png",
        alt: detailAlt("Automation", "Integrations marketplace"),
        caption: "First-party integrations for GitHub, GitLab, Slack, Jira, PagerDuty, and more.",
      },
    ],
    features: [
      { title: "Event-driven webhooks", description: "Fire webhooks on any platform event with HMAC signing and exponential retries." },
      { title: "Scheduled jobs", description: "Cron-style scheduler with timezone awareness, blackout windows, and run history." },
      { title: "Approval chains", description: "Multi-step, multi-party approvals wired into both webhooks and CI/CD." },
      { title: "Workflow timeline", description: "Unified timeline across triggers, jobs, integrations, and delivery logs." },
      { title: "Integration catalog", description: "Pre-built connectors for GitHub, GitLab, Slack, Jira, PagerDuty, and Webhooks." },
      { title: "Webhook tester", description: "Replay, redact, and step-through delivery payloads for fast debugging." },
    ],
    useCases: [
      { audience: "Platform engineers", scenario: "Trigger CI on every approved schema change without writing glue code." },
      { audience: "SRE teams", scenario: "Open a PagerDuty incident the instant a quality score drops below threshold." },
      { audience: "Compliance officers", scenario: "Route every contract change through a 3-party signoff with auditable history." },
    ],
    enterprise: [
      "FedRAMP-aligned outbound proxy with allow-listed destinations",
      "Self-hosted runners for on-prem CI/CD targets",
      "Tenant-isolated secrets vaults for webhook signing keys",
      "Workflow blueprints for SOC 2, ISO 27001, and HIPAA controls",
      "Org-wide rate limits, queue priorities, and burst budgets",
    ],
    ai: {
      headline: "Workflows that write themselves",
      description:
        "Describe what should happen — “when a breaking change is merged, post in #api-platform and open a Jira” — and Automation drafts the trigger, integration, and approvals for you.",
      capabilities: [
        "Natural-language workflow builder",
        "AI-suggested fixes for failing webhook deliveries",
        "Anomaly detection across job runtimes and queue depths",
        "Auto-generated runbooks for every integration failure",
      ],
    },
    modules: ["dashboard", "webhooks", "webhook-test", "jobs", "triggers", "integrations", "approvals", "delivery-logs", "timeline"],
    highlights: [
      { label: "First-party integrations", value: "20+" },
      { label: "Delivery success", value: "99.95%" },
      { label: "Retry strategies", value: "Adaptive" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Browser
  {
    slug: "browser",
    name: "Browser",
    fullName: "Apiome Browser",
    category: "Public · Developer Portal",
    tagline:
      "A polished public face for every API your tenant publishes.",
    summary:
      "Browser is the public-facing portal for your APIs — tenant home pages, Monaco-powered spec viewers, version comparison, embeddable snippets, and a try-it playground. Ship a beautiful developer hub without building one.",
    tone: "sky",
    icon: "Globe",
    status: "coming-soon",
    cover: "/suite/browser-cover.png",
    hub: "/suite/browser-hub.png",
    details: [
      {
        src: "/suite/browser-detail-1.png",
        alt: detailAlt("Browser", "Spec viewer"),
        caption: "Monaco-powered spec viewer with deep links to operations and schemas.",
      },
      {
        src: "/suite/browser-detail-2.png",
        alt: detailAlt("Browser", "Version compare"),
        caption: "Side-by-side compare with semantic diff for breaking changes.",
      },
      {
        src: "/suite/browser-detail-3.png",
        alt: detailAlt("Browser", "Try-it playground"),
        caption: "Try-it playground with auth presets, history, and shareable runs.",
      },
    ],
    features: [
      { title: "Tenant home pages", description: "Branded landing pages summarizing every published API per tenant." },
      { title: "Spec viewer", description: "Monaco-powered code view with deep links into any operation or schema." },
      { title: "Version compare", description: "Semantic diff highlighting added, removed, and breaking changes." },
      { title: "Share & embed", description: "Embed live spec snippets in docs sites with auto-updating versions." },
      { title: "Global search", description: "Cross-tenant search over operations, schemas, tags, and changelogs." },
      { title: "Try-it playground", description: "Run real requests with auth presets and shareable result links." },
    ],
    useCases: [
      { audience: "Developer relations", scenario: "Replace your hand-built API docs site with a maintained hub." },
      { audience: "External developers", scenario: "Discover, try, and integrate APIs without leaving the browser." },
      { audience: "Sales engineering", scenario: "Send prospects a live, embed-able snippet instead of a static PDF." },
    ],
    enterprise: [
      "Custom domains, white-label themes, and per-tenant branding",
      "Visibility controls — public, partner-gated, or fully private",
      "Embed SDK with allowlisted origins and analytics",
      "Audience analytics tied back to Apiome Analytics",
      "Automatic search-engine indexing controls per surface",
    ],
    ai: {
      headline: "Search that understands intent",
      description:
        "Browser ships with semantic search, AI-generated changelog summaries, and a chat assistant that can answer “how do I list invoices for a customer?” with the right endpoint and a working example.",
      capabilities: [
        "Semantic search across every published spec",
        "AI changelog summarisation per release",
        "Conversational API assistant grounded in your specs",
        "Auto-generated code snippets in 8+ languages",
      ],
    },
    modules: ["tenant-home", "version-viewer", "compare", "embed-share", "search", "playground", "changelog", "analytics"],
    highlights: [
      { label: "Spec formats", value: "OpenAPI · Swagger · AsyncAPI · GraphQL · gRPC" },
      { label: "Snippet languages", value: "8+" },
      { label: "Embed targets", value: "Any docs site" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Code-Gen
  {
    slug: "code-gen",
    name: "Code Generation",
    fullName: "Apiome Code Generation",
    category: "DevEx · Productivity",
    tagline:
      "Production-ready SDKs, server stubs, CRUD, and mock data from your specs.",
    summary:
      "Code Generation turns every schema and path into working code — typed clients, server stubs, CRUD endpoints, and realistic mock data — across the languages your stack speaks. Keep clients in lock-step with the spec, automatically.",
    tone: "purple",
    icon: "FileCode",
    status: "coming-soon",
    cover: "/suite/code-gen-cover.png",
    hub: "/suite/code-gen-hub.png",
    details: [
      {
        src: "/suite/code-gen-detail-1.png",
        alt: detailAlt("Code Generation", "Client SDK"),
        caption: "Typed client SDKs with auth, retries, and pagination baked in.",
      },
      {
        src: "/suite/code-gen-detail-2.png",
        alt: detailAlt("Code Generation", "Server stubs"),
        caption: "Server stubs scaffolded for FastAPI, NestJS, Spring, Go, and more.",
      },
      {
        src: "/suite/code-gen-detail-3.png",
        alt: detailAlt("Code Generation", "Mock data"),
        caption: "Realistic mock-data generator with locale-aware seed data.",
      },
    ],
    features: [
      { title: "Schema-to-code", description: "Generate DTOs, models, and validators in TypeScript, Python, Go, Java, and more." },
      { title: "Client SDKs", description: "Typed SDKs with built-in auth, retries, pagination, and error envelope handling." },
      { title: "Server stubs", description: "Scaffolds for FastAPI, NestJS, Spring, Go, and ASP.NET — wired to your paths." },
      { title: "CRUD generator", description: "Spin up a working CRUD service from any schema with seeded persistence." },
      { title: "Mock data", description: "Locale-aware fake data tuned by property names, formats, and constraints." },
      { title: "Generation studio", description: "Browse, configure, and preview every artefact before committing." },
    ],
    useCases: [
      { audience: "Frontend teams", scenario: "Stop hand-rolling API clients — pull a typed SDK on every spec change." },
      { audience: "Backend teams", scenario: "Bootstrap a new microservice in minutes from an approved schema." },
      { audience: "QA teams", scenario: "Power test environments with deterministic, realistic mock data." },
    ],
    enterprise: [
      "Private template registry with org-approved generators",
      "Signed artefacts published to private npm / PyPI / Maven feeds",
      "Reproducible builds with pinned generator versions and SBOMs",
      "Custom code-style presets (lint, formatter, license headers)",
      "Pre-merge generator runs in CI with quality gates",
    ],
    ai: {
      headline: "Generators that respect your code style",
      description:
        "AI tunes generated code to match your existing patterns — naming conventions, error handling, lint rules — so the output reads like a teammate wrote it.",
      capabilities: [
        "Style-aware generators trained on your repo conventions",
        "AI-suggested CRUD operations from any schema",
        "Mock-data tuned by domain (medical, finance, retail, …)",
        "Auto-generated tests covering happy-path and edge cases",
      ],
    },
    modules: ["studio", "client-sdk", "server-stubs", "crud-generator", "mock-data", "jobs", "settings"],
    highlights: [
      { label: "Languages", value: "10+" },
      { label: "Server frameworks", value: "12+" },
      { label: "Generation speed", value: "≤ 5s" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Collaboration
  {
    slug: "collaboration",
    name: "Collaboration",
    fullName: "Apiome Collaboration",
    category: "Teamwork · Review",
    tagline:
      "Real-time editing, threaded reviews, and approval workflows on every artifact.",
    summary:
      "Collaboration brings Figma-grade presence to schema and path design. Co-edit in real time, leave threaded comments anchored to nodes, manage change requests with reviewers, and run formal approval workflows — all without leaving the canvas.",
    tone: "emerald",
    icon: "Users",
    status: "coming-soon",
    cover: "/suite/collaboration-cover.png",
    hub: "/suite/collaboration-hub.png",
    details: [
      {
        src: "/suite/collaboration-detail-1.png",
        alt: detailAlt("Collaboration", "Comments"),
        caption: "Threaded comments anchored to canvas nodes and properties.",
      },
      {
        src: "/suite/collaboration-detail-2.png",
        alt: detailAlt("Collaboration", "Diff viewer"),
        caption: "Visual diff viewer with semantic change highlighting.",
      },
      {
        src: "/suite/collaboration-detail-3.png",
        alt: detailAlt("Collaboration", "Approvals"),
        caption: "Multi-stage approvals with required reviewers and SLAs.",
      },
    ],
    features: [
      { title: "Real-time multiplayer", description: "Live cursors, selections, and edits with conflict-free CRDT replication." },
      { title: "Comments & threads", description: "Anchor discussions to any node, edge, or property — with mentions and reactions." },
      { title: "Change requests", description: "Spec-aware pull-requests with reviewer assignment and required approvers." },
      { title: "Diff viewer", description: "Side-by-side and overlay diffs that understand schemas, paths, and policies." },
      { title: "Activity & inbox", description: "Unified inbox for mentions, reviews, approvals, and team broadcasts." },
      { title: "Team management", description: "Spaces, roles, default reviewers, and per-team notification preferences." },
    ],
    useCases: [
      { audience: "API design groups", scenario: "Run synchronous design reviews on the live canvas with the whole team." },
      { audience: "Distributed teams", scenario: "Replace 30-minute meetings with asynchronous threaded reviews." },
      { audience: "Governance teams", scenario: "Require sign-off from security or legal before any breaking change ships." },
    ],
    enterprise: [
      "Tenant-isolated CRDT relay with per-region residency",
      "Audit-grade event log for every comment, edit, and approval",
      "Required-reviewer policies enforced via CODEOWNERS-style rules",
      "Slack & Teams two-way mirror for review threads",
      "Read-only observer roles for auditors and external counsel",
    ],
    ai: {
      headline: "AI reviewer on every change request",
      description:
        "AI summarizes diffs, flags risky changes, and pre-fills review comments so humans focus on judgement, not boilerplate.",
      capabilities: [
        "Plain-English summaries of every diff",
        "AI-suggested reviewers based on file ownership and history",
        "Risk scoring for breaking changes and security regressions",
        "Auto-drafted release notes from approved change requests",
      ],
    },
    modules: ["workspace", "comments", "diff-viewer", "approvals", "change-requests", "activity", "notifications", "teams"],
    highlights: [
      { label: "Concurrent editors", value: "Unlimited" },
      { label: "Replay window", value: "90 days" },
      { label: "Review templates", value: "Custom" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Connect
  {
    slug: "connect",
    name: "Connect",
    fullName: "Apiome Connect",
    category: "Integration · iPaaS",
    tagline:
      "A built-in iPaaS — connectors, schema mapping, real-time sync, and event routing.",
    summary:
      "Connect is the integration plane: a connector framework, visual schema mapping, real-time CDC sync, and an event router. Move data between Apiome and the rest of your stack without standing up a separate iPaaS.",
    tone: "cyan",
    icon: "Network",
    status: "coming-soon",
    cover: "/suite/connect-cover.png",
    hub: "/suite/connect-hub.png",
    details: [
      {
        src: "/suite/connect-detail-1.png",
        alt: detailAlt("Connect", "Mapping editor"),
        caption: "Visual mapping editor with transforms, filters, and live preview.",
      },
      {
        src: "/suite/connect-detail-2.png",
        alt: detailAlt("Connect", "Event router"),
        caption: "Event router with topics, subscriptions, and DLQ handling.",
      },
      {
        src: "/suite/connect-detail-3.png",
        alt: detailAlt("Connect", "Marketplace"),
        caption: "Connector marketplace with first-party and community connectors.",
      },
    ],
    features: [
      { title: "Connector framework", description: "Pluggable connectors with lifecycle, secrets, retries, and health checks." },
      { title: "Schema mapping", description: "Visual mapper with transforms, derived fields, and reusable function library." },
      { title: "Real-time sync & CDC", description: "Change-data-capture pipelines with at-least-once delivery and replay." },
      { title: "Event-driven messaging", description: "Topics, subscriptions, filters, and DLQ for the messaging substrate." },
      { title: "Connection wizard", description: "Guided onboarding for OAuth, API keys, and self-hosted edge agents." },
      { title: "Conflict resolver", description: "Configurable merge strategies and human-in-the-loop conflict workspace." },
    ],
    useCases: [
      { audience: "Data engineers", scenario: "Sync versioned records from Apiome Database to your downstream warehouse." },
      { audience: "Integration teams", scenario: "Replace bespoke ETL scripts with versioned, reviewable mappings." },
      { audience: "Field engineers", scenario: "Push tenant-scoped data to customer systems via signed webhooks or files." },
    ],
    enterprise: [
      "Self-hosted edge runners for on-prem source systems",
      "Encryption-at-rest with customer-managed KMS keys",
      "Connector code signing and supply-chain attestation",
      "Tenant-isolated event buses with per-topic ACLs",
      "DR-grade replay with 30-day retention windows",
    ],
    ai: {
      headline: "Mapping by demonstration",
      description:
        "Drop in a sample of source and target records — Connect proposes the mapping, the transforms, and the test cases.",
      capabilities: [
        "AI-proposed field mappings from schema similarity",
        "Anomaly detection on sync volume, latency, and error rates",
        "Natural-language transform builder",
        "Auto-suggested DLQ remediation playbooks",
      ],
    },
    modules: ["dashboard", "connections", "connection-wizard", "mapping-editor", "transforms", "templates", "sync-jobs", "sync-logs", "event-router", "webhooks", "marketplace", "sdk", "conflicts"],
    highlights: [
      { label: "Connectors at launch", value: "30+" },
      { label: "Throughput", value: "100k events/s" },
      { label: "Delivery", value: "At-least-once" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Contracts
  {
    slug: "contracts",
    name: "Contracts",
    fullName: "Apiome Contracts",
    category: "Commercial · Compliance",
    tagline:
      "Programmable data contracts — terms, consent, billing, and audit in one place.",
    summary:
      "Contracts gives every API a real legal and commercial spine: machine-readable terms, consent capture, usage-based billing, and a tamper-evident audit trail. Negotiate, sign, and enforce data-sharing agreements without bouncing between tools.",
    tone: "rose",
    icon: "ScrollText",
    status: "coming-soon",
    cover: "/suite/contracts-cover.png",
    hub: "/suite/contracts-hub.png",
    details: [
      {
        src: "/suite/contracts-detail-1.png",
        alt: detailAlt("Contracts", "Terms editor"),
        caption: "Block-based terms editor with reusable clauses and redlines.",
      },
      {
        src: "/suite/contracts-detail-2.png",
        alt: detailAlt("Contracts", "Billing & invoices"),
        caption: "Usage-based billing tied directly to API consumption events.",
      },
      {
        src: "/suite/contracts-detail-3.png",
        alt: detailAlt("Contracts", "Consent capture"),
        caption: "Consent capture with versioned receipts and revocation flows.",
      },
    ],
    features: [
      { title: "Contract builder", description: "Reusable clauses, branching templates, and side-by-side redlining." },
      { title: "Data sharing", description: "Scope APIs to specific counterparties with field-level allowlists." },
      { title: "Consent management", description: "Versioned consent receipts, revocation flows, and replay-safe audit." },
      { title: "Billing & revenue", description: "Usage-based billing tied to telemetry, with invoices and dispute handling." },
      { title: "E-signature", description: "Native sign flow with attachments, witnesses, and tamper-evident hashes." },
      { title: "Compliance audit", description: "Compliance dashboard with control coverage and evidence pack export." },
    ],
    useCases: [
      { audience: "Data partnerships", scenario: "Negotiate API terms once and enforce them automatically at the edge." },
      { audience: "RevOps", scenario: "Bill customers on real consumption metrics with itemised invoices." },
      { audience: "Privacy & legal", scenario: "Prove consent for any downstream data use, on demand." },
    ],
    enterprise: [
      "DocuSign / Adobe Sign federation alongside native sign",
      "Stripe / NetSuite / SAP integrations for billing pipelines",
      "Policy-as-code enforcement at the API gateway",
      "Tamper-evident WORM storage with optional on-chain anchoring",
      "Regulator-ready evidence pack exports (SOC 2, ISO, GDPR, HIPAA)",
    ],
    ai: {
      headline: "Contracts that explain themselves",
      description:
        "AI summarizes contracts into plain language, flags risky clauses, and proposes counter-redlines — grounded in your firm's playbook.",
      capabilities: [
        "Plain-English contract summaries with risk flags",
        "AI-proposed redlines from your firm's playbook",
        "Anomaly detection on usage and billing patterns",
        "Auto-drafted dispute responses from telemetry evidence",
      ],
    },
    modules: ["dashboard", "templates", "terms-editor", "negotiate", "sign", "data-sharing", "consent", "billing", "invoice", "usage", "disputes", "compliance", "history"],
    highlights: [
      { label: "Clause library", value: "200+" },
      { label: "E-sign jurisdictions", value: "Global" },
      { label: "Audit retention", value: "7+ years" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Data Insights
  {
    slug: "data-insights",
    name: "Data Insights",
    fullName: "Apiome Data Insights",
    category: "Product · Outcome Analytics",
    tagline:
      "Outcome-grade analytics: churn, funnels, revenue, tech debt, and DX in one place.",
    summary:
      "Data Insights goes beyond raw metrics to surface the outcomes that matter: customer health, churn risk, conversion funnels, revenue, and developer experience. Build dashboards, schedule reports, and let AI tell you what to investigate next.",
    tone: "teal",
    icon: "TrendingUp",
    status: "coming-soon",
    cover: "/suite/data-insights-cover.png",
    hub: "/suite/data-insights-hub.png",
    details: [
      {
        src: "/suite/data-insights-detail-1.png",
        alt: detailAlt("Data Insights", "Health score"),
        caption: "Per-customer health score with leading indicators and drill-down.",
      },
      {
        src: "/suite/data-insights-detail-2.png",
        alt: detailAlt("Data Insights", "Funnels"),
        caption: "Funnel analysis with cohort breakdown and step-by-step drop-off.",
      },
      {
        src: "/suite/data-insights-detail-3.png",
        alt: detailAlt("Data Insights", "Revenue"),
        caption: "Revenue waterfall with expansion, contraction, and churn attribution.",
      },
    ],
    features: [
      { title: "Dashboard builder", description: "Drag-and-drop dashboards with branded themes and shareable links." },
      { title: "Health scoring", description: "Composite health scores per tenant, customer, or product surface." },
      { title: "Churn analysis", description: "Predictive churn with leading indicators and intervention playbooks." },
      { title: "Funnel analytics", description: "Multi-step funnels with cohort breakdown and time-to-convert curves." },
      { title: "Revenue analytics", description: "MRR / ARR waterfalls, expansion, contraction, and churn attribution." },
      { title: "DX & tech-debt metrics", description: "Quality, deprecation, and developer-experience indices over time." },
    ],
    useCases: [
      { audience: "Customer success", scenario: "Catch at-risk accounts weeks before they churn." },
      { audience: "Product leaders", scenario: "Prove which feature investments actually moved the funnel." },
      { audience: "Engineering leadership", scenario: "Track tech-debt and DX velocity alongside business outcomes." },
    ],
    enterprise: [
      "Multi-portfolio roll-ups with role-aware visibility",
      "Predictive models with explainable feature attribution",
      "Scheduled QBR / board exports with branded narrative",
      "Reverse-ETL into CRM and CS tools (Salesforce, Gainsight, HubSpot)",
      "Fine-grained metric residency for regulated workloads",
    ],
    ai: {
      headline: "An analyst that never sleeps",
      description:
        "Insights' AI proactively surfaces the most important changes in your business each morning, with the chart, the cause, and the suggested action.",
      capabilities: [
        "Daily AI-generated insight digest",
        "Natural-language dashboard builder",
        "Causal-style diagnosis (“why did conversion drop?”)",
        "What-if scenario planner for pricing and packaging",
      ],
    },
    modules: ["dashboard-builder", "health-score", "churn", "funnels", "revenue", "pipeline", "portfolio", "tech-debt", "dx-metrics", "deprecation", "reports"],
    highlights: [
      { label: "Out-of-box dashboards", value: "30+" },
      { label: "Predictive models", value: "Bundled" },
      { label: "Reverse-ETL", value: "Salesforce · HubSpot" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Shield
  {
    slug: "data-shield",
    name: "Shield",
    fullName: "Apiome Shield",
    category: "Security · Runtime Protection",
    tagline:
      "API security & runtime protection — scanning, firewall, anomaly, and compliance.",
    summary:
      "Shield is the security plane for everything Apiome ships. OWASP-grade vulnerability scanning, runtime API firewall, ML anomaly detection, encrypted secret vault, and continuous compliance posture — all on one console.",
    tone: "red",
    icon: "ShieldHalf",
    status: "coming-soon",
    cover: "/suite/data-shield-cover.png",
    hub: "/suite/data-shield-hub.png",
    details: [
      {
        src: "/suite/data-shield-detail-1.png",
        alt: detailAlt("Shield", "Firewall"),
        caption: "API firewall with OWASP rules, rate limits, and decision pipeline.",
      },
      {
        src: "/suite/data-shield-detail-2.png",
        alt: detailAlt("Shield", "Anomaly detection"),
        caption: "Per-consumer ML anomaly profiles with tunable model card.",
      },
      {
        src: "/suite/data-shield-detail-3.png",
        alt: detailAlt("Shield", "Secret vault"),
        caption: "Encrypted vault with rotation, KMS, and tamper-evident audit log.",
      },
    ],
    features: [
      { title: "Vulnerability scanner", description: "Continuous scans across the OWASP API Top 10 with PII/over-exposure findings." },
      { title: "Runtime firewall", description: "OWASP-aligned rules, rate-limit policies, and a transparent decision pipeline." },
      { title: "Bot & DDoS defense", description: "Bot classification, signature library, and challenge-or-deny queueing." },
      { title: "Anomaly detection", description: "Per-consumer ML profiles with tunable sensitivity and explainable scores." },
      { title: "Threat feeds", description: "AbuseIPDB, GreyNoise, OTX feeds and a curated attack-pattern library." },
      { title: "Vault & leaks", description: "Encrypted secret vault with rotation, plus credential-leak detection across the web." },
    ],
    useCases: [
      { audience: "Security teams", scenario: "Replace 4 disparate tools with one console for API security." },
      { audience: "SRE / on-call", scenario: "Triage incidents with one timeline that fuses traffic, threats, and code." },
      { audience: "Compliance officers", scenario: "Show SOC 2 / PCI / GDPR posture as a live dashboard, not an annual audit." },
    ],
    enterprise: [
      "Bring-your-own KMS / HSM with per-tenant encryption envelopes",
      "Tamper-evident WORM log and SOC 2 / PCI / GDPR / HIPAA reports",
      "Zero-trust policies with simulator and Rego excerpt export",
      "PagerDuty / Opsgenie / SOAR integrations for live SOC workflows",
      "Geo-aware deployment with dedicated runtime nodes per region",
    ],
    ai: {
      headline: "AI SOC analyst on duty 24/7",
      description:
        "Shield's AI fuses signals from scans, firewall, anomalies, and threat feeds into ranked, plain-English investigation cards your team can action in seconds.",
      capabilities: [
        "Investigation summaries with linked evidence",
        "AI-suggested firewall rules from anomaly clusters",
        "Auto-classification of bot vs human vs unknown",
        "Compliance gap explanations and remediation steps",
      ],
    },
    modules: ["dashboard", "scanner", "sensitive-data", "auth-gaps", "scans", "firewall", "bots", "events", "anomalies", "threat-feeds", "alerts", "investigations", "vault", "leaks", "compliance", "policies"],
    highlights: [
      { label: "OWASP Top 10", value: "Full coverage" },
      { label: "Threat feeds", value: "Bundled" },
      { label: "Compliance frameworks", value: "SOC 2 · PCI · GDPR · HIPAA" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Data Transform
  {
    slug: "data-transform",
    name: "Data Transform",
    fullName: "Apiome Data Transform",
    category: "Migration · Versioning",
    tagline:
      "Schema migrations done right — compatibility, rules, plans, and Spark at scale.",
    summary:
      "Data Transform handles the gnarly side of evolving schemas at scale: compatibility analysis, declarative translation rules, blocking-condition guardrails, visual migration plans, an interim MongoDB store, and Apache Spark for parallel migrations.",
    tone: "amber",
    icon: "Wand2",
    status: "coming-soon",
    cover: "/suite/data-transform-cover.png",
    hub: "/suite/data-transform-hub.png",
    details: [
      {
        src: "/suite/data-transform-detail-1.png",
        alt: detailAlt("Data Transform", "Rule editor"),
        caption: "Declarative translation-rule editor with live before/after preview.",
      },
      {
        src: "/suite/data-transform-detail-2.png",
        alt: detailAlt("Data Transform", "Migration plan"),
        caption: "Step-by-step migration plan with dependencies and rollbacks.",
      },
      {
        src: "/suite/data-transform-detail-3.png",
        alt: detailAlt("Data Transform", "Spark jobs"),
        caption: "Apache Spark jobs panel for parallel mass-migration runs.",
      },
    ],
    features: [
      { title: "Compatibility report", description: "Diff and classify every change as safe, additive, breaking, or quarantined." },
      { title: "Translation rules", description: "Declarative field-level rules with reusable functions and unit tests." },
      { title: "Blocking conditions", description: "Guardrails that pause migrations on data quality or business-rule violations." },
      { title: "Migration plans", description: "Visual, step-by-step plans with dependencies, rollback, and dry-run mode." },
      { title: "MongoDB interim store", description: "Stage in-flight data before promoting it to your authoritative store." },
      { title: "Spark execution", description: "Parallel migration on Apache Spark for billion-row datasets." },
    ],
    useCases: [
      { audience: "Platform engineers", scenario: "Roll out a v2 schema across 200 tenants without downtime." },
      { audience: "Data teams", scenario: "Re-shape historical data into a new model with full lineage retained." },
      { audience: "Compliance", scenario: "Apply a deletion or redaction policy across an entire portfolio in a single plan." },
    ],
    enterprise: [
      "Bring-your-own Spark cluster and MongoDB instance",
      "Policy gates on every plan (4-eyes, security, data-residency)",
      "Tamper-evident audit log per migration step",
      "Custom partitioning and parallelism budgets per tenant",
      "Disaster-recovery snapshots before any major version cut-over",
    ],
    ai: {
      headline: "Migrations that explain themselves",
      description:
        "AI explains every diff in plain language, generates rules from sample input/output, and picks safe migration sequences with confidence scoring.",
      capabilities: [
        "AI-generated translation rules from sample data",
        "Plain-English explanations of compatibility findings",
        "Anomaly detection on row-level transformation outcomes",
        "Suggested rollback playbooks for each plan",
      ],
    },
    modules: ["dashboard", "compatibility-report", "rule-sets", "rule-editor", "blocking-conditions", "version-policy", "deletion-policy", "migration-plans", "migration-plan-detail", "interim-store", "spark-jobs"],
    highlights: [
      { label: "Execution engine", value: "Apache Spark" },
      { label: "Interim store", value: "MongoDB" },
      { label: "Plan modes", value: "Dry-run · Live · Rollback" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── DB
  {
    slug: "db",
    name: "Database",
    fullName: "Apiome Database",
    category: "Storage · Event-Sourced",
    tagline:
      "An event-sourced instance database with NL queries, vectors, and time travel.",
    summary:
      "Database is the storage substrate for every Apiome class instance. Event-sourced writes, point-in-time queries, natural-language search, vector retrieval, and tiered storage — wrapped in tenant-grade governance.",
    tone: "blue",
    icon: "Database",
    status: "coming-soon",
    cover: "/suite/db-cover.png",
    hub: "/suite/db-hub.png",
    details: [
      {
        src: "/suite/db-detail-1.png",
        alt: detailAlt("Database", "NL query"),
        caption: "Natural-language query bar with SQL preview and result grid.",
      },
      {
        src: "/suite/db-detail-2.png",
        alt: detailAlt("Database", "Relationship graph"),
        caption: "Live relationship graph for any class instance and its neighbours.",
      },
      {
        src: "/suite/db-detail-3.png",
        alt: detailAlt("Database", "Vector search"),
        caption: "Vector search with hybrid keyword + semantic ranking.",
      },
    ],
    features: [
      { title: "Schema capture", description: "Versioned schema-of-record with deterministic upgrade paths." },
      { title: "Event-sourced writes", description: "Every change is a replayable event with full lineage and time travel." },
      { title: "Read & query API", description: "Visual query builder, SQL, and NL queries powered by the same engine." },
      { title: "Vector + AI search", description: "Hybrid lexical + semantic search across instances and attachments." },
      { title: "Bulk & batch ops", description: "Idempotent batch jobs with progress tracking and resumable execution." },
      { title: "Tiered storage", description: "Hot, warm, and cold tiers with per-tenant policies and S3-class offload." },
    ],
    useCases: [
      { audience: "Application teams", scenario: "Stand up new domain models in minutes with persistence already wired." },
      { audience: "Data scientists", scenario: "Run vector + SQL hybrid queries across the entire tenant data set." },
      { audience: "Compliance teams", scenario: "Replay any record's full history for legal hold or regulator review." },
    ],
    enterprise: [
      "Tenant-isolated event log with per-region residency",
      "Customer-managed encryption keys (KMS / HSM)",
      "Tiered storage with S3-class offload and intelligent tiering",
      "Granular role-based access control down to property level",
      "Backup & PITR with object-level restore",
    ],
    ai: {
      headline: "Query the way you think",
      description:
        "Type a question — AI converts it into a safe, parameterised query, explains what it does, and returns a ready-to-share result with provenance.",
      capabilities: [
        "Natural-language to safe SQL with explainable diffs",
        "Vector search tuned for your domain vocabulary",
        "AI-generated indexes from real query patterns",
        "Auto-summarisation of large result sets",
      ],
    },
    modules: ["dashboard", "schema-capture", "instance-browser", "instance-detail", "query-builder", "nl-query", "relationship-graph", "vector-search", "time-travel", "batch-jobs", "audit-log", "storage-tiers", "api-keys"],
    highlights: [
      { label: "Engines", value: "Postgres · Mongo · Redis" },
      { label: "Time travel", value: "Per-event" },
      { label: "Search", value: "Lexical + Vector" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Detective
  {
    slug: "detective",
    name: "Detective",
    fullName: "Apiome Detective",
    category: "Forensics · Investigation",
    tagline:
      "Forensic-grade investigation across instances, pipelines, and migrations.",
    summary:
      "Detective is the always-on investigator. Correlate signals across schemas, instances, and pipelines; reconcile discrepancies; reconstruct timelines for any record; and export evidence packs for legal, regulatory, or incident response.",
    tone: "purple",
    icon: "Search",
    status: "coming-soon",
    cover: "/suite/detective-cover.png",
    hub: "/suite/detective-hub.png",
    details: [
      {
        src: "/suite/detective-detail-1.png",
        alt: detailAlt("Detective", "Lineage graph"),
        caption: "Lineage graph stitching pipelines, schemas, and instances together.",
      },
      {
        src: "/suite/detective-detail-2.png",
        alt: detailAlt("Detective", "Investigations"),
        caption: "Investigation workbench with timeline, evidence, and notes.",
      },
      {
        src: "/suite/detective-detail-3.png",
        alt: detailAlt("Detective", "Reconciliation"),
        caption: "Reconciliation workspace with diff scoring and resolution actions.",
      },
    ],
    features: [
      { title: "Correlation fabric", description: "Stitch events across schemas, instances, and pipelines into a single narrative." },
      { title: "Instance forensics", description: "Reconstruct any record's full history with reasons and authors per change." },
      { title: "ETL forensics", description: "Investigate failed pipeline runs with replayable steps and payload dumps." },
      { title: "Lineage graph", description: "End-to-end lineage from raw event to dashboard tile, rendered live." },
      { title: "Reconciliation", description: "Compare expected vs actual, score discrepancies, and apply resolutions." },
      { title: "Evidence exports", description: "Tamper-evident evidence packs for legal, regulatory, or incident response." },
    ],
    useCases: [
      { audience: "Incident response", scenario: "Reconstruct a 3am production incident with full lineage in minutes." },
      { audience: "Data quality", scenario: "Reconcile two systems and apply targeted fixes instead of full reloads." },
      { audience: "Legal & regulatory", scenario: "Produce defensible evidence packs for audit or discovery." },
    ],
    enterprise: [
      "WORM evidence storage with chain-of-custody guarantees",
      "Granular legal-hold scopes and tamper-evident timestamps",
      "Investigator workspaces isolated per case with audit trails",
      "SIEM / SOAR integration for automated investigation kick-off",
      "Pre-built report templates for SOC 2, GDPR, HIPAA inquiries",
    ],
    ai: {
      headline: "An investigator that never blinks",
      description:
        "AI proposes likely root causes, ranks suspect events, and writes the first draft of every investigation summary — keeping humans in the judgement seat.",
      capabilities: [
        "Root-cause hypothesis ranking with cited evidence",
        "Anomaly detection on integrity, drift, and policy signals",
        "Auto-drafted investigation summaries and timelines",
        "Suggested reconciliation actions with risk scoring",
      ],
    },
    modules: ["dashboard", "lineage-graph", "instance-timeline", "pipeline-runs", "version-compare", "reconciliation", "investigations", "exports"],
    highlights: [
      { label: "Lineage depth", value: "End-to-end" },
      { label: "Evidence retention", value: "7+ years" },
      { label: "Case workspaces", value: "Per investigation" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Import
  {
    slug: "import",
    name: "Import",
    fullName: "Apiome Import",
    category: "Onboarding · Ingestion",
    tagline:
      "Enterprise-grade ingestion — multi-source, scheduled, governed, and resumable.",
    summary:
      "Import is the front door for every spec, schema, and data set entering Apiome. Multi-source ingestion, governance and approvals, schedules, sandbox previews, and a transformation pipeline — all wired into your CI/CD with a headless API.",
    tone: "purple",
    icon: "Import",
    status: "coming-soon",
    cover: "/suite/import-cover.png",
    hub: "/suite/import-hub.png",
    details: [
      {
        src: "/suite/import-detail-1.png",
        alt: detailAlt("Import", "Multi-source"),
        caption: "Multi-source import — file, URL, clipboard, Git, SwaggerHub, Postman, MCP, AI.",
      },
      {
        src: "/suite/import-detail-2.png",
        alt: detailAlt("Import", "Transforms"),
        caption: "Pre-import transformation pipeline with reusable steps.",
      },
      {
        src: "/suite/import-detail-3.png",
        alt: detailAlt("Import", "Approvals"),
        caption: "Multi-stage approval workflow with reviewers and SLAs.",
      },
    ],
    features: [
      { title: "Multi-source", description: "File, URL, Git, SwaggerHub, clipboard, DDL, and AI-generated specs." },
      { title: "Transform pipeline", description: "Compose reusable transforms before commit, with dry-run previews." },
      { title: "Governance & approvals", description: "Reviewer queues, required approvers, and tenant-aware visibility." },
      { title: "Schedules & sync", description: "Cron-style schedules with diff-aware re-import and notification rules." },
      { title: "Headless API & CI/CD", description: "Run imports from CI with deterministic, scriptable behaviour." },
      { title: "Sandbox & history", description: "Sandbox each import, audit every run, and roll back any commit." },
    ],
    useCases: [
      { audience: "Platform teams", scenario: "Ingest hundreds of legacy specs from Git mirrors with one job." },
      { audience: "Customer success", scenario: "Onboard a new tenant by importing their existing OpenAPI catalog." },
      { audience: "Architecture", scenario: "Reverse-engineer a database into managed schemas and contracts." },
    ],
    enterprise: [
      "Headless import API for CI/CD pipelines",
      "Approval gates aligned to SOX / SOC 2 change-control",
      "Self-hosted import runners for air-gapped sources",
      "Per-tenant size, throughput, and concurrency budgets",
      "Detailed audit log with redacted payload retention",
    ],
    ai: {
      headline: "Imports that fix themselves",
      description:
        "AI scores quality, fixes structural issues, suggests deduplication, and proposes follow-up cleanup tasks — all before the first commit lands.",
      capabilities: [
        "AI-powered import from a plain-English description",
        "Quality scoring (A–F) with auto-suggested fixes",
        "Conflict resolution recommendations",
        "Auto-generated transform suggestions from sample data",
      ],
    },
    modules: ["dashboard", "multi-source", "ddl-import", "transforms", "presets", "approvals", "schedules", "governance", "history", "sandbox", "conflicts", "import-detail", "api"],
    highlights: [
      { label: "Source types", value: "8+" },
      { label: "Format coverage", value: "OpenAPI · Swagger · GraphQL · DDL" },
      { label: "Run modes", value: "Sandbox · Live · Headless" },
    ],
  },

  // ─────────────────────────────────────────────────────────────── Linting
  {
    slug: "linting",
    name: "Linting",
    fullName: "Apiome Linting & Quality",
    category: "Quality · Governance",
    tagline:
      "Real-time validation, A–F quality scoring, and breaking-change detection.",
    summary:
      "Linting & Quality scores every schema and spec from A to F, validates them in real time as you type, catches breaking changes before they ship, and lets you author custom rule packs that travel with your platform.",
    tone: "green",
    icon: "ShieldCheck",
    status: "coming-soon",
    cover: "/suite/linting-cover.png",
    hub: "/suite/linting-hub.png",
    details: [
      {
        src: "/suite/linting-detail-1.png",
        alt: detailAlt("Linting", "Editor validation"),
        caption: "In-editor validation with squiggly underlines and quick-fix actions.",
      },
      {
        src: "/suite/linting-detail-2.png",
        alt: detailAlt("Linting", "Rule config"),
        caption: "Rule pack configuration with severity and per-tenant overrides.",
      },
      {
        src: "/suite/linting-detail-3.png",
        alt: detailAlt("Linting", "Breaking changes"),
        caption: "Breaking-change detector with semantic-version recommendation.",
      },
    ],
    features: [
      { title: "Quality scoring", description: "A–F grades for completeness, consistency, security, and best practices." },
      { title: "Real-time validation", description: "Squiggly underlines, hover messages, and quick-fix actions in the editor." },
      { title: "Custom rule packs", description: "Author org-specific rules with versioning, severity, and inheritance." },
      { title: "Breaking-change detection", description: "Spec-aware diff with semantic-version impact and consumer hints." },
      { title: "Dependency graph", description: "Cross-schema impact analysis with reach metrics." },
      { title: "Quality dashboard", description: "Tenant-wide quality dashboard tracking score trends per team and product." },
    ],
    useCases: [
      { audience: "API design groups", scenario: "Set a minimum quality bar for every spec entering production." },
      { audience: "Platform owners", scenario: "Roll out org-wide naming and security rules in a single rule pack." },
      { audience: "Release managers", scenario: "Block any breaking change without an explicit acknowledgement." },
    ],
    enterprise: [
      "Versioned rule packs published to a private registry",
      "CODEOWNERS-style ownership of rule scopes",
      "CI/CD gates with PR comments and merge protection",
      "Quality SLOs per team with violation alerting",
      "Audit log of every rule decision and override",
    ],
    ai: {
      headline: "Suggestions, not lectures",
      description:
        "Each finding ships with an AI-drafted fix preview and a one-click apply — turning lint warnings into shipped improvements.",
      capabilities: [
        "AI-explained findings with suggested fixes",
        "Auto-generated rule packs from your existing best practices",
        "Plain-English breaking-change summaries",
        "Quality coaching for new contributors",
      ],
    },
    modules: ["quality-score", "editor-validation", "rule-config", "custom-rules", "breaking-changes", "dependency-graph"],
    highlights: [
      { label: "Default rules", value: "150+" },
      { label: "Score grades", value: "A–F" },
      { label: "Validation latency", value: "≤ 50ms" },
    ],
  },
];

export const SUITES_BY_SLUG: Record<string, Suite> = SUITES.reduce(
  (acc, s) => ((acc[s.slug] = s), acc),
  {} as Record<string, Suite>,
);
