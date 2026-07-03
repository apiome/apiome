import { getLinks } from "@/lib/links";
import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Boxes,
  Gauge,
  GitCompare,
  Globe,
  Import,
  KeyRound,
  ListChecks,
  Lock,
  Network,
  RefreshCw,
  Search,
  Server,
  Shield,
  Sparkles,
  Terminal,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Aurora } from "../components/ui/Aurora";
import { GlassCard, ToneChip } from "../components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem } from "../components/motion/Reveal";

export const metadata: Metadata = {
  title: "MCP - Apiome",
  description:
    "Apiome speaks MCP both ways: it serves your published OpenAPI to Model Context Protocol hosts, and it imports, catalogs, scores, and publishes the MCP servers your organization depends on — browsable in the public MCP catalog.",
};

const TRANSPORTS = [
  {
    name: "stdio",
    icon: <Terminal className="h-5 w-5" />,
    detail: "Local MCP hosts (Claude Desktop, MCP Inspector, Cursor). Credentials can travel in tool call metadata when the host supports it.",
  },
  {
    name: "Streamable HTTP",
    icon: <Network className="h-5 w-5" />,
    detail: "Remote endpoint at /mcp with Bearer tokens per request. Binds with APIOME_MCP_HTTP_HOST / PORT (or CLI flags). Health at GET /health.",
  },
];

const TOOL_GROUPS: { title: string; items: string[] }[] = [
  {
    title: "Catalog & discovery",
    items: [
      "ping — service id, version, Postgres reachability",
      "spec.list — cursor-paginated published specs (public catalog; optional private scope with API key)",
      "project.list — distinct projects visible to the caller",
      "spec.list_my_specs — same shape as spec.list; requires MCP API key",
      "spec.describe — metadata for one revision UUID",
      "spec.list_tags — public tags with counts",
    ],
  },
  {
    title: "Search & retrieval",
    items: [
      "spec.search — full-text search over public specs (ranked, paginated)",
      "spec.search_semantic — vector similarity when embeddings are configured (OpenAI-compatible endpoint)",
      "spec.get_openapi — full OpenAPI JSON for a revision",
      "spec.export_yaml — same bundle as YAML text",
    ],
  },
  {
    title: "Operations & components",
    items: [
      "spec.list_operations — compact index of paths and methods",
      "spec.describe_operation — parameters, body, responses, security",
      "spec.list_components — component keys by kind",
      "spec.describe_component — single component with $ref expansion",
    ],
  },
];

// Inbound side (MCP cataloging, MCAT): importing and monitoring external MCP servers.
const CATALOG_CAPABILITIES: { icon: React.ReactNode; title: string; detail: string; tone: "blue" | "purple" | "emerald" | "indigo" | "rose" | "amber" }[] = [
  {
    icon: <Import className="h-5 w-5" />,
    title: "Import any MCP endpoint",
    detail:
      "Add a server by URL over Streamable HTTP, Server-Sent Events (SSE), or stdio. Connect anonymously, or with a Bearer token, a custom header, or an OAuth 2.1 access token for protected servers.",
    tone: "blue",
  },
  {
    icon: <Boxes className="h-5 w-5" />,
    title: "Discover the full surface",
    detail:
      "One discovery run lists everything the server offers — tools, resources, resource templates, and prompts — with their schemas, captured as a structured catalog entry instead of a screenshot.",
    tone: "purple",
  },
  {
    icon: <GitCompare className="h-5 w-5" />,
    title: "Versioned snapshots & diffs",
    detail:
      "Every discovery is fingerprinted. An unchanged surface is a no-op; when a server adds, removes, or changes a capability, a new version is recorded with an exact added / removed / modified diff.",
    tone: "indigo",
  },
  {
    icon: <Gauge className="h-5 w-5" />,
    title: "Automatic A–F quality scoring",
    detail:
      "Each snapshot is linted and graded A–F for naming, descriptions, schema completeness, and annotations — so you can tell a well-built server from a risky one at a glance.",
    tone: "emerald",
  },
  {
    icon: <Lock className="h-5 w-5" />,
    title: "Encrypted credentials",
    detail:
      "Secrets for protected servers are sealed with AES-256-GCM envelope encryption before they touch the database. The catalog stores ciphertext only — never a usable token.",
    tone: "rose",
  },
  {
    icon: <RefreshCw className="h-5 w-5" />,
    title: "Scheduled re-discovery",
    detail:
      "Set a per-server cadence and Apiome re-checks on its own, with exponential backoff on failure and automatic quarantine of an endpoint that keeps erroring — so your catalog stays current without babysitting.",
    tone: "amber",
  },
];

