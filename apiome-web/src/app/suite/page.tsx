import { links } from "@/lib/links";
import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import { ArrowRight, Sparkles, Rocket, ShieldCheck, Building2 } from "lucide-react";
import { Button } from "../components/ui/Button";
import { Aurora } from "../components/ui/Aurora";
import { GlassCard, ToneChip, type Tone } from "../components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem } from "../components/motion/Reveal";
import { SUITES } from "./data";
import { SuiteIcon } from "./icons";

export const metadata: Metadata = {
  title: "The Apiome Suite — Coming Soon",
  description:
    "Sixteen enterprise-grade suites coming to the Apiome platform — Academy, Analytics, Architect, Automation, Browser, Code Generation, Collaboration, Connect, Contracts, Data Insights, Database, Data Transform, Detective, Import, Linting, and Shield. Each ships with deep AI integration and is available for early access.",
};

const TONE_CHIP_BG: Record<Tone, string> = {
  blue: "bg-blue-100/80 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300",
  emerald: "bg-emerald-100/80 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300",
  purple: "bg-purple-100/80 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300",
  orange: "bg-orange-100/80 text-orange-700 dark:bg-orange-950/60 dark:text-orange-300",
  indigo: "bg-indigo-100/80 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300",
  sky: "bg-sky-100/80 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300",
  rose: "bg-rose-100/80 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300",
  cyan: "bg-cyan-100/80 text-cyan-700 dark:bg-cyan-950/60 dark:text-cyan-300",
  violet: "bg-violet-100/80 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300",
  amber: "bg-amber-100/80 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300",
  pink: "bg-pink-100/80 text-pink-700 dark:bg-pink-950/60 dark:text-pink-300",
  red: "bg-red-100/80 text-red-700 dark:bg-red-950/60 dark:text-red-300",
  teal: "bg-teal-100/80 text-teal-700 dark:bg-teal-950/60 dark:text-teal-300",
  green: "bg-green-100/80 text-green-700 dark:bg-green-950/60 dark:text-green-300",
};

