import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Sparkles,
  ShieldCheck,
  Users,
  Layers,
  Rocket,
  Building2,
} from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Aurora } from "../../components/ui/Aurora";
import { GlassCard, ToneChip, type Tone } from "../../components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem } from "../../components/motion/Reveal";
import { SUITES, SUITES_BY_SLUG } from "../data";
import { SuiteIcon } from "../icons";

const TONE_BANNER: Record<Tone, string> = {
  blue: "from-blue-500/15 via-blue-500/5 to-transparent dark:from-blue-500/25",
  emerald: "from-emerald-500/15 via-emerald-500/5 to-transparent dark:from-emerald-500/25",
  purple: "from-purple-500/15 via-purple-500/5 to-transparent dark:from-purple-500/25",
  orange: "from-orange-500/15 via-orange-500/5 to-transparent dark:from-orange-500/25",
  indigo: "from-indigo-500/15 via-indigo-500/5 to-transparent dark:from-indigo-500/25",
  sky: "from-sky-500/15 via-sky-500/5 to-transparent dark:from-sky-500/25",
  rose: "from-rose-500/15 via-rose-500/5 to-transparent dark:from-rose-500/25",
  cyan: "from-cyan-500/15 via-cyan-500/5 to-transparent dark:from-cyan-500/25",
  violet: "from-violet-500/15 via-violet-500/5 to-transparent dark:from-violet-500/25",
  amber: "from-amber-500/15 via-amber-500/5 to-transparent dark:from-amber-500/25",
  pink: "from-pink-500/15 via-pink-500/5 to-transparent dark:from-pink-500/25",
  red: "from-red-500/15 via-red-500/5 to-transparent dark:from-red-500/25",
  teal: "from-teal-500/15 via-teal-500/5 to-transparent dark:from-teal-500/25",
  green: "from-green-500/15 via-green-500/5 to-transparent dark:from-green-500/25",
};

const TONE_EYEBROW: Record<Tone, string> = {
  blue: "border-blue-200/60 bg-blue-50/80 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300",
  emerald: "border-emerald-200/60 bg-emerald-50/80 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300",
  purple: "border-purple-200/60 bg-purple-50/80 text-purple-700 dark:border-purple-900/60 dark:bg-purple-950/50 dark:text-purple-300",
  orange: "border-orange-200/60 bg-orange-50/80 text-orange-700 dark:border-orange-900/60 dark:bg-orange-950/50 dark:text-orange-300",
  indigo: "border-indigo-200/60 bg-indigo-50/80 text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/50 dark:text-indigo-300",
  sky: "border-sky-200/60 bg-sky-50/80 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/50 dark:text-sky-300",
  rose: "border-rose-200/60 bg-rose-50/80 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/50 dark:text-rose-300",
  cyan: "border-cyan-200/60 bg-cyan-50/80 text-cyan-700 dark:border-cyan-900/60 dark:bg-cyan-950/50 dark:text-cyan-300",
  violet: "border-violet-200/60 bg-violet-50/80 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/50 dark:text-violet-300",
  amber: "border-amber-200/60 bg-amber-50/80 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/50 dark:text-amber-300",
  pink: "border-pink-200/60 bg-pink-50/80 text-pink-700 dark:border-pink-900/60 dark:bg-pink-950/50 dark:text-pink-300",
  red: "border-red-200/60 bg-red-50/80 text-red-700 dark:border-red-900/60 dark:bg-red-950/50 dark:text-red-300",
  teal: "border-teal-200/60 bg-teal-50/80 text-teal-700 dark:border-teal-900/60 dark:bg-teal-950/50 dark:text-teal-300",
  green: "border-green-200/60 bg-green-50/80 text-green-700 dark:border-green-900/60 dark:bg-green-950/50 dark:text-green-300",
};

export function generateStaticParams() {
  return SUITES.map((s) => ({ slug: s.slug }));
}

type Params = { slug: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { slug } = await params;
  const suite = SUITES_BY_SLUG[slug];
  if (!suite) return {};
  return {
    title: `${suite.fullName} — Coming Soon | Apiome Suite`,
    description: suite.tagline,
    openGraph: {
      title: `${suite.fullName} — ${suite.tagline}`,
      description: suite.summary,
      images: [{ url: suite.cover }],
    },
  };
}

