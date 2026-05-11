import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  KeyRound,
  Network,
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
  title: "MCP Server - Objectified",
  description:
    "Objectified MCP exposes published OpenAPI specifications to Model Context Protocol hosts: list, search, semantic search, and export tools backed by Postgres.",
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
    detail: "Remote endpoint at /mcp with Bearer tokens per request. Binds with OBJECTIFIED_MCP_HTTP_HOST / PORT (or CLI flags). Health at GET /health.",
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

export default function McpPage() {
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
              Objectified for your <span className="display-accent">AI tools</span>
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mx-auto max-w-2xl text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
              The Objectified MCP server is a read-only FastMCP service that lists, searches, and returns published OpenAPI from PostgreSQL — so assistants and
              automation can work from the same specs your teams ship in Studio.
            </p>
          </Reveal>
          <Reveal delay={0.2}>
            <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener noreferrer">
                <Button size="lg" variant="outline">
                  About MCP
                </Button>
              </a>
              <Link href="/screenshots">
                <Button size="lg" className="group">
                  See product screenshots
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 text-center">
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
                  The MCP package ships in this monorepo as <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">objectified-mcp</code>. Configure{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">OBJECTIFIED_MCP_DATABASE_URL</code>,{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">OBJECTIFIED_MCP_INTERNAL_SECRET</code>, and optional embedding variables, then start{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 text-xs dark:bg-zinc-800">objectified-mcp serve --transport stdio|http</code>. Full env reference lives in the
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
              <a href="https://app.objectified.dev" target="_blank" rel="noopener noreferrer">
                <Button size="lg" className="group">
                  Open Objectified
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