const CATALOG_STEPS: { step: number; title: string; description: string; dotClass: string }[] = [
  { step: 1, title: "Connect", description: "Point Apiome at an MCP endpoint, pick the transport, and add credentials if the server is protected.", dotClass: "from-blue-500 to-blue-600" },
  { step: 2, title: "Discover", description: "Apiome connects, lists every tool, resource, template, and prompt, and records a versioned snapshot.", dotClass: "from-purple-500 to-purple-600" },
  { step: 3, title: "Score & review", description: "The snapshot is graded A–F and diffed against the prior version, so quality and change are both obvious.", dotClass: "from-emerald-500 to-emerald-600" },
  { step: 4, title: "Publish", description: "Mark a server public to list it in the public MCP catalog on the browser for anyone to discover.", dotClass: "from-orange-500 to-orange-600" },
];

const BROWSE_FEATURES: { icon: React.ReactNode; title: string; detail: string; tone: "emerald" | "purple" | "blue" }[] = [
  {
    icon: <Gauge className="h-5 w-5" />,
    title: "Grade-led, ranked by host",
    detail:
      "Published servers are grouped by host and led by their A–F grade and score (for example B · 82), so the highest-quality servers for each site surface first.",
    tone: "emerald",
  },
  {
    icon: <ListChecks className="h-5 w-5" />,
    title: "Capability counts at a glance",
    detail:
      "Each card shows what a server actually exposes — tool, resource, template, and prompt counts — before you ever open it.",
    tone: "blue",
  },
  {
    icon: <Search className="h-5 w-5" />,
    title: "Full-text capability search",
    detail:
      "Search tool, resource, and prompt names and descriptions across every published public server, ranked server-side, to find the exact capability you need.",
    tone: "purple",
  },
];

