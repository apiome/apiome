"use client";

import { useMemo, useState } from "react";
import {
  ArrowRight,
  Building2,
  Users,
  TrendingDown,
  Clock,
  Zap,
  ShieldCheck,
  GitBranch,
  Code2,
  Database,
  CheckCircle2,
  HelpCircle,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Aurora } from "../components/ui/Aurora";
import { GlassCard, ToneChip, type Tone } from "../components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem, CountUp } from "../components/motion/Reveal";

function formatCurrency(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  }).format(n);
}

function ROICalculator() {
  const [teamSize, setTeamSize] = useState(5);
  const [hourlyRate, setHourlyRate] = useState(100);
  const [projectsPerYear, setProjectsPerYear] = useState(4);

  const savings = useMemo(() => {
    const scale = (teamSize / 5) * (hourlyRate / 100) * (projectsPerYear / 4);
    const devTime = Math.round(32000 * scale);
    const techDebt = Math.round(15000 * scale);
    const onboarding = Math.round(10000 * scale);
    const bugPrevention = Math.round(15000 * scale);
    const total = devTime + techDebt + onboarding + bugPrevention;
    return { devTime, techDebt, onboarding, bugPrevention, total };
  }, [teamSize, hourlyRate, projectsPerYear]);

  return (
    <GlassCard interactive={false} className="p-8" data-always="true">
      <div className="mb-8 space-y-6">
        <ROIInput
          id="roi-team-size"
          label="Number of developers on your team"
          value={teamSize}
          min={1}
          max={100}
          onChange={setTeamSize}
        />
        <ROIInput
          id="roi-hourly-rate"
          label="Average developer hourly rate ($)"
          value={hourlyRate}
          min={50}
          max={500}
          onChange={setHourlyRate}
        />
        <ROIInput
          id="roi-projects"
          label="Number of API projects per year"
          value={projectsPerYear}
          min={1}
          max={20}
          onChange={setProjectsPerYear}
        />
      </div>

      <div className="relative overflow-hidden rounded-xl p-6 ring-1 ring-blue-200/60 dark:ring-blue-900/40">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 bg-gradient-to-br from-blue-50/90 to-indigo-50/90 dark:from-blue-950/40 dark:to-indigo-950/40"
        />
        <div className="mb-2 text-center text-sm font-medium text-zinc-600 dark:text-zinc-400">
          Estimated Annual Savings
        </div>
        <div className="mb-4 text-center text-5xl font-semibold tracking-tight text-blue-600 dark:text-blue-400">
          <CountUp to={savings.total} prefix="$" />
        </div>
        <div className="space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
          <SavingsRow label="Development time saved:" value={savings.devTime} />
          <SavingsRow label="Technical debt reduced:" value={savings.techDebt} />
          <SavingsRow label="Faster onboarding:" value={savings.onboarding} />
          <SavingsRow label="Bug prevention:" value={savings.bugPrevention} />
        </div>
      </div>

      <div className="mt-6 text-center text-xs text-zinc-500 dark:text-zinc-500">
        * Estimates based on industry averages and typical usage patterns
      </div>
    </GlassCard>
  );
}

function ROIInput({
  id,
  label,
  value,
  min,
  max,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || min)))}
        className="w-full rounded-lg border border-zinc-200/70 bg-white/70 px-4 py-3 text-zinc-900 backdrop-blur transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-zinc-700/70 dark:bg-zinc-900/60 dark:text-zinc-100 dark:focus:border-blue-400"
      />
    </div>
  );
}

function SavingsRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex justify-between">
      <span>{label}</span>
      <span className="font-semibold text-zinc-900 dark:text-zinc-50">{formatCurrency(value)}</span>
    </div>
  );
}

type RoleCard = {
  icon: React.ReactNode;
  title: string;
  description: string;
  bullets: string[];
  tone: Tone;
};