export default function SuitePage() {
  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-32">
        <Aurora />
        <div className="container relative mx-auto max-w-5xl text-center">
          <Reveal>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/80 px-4 py-2 text-sm font-medium text-blue-700 backdrop-blur dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300">
              <Sparkles className="h-4 w-4" />
              Coming Soon · Early Access Open
            </div>
          </Reveal>
          <Reveal delay={0.06}>
            <h1 className="mb-6 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl lg:text-7xl">
              The Apiome <span className="display-accent">Suite</span>
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mb-6 font-display text-2xl italic text-zinc-700 dark:text-zinc-200 sm:text-3xl">
              Sixteen enterprise suites. One platform.
            </p>
          </Reveal>
          <Reveal delay={0.2}>
            <p className="mx-auto mb-10 max-w-3xl text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
              Apiome is expanding from a visual API and schema design platform into a full
              suite of enterprise-grade applications. Each suite is independently subscribable,
              deeply integrated with the rest of the platform, and ships with its own AI co-pilot.
              Sign up for early access and shape the next decade of API tooling.
            </p>
          </Reveal>
          <Reveal delay={0.28}>
            <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a href="mailto:hello@apiome.app?subject=Early%20Access%20%E2%80%94%20Apiome%20Suite">
                <Button size="lg" className="group">
                  Apply for Early Access
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </a>
              <a href="#suites">
                <Button size="lg" variant="outline">
                  Explore the Suites
                </Button>
              </a>
            </div>
          </Reveal>
          <Reveal delay={0.34}>
            <p className="mt-6 text-sm text-zinc-500 dark:text-zinc-500">
              No commitment required · Designed for enterprise procurement & InfoSec review
            </p>
          </Reveal>
        </div>
      </section>

      {/* Three pillars */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                Built on three principles
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                Every suite in the catalog follows the same playbook so they compose,
                integrate, and scale the same way.
              </p>
            </div>
          </Reveal>
          <StaggerGroup className="grid gap-6 md:grid-cols-3">
            <StaggerItem>
              <GlassCard className="h-full p-7">
                <ToneChip tone="sky" className="mb-5">
                  <Sparkles className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                  AI inside every surface
                </h3>
                <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Each suite ships with its own grounded AI integration — drafting, summarizing,
                  diagnosing, and recommending — without ever leaving the product context.
                </p>
              </GlassCard>
            </StaggerItem>
            <StaggerItem>
              <GlassCard className="h-full p-7">
                <ToneChip tone="rose" className="mb-5">
                  <ShieldCheck className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                  Enterprise from day one
                </h3>
                <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  SSO, SCIM, audit logs, residency controls, customer-managed keys, and
                  policy-as-code are baseline features — not premium upgrades.
                </p>
              </GlassCard>
            </StaggerItem>
            <StaggerItem>
              <GlassCard className="h-full p-7">
                <ToneChip tone="emerald" className="mb-5">
                  <Building2 className="h-5 w-5" />
                </ToneChip>
                <h3 className="mb-2 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                  Subscribe what you need
                </h3>
                <p className="text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  Each suite is a separately subscribable product. Start with one, add more as
                  your platform grows — without re-platforming or migrating data.
                </p>
              </GlassCard>
            </StaggerItem>
          </StaggerGroup>
        </div>
      </section>

      {/* Suite grid */}
      <section id="suites" className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-14 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Explore the <span className="display-accent">Suite</span> catalog
              </h2>
              <p className="mx-auto max-w-2xl text-lg text-zinc-600 dark:text-zinc-400">
                {SUITES.length} enterprise applications, each with its own design surfaces, AI
                integration, and enterprise controls. Click any suite to dive in.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {SUITES.map((suite) => (
              <StaggerItem key={suite.slug}>
                <Link href={`/suite/${suite.slug}`} className="group block h-full">
                  <GlassCard className="flex h-full flex-col overflow-hidden p-0">
                    <div className="relative aspect-[16/10] w-full overflow-hidden border-b border-zinc-200/60 bg-zinc-50 dark:border-zinc-800/60 dark:bg-zinc-900">
                      <Image
                        src={suite.cover}
                        alt={`${suite.fullName} preview`}
                        fill
                        sizes="(max-width: 768px) 100vw, (max-width: 1024px) 50vw, 33vw"
                        className="object-cover object-top transition-transform duration-500 group-hover:scale-[1.03]"
                      />
                      <span
                        className={`absolute left-4 top-4 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider backdrop-blur ${TONE_CHIP_BG[suite.tone]}`}
                      >
                        <Sparkles className="h-3 w-3" />
                        {statusLabel(suite.status)}
                      </span>
                    </div>
                    <div className="flex flex-1 flex-col p-6">
                      <div className="mb-3 flex items-center gap-3">
                        <ToneChip tone={suite.tone} className="h-9 w-9 rounded-lg">
                          <SuiteIcon name={suite.icon} className="h-4 w-4" />
                        </ToneChip>
                        <div className="min-w-0">
                          <h3 className="truncate text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                            {suite.fullName}
                          </h3>
                          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                            {suite.category}
                          </p>
                        </div>
                      </div>
                      <p className="mb-4 line-clamp-3 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                        {suite.tagline}
                      </p>
                      <div className="mt-auto flex items-center justify-between text-sm">
                        <span className="text-zinc-500 dark:text-zinc-400">
                          {suite.modules.length} surfaces
                        </span>
                        <span className="inline-flex items-center gap-1 font-medium text-blue-600 transition-transform group-hover:translate-x-1 dark:text-blue-400">
                          Learn more <ArrowRight className="h-4 w-4" />
                        </span>
                      </div>
                    </div>
                  </GlassCard>
                </Link>
              </StaggerItem>
            ))}
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
                    "radial-gradient(circle at 20% 20%, rgba(255,255,255,0.35), transparent 40%), radial-gradient(circle at 80% 80%, rgba(255,255,255,0.25), transparent 45%)",
                }}
              />
              <div className="shine-ambient" />
              <div className="relative">
                <Rocket className="mx-auto mb-4 h-10 w-10" />
                <h2 className="mb-4 text-4xl font-semibold tracking-tight sm:text-5xl">
                  Get early access to the Suite
                </h2>
                <p className="mb-10 text-lg text-blue-100 sm:text-xl">
                  Join the design partner program — help shape the suites your team will rely on
                  for the next decade.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <a href="mailto:hello@apiome.app?subject=Early%20Access%20%E2%80%94%20Apiome%20Suite">
                    <Button size="lg" variant="secondary" className="bg-white text-blue-600 hover:bg-zinc-100">
                      Apply for Early Access
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </Button>
                  </a>
                  <a href={links.app} target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="ghost-glass" className="text-white">
                      Launch the App
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

function statusLabel(status: "coming-soon" | "early-access" | "beta") {
  switch (status) {
    case "early-access":
      return "Early Access";
    case "beta":
      return "Public Beta";
    default:
      return "Coming Soon";
  }
}