export default function McpPage() {
  const links = getLinks();
  return (
    <div className="flex flex-col">
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-32">
        <Aurora />
        <div className="container relative mx-auto max-w-4xl text-center">
          <Reveal>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-200/60 bg-emerald-50/80 px-4 py-2 text-sm font-medium text-emerald-800 backdrop-blur dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-200">
              <Server className="h-4 w-4" />
              Model Context Protocol
            </div>
          </Reveal>
          <Reveal delay={0.06}>
            <h1 className="mb-6 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl">
              Apiome for your <span className="display-accent">AI tools</span>
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mx-auto max-w-2xl text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
              Apiome speaks MCP in both directions. It <strong className="font-semibold text-zinc-800 dark:text-zinc-200">serves</strong> your published OpenAPI to
              Model Context Protocol hosts, and it <strong className="font-semibold text-zinc-800 dark:text-zinc-200">catalogs</strong> the MCP servers your organization
              depends on — importing, scoring, and publishing them to a browsable public catalog.
            </p>
          </Reveal>
          <Reveal delay={0.2}>
            <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a href={`${links.browse}/mcp`} target="_blank" rel="noopener noreferrer">
                <Button size="lg" className="group">
                  Browse the MCP catalog
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </a>
              <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener noreferrer">
                <Button size="lg" variant="outline">
                  About MCP
                </Button>
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 text-center">
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                Two directions, one platform
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                The same MCP fluency works outbound and inbound — expose what you build, and keep a graded catalog of what you consume.
              </p>
            </div>
          </Reveal>
          <div className="grid gap-6 md:grid-cols-2">
            <Reveal>
              <GlassCard className="h-full p-7">
                <ToneChip tone="emerald" className="mb-4 h-10 w-10 rounded-lg">
                  <Server className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">Serve your specs</h3>
                <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Apiome runs a read-only MCP server that lists, searches, and returns your published OpenAPI straight from Postgres — so assistants and automation
                  work from the same specs your teams ship in Studio.
                </p>
              </GlassCard>
            </Reveal>
            <Reveal delay={0.08}>
              <GlassCard className="h-full p-7">
                <ToneChip tone="blue" className="mb-4 h-10 w-10 rounded-lg">
                  <Network className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">Catalog the servers you use</h3>
                <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Import any external MCP server, discover its full capability surface, version and grade it, and publish the best ones to a public catalog anyone can
                  browse.
                </p>
              </GlassCard>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 text-center">
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-emerald-200/60 bg-emerald-50/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-700 backdrop-blur dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300">
                <Server className="h-3.5 w-3.5" />
                Serving specs
              </div>
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                How it fits together
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                MCP hosts connect over stdio or HTTP. The server uses a shared async Postgres pool; public rows come from published public revisions, and scoped MCP API keys
                unlock in-tenant private published content according to key scope.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-3">
            <StaggerItem>
              <GlassCard className="h-full p-6">
                <ToneChip tone="blue" className="mb-4 h-10 w-10 rounded-lg">
                  <Shield className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Visibility &amp; keys</h3>
                <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Anonymous callers see the public catalog. Bearer tokens (HTTP) or metadata secrets (stdio) map to MCP API keys with tenant/project scope stored hashed in the
                  database.
                </p>
              </GlassCard>
            </StaggerItem>
            <StaggerItem>
              <GlassCard className="h-full p-6">
                <ToneChip tone="purple" className="mb-4 h-10 w-10 rounded-lg">
                  <Search className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Full-text &amp; semantic search</h3>
                <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Keyword search uses Postgres full-text ranking. Semantic search uses pgvector where embeddings are backfilled, with an OpenAI-compatible embedding endpoint
                  configured on the server.
                </p>
              </GlassCard>
            </StaggerItem>
            <StaggerItem>
              <GlassCard className="h-full p-6">
                <ToneChip tone="emerald" className="mb-4 h-10 w-10 rounded-lg">
                  <Sparkles className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Spec-shaped tools</h3>
                <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Pull whole OpenAPI documents or drill into operations and components — designed for agents that need structured fragments, not a wall of YAML.
                </p>
              </GlassCard>
            </StaggerItem>
          </StaggerGroup>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <h2 className="mb-10 text-center text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
              Transports
            </h2>
          </Reveal>
          <div className="grid gap-6 md:grid-cols-2">
            {TRANSPORTS.map((t) => (
              <GlassCard key={t.name} interactive={false} className="p-6" data-always="true">
                <div className="mb-3 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-100">
                    {t.icon}
                  </div>
                  <h3 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">{t.name}</h3>
                </div>
                <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">{t.detail}</p>
              </GlassCard>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-10 flex flex-col items-center text-center sm:flex-row sm:items-end sm:justify-between sm:text-left">
              <div>
                <h2 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                  Tools exposed to hosts
                </h2>
                <p className="mt-2 max-w-xl text-zinc-600 dark:text-zinc-400">
                  Names follow the <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-sm dark:bg-zinc-800">spec.*</code> and{" "}
                  <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-sm dark:bg-zinc-800">project.*</code> conventions from the server implementation.
                </p>
              </div>
            </div>
          </Reveal>

          <div className="grid gap-8 lg:grid-cols-3">
            {TOOL_GROUPS.map((group) => (
              <GlassCard key={group.title} interactive={false} className="p-6" data-always="true">
                <h3 className="mb-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{group.title}</h3>
                <ul className="space-y-3 text-sm text-zinc-600 dark:text-zinc-400">
                  {group.items.map((line) => (
                    <li key={line} className="flex gap-2">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" aria-hidden />
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </GlassCard>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 text-center">
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-blue-700 backdrop-blur dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300">
                <Network className="h-3.5 w-3.5" />
                MCP cataloging
              </div>
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                Catalog &amp; monitor the MCP servers you use
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                Import an external MCP server and Apiome discovers its entire capability surface, records a graded, versioned snapshot, and keeps it current on a
                schedule — turning a sprawl of endpoints into an inventory you can trust.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {CATALOG_CAPABILITIES.map((c) => (
              <StaggerItem key={c.title}>
                <GlassCard className="h-full p-6">
                  <ToneChip tone={c.tone} className="mb-4 h-10 w-10 rounded-lg">
                    {c.icon}
                  </ToneChip>
                  <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{c.title}</h3>
                  <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{c.detail}</p>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>

          <div className="relative mt-16">
            <div
              aria-hidden
              className="absolute inset-x-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-zinc-300 to-transparent dark:via-zinc-700 lg:block"
            />
            <StaggerGroup className="grid gap-8 lg:grid-cols-4">
              {CATALOG_STEPS.map(({ step, title, description, dotClass }) => (
                <StaggerItem key={step}>
                  <div className="text-center">
                    <div
                      className={`relative mx-auto mb-6 inline-flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br ${dotClass} text-xl font-semibold text-white shadow-lg ring-4 ring-white dark:ring-zinc-950`}
                    >
                      {step}
                    </div>
                    <h3 className="mb-3 text-xl font-semibold text-zinc-900 dark:text-zinc-50">{title}</h3>
                    <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">{description}</p>
                  </div>
                </StaggerItem>
              ))}
            </StaggerGroup>
          </div>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
            <Reveal>
              <div>
                <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-emerald-200/60 bg-emerald-50/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-700 backdrop-blur dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300">
                  <Globe className="h-3.5 w-3.5" />
                  On the browser
                </div>
                <h2 className="mb-4 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                  Published to the public MCP catalog
                </h2>
                <p className="mb-8 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Mark a cataloged server public and it joins the public MCP catalog on the Apiome browser — a credential-free directory where anyone can find
                  quality servers by site, grade, and capability.
                </p>
                <div className="space-y-5">
                  {BROWSE_FEATURES.map((f) => (
                    <div key={f.title} className="flex gap-4">
                      <ToneChip tone={f.tone} className="h-10 w-10 shrink-0 rounded-lg">
                        {f.icon}
                      </ToneChip>
                      <div>
                        <h3 className="mb-1 text-base font-semibold text-zinc-900 dark:text-zinc-50">{f.title}</h3>
                        <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{f.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <a href={`${links.browse}/mcp`} target="_blank" rel="noopener noreferrer" className="mt-8 inline-block">
                  <Button size="lg" className="group">
                    Open the MCP catalog
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </a>
              </div>
            </Reveal>

            <Reveal delay={0.1}>
              <GlassCard interactive={false} className="p-6" data-always="true">
                <p className="mb-5 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                  api.example.com
                </p>
                <div className="space-y-3">
                  {[
                    { name: "Acme Weather", grade: "A", score: 94, transport: "Streamable HTTP", caps: "8 tools · 3 resources · 2 prompts", tone: "text-emerald-700 bg-emerald-50 ring-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/50 dark:ring-emerald-900/60" },
                    { name: "Ledger MCP", grade: "B", score: 82, transport: "SSE", caps: "12 tools · 5 resources", tone: "text-blue-700 bg-blue-50 ring-blue-200 dark:text-blue-300 dark:bg-blue-950/50 dark:ring-blue-900/60" },
                    { name: "Docs Search", grade: "C", score: 68, transport: "stdio", caps: "4 tools · 1 prompt", tone: "text-amber-700 bg-amber-50 ring-amber-200 dark:text-amber-300 dark:bg-amber-950/50 dark:ring-amber-900/60" },
                  ].map((row) => (
                    <div
                      key={row.name}
                      className="flex items-center gap-3 rounded-xl border border-zinc-200/70 bg-white/60 p-3 dark:border-zinc-800/70 dark:bg-zinc-900/40"
                    >
                      <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-sm font-semibold tabular-nums ring-1 ring-inset ${row.tone}`}>
                        {row.grade} · {row.score}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-50">{row.name}</p>
                        <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{row.caps}</p>
                      </div>
                      <span className="hidden shrink-0 rounded-md bg-zinc-100 px-2 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 sm:inline">
                        {row.transport}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="mt-5 text-center text-xs text-zinc-400 dark:text-zinc-500">
                  Illustrative — endpoints grouped by host, led by grade.
                </p>
              </GlassCard>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <div className="grid gap-10 lg:grid-cols-2 lg:items-start">
            <Reveal>
              <GlassCard className="h-full p-6">
                <ToneChip tone="rose" className="mb-4 h-10 w-10 rounded-lg">
                  <KeyRound className="h-5 w-5" />
                </ToneChip>
                <h2 className="mb-3 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Authentication</h2>
                <ul className="space-y-3 text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  <li>
                    <strong className="text-zinc-800 dark:text-zinc-200">HTTP:</strong> send{" "}
                    <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">Authorization: Bearer …</code>. Missing or non-Bearer requests run as anonymous
                    where allowed.
                  </li>
                  <li>
                    <strong className="text-zinc-800 dark:text-zinc-200">stdio:</strong> hosts may pass secrets via tool-call metadata fields documented for MCP auth (for
                    example authorization or api_key shaped fields).
                  </li>
                  <li>Keys are scoped with JSON tenant/project UUID lists; the server intersects scope with revision visibility before returning private documents.</li>
                </ul>
              </GlassCard>
            </Reveal>
            <Reveal delay={0.08}>
              <GlassCard className="h-full p-6">
                <ToneChip tone="indigo" className="mb-4 h-10 w-10 rounded-lg">
                  <BookOpen className="h-5 w-5" />
                </ToneChip>
                <h2 className="mb-3 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Run it yourself</h2>
                <p className="mb-4 text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  The MCP package ships in this monorepo as <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">apiome-mcp</code>. Configure{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">APIOME_MCP_DATABASE_URL</code>,{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">APIOME_MCP_INTERNAL_SECRET</code>, and optional embedding variables, then start{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">apiome-mcp serve --transport stdio|http</code>. Full env reference lives in the
                  package CONFIGURATION doc.
                </p>
                <p className="text-sm text-zinc-500 dark:text-zinc-500">
                  Docker Compose at the repo root can bring up Postgres, migrations, and the MCP image for local integration testing.
                </p>
              </GlassCard>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="px-6 py-20">
        <div className="container mx-auto max-w-3xl text-center">
          <Reveal>
            <h2 className="mb-4 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Wire it into your host</h2>
            <p className="mb-8 text-lg text-zinc-600 dark:text-zinc-400">
              Add the server to Cursor, Claude Desktop, or any MCP-compatible client using stdio or your deployed HTTP endpoint. Use a scoped MCP API key when agents need
              private published revisions.
            </p>
            <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a href={links.app} target="_blank" rel="noopener noreferrer">
                <Button size="lg" className="group">
                  Open Apiome
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </a>
              <Link href="/features">
                <Button size="lg" variant="outline">
                  Platform features
                </Button>
              </Link>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