const ROLES: RoleCard[] = [
  {
    icon: <Code2 className="h-5 w-5" />,
    title: "API Development Teams",
    description:
      "Backend developers building RESTful APIs who need clear specifications, consistent schemas, and automated documentation.",
    bullets: ["Eliminate spec drift", "Generate consistent DTOs", "Auto-sync documentation"],
    tone: "blue",
  },
  {
    icon: <Database className="h-5 w-5" />,
    title: "Database Architects",
    description:
      "DBAs and data engineers designing complex schemas who need visualization, version control, and migration management.",
    bullets: ["Visual schema design", "Automated migrations", "Multi-database support"],
    tone: "purple",
  },
  {
    icon: <Users className="h-5 w-5" />,
    title: "Product Teams",
    description:
      "Product managers and technical leads who need to understand API contracts, plan features, and align stakeholders.",
    bullets: ["Visual data models", "Non-technical collaboration", "Stakeholder alignment"],
    tone: "green",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    title: "Frontend Developers",
    description:
      "UI developers who need clear API contracts, type-safe SDKs, and reliable backend specifications.",
    bullets: ["Type-safe SDKs", "Clear API contracts", "Mock server generation"],
    tone: "orange",
  },
  {
    icon: <GitBranch className="h-5 w-5" />,
    title: "DevOps Engineers",
    description:
      "Infrastructure teams managing deployments, CI/CD pipelines, and database migrations across environments.",
    bullets: ["Automated migrations", "Environment consistency", "CI/CD integration"],
    tone: "indigo",
  },
  {
    icon: <Building2 className="h-5 w-5" />,
    title: "Enterprise CTOs",
    description:
      "Technical leaders who need governance, compliance, and visibility across all API and database assets.",
    bullets: ["Granular role-based access", "Tamper-evident audit trails", "Member lifecycle controls"],
    tone: "rose",
  },
];

type Saving = {
  icon: React.ReactNode;
  percent: number;
  percentLabel: string;
  title: string;
  description: string;
  before: string;
  after: string;
  savings: string;
  tone: Tone;
  colorClass: string;
};

const COST_SAVINGS: Saving[] = [
  {
    icon: <Clock className="h-5 w-5" />,
    percent: 60,
    percentLabel: "Time Saved",
    title: "Reduce Development Time",
    description: "Eliminate hours of manual API documentation, schema design, and boilerplate code generation.",
    before: "2-3 weeks for API design + documentation",
    after: "3-5 days with visual design + auto-generation",
    savings: "Save $15,000-$30,000 per API project",
    tone: "blue",
    colorClass: "text-blue-600",
  },
  {
    icon: <ShieldCheck className="h-5 w-5" />,
    percent: 80,
    percentLabel: "Less Debt",
    title: "Eliminate Technical Debt",
    description: "Stop paying the \"documentation debt tax\" where specs and code drift apart over time.",
    before: "10-15 hours/month maintaining docs",
    after: "Auto-synced specs, zero maintenance",
    savings: "Save $12,000-$18,000 per year per team",
    tone: "purple",
    colorClass: "text-purple-600",
  },
  {
    icon: <Users className="h-5 w-5" />,
    percent: 75,
    percentLabel: "Faster Onboarding",
    title: "Faster Team Onboarding",
    description: "New developers understand your APIs and schemas instantly with visual documentation.",
    before: "2-4 weeks to understand system",
    after: "3-5 days with visual models",
    savings: "Save $8,000-$12,000 per new hire",
    tone: "green",
    colorClass: "text-green-600",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    percent: 70,
    percentLabel: "Fewer Bugs",
    title: "Prevent Integration Bugs",
    description: "Type-safe code generation and contract testing catch issues before production.",
    before: "20-30 integration bugs per quarter",
    after: "5-10 bugs caught at compile time",
    savings: "Save $25,000-$40,000 per year in bug fixes",
    tone: "orange",
    colorClass: "text-orange-600",
  },
];

const QUESTION_BLOCKS: { title: string; tone: Tone; items: string[] }[] = [
  {
    title: "API Design Questions",
    tone: "blue",
    items: [
      "What endpoints does this API expose?",
      "What's the request/response format?",
      "Which parameters are required?",
      "What authentication is needed?",
      "What are the error responses?",
      "Is this API versioned?",
    ],
  },
  {
    title: "Database Questions",
    tone: "purple",
    items: [
      "What tables exist in the database?",
      "What are the relationships?",
      "Which fields are indexed?",
      "What constraints are defined?",
      "How do I migrate this schema?",
      "What's the data model?",
    ],
  },
  {
    title: "Integration Questions",
    tone: "green",
    items: [
      "How do I connect to this API?",
      "What SDK should I use?",
      "How do I handle errors?",
      "What's the rate limit?",
      "How do I test this integration?",
      "Where's the documentation?",
    ],
  },
  {
    title: "Team Questions",
    tone: "orange",
    items: [
      "Who owns this API?",
      "When was it last updated?",
      "What changed in this version?",
      "Who approved this schema?",
      "What's the review process?",
      "How do I request access?",
    ],
  },
  {
    title: "Compliance Questions",
    tone: "indigo",
    items: [
      "Is this data GDPR compliant?",
      "What PII is stored?",
      "Who has access to this data?",
      "What's our data retention policy?",
      "Are changes audited?",
      "How do we handle deletions?",
    ],
  },
  {
    title: "Business Questions",
    tone: "rose",
    items: [
      "What features can we build?",
      "What data do we have access to?",
      "What's the timeline estimate?",
      "What dependencies exist?",
      "How will this impact users?",
      "What's the cost to implement?",
    ],
  },
];

