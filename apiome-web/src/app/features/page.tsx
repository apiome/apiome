import { links } from "@/lib/links";
import type { Metadata } from "next";
import Image from "next/image";
import {
  ArrowRight,
  CheckCircle2,
  Layers,
  Zap,
  GitBranch,
  FileCode,
  Eye,
  Shield,
  Globe,
  BarChart3,
  Route,
  Search,
  Sparkles,
  SlidersHorizontal,
  LayoutGrid,
  Import,
  Network,
  Paintbrush,
  MousePointerClick,
  ShieldCheck,
  Users,
  ScrollText,
  KeyRound,
  Upload,
  Link2,
  Clipboard,
  Cloud,
  FileJson,
  Radio,
  Waypoints,
  Share2,
  Braces,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Aurora } from "../components/ui/Aurora";
import { GlassCard, ToneChip, type Tone } from "../components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem } from "../components/motion/Reveal";

export const metadata: Metadata = {
  title: "Features - Apiome",
  description:
    "Explore the powerful features of Apiome — the visual API and schema design platform for enterprise teams.",
};

type SpotlightSectionProps = {
  eyebrow: string;
  eyebrowTone: Tone;
  title: React.ReactNode;
  description: string;
  bullets: string[];
  image: { src: string; alt: string; priority?: boolean };
  reverse?: boolean;
  surface?: 'plain' | 'glass';
};

