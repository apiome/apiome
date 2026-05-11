import {
  ArrowRight,
  Database,
  Zap,
  Star,
  GitBranch,
  Route,
  Import,
  LayoutGrid,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { Button } from "./components/ui/Button";
import { Aurora } from "./components/ui/Aurora";
import { GlassCard, ToneChip, type Tone } from "./components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem, CountUp } from "./components/motion/Reveal";

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
      "Import from file, URL, Git, SwaggerHub, clipboard, or AI. Guided wizard with quality scoring, validation, and transaction-based execution.",
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

export default function Home() {
  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-36">
        <Aurora />
        <div className="container relative mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <Reveal>
              <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/80 px-4 py-2 text-sm font-medium text-blue-700 backdrop-blur animate-pulse-ring dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300">
                <Star className="h-4 w-4" />
                Now in Public Beta
              </div>
            </Reveal>
            <Reveal delay={0.05}>
              <h1 className="mb-8 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl lg:text-7xl">
                Design APIs &amp; Databases{" "}
                <span className="display-accent">Visually</span>
              </h1>
            </Reveal>
            <Reveal delay={0.12}>
              <p className="mb-6 font-display text-2xl italic text-zinc-700 dark:text-zinc-200 sm:text-3xl">
                Your data: Designed, Defined, Discovered.
              </p>
            </Reveal>
            <Reveal delay={0.18}>
              <p className="mb-12 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
                The modern platform for creating OpenAPI specifications and database schemas.
                <br className="hidden sm:block" />
                Design schemas on an interactive canvas, author API paths visually, import from anywhere,
                and export production-ready specs.
              </p>
            </Reveal>
            <Reveal delay={0.24}>
              <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                <a href="https://app.objectified.dev" target="_blank" rel="noopener noreferrer">
                  <Button size="lg" className="group">
                    Launch App
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </a>
                <a href="https://browse.objectified.dev" target="_blank" rel="noopener noreferrer">
                  <Button size="lg" variant="outline">
                    Browse APIs
                  </Button>
                </a>
                <a href="https://www.youtube.com/@objectifieddev" target="_blank" rel="noopener noreferrer">
                  <Button size="lg" variant="outline">
                    Watch Demo
                  </Button>
                </a>
              </div>
            </Reveal>
            <Reveal delay={0.32}>
              <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-500">
                No credit card required &middot; Free forever for personal use
              </p>
            </Reveal>
          </div>
        </div>
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
                <GlassCard className="h-full p-7">
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
              <Link href="/features">
                <Button size="lg" variant="outline" className="group">
                  See All Features
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </Link>
              <Link href="/screenshots">
                <Button size="lg" variant="outline" className="group">
                  Product screenshots
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </Link>
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
                How Objectified Works
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
                <a href="https://browse.objectified.dev" target="_blank" rel="noopener noreferrer">
                  <Button size="lg" className="group">
                    Browse Public APIs
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </a>
              </div>
            </Reveal>
            <Reveal delay={0.15}>
              <GlassCard interactive={false} className="p-6" data-always="true">
                <div className="relative aspect-video overflow-hidden rounded-lg ring-1 ring-black/10 dark:ring-white/10">
                  <Image
                    src="/browser-01.png"
                    alt="Public API Browser — explore OpenAPI specifications"
                    fill
                    className="object-cover"
                    sizes="(max-width: 1024px) 100vw, 50vw"
                  />
                </div>
              </GlassCard>
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
                  Join developers and teams already using Objectified to visually design, validate,
                  and ship their API specifications.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <a href="https://app.objectified.dev" target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="secondary" className="bg-white text-blue-600 hover:bg-zinc-100">
                      Launch App
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </Button>
                  </a>
                  <a href="https://browse.objectified.dev" target="_blank" rel="noopener noreferrer">
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