const TONE_ACCENT: Record<Tone, string> = {
  blue:    'text-blue-600 dark:text-blue-400',
  emerald: 'text-emerald-600 dark:text-emerald-400',
  purple:  'text-purple-600 dark:text-purple-400',
  orange:  'text-orange-600 dark:text-orange-400',
  indigo:  'text-indigo-600 dark:text-indigo-400',
  sky:     'text-sky-600 dark:text-sky-400',
  rose:    'text-rose-600 dark:text-rose-400',
  cyan:    'text-cyan-600 dark:text-cyan-400',
  violet:  'text-violet-600 dark:text-violet-400',
  amber:   'text-amber-600 dark:text-amber-400',
  pink:    'text-pink-600 dark:text-pink-400',
  red:     'text-red-600 dark:text-red-400',
  teal:    'text-teal-600 dark:text-teal-400',
  green:   'text-green-600 dark:text-green-400',
};

export default function ForTeamsPage() {
  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-36">
        <Aurora />
        <div className="container relative mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <Reveal>
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/80 px-4 py-2 text-sm font-medium text-blue-700 backdrop-blur dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300">
                <Building2 className="h-4 w-4" />
                For Development Teams
              </div>
            </Reveal>
            <Reveal delay={0.05}>
              <h1 className="mb-6 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl lg:text-7xl">
                Built for teams who{" "}
                <span className="display-accent">ship faster</span>
              </h1>
            </Reveal>
            <Reveal delay={0.12}>
              <p className="mb-8 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
                Reduce development time, cut costs, and eliminate documentation debt with the
                platform that brings your entire team together around a single source of truth.
              </p>
            </Reveal>
            <Reveal delay={0.2}>
              <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                <a href="https://app.apiome.app" target="_blank" rel="noopener noreferrer">
                  <Button size="lg" className="group">
                    Start Free Trial
                    <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Button>
                </a>
                <a href="#roi-calculator">
                  <Button size="lg" variant="outline">
                    Calculate Your Savings
                  </Button>
                </a>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* Who this is for */}
      <section className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Who Apiome is built for
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                Whether you&apos;re a startup or enterprise, Apiome accelerates your development workflow.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {ROLES.map((role) => (
              <StaggerItem key={role.title}>
                <GlassCard className="h-full p-7">
                  <ToneChip tone={role.tone} className="mb-4">
                    {role.icon}
                  </ToneChip>
                  <h3 className="mb-3 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                    {role.title}
                  </h3>
                  <p className="mb-4 text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                    {role.description}
                  </p>
                  <ul className="space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
                    {role.bullets.map((b) => (
                      <li key={b} className="flex items-start gap-2">
                        <CheckCircle2 className={`mt-0.5 h-4 w-4 flex-shrink-0 ${TONE_ACCENT[role.tone]}`} />
                        <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </div>
      </section>

      {/* Cost savings */}
      <section className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-24 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                How Apiome saves your company <span className="display-accent">money</span>
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                Real cost savings that impact your bottom line.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-6 md:grid-cols-2">
            {COST_SAVINGS.map((s) => (
              <StaggerItem key={s.title}>
                <GlassCard className="h-full p-8">
                  <div className="mb-4 flex items-start justify-between">
                    <ToneChip tone={s.tone}>{s.icon}</ToneChip>
                    <div className="text-right">
                      <div className={`text-3xl font-semibold ${s.colorClass}`}>
                        <CountUp to={s.percent} suffix="%" />
                      </div>
                      <div className="text-sm text-zinc-600 dark:text-zinc-400">{s.percentLabel}</div>
                    </div>
                  </div>
                  <h3 className="mb-3 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
                    {s.title}
                  </h3>
                  <p className="mb-4 text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                    {s.description}
                  </p>
                  <ul className="space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
                    <li className="flex items-start gap-2">
                      <TrendingDown className={`mt-0.5 h-4 w-4 flex-shrink-0 ${s.colorClass}`} />
                      <span><strong>Before:</strong> {s.before}</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-green-600" />
                      <span><strong>After:</strong> {s.after}</span>
                    </li>
                    <li className="pl-6">
                      <span className="font-semibold text-zinc-900 dark:text-zinc-50">{s.savings}</span>
                    </li>
                  </ul>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>

          <Reveal delay={0.1}>
            <div className="mt-12 overflow-hidden rounded-2xl border-2 border-blue-600/80 bg-gradient-to-br from-blue-50 to-indigo-50 p-10 text-center dark:from-blue-950/40 dark:to-indigo-950/40">
              <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-400">
                Estimated Annual Savings
              </div>
              <div className="mb-2 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl">
                $60,000 - $100,000
              </div>
              <div className="mb-4 text-lg text-zinc-600 dark:text-zinc-400">
                Per 5-person development team
              </div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Based on industry averages for time saved, reduced bugs, and eliminated technical debt.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Questions */}
      <section className="border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Questions Apiome answers
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                Get instant answers to critical questions that slow down development.
              </p>
            </div>
          </Reveal>

          <StaggerGroup className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {QUESTION_BLOCKS.map((block) => (
              <StaggerItem key={block.title}>
                <GlassCard className="h-full p-6">
                  <div className={`mb-3 flex items-center gap-2 ${TONE_ACCENT[block.tone]}`}>
                    <HelpCircle className="h-5 w-5" />
                    <h3 className="font-semibold">{block.title}</h3>
                  </div>
                  <ul className="space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
                    {block.items.map((q) => (
                      <li key={q}>&bull; {q}</li>
                    ))}
                  </ul>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>

          <Reveal delay={0.12}>
            <div className="mt-12 overflow-hidden rounded-2xl bg-gradient-to-r from-blue-50 to-indigo-50 p-10 text-center dark:from-blue-950/30 dark:to-indigo-950/30">
              <h3 className="mb-3 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                Stop asking. <span className="display-accent">Start building.</span>
              </h3>
              <p className="mb-6 text-zinc-600 dark:text-zinc-400">
                Every question answered instantly means less time in meetings and more time shipping features.
              </p>
              <a href="https://app.apiome.app" target="_blank" rel="noopener noreferrer">
                <Button size="lg" className="group">
                  Get Started Free
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </a>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ROI Calculator */}
      <section
        id="roi-calculator"
        className="border-b border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-24 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40"
      >
        <div className="container mx-auto max-w-4xl">
          <Reveal>
            <div className="mb-12 text-center">
              <h2 className="mb-4 text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
                Calculate your <span className="display-accent">savings</span>
              </h2>
              <p className="text-lg text-zinc-600 dark:text-zinc-400">
                See how much Apiome could save your team.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.08}>
            <ROICalculator />
          </Reveal>
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-6 py-24">
        <div className="container mx-auto max-w-5xl">
          <Reveal>
            <div className="shine-on-hover relative overflow-hidden rounded-[2rem] border border-white/10 bg-gradient-to-br from-blue-600 via-indigo-600 to-purple-600 p-12 text-center text-white shadow-2xl sm:p-16">
              <div aria-hidden className="shine-ambient" />
              <div className="relative">
                <h2 className="mb-4 text-4xl font-semibold tracking-tight sm:text-5xl">
                  Ready to save time and money?
                </h2>
                <p className="mb-10 text-lg text-blue-100 sm:text-xl">
                  Join development teams who&apos;ve reduced API development time by 60% and saved thousands
                  in technical debt.
                </p>
                <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
                  <a href="https://app.apiome.app" target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="secondary" className="bg-white text-blue-600 hover:bg-zinc-100">
                      Start Free Trial
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </Button>
                  </a>
                  <a href="https://www.youtube.com/@objectifieddev" target="_blank" rel="noopener noreferrer">
                    <Button size="lg" variant="ghost-glass" className="text-white">
                      Watch Demo
                    </Button>
                  </a>
                </div>
                <p className="mt-6 text-sm text-blue-100">
                  No credit card required &middot; 14-day free trial &middot; Cancel anytime
                </p>
              </div>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