export default async function SuiteDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { slug } = await params;
  const suite = SUITES_BY_SLUG[slug];
  if (!suite) notFound();

  const otherSuites = SUITES.filter((s) => s.slug !== suite.slug).slice(0, 3);

  return (
    <div className="flex flex-col">
      {/* Back link */}
      <div className="border-b border-zinc-200/60 bg-white/40 px-6 py-3 backdrop-blur dark:border-zinc-800/60 dark:bg-zinc-950/40">
        <div className="container mx-auto max-w-6xl">
          <Link
            href="/suite"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-600 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            <ArrowLeft className="h-4 w-4" />
            All Suites
          </Link>
        </div>
      </div>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70 sm:py-28">
        <Aurora />
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br ${TONE_BANNER[suite.tone]}`}
        />
        <div className="container relative mx-auto max-w-6xl">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <Reveal>
              <div>
                <div
                  className={`mb-5 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${TONE_EYEBROW[suite.tone]}`}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {statusLabel(suite.status)} · {suite.category}
                </div>
                <div className="mb-6 flex items-center gap-4">
                  <ToneChip tone={suite.tone} className="h-14 w-14 rounded-2xl">
                    <SuiteIcon name={suite.icon} className="h-7 w-7" />
                  </ToneChip>
                  <h1 className="text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                    {suite.fullName}
                  </h1>
                </div>
                <p className="mb-6 font-display text-xl italic text-zinc-700 dark:text-zinc-200">
                  {suite.tagline}
                </p>
                <p className="mb-8 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {suite.summary}
                </p>
                <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
                  <a
                    href={`mailto:hello@apiome.app?subject=Early%20Access%20%E2%80%94%20${encodeURIComponent(
                      suite.fullName,
                    )}`}
                  >
                    <Button size="lg" className="group">
                      Apply for Early Access
                      <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                    </Button>
                  </a>
                  <Link href="/suite">
                    <Button size="lg" variant="outline">
                      Browse other Suites
                    </Button>
                  </Link>
                </div>
              </div>
            </Reveal>

            <Reveal delay={0.15}>
              <GlassCard interactive={false} className="overflow-hidden p-3" data-always="true">
                <div className="relative aspect-[16/10] overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10">
                  <Image
                    src={suite.cover}
                    alt={`${suite.fullName} primary surface`}
                    fill
                    sizes="(max-width: 1024px) 100vw, 50vw"
                    className="object-cover object-top"
                    priority
                  />
                </div>
              </GlassCard>
            </Reveal>
          </div>

          {suite.highlights.length > 0 && (
            <Reveal delay={0.2}>
              <div className="mt-12 grid gap-4 rounded-2xl border border-zinc-200/70 bg-white/70 p-5 shadow-sm backdrop-blur sm:grid-cols-3 dark:border-zinc-800/70 dark:bg-zinc-950/60">
                {suite.highlights.map((h) => (
                  <div key={h.label} className="text-center">
                    <div className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                      {h.value}
                    </div>
                    <div className="mt-1 text-xs uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      {h.label}
                    </div>
                  </div>
                ))}
              </div>
            </Reveal>
          )}
        </div>
      </section>

      {/* Features */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 max-w-3xl">
              <div
                className={`mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${TONE_EYEBROW[suite.tone]}`}
              >
                <Layers className="h-3.5 w-3.5" />
                Core capabilities
              </div>
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                What ships with {suite.name}
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                Every {suite.name} surface is wired into the rest of the Apiome platform —
                no glue code, no separate identity, no bolt-on integrations.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {suite.features.map((feature) => (
              <StaggerItem key={feature.title}>
                <GlassCard className="h-full p-6">
                  <ToneChip tone={suite.tone} className="mb-4 h-10 w-10 rounded-lg">
                    <CheckCircle2 className="h-5 w-5" />
                  </ToneChip>
                  <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                    {feature.title}
                  </h3>
                  <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                    {feature.description}
                  </p>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </div>
      </section>

      {/* Screenshots gallery */}
      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 max-w-3xl">
              <div
                className={`mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${TONE_EYEBROW[suite.tone]}`}
              >
                <Sparkles className="h-3.5 w-3.5" />
                Inside the product
              </div>
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                A look inside {suite.fullName}
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                Live design previews from the {suite.name} mockup pack —{" "}
                {suite.modules.length} surfaces in total.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-2">
            {suite.details.map((shot) => (
              <StaggerItem key={shot.src}>
                <GlassCard interactive={false} className="overflow-hidden p-3" data-always="true">
                  <div className="relative aspect-[16/10] overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10">
                    <Image
                      src={shot.src}
                      alt={shot.alt}
                      fill
                      sizes="(max-width: 768px) 100vw, 50vw"
                      className="object-cover object-top"
                    />
                  </div>
                  <p className="px-2 pt-3 text-sm text-zinc-600 dark:text-zinc-400">
                    {shot.caption}
                  </p>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>

          <Reveal delay={0.1}>
            <GlassCard interactive={false} className="mt-8 overflow-hidden p-3" data-always="true">
              <div className="relative aspect-[16/9] overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10">
                <Image
                  src={suite.hub}
                  alt={`${suite.fullName} mockup hub`}
                  fill
                  sizes="(max-width: 1024px) 100vw, 80vw"
                  className="object-cover object-top"
                />
              </div>
              <p className="px-2 pt-3 text-sm text-zinc-600 dark:text-zinc-400">
                The full {suite.name} surface map — all {suite.modules.length} screens linked
                from a single hub.
              </p>
            </GlassCard>
          </Reveal>
        </div>
      </section>

      {/* Use cases */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-12 max-w-3xl">
              <div
                className={`mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${TONE_EYEBROW[suite.tone]}`}
              >
                <Users className="h-3.5 w-3.5" />
                Built for these teams
              </div>
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                Use cases
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                {suite.name} is designed around the way real teams actually work — not the way
                a tool wants them to work.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-5 md:grid-cols-3">
            {suite.useCases.map((uc) => (
              <StaggerItem key={uc.audience}>
                <GlassCard className="h-full p-6">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    {uc.audience}
                  </div>
                  <p className="text-[15px] leading-relaxed text-zinc-700 dark:text-zinc-200">
                    {uc.scenario}
                  </p>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </div>
      </section>

      {/* Enterprise */}
      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <div className="grid gap-12 lg:grid-cols-2 lg:items-start">
            <Reveal>
              <div>
                <div
                  className={`mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${TONE_EYEBROW[suite.tone]}`}
                >
                  <Building2 className="h-3.5 w-3.5" />
                  Enterprise-grade
                </div>
                <h2 className="mb-4 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                  Built for procurement, InfoSec, and audit
                </h2>
                <p className="mb-6 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {suite.name} ships with the controls your security, legal, and finance
                  partners ask for first — so you can deploy with confidence and pass review
                  with evidence.
                </p>
                <a
                  href={`mailto:hello@apiome.app?subject=Enterprise%20Brief%20%E2%80%94%20${encodeURIComponent(
                    suite.fullName,
                  )}`}
                >
                  <Button size="lg" variant="outline" className="group">
                    Request Enterprise Brief
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </a>
              </div>
            </Reveal>

            <Reveal delay={0.1}>
              <GlassCard interactive={false} className="p-6" data-always="true">
                <ul className="space-y-3">
                  {suite.enterprise.map((item) => (
                    <li key={item} className="flex items-start gap-3">
                      <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-xs text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-300">
                        <ShieldCheck className="h-3.5 w-3.5" />
                      </div>
                      <span className="text-zinc-700 dark:text-zinc-200">{item}</span>
                    </li>
                  ))}
                </ul>
              </GlassCard>
            </Reveal>
          </div>
        </div>
      </section>

      {/* AI */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
            <Reveal delay={0.1} className="order-2 lg:order-1">
              <GlassCard interactive={false} className="p-6" data-always="true">
                <ul className="space-y-3">
                  {suite.ai.capabilities.map((cap) => (
                    <li key={cap} className="flex items-start gap-3">
                      <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-100 text-xs text-sky-600 dark:bg-sky-950/60 dark:text-sky-300">
                        <Sparkles className="h-3.5 w-3.5" />
                      </div>
                      <span className="text-zinc-700 dark:text-zinc-200">{cap}</span>
                    </li>
                  ))}
                </ul>
              </GlassCard>
            </Reveal>

            <Reveal className="order-1 lg:order-2">
              <div>
                <div
                  className={`mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider backdrop-blur ${TONE_EYEBROW.sky}`}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  AI integration
                </div>
                <h2 className="mb-4 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                  {suite.ai.headline}
                </h2>
                <p className="mb-6 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {suite.ai.description}
                </p>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  Every {suite.name} AI feature is grounded in your tenant's data, runs under
                  your data-residency policy, and respects every role and ACL the platform
                  enforces.
                </p>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* Surfaces list */}
      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-10 max-w-3xl">
              <h2 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                Every surface in {suite.fullName}
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                A look at the {suite.modules.length} screens designed for this suite — covering
                everything from day-1 onboarding to day-100 operations.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.05}>
            <GlassCard interactive={false} className="p-6" data-always="true">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {suite.modules.map((m) => (
                  <div
                    key={m}
                    className="flex items-center gap-2 rounded-lg border border-zinc-200/70 bg-white/60 px-3 py-2 text-sm text-zinc-700 dark:border-zinc-800/70 dark:bg-zinc-950/40 dark:text-zinc-200"
                  >
                    <span
                      className={`inline-block h-2 w-2 rounded-full bg-gradient-to-br ${toneDot(suite.tone)}`}
                    />
                    <span className="font-mono text-xs">{m}</span>
                  </div>
                ))}
              </div>
            </GlassCard>
          </Reveal>
        </div>
      </section>

      {/* Other suites */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-20 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
              <div>
                <h2 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
                  Continue exploring the Suite
                </h2>
                <p className="mt-2 text-lg text-zinc-600 dark:text-zinc-400">
                  Each suite is independently subscribable — and even better together.
                </p>
              </div>
              <Link href="/suite">
                <Button variant="outline" className="group">
                  All Suites
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </Link>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-3">
            {otherSuites.map((other) => (
              <StaggerItem key={other.slug}>
                <Link href={`/suite/${other.slug}`} className="group block h-full">
                  <GlassCard className="flex h-full flex-col overflow-hidden p-0">
                    <div className="relative aspect-[16/10] w-full overflow-hidden border-b border-zinc-200/60 bg-zinc-50 dark:border-zinc-800/60 dark:bg-zinc-900">
                      <Image
                        src={other.cover}
                        alt={`${other.fullName} preview`}
                        fill
                        sizes="(max-width: 768px) 100vw, 33vw"
                        className="object-cover object-top transition-transform duration-500 group-hover:scale-[1.03]"
                      />
                    </div>
                    <div className="flex flex-1 flex-col p-5">
                      <div className="mb-2 flex items-center gap-3">
                        <ToneChip tone={other.tone} className="h-9 w-9 rounded-lg">
                          <SuiteIcon name={other.icon} className="h-4 w-4" />
                        </ToneChip>
                        <h3 className="truncate text-base font-semibold text-zinc-900 dark:text-zinc-50">
                          {other.fullName}
                        </h3>
                      </div>
                      <p className="line-clamp-2 text-sm text-zinc-600 dark:text-zinc-400">
                        {other.tagline}
                      </p>
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
              <div className="shine-ambient" />
              <div className="relative">
                <Rocket className="mx-auto mb-4 h-10 w-10" />
                <h2 className="mb-4 text-4xl font-semibold tracking-tight sm:text-5xl">
                  Be first in line for {suite.name}
                </h2>
                <p className="mb-10 text-lg text-blue-100 sm:text-xl">
                  Early-access tenants help us shape {suite.name} — and get production-grade
                  pricing locked in before general availability.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <a
                    href={`mailto:hello@apiome.app?subject=Early%20Access%20%E2%80%94%20${encodeURIComponent(
                      suite.fullName,
                    )}`}
                  >
                    <Button size="lg" variant="secondary" className="bg-white text-blue-600 hover:bg-zinc-100">
                      Apply for Early Access
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </Button>
                  </a>
                  <Link href="/suite">
                    <Button size="lg" variant="ghost-glass" className="text-white">
                      Browse all Suites
                    </Button>
                  </Link>
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

function toneDot(tone: Tone): string {
  const map: Record<Tone, string> = {
    blue: "from-blue-500 to-blue-600",
    emerald: "from-emerald-500 to-emerald-600",
    purple: "from-purple-500 to-purple-600",
    orange: "from-orange-500 to-orange-600",
    indigo: "from-indigo-500 to-indigo-600",
    sky: "from-sky-500 to-sky-600",
    rose: "from-rose-500 to-rose-600",
    cyan: "from-cyan-500 to-cyan-600",
    violet: "from-violet-500 to-violet-600",
    amber: "from-amber-500 to-amber-600",
    pink: "from-pink-500 to-pink-600",
    red: "from-red-500 to-red-600",
    teal: "from-teal-500 to-teal-600",
    green: "from-green-500 to-green-600",
  };
  return map[tone];
}