function SpotlightSection({
  eyebrow,
  eyebrowTone,
  title,
  description,
  bullets,
  image,
  reverse,
  surface = 'plain',
}: SpotlightSectionProps) {
  const eyebrowClass = TONE_EYEBROW[eyebrowTone];
  return (
    <section
      className={`border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 ${
        surface === 'glass' ? 'bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40' : ''
      }`}
    >
      <div className="container mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
          <Reveal className={reverse ? 'order-1 lg:order-2' : ''}>
            <div>
              <div className={`mb-4 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${eyebrowClass}`}>
                {eyebrow}
              </div>
              <h2 className="mb-4 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                {title}
              </h2>
              <p className="mb-6 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
                {description}
              </p>
              <ul className="space-y-3">
                {bullets.map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-green-600" />
                    <span className="text-zinc-600 dark:text-zinc-400">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Reveal>
          <Reveal delay={0.12} className={reverse ? 'order-2 lg:order-1' : ''}>
            <GlassCard interactive={false} className="p-6" data-always="true">
              <div className="relative aspect-video overflow-hidden rounded-lg ring-1 ring-black/10 dark:ring-white/10">
                <Image
                  src={image.src}
                  alt={image.alt}
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 100vw, 50vw"
                  priority={image.priority}
                />
              </div>
            </GlassCard>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

const TONE_EYEBROW: Record<Tone, string> = {
  blue:    'border-blue-200/60 bg-blue-50/80 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300',
  emerald: 'border-emerald-200/60 bg-emerald-50/80 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300',
  purple:  'border-purple-200/60 bg-purple-50/80 text-purple-700 dark:border-purple-900/60 dark:bg-purple-950/50 dark:text-purple-300',
  orange:  'border-orange-200/60 bg-orange-50/80 text-orange-700 dark:border-orange-900/60 dark:bg-orange-950/50 dark:text-orange-300',
  indigo:  'border-indigo-200/60 bg-indigo-50/80 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/50 dark:text-indigo-300',
  sky:     'border-sky-200/60 bg-sky-50/80 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/50 dark:text-sky-300',
  rose:    'border-rose-200/60 bg-rose-50/80 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/50 dark:text-rose-300',
  cyan:    'border-cyan-200/60 bg-cyan-50/80 text-cyan-700 dark:border-cyan-900/60 dark:bg-cyan-950/50 dark:text-cyan-300',
  violet:  'border-violet-200/60 bg-violet-50/80 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/50 dark:text-violet-300',
  amber:   'border-amber-200/60 bg-amber-50/80 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/50 dark:text-amber-300',
  pink:    'border-pink-200/60 bg-pink-50/80 text-pink-700 dark:border-pink-900/60 dark:bg-pink-950/50 dark:text-pink-300',
  red:     'border-red-200/60 bg-red-50/80 text-red-700 dark:border-red-900/60 dark:bg-red-950/50 dark:text-red-300',
  teal:    'border-teal-200/60 bg-teal-50/80 text-teal-700 dark:border-teal-900/60 dark:bg-teal-950/50 dark:text-teal-300',
  green:   'border-green-200/60 bg-green-50/80 text-green-700 dark:border-green-900/60 dark:bg-green-950/50 dark:text-green-300',
};

type FeatureDef = {
  icon: React.ReactNode;
  title: string;
  description: string;
  tone: Tone;
};

const FEATURE_GRID: FeatureDef[] = [
  { icon: <LayoutGrid className="h-5 w-5" />, title: 'Interactive Canvas', description: 'Drag-and-drop schema design with smart auto-layout, grid snapping, minimap navigation, and zoom controls.', tone: 'blue' },
  { icon: <Route className="h-5 w-5" />, title: 'Paths Designer', description: 'Visual endpoint authoring with HTTP method color coding, parameter editing, and response schema binding.', tone: 'emerald' },
  { icon: <Import className="h-5 w-5" />, title: 'Multi-Source Import', description: 'Import from file, URL, clipboard, Git, SwaggerHub, Postman, MCP servers, or AI — across REST, event, GraphQL, and gRPC APIs.', tone: 'purple' },
  { icon: <Layers className="h-5 w-5" />, title: 'Multi-Tenant Architecture', description: 'Organize projects by teams and organizations with granular permission controls and isolated workspaces.', tone: 'green' },
  { icon: <GitBranch className="h-5 w-5" />, title: 'Version Control', description: 'Full version history with side-by-side comparison, diff highlighting, and semantic change tracking.', tone: 'indigo' },
  { icon: <Zap className="h-5 w-5" />, title: 'Code Generation', description: 'Generate OpenAPI specs, database migrations, and DTO stubs from your visual designs automatically.', tone: 'orange' },
  { icon: <Paintbrush className="h-5 w-5" />, title: '10+ Canvas Themes', description: 'Light, dark, high contrast, blueprint, whiteboard, solarized, nord, and more — switch instantly.', tone: 'pink' },
  { icon: <Network className="h-5 w-5" />, title: 'Relationship Visualization', description: 'Animated edges with smart routing, cardinality labels, and constraint badges for clear data flow.', tone: 'cyan' },
  { icon: <FileCode className="h-5 w-5" />, title: 'Rich Export Options', description: 'Export canvas to PNG, SVG, PDF, Mermaid, PlantUML, GraphML, DOT, or raw JSON with an export wizard.', tone: 'violet' },
  { icon: <Search className="h-5 w-5" />, title: 'Canvas Search', description: 'Find any class or property instantly with Cmd+F search, regex support, and result highlighting.', tone: 'amber' },
  { icon: <ShieldCheck className="h-5 w-5" />, title: 'Granular RBAC', description: 'Built-in Owner, Admin, Editor, and Viewer roles per workspace, with a resource-by-action permission matrix you can tune to your team.', tone: 'rose' },
  { icon: <Users className="h-5 w-5" />, title: 'Member Lifecycle', description: 'Invite, suspend, and offboard members with status-aware access — suspended members are denied tenant access immediately.', tone: 'teal' },
  { icon: <ScrollText className="h-5 w-5" />, title: 'Tamper-Evident Audit Log', description: 'Every privileged action is recorded to an append-only, hash-chained access ledger, exportable to JSON or CSV for compliance.', tone: 'amber' },
  { icon: <KeyRound className="h-5 w-5" />, title: 'Platform Admin Plane', description: 'A platform-administration plane kept separate from tenant administration, with SSO and SCIM provisioning on the roadmap.', tone: 'violet' },
  { icon: <Shield className="h-5 w-5" />, title: 'API Security Schemes', description: 'Configure OAuth2, API Key, Bearer token, and OpenID Connect security directly on operations.', tone: 'red' },
  { icon: <Sparkles className="h-5 w-5" />, title: 'AI-Powered Import', description: 'Describe your API in plain English and let AI generate a complete OpenAPI specification for you.', tone: 'sky' },
  { icon: <SlidersHorizontal className="h-5 w-5" />, title: 'Quality Scoring', description: 'Automated A–F quality grades measuring completeness, consistency, best practices, and security coverage.', tone: 'teal' },
  { icon: <Globe className="h-5 w-5" />, title: 'Public API Browser', description: 'Share your API specifications publicly and browse community-shared designs for inspiration.', tone: 'emerald' },
  { icon: <MousePointerClick className="h-5 w-5" />, title: 'Drag-and-Drop Everything', description: 'Operations, classes, properties, and schemas can all be dragged from the sidebar directly onto the canvas.', tone: 'orange' },
  { icon: <Eye className="h-5 w-5" />, title: 'Level of Detail', description: "Nodes simplify automatically when zoomed out, showing only class names for a clean bird's-eye view.", tone: 'indigo' },
  { icon: <BarChart3 className="h-5 w-5" />, title: 'Schema Analytics', description: 'Track total classes, properties, relationships, and complexity metrics across your entire project.', tone: 'blue' },
];

type ImportSourceDef = {
  icon: React.ReactNode;
  label: string;
  detail: string;
  tone: Tone;
};

/**
 * Every intake channel the import wizard can pull from. Mirrors the built-in source cards in the
 * app (file / url / clipboard / git / swaggerhub / postman / mcp) plus AI generation.
 */
const IMPORT_CHANNELS: ImportSourceDef[] = [
  { icon: <Upload className="h-5 w-5" />, label: 'File Upload', detail: 'Drop or browse for a spec file', tone: 'blue' },
  { icon: <Link2 className="h-5 w-5" />, label: 'URL Fetch', detail: 'Pull a spec straight from a URL', tone: 'emerald' },
  { icon: <Clipboard className="h-5 w-5" />, label: 'Clipboard Paste', detail: 'Paste raw JSON or YAML content', tone: 'purple' },
  { icon: <GitBranch className="h-5 w-5" />, label: 'Git Repository', detail: 'GitHub, GitLab, Bitbucket + branches', tone: 'orange' },
  { icon: <Cloud className="h-5 w-5" />, label: 'SwaggerHub', detail: 'Public and private SwaggerHub APIs', tone: 'cyan' },
  { icon: <FileJson className="h-5 w-5" />, label: 'Postman Collection', detail: 'Import Postman v2.1 collections', tone: 'amber' },
  { icon: <Network className="h-5 w-5" />, label: 'MCP Server', detail: 'Discover a live MCP endpoint', tone: 'teal' },
  { icon: <Sparkles className="h-5 w-5" />, label: 'AI Generation', detail: 'Describe your API in plain English', tone: 'sky' },
];

/**
 * Every API paradigm / format the import adapters accept for cataloging. Mirrors the registry
 * adapters served by `GET /v1/import/sources` (openapi, asyncapi, graphql, grpc).
 */
const IMPORT_PARADIGMS: ImportSourceDef[] = [
  { icon: <FileCode className="h-5 w-5" />, label: 'OpenAPI 3.1 / 3.0', detail: 'REST APIs — the modern OpenAPI standard', tone: 'blue' },
  { icon: <FileCode className="h-5 w-5" />, label: 'Swagger 2.0', detail: 'Legacy REST API descriptions', tone: 'indigo' },
  { icon: <Braces className="h-5 w-5" />, label: 'JSON Schema', detail: 'Standalone data-model schemas', tone: 'violet' },
  { icon: <Radio className="h-5 w-5" />, label: 'AsyncAPI 2.x / 3.x', detail: 'Event-driven and streaming APIs', tone: 'rose' },
  { icon: <Waypoints className="h-5 w-5" />, label: 'GraphQL', detail: 'SDL or live endpoint introspection', tone: 'pink' },
  { icon: <Share2 className="h-5 w-5" />, label: 'gRPC / Protobuf', detail: '.proto files or server reflection', tone: 'green' },
];

export default function FeaturesPage() {
  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-36">
        <Aurora />
        <div className="container relative mx-auto max-w-4xl text-center">
          <Reveal>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/80 px-4 py-2 text-sm font-medium text-blue-700 backdrop-blur dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300">
              <Sparkles className="h-4 w-4" />
              Now in Release Candidate &middot; RC2
            </div>
          </Reveal>
          <Reveal delay={0.06}>
            <h1 className="mb-6 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl">
              Everything You Need to
              <br />
              <span className="display-accent">Design Better APIs</span>
            </h1>
          </Reveal>
          <Reveal delay={0.14}>
            <p className="mb-8 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
              A unified visual platform for schema design, API path authoring, enterprise-grade importing,
              and OpenAPI specification generation — built for teams who ship faster.
            </p>
          </Reveal>
          <Reveal delay={0.22}>
            <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a href={links.app} target="_blank" rel="noopener noreferrer">
                <Button size="lg" className="group">
                  Launch App
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </a>
              <a href={links.demo} target="_blank" rel="noopener noreferrer">
                <Button size="lg" variant="outline">
                  Watch Demo
                </Button>
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      <SpotlightSection
        eyebrow="Schema Canvas"
        eyebrowTone="blue"
        title={<>Visual <span className="display-accent">Schema</span> Designer</>}
        description="Design data models on an interactive canvas with drag-and-drop simplicity. See relationships, constraints, and dependencies at a glance — no YAML editing required."
        bullets={[
          "Drag-and-drop class creation with property editors",
          "Smart auto-layout algorithms",
          "Color-coded groups with collapsible containers",
          "Real-time relationship visualization with animated edges",
          "Version comparison with side-by-side diff highlighting",
          "10+ canvas themes including dark mode and blueprint",
          "Canvas export to PNG, SVG, PDF, Mermaid, PlantUML, and more",
          "Quality scoring with completeness and consistency grades",
        ]}
        image={{ src: '/features-01.png', alt: 'Visual Schema Designer canvas showing drag-and-drop classes, relationships, and auto-layout', priority: true }}
      />

      <SpotlightSection
        surface="glass"
        reverse
        eyebrow="Paths Designer"
        eyebrowTone="emerald"
        title={<>Visual API <span className="display-accent">Path Authoring</span></>}
        description="Design every endpoint visually — operations, parameters, request bodies, responses, and security schemes — all on a dedicated developer-focused canvas with HTTP method color coding and real-time OpenAPI validation."
        bullets={[
          "HTTP method nodes with GET, POST, PUT, PATCH, DELETE color coding",
          "Drag-and-drop parameters, responses, and schema bindings",
          "Multi-content-type support (JSON, XML, multipart/form-data)",
          "Inline schema editing with class reference ($ref) binding",
          "Response status code color bands (2xx, 3xx, 4xx, 5xx)",
          "Security scheme configuration (API Key, Bearer, OAuth2)",
          "Smart edge routing with animated data flow visualization",
          "Auto-generate CRUD operations from existing schemas",
        ]}
        image={{ src: '/features-02.png', alt: 'Paths Designer showing HTTP operations, parameters, and response schema binding' }}
      />

      <SpotlightSection
        eyebrow="Enterprise Import"
        eyebrowTone="purple"
        title={<>Import from <span className="display-accent">Anywhere</span></>}
        description="Bring your existing API specifications into Apiome with a guided, multi-step import wizard. Pull from file upload, URL fetch, clipboard paste, Git cloning, SwaggerHub, Postman collections, live MCP servers, or AI-generated specs — spanning REST, event-driven, GraphQL, and gRPC APIs."
        bullets={[
          "OpenAPI 3.1 / 3.0, Swagger 2.0, and JSON Schema (REST)",
          "AsyncAPI 2.x / 3.x for event-driven and streaming APIs",
          "GraphQL from SDL or live endpoint introspection",
          "gRPC / Protobuf from .proto files or server reflection",
          "Git import from GitHub, GitLab, and Bitbucket with branch selection",
          "SwaggerHub, Postman v2.1 collections, and MCP server discovery",
          "AI-powered import: describe your API in plain English",
          "Quality scoring (A–F), transaction-based execution, and live progress logs",
        ]}
        image={{ src: '/features-03.png', alt: 'Enterprise Import wizard with multi-source import and quality scoring' }}
      />

      {/* Import Sources Showcase */}
      <section className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-purple-200/60 bg-purple-50/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-purple-700 backdrop-blur dark:border-purple-900/60 dark:bg-purple-950/50 dark:text-purple-300">
                <Import className="h-4 w-4" />
                Import Sources
              </div>
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Every source, <span className="display-accent">one catalog</span>
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                Bring in APIs however they live today — from a file on disk to a running server —
                across every major paradigm. The wizard detects, normalizes, scores, and catalogs each one.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.06}>
            <h3 className="mb-6 text-sm font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Where you import from
            </h3>
          </Reveal>
          <StaggerGroup className="mb-16 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {IMPORT_CHANNELS.map((s) => (
              <StaggerItem key={s.label}>
                <GlassCard className="flex h-full items-start gap-4 p-5">
                  <ToneChip tone={s.tone} className="h-10 w-10 shrink-0 rounded-lg">
                    {s.icon}
                  </ToneChip>
                  <div>
                    <h4 className="mb-1 text-[15px] font-semibold text-zinc-900 dark:text-zinc-50">
                      {s.label}
                    </h4>
                    <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                      {s.detail}
                    </p>
                  </div>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>

          <Reveal delay={0.06}>
            <h3 className="mb-6 text-sm font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              What you can import
            </h3>
          </Reveal>
          <StaggerGroup className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {IMPORT_PARADIGMS.map((s) => (
              <StaggerItem key={s.label}>
                <GlassCard className="flex h-full items-start gap-4 p-5">
                  <ToneChip tone={s.tone} className="h-10 w-10 shrink-0 rounded-lg">
                    {s.icon}
                  </ToneChip>
                  <div>
                    <h4 className="mb-1 text-[15px] font-semibold text-zinc-900 dark:text-zinc-50">
                      {s.label}
                    </h4>
                    <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                      {s.detail}
                    </p>
                  </div>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </div>
      </section>

      {/* Complete Grid */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-24 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Complete <span className="display-accent">platform</span> capabilities
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                Every tool you need to design, validate, export, and collaborate on APIs — in one place.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {FEATURE_GRID.map((f) => (
              <StaggerItem key={f.title}>
                <GlassCard className="h-full p-6">
                  <ToneChip tone={f.tone} className="mb-4 h-10 w-10 rounded-lg">
                    {f.icon}
                  </ToneChip>
                  <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                    {f.title}
                  </h3>
                  <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                    {f.description}
                  </p>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </div>
      </section>

      {/* Comparison */}
      <section className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-14 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Why teams choose <span className="display-accent">Apiome</span>
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                Unlike text-only spec editors or heavyweight API gateways, Apiome is a
                visual-first design platform purpose-built for teams who think in data models
                and endpoints.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.1}>
            <GlassCard interactive={false} className="overflow-hidden p-0" data-always="true">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200/70 dark:border-zinc-800/70">
                      <th className="sticky left-0 bg-[var(--surface-glass)] py-4 pl-6 pr-6 font-semibold text-zinc-900 backdrop-blur dark:text-zinc-50">
                        Capability
                      </th>
                      <th className="px-4 py-4 text-center font-semibold text-blue-600 dark:text-blue-400">
                        Apiome
                      </th>
                      <th className="px-4 py-4 text-center font-semibold text-zinc-500 dark:text-zinc-400">
                        Swagger Editor
                      </th>
                      <th className="px-4 py-4 text-center font-semibold text-zinc-500 dark:text-zinc-400">
                        Stoplight Studio
                      </th>
                      <th className="px-4 py-4 pr-6 text-center font-semibold text-zinc-500 dark:text-zinc-400">
                        Postman
                      </th>
                    </tr>
                  </thead>
                  <tbody className="text-zinc-600 dark:text-zinc-400">
                    {comparisonRows.map(({ feature, apiome, swagger, stoplight, postman }, i) => (
                      <tr
                        key={feature}
                        className={`border-b border-zinc-100/80 transition-colors hover:bg-blue-50/40 dark:border-zinc-800/40 dark:hover:bg-blue-950/20 ${
                          i % 2 === 0 ? 'bg-transparent' : 'bg-zinc-50/40 dark:bg-zinc-900/30'
                        }`}
                      >
                        <td className="sticky left-0 bg-inherit py-3 pl-6 pr-6 font-medium text-zinc-900 dark:text-zinc-200">
                          {feature}
                        </td>
                        <td className="px-4 py-3 text-center">{apiome}</td>
                        <td className="px-4 py-3 text-center">{swagger}</td>
                        <td className="px-4 py-3 text-center">{stoplight}</td>
                        <td className="px-4 py-3 pr-6 text-center">{postman}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          </Reveal>

          <p className="mt-6 text-center text-xs text-zinc-400 dark:text-zinc-500">
            Comparison based on publicly available feature sets as of February 2026. Feature availability may change.
          </p>
        </div>
      </section>

      {/* Workflow */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-24 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Your design-to-deployment <span className="display-accent">workflow</span>
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                From first schema sketch to production-ready OpenAPI spec in four steps.
              </p>
            </div>
          </Reveal>

          <div className="relative">
            <div
              aria-hidden
              className="absolute inset-x-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-zinc-300 to-transparent dark:via-zinc-700 lg:block"
            />
            <StaggerGroup className="grid gap-8 lg:grid-cols-4">
              {[
                { step: 1, title: 'Design Schemas', description: 'Drag classes onto the canvas, define properties and types, and draw relationships between your data models.', dotClass: 'from-blue-500 to-blue-600' },
                { step: 2, title: 'Author Paths', description: 'Open the Paths Designer to create endpoints, bind schemas to request bodies and responses, and configure security.', dotClass: 'from-emerald-500 to-emerald-600' },
                { step: 3, title: 'Validate & Score', description: 'Run real-time OpenAPI validation, review quality scores, and fix issues before exporting your specification.', dotClass: 'from-purple-500 to-purple-600' },
                { step: 4, title: 'Export & Ship', description: 'Export as OpenAPI YAML/JSON, generate code stubs, or share your API documentation with your team and consumers.', dotClass: 'from-orange-500 to-orange-600' },
              ].map(({ step, title, description, dotClass }) => (
                <StaggerItem key={step}>
                  <div className="text-center">
                    <div
                      className={`relative mx-auto mb-6 inline-flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br ${dotClass} text-xl font-semibold text-white shadow-lg ring-4 ring-white dark:ring-zinc-950`}
                    >
                      {step}
                    </div>
                    <h3 className="mb-3 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                      {title}
                    </h3>
                    <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                      {description}
                    </p>
                  </div>
                </StaggerItem>
              ))}
            </StaggerGroup>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 py-24">
        <div className="container mx-auto max-w-5xl">
          <Reveal>
            <div className="shine-on-hover relative overflow-hidden rounded-[2rem] border border-white/10 bg-gradient-to-br from-blue-600 via-indigo-600 to-purple-600 p-12 text-center text-white shadow-2xl sm:p-16">
              <div aria-hidden className="shine-ambient" />
              <div className="relative">
                <h2 className="mb-4 text-4xl font-semibold tracking-tight sm:text-5xl">
                  Ready to design better APIs?
                </h2>
                <p className="mb-10 text-lg text-blue-100 sm:text-xl">
                  Join the developers and teams already using Apiome to visually design,
                  validate, and ship their API specifications.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <a href={links.app} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="secondary" className="bg-white text-blue-600 hover:bg-zinc-100">
                      Launch App
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </Button>
                  </a>
                  <a href={links.browse} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="ghost-glass" className="text-white">
                      Browse Public APIs
                    </Button>
                  </a>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}

const comparisonRows = [
  { feature: 'Visual Schema Canvas', apiome: '✅', swagger: '❌', stoplight: '✅', postman: '❌' },
  { feature: 'Visual Path / Endpoint Designer', apiome: '✅', swagger: '❌', stoplight: 'Partial', postman: '❌' },
  { feature: 'OpenAPI 3.1 Support', apiome: '✅', swagger: '✅', stoplight: '✅', postman: '✅' },
  { feature: 'Drag-and-Drop Nodes', apiome: '✅', swagger: '❌', stoplight: '✅', postman: '❌' },
  { feature: 'Multi-Source Import (File, URL, Git, SwaggerHub, Postman, MCP, AI)', apiome: '✅', swagger: 'File only', stoplight: 'File / URL', postman: 'File / URL' },
  { feature: 'Multi-Paradigm Import (REST, AsyncAPI, GraphQL, gRPC)', apiome: '✅', swagger: '❌', stoplight: 'Partial', postman: '❌' },
  { feature: 'AI-Powered Spec Generation', apiome: '✅', swagger: '❌', stoplight: '❌', postman: '❌' },
  { feature: 'Quality Scoring (A–F)', apiome: '✅', swagger: '❌', stoplight: 'Partial', postman: '❌' },
  { feature: 'Canvas Themes (10+)', apiome: '✅', swagger: '❌', stoplight: '❌', postman: '❌' },
  { feature: 'Canvas Export (PNG, SVG, PDF, Mermaid)', apiome: '✅', swagger: '❌', stoplight: '❌', postman: '❌' },
  { feature: 'Version Side-by-Side Diff', apiome: '✅', swagger: '❌', stoplight: '✅', postman: '❌' },
  { feature: 'Group Containers for Schemas', apiome: '✅', swagger: '❌', stoplight: '❌', postman: '❌' },
  { feature: 'Smart Edge Routing (4 styles)', apiome: '✅', swagger: '❌', stoplight: 'Basic', postman: '❌' },
  { feature: 'Multi-Tenant / Team Workspaces', apiome: '✅', swagger: '❌', stoplight: '✅', postman: '✅' },
  { feature: 'Granular RBAC (Owner / Editor / Viewer)', apiome: '✅', swagger: '❌', stoplight: 'Partial', postman: 'Partial' },
  { feature: 'Tamper-Evident Access Audit Log', apiome: '✅', swagger: '❌', stoplight: '❌', postman: '❌' },
  { feature: 'Free Personal Tier', apiome: '✅', swagger: '✅', stoplight: '✅', postman: '✅' },
];
