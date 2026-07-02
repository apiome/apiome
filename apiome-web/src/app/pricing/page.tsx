import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Tag } from "lucide-react";
import { buttonVariants } from "../components/ui/Button";
import { Aurora } from "../components/ui/Aurora";
import { Reveal, StaggerGroup, StaggerItem } from "../components/motion/Reveal";
import { FAQAccordion } from "./FAQAccordion";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Pricing - Apiome",
  description:
    "Simple, transparent pricing: Free, Pro, Groups, Ultra, Enterprise, and Self-Hosted plans for API and schema design.",
};

interface PricingCardProps {
  name: string;
  price: string;
  period?: string;
  annualNote?: string;
  featuresHeading: string;
  features: string[];
  cta: {
    text: string;
    href: string;
    variant: "default" | "outline";
    external?: boolean;
  };
  recommended?: boolean;
}

function PricingCard({
  name,
  price,
  period,
  annualNote,
  featuresHeading,
  features,
  cta,
  recommended,
}: PricingCardProps) {
  const CtaWrapper = cta.external ? "a" : Link;
  const ctaProps = cta.external
    ? { href: cta.href, target: "_blank" as const, rel: "noopener noreferrer" }
    : { href: cta.href };

  return (
    <div
      className={cn(
        "group relative flex min-h-full flex-col rounded-2xl p-8 transition-all duration-300",
        recommended
          ? "conic-border bg-white shadow-[0_18px_60px_-20px_rgba(79,70,229,0.35)] dark:bg-zinc-950 dark:shadow-[0_18px_60px_-20px_rgba(99,102,241,0.45)] lg:scale-[1.02]"
          : "glass gradient-border hover:-translate-y-1 hover:shadow-[0_18px_60px_-20px_rgba(37,99,235,0.25)] dark:hover:shadow-[0_18px_60px_-20px_rgba(96,165,250,0.35)]",
      )}
    >
      {recommended && (
        <div className="absolute -top-3 left-1/2 z-10 -translate-x-1/2 rounded-full bg-gradient-to-r from-blue-600 to-indigo-600 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-white shadow-lg">
          Recommended
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-baseline gap-2">
        <h3 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {name}
        </h3>
      </div>
      <div className="mb-6">
        <div className="text-2xl font-normal text-zinc-800 dark:text-zinc-100">{price}</div>
        {period && (
          <div className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">{period}</div>
        )}
        {annualNote && (
          <div className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-500">{annualNote}</div>
        )}
      </div>
      <p className="mb-3 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        {featuresHeading}
      </p>
      <ul className="flex-1 space-y-2.5">
        {features.map((feature, index) => (
          <li key={index} className="flex items-start gap-3">
            <span className="mt-0.5 text-blue-500 dark:text-blue-400" aria-hidden>
              ✓
            </span>
            <span className="text-sm text-zinc-600 dark:text-zinc-400">{feature}</span>
          </li>
        ))}
      </ul>
      <CtaWrapper
        {...ctaProps}
        className={cn(
          buttonVariants({
            variant: recommended ? "default" : cta.variant,
            size: "lg",
          }),
          "mt-6 w-full inline-flex",
        )}
      >
        {cta.text}
        {(cta.variant === "default" || recommended) && (
          <ArrowRight className="ml-1 h-4 w-4" />
        )}
      </CtaWrapper>
    </div>
  );
}

export default function PricingPage() {
  return (
    <div className="flex flex-col">
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-36">
        <Aurora />
        <div className="container relative mx-auto max-w-4xl text-center">
          <Reveal>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-200/60 bg-blue-50/80 px-4 py-2 text-sm font-medium text-blue-700 backdrop-blur dark:border-blue-900/60 dark:bg-blue-950/50 dark:text-blue-300">
              <Tag className="h-4 w-4" />
              Simple, Transparent Pricing
            </div>
          </Reveal>
          <Reveal delay={0.06}>
            <h1 className="mb-6 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl">
              Affordable plans for
              <br />
              <span className="display-accent">every team</span>
            </h1>
          </Reveal>
          <Reveal delay={0.14}>
            <p className="mb-8 text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
              Choose the plan that&apos;s right for you and your team.
            </p>
          </Reveal>
        </div>
      </section>

      <section className="px-6 py-24">
        <div className="container mx-auto max-w-6xl">
          <Reveal>
            <p className="mb-10 text-center text-xl font-semibold text-zinc-900 dark:text-zinc-50">
              Early adopters receive free Pro accounts for a year.
            </p>
          </Reveal>

          <Reveal>
            <h2 className="mb-10 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
              Individual Plans
            </h2>
          </Reveal>

          <StaggerGroup className="grid gap-8 pt-2 sm:grid-cols-2 xl:grid-cols-4">
            <StaggerItem>
              <PricingCard
                name="Free"
                price="Free"
                period="No credit card required"
                featuresHeading="Includes:"
                features={["1 tenant", "3 projects", "No AI assistance", "Public-only publishing"]}
                cta={{
                  text: "Get Started",
                  href: "https://app.apiome.app",
                  variant: "outline",
                  external: true,
                }}
              />
            </StaggerItem>
            <StaggerItem>
              <PricingCard
                name="Pro"
                price="$20/mo."
                period="per month"
                annualNote="$200/year billed annually"
                featuresHeading="Everything in Free, plus:"
                features={[
                  "10 projects",
                  "AI assistance",
                  "Public & private publishing",
                  "Beta Access",
                  "MCP Access",
                ]}
                cta={{
                  text: "Get Pro",
                  href: "https://app.apiome.app",
                  variant: "default",
                  external: true,
                }}
                recommended
              />
            </StaggerItem>
            <StaggerItem>
              <PricingCard
                name="Startup"
                price="$40/mo."
                period="per month"
                annualNote="$400/year billed annually"
                featuresHeading="Everything in Pro, plus:"
                features={["5 tenants", "20 projects per tenant"]}
                cta={{
                  text: "Get Startup",
                  href: "https://app.apiome.app",
                  variant: "outline",
                  external: true,
                }}
              />
            </StaggerItem>
            <StaggerItem>
              <PricingCard
                name="Ultra"
                price="$200/mo."
                period="per month"
                featuresHeading="Everything in Groups, plus:"
                features={[
                  "10 tenants",
                  "Unlimited projects per tenant",
                  "Voting rights for new features",
                  "Priority New Feature Access",
                ]}
                cta={{
                  text: "Get Ultra",
                  href: "mailto:sales@apiome.app",
                  variant: "outline",
                  external: true,
                }}
              />
            </StaggerItem>
          </StaggerGroup>

          <Reveal>
            <h2 className="mb-10 mt-20 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
              Organization & Self-Hosted
            </h2>
          </Reveal>

          <StaggerGroup className="grid gap-8 sm:grid-cols-2">
            <StaggerItem>
              <PricingCard
                name="Enterprise Unlimited"
                price="Contact sales"
                period="No limits"
                featuresHeading="Includes:"
                features={[
                  "Unlimited tenants, projects, and users",
                  "AI assistance",
                  "Public & private publishing",
                  "Your tenant's own custom URL",
                  "Dedicated support & SLA",
                  "SSO & advanced security",
                  "Priority New Feature Access",
                ]}
                cta={{
                  text: "Contact Sales",
                  href: "mailto:sales@apiome.app",
                  variant: "outline",
                  external: true,
                }}
              />
            </StaggerItem>
            <StaggerItem>
              <PricingCard
                name="Self-Hosted"
                price="Yearly subscription"
                period="No limits"
                featuresHeading="Includes:"
                features={[
                  "No tenant or project limits",
                  "Unlimited versioning",
                  "AI assistance",
                  "Public & private publishing",
                  "Private Docker repository",
                  "Access to updates",
                  "Full control of your data",
                  "Priority New Feature Access",
                ]}
                cta={{
                  text: "Contact Sales",
                  href: "mailto:sales@apiome.app",
                  variant: "outline",
                  external: true,
                }}
              />
            </StaggerItem>
          </StaggerGroup>
        </div>
      </section>

      <section className="border-t border-zinc-200/70 bg-gradient-to-b from-zinc-50/80 via-white/0 to-zinc-50/80 px-6 py-24 dark:border-zinc-800/70 dark:from-zinc-900/40 dark:via-transparent dark:to-zinc-900/40">
        <div className="container mx-auto max-w-3xl">
          <Reveal>
            <h2 className="mb-12 text-center text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl">
              Frequently asked <span className="display-accent">questions</span>
            </h2>
          </Reveal>
          <Reveal delay={0.08}>
            <FAQAccordion
              items={[
                {
                  question: "Can I change plans later?",
                  answer:
                    "Yes! You can upgrade or downgrade your plan at any time. Changes take effect immediately, and we'll prorate any charges.",
                },
                {
                  question: "Is there a free trial?",
                  answer:
                    "Yes! Pro and paid plans come with a free trial. No credit card required to start with the Free plan.",
                },
                {
                  question: "What payment methods do you accept?",
                  answer:
                    "We accept all major credit cards. For Enterprise and Self-Hosted, we can arrange invoicing.",
                },
                {
                  question: "What happens to my data if I cancel?",
                  answer:
                    "You can export all your data before canceling. We'll keep your data for 30 days after cancellation in case you want to reactivate.",
                },
              ]}
            />
          </Reveal>
        </div>
      </section>
    </div>
  );
}
