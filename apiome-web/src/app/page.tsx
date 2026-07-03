import { links } from "@/lib/links";
import {
  ArrowRight,
  ChevronDown,
  Database,
  Zap,
  Star,
  GitBranch,
  Route,
  Import,
  LayoutGrid,
  Sparkles,
  ShieldCheck,
  Layers,
  Globe,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { Button } from "./components/ui/Button";
import { GlassCard, ToneChip, type Tone } from "./components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem, CountUp } from "./components/motion/Reveal";
import { Magnetic } from "./components/motion/Magnetic";
import { Parallax } from "./components/motion/Parallax";
import { Marquee } from "./components/motion/Marquee";
import { HeroHive } from "./components/hive/HeroHive";

type HomeFeature = {
  icon: React.ReactNode;
  title: string;
  description: string;
  tone: Tone;
};

const HOME_FEATURES: HomeFeature[] = [
  {
    icon: <LayoutGrid className="h-5 w-5" />,
    title: "Visual Schema Canvas",
    description:
      "Design data models on an interactive canvas with drag-and-drop, smart auto-layout, color-coded groups, animated edges, and 10+ themes.",
    tone: "blue",
  },
  {
    icon: <Route className="h-5 w-5" />,
    title: "Paths Designer",
    description:
      "Author API endpoints visually with HTTP method color coding, parameter editing, response schema binding, and real-time OpenAPI validation.",
    tone: "emerald",
  },
  {
    icon: <Import className="h-5 w-5" />,
    title: "Enterprise Import",
    description:
      "Import from file, URL, clipboard, Git, SwaggerHub, Postman, MCP servers, or AI — across REST, AsyncAPI, GraphQL, and gRPC. Guided wizard with quality scoring, validation, and transaction-based execution.",
    tone: "purple",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    title: "Export & Code Generation",
    description:
      "Export to OpenAPI YAML/JSON, PNG, SVG, PDF, Mermaid, PlantUML, and more. Generate DTO stubs and database migrations automatically.",
    tone: "orange",
  },
  {
    icon: <GitBranch className="h-5 w-5" />,
    title: "Version Control & Diff",
    description:
      "Track changes with full version history. Compare versions side by side with diff highlighting for added, modified, and removed schemas.",
    tone: "indigo",
  },
  {
    icon: <Sparkles className="h-5 w-5" />,
    title: "AI-Powered Design",
    description:
      "Describe your API in plain English and let AI generate a complete OpenAPI specification. Quality scoring grades your spec from A to F.",
    tone: "sky",
  },
  {
    icon: <ShieldCheck className="h-5 w-5" />,
    title: "Roles & Access Control",
    description:
      "Granular RBAC with built-in Owner, Admin, Editor, and Viewer roles, a tunable permission matrix, member lifecycle controls, and a tamper-evident access audit log.",
    tone: "rose",
  },
  {
    icon: <Layers className="h-5 w-5" />,
    title: "Multi-Tenant Workspaces",
    description:
      "Organize projects by team and organization with isolated workspaces, per-tenant roles, and a separate platform-admin plane for operators.",
    tone: "green",
  },
  {
    icon: <Globe className="h-5 w-5" />,
    title: "Public API Browser",
    description:
      "Publish specifications to a public portal with Monaco-powered viewers, version comparison, and embeddable snippets — or browse community designs.",
    tone: "cyan",
  },
];

const HOW_STEPS: { title: string; description: string; dotClass: string }[] = [
  {
    title: "Design Schemas",
    description:
      "Drag classes onto the canvas, define properties and types, and draw relationships — or import an existing OpenAPI spec.",
    dotClass: "from-blue-500 to-blue-600",
  },
  {
    title: "Author Paths",
    description:
      "Switch to the Paths Designer to create endpoints, bind schemas to request bodies and responses, and configure security.",
    dotClass: "from-emerald-500 to-emerald-600",
  },
  {
    title: "Validate & Score",
    description:
      "Run real-time OpenAPI validation, review quality scores from A to F, and fix issues before exporting.",
    dotClass: "from-purple-500 to-purple-600",
  },
  {
    title: "Export & Ship",
    description:
      "Export as OpenAPI YAML/JSON, generate code stubs, or share your API documentation with your team and consumers.",
    dotClass: "from-orange-500 to-orange-600",
  },
];

const MARQUEE_ITEMS = [
  "OpenAPI 3.1.0",
  "Visual Schema Canvas",
  "Paths Designer",
  "Enterprise Import",
  "Code Generation",
  "Version Control",
  "AI-Powered Design",
  "Granular RBAC",
  "Access Audit Log",
  "Mermaid · PlantUML",
  "PNG · SVG · PDF",
];

export default function Home() {
  return (
    <div className="flex flex-col">
      {/* Brand splash */}
      <section className="grain relative isolate flex min-h-[100svh] items-center overflow-hidden px-6 py-24">
        <HeroHive />
        <div aria-hidden className="hero-halo absolute inset-0 -z-20" />
        <div
          aria-hidden
          className="absolute inset-x-0 bottom-0 -z-10 h-40 bg-gradient-to-b from-transparent to-[var(--background)]"
        />

        <div className="container relative mx-auto max-w-6xl">
          <div className="mx-auto max-w-4xl text-center">
            <h1 className="sr-only">Apiome &mdash; Platform for APIs &amp; Schemas</h1>
            <Reveal>
              <div className="mb-10 flex flex-col items-center gap-5">
                <Image
                  src="/Apiome-02.png"
                  alt="Apiome logo"
                  width={1174}
                  height={398}
                  priority
                  className="h-28 w-auto object-contain drop-shadow-[0_10px_30px_rgba(37,99,235,0.25)] dark:hidden sm:h-36"
                />
                <Image
                  src="/Apiome-05.png"
                  alt="Apiome logo"
                  width={1174}
                  height={398}
                  priority
                  className="hidden h-28 w-auto object-contain drop-shadow-[0_10px_30px_rgba(37,99,235,0.25)] dark:block sm:h-36"
                />
                <p className="text-xs font-semibold uppercase tracking-[0.32em] text-zinc-500 dark:text-zinc-400 sm:text-sm">
                  Platform for APIs &amp; Schemas
                </p>
              </div>
            </Reveal>

            <Reveal delay={0.08}>
              <div className="mb-10 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/70 px-4 py-2 text-sm font-medium text-blue-700 backdrop-blur animate-pulse-ring dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-300">
                <Star className="h-4 w-4" />
                <span className="text-shimmer">Now in Release Candidate &middot; RC2</span>
              </div>
            </Reveal>

            <Reveal delay={0.14}>
              <p className="mx-auto mb-10 max-w-3xl font-display text-xl leading-relaxed text-zinc-700 dark:text-zinc-200 sm:text-2xl">
                <span className="block">
                  Every organization has an <span className="italic">apiome</span> &mdash; the
                  complete set of APIs it runs on.
                </span>
                <span className="block">
                  <span className="font-semibold text-zinc-900 dark:text-zinc-50">Apiome by NobuData</span>{" "}
                  is its <span className="display-accent">system of record</span>.
                </span>
              </p>
            </Reveal>

            <Reveal delay={0.2}>
              <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                <Magnetic>
                  <a href={links.app} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" className="group">
                      Launch App
                      <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                    </Button>
                  </a>
                </Magnetic>
                <Magnetic strength={0.3}>
                  <a href={links.browse} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="outline">
                      Browse APIs
                    </Button>
                  </a>
                </Magnetic>
                <Magnetic strength={0.3}>
                  <a href={links.demo} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="outline">
                      Watch Demo
                    </Button>
                  </a>
                </Magnetic>
              </div>
            </Reveal>
          </div>
        </div>

        <a
          href="#capabilities"
          aria-label="Scroll to learn more"
          className="absolute bottom-8 left-1/2 -translate-x-1/2 text-zinc-400 transition-colors hover:text-zinc-600 dark:text-zinc-600 dark:hover:text-zinc-300"
        >
          <ChevronDown className="h-7 w-7 animate-bounce motion-reduce:animate-none" />
        </a>
      </section>

      {/* Capability marquee */}
      <section
        id="capabilities"
        className="scroll-mt-16 border-b border-zinc-200/70 py-8 dark:border-zinc-800/70"
      >
        <Marquee duration={36}>
          {MARQUEE_ITEMS.map((item) => (
            <span
              key={item}
              className="flex items-center gap-3 whitespace-nowrap text-lg font-medium tracking-tight text-zinc-400 dark:text-zinc-600"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500/70" />
              {item}
            </span>
          ))}
        </Marquee>
      </section>

      {/* Features Overview */}
      <section className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Everything you need to build{" "}
                <span className="display-accent">better APIs</span>
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                Powerful features that streamline your entire API development workflow.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {HOME_FEATURES.map((feature) => (
              <StaggerItem key={feature.title}>
                <GlassCard className="shine-on-hover h-full p-7">
                  <ToneChip tone={feature.tone} className="mb-5">
                    {feature.icon}
                  </ToneChip>
                  <h3 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                    {feature.title}
                  </h3>
                  <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                    {feature.description}
                  </p>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>

          <Reveal delay={0.1}>
            <div className="mt-14 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Magnetic strength={0.3}>
                <Link href="/features">
                  <Button size="lg" variant="outline" className="group">
                    See All Features
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </Link>
              </Magnetic>
              <Magnetic strength={0.3}>
                <Link href="/screenshots">
                  <Button size="lg" variant="outline" className="group">
                    Product screenshots
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </Link>
              </Magnetic>
            </div>
          </Reveal>
        </div>
      </section>

      {/* How It Works */}
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div aria-hidden className="absolute inset-0 -z-10 bg-gradient-to-b from-zinc-50/80 via-white to-zinc-50/80 dark:from-zinc-900/40 dark:via-zinc-950 dark:to-zinc-900/40" />
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                How Apiome Works
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                From design to deployment in four simple steps.
              </p>
            </div>
          </Reveal>

          <div className="relative">
            {/* Connecting line on desktop */}
            <div
              aria-hidden
              className="absolute inset-x-0 top-8 hidden h-px bg-gradient-to-r from-transparent via-zinc-300 to-transparent dark:via-zinc-700 lg:block"
            />

            <StaggerGroup className="relative grid gap-10 lg:grid-cols-4">
              {HOW_STEPS.map((step, i) => (
                <StaggerItem key={step.title}>
                  <div className="relative text-center">
                    <div
                      className={`relative mx-auto mb-6 inline-flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br ${step.dotClass} text-2xl font-semibold text-white shadow-lg ring-4 ring-white dark:ring-zinc-950`}
                    >
                      {i + 1}
                    </div>
                    <h3 className="mb-3 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                      {step.title}
                    </h3>
                    <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                      {step.description}
                    </p>
                  </div>
                </StaggerItem>
              ))}
            </StaggerGroup>
          </div>
        </div>
      </section>

      {/* Public Browser Section */}
      <section className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <Reveal>
              <div>
                <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-indigo-200/60 bg-indigo-50/80 px-4 py-2 text-sm font-medium text-indigo-700 backdrop-blur dark:border-indigo-900/60 dark:bg-indigo-950/50 dark:text-indigo-300">
                  <Database className="h-4 w-4" />
                  Public API Browser
                </div>
                <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                  Explore Public{" "}
                  <span className="display-accent">OpenAPI</span>{" "}
                  Specifications
                </h2>
                <p className="mb-6 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Discover and learn from publicly available OpenAPI specifications shared by the community.
                  Browse real-world API designs, get inspiration for your projects, and see how others
                  structure their APIs.
                </p>
                <ul className="mb-8 space-y-3 text-zinc-600 dark:text-zinc-400">
                  {[
                    "Browse hundreds of public API specifications",
                    "View detailed endpoint documentation and schemas",
                    "Learn best practices from community-shared designs",
                    "Share your own APIs with the community",
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-3">
                      <div className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs text-indigo-600 dark:bg-indigo-950/60 dark:text-indigo-300">
                        ✓
                      </div>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
                <Magnetic>
                  <a href={links.browse} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" className="group">
                      Browse Public APIs
                      <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                    </Button>
                  </a>
                </Magnetic>
              </div>
            </Reveal>
            <Reveal delay={0.15}>
              <Parallax speed={28}>
                <GlassCard interactive={false} className="overflow-hidden p-0" data-always="true">
                  <div className="flex items-center gap-2 border-b border-zinc-200/80 bg-zinc-50/80 px-4 py-2.5 dark:border-zinc-800/80 dark:bg-zinc-900/80">
                    <span className="h-3 w-3 rounded-full bg-red-400/80" aria-hidden />
                    <span className="h-3 w-3 rounded-full bg-amber-400/80" aria-hidden />
                    <span className="h-3 w-3 rounded-full bg-emerald-400/80" aria-hidden />
                    <div className="ml-3 hidden flex-1 sm:block">
                      <div className="inline-flex max-w-full items-center rounded-md bg-white/70 px-3 py-1 text-xs font-medium text-zinc-500 ring-1 ring-inset ring-zinc-200/80 dark:bg-zinc-950/60 dark:text-zinc-400 dark:ring-zinc-800/80">
                        browse.apiome.app
                      </div>
                    </div>
                  </div>
                  <div className="relative aspect-video overflow-hidden">
                    <Image
                      src="/browser-01.png"
                      alt="Public API Browser — explore OpenAPI specifications"
                      fill
                      className="object-cover object-top"
                      sizes="(max-width: 1024px) 100vw, 50vw"
                    />
                  </div>
                </GlassCard>
              </Parallax>
            </Reveal>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <StaggerGroup className="grid gap-8 md:grid-cols-4">
            <StaggerItem>
              <StatItem value={500} suffix="+" label="Active Projects" color="text-blue-600 dark:text-blue-400" />
            </StaggerItem>
            <StaggerItem>
              <StatItem value={50} suffix="k+" label="API Endpoints Designed" color="text-purple-600 dark:text-purple-400" />
            </StaggerItem>
            <StaggerItem>
              <StatItem value={1} suffix="k+" label="Happy Developers" color="text-green-600 dark:text-green-400" />
            </StaggerItem>
            <StaggerItem>
              <StatItem value={99.9} suffix="%" decimals={1} label="Uptime SLA" color="text-orange-600 dark:text-orange-400" />
            </StaggerItem>
          </StaggerGroup>
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 py-24">
        <div className="container mx-auto max-w-5xl">
          <Reveal>
            <div className="shine-on-hover relative overflow-hidden rounded-[2rem] border border-white/10 bg-gradient-to-br from-blue-600 via-indigo-600 to-purple-600 p-12 text-center text-white shadow-2xl sm:p-16">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 opacity-40"
                style={{
                  background:
                    'radial-gradient(circle at 20% 20%, rgba(255,255,255,0.35), transparent 40%), radial-gradient(circle at 80% 80%, rgba(255,255,255,0.25), transparent 45%)',
                }}
              />
              <div className="shine-ambient" />
              <div className="relative">
                <h2 className="mb-4 text-4xl font-semibold tracking-tight sm:text-5xl">
                  Ready to build better APIs?
                </h2>
                <p className="mb-10 text-lg text-blue-100 sm:text-xl">
                  Join developers and teams already using Apiome to visually design, validate,
                  and ship their API specifications.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <Magnetic>
                    <a href={links.app} target="_blank" rel="noopener noreferrer">
                      <Button size="lg" variant="secondary" className="bg-white text-blue-600 hover:bg-zinc-100">
                        Launch App
                        <ArrowRight className="ml-1 h-4 w-4" />
                      </Button>
                    </a>
                  </Magnetic>
                  <Magnetic strength={0.3}>
                    <a href={links.browse} target="_blank" rel="noopener noreferrer">
                      <Button size="lg" variant="ghost-glass" className="text-white">
                        Browse Public APIs
                      </Button>
                    </a>
                  </Magnetic>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}

function StatItem({
  value,
  suffix,
  label,
  color,
  decimals = 0,
}: {
  value: number;
  suffix?: string;
  label: string;
  color: string;
  decimals?: number;
}) {
  return (
    <div className="text-center">
      <div className={`mb-2 text-4xl font-semibold tracking-tight sm:text-5xl ${color}`}>
        <CountUp to={value} suffix={suffix} decimals={decimals} />
      </div>
      <div className="text-zinc-600 dark:text-zinc-400">{label}</div>
    </div>
  );
}
