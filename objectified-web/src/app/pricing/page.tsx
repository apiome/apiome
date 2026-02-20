import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "../components/ui/Button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Pricing - Objectified",
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
    <div className="relative flex min-h-full flex-col rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-4 flex flex-wrap items-baseline gap-2">
        <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
          {name}
        </h3>
        {recommended && (
          <span className="text-sm font-medium text-amber-600 dark:text-amber-400">
            Recommended
          </span>
        )}
      </div>
      <div className="mb-6">
        <div className="text-xl font-normal text-zinc-700 dark:text-zinc-200">
          {price}
        </div>
        {period && (
          <div className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">
            {period}
          </div>
        )}
        {annualNote && (
          <div className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-500">
            {annualNote}
          </div>
        )}
      </div>
      <p className="mb-3 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        {featuresHeading}
      </p>
      <ul className="flex-1 space-y-2.5">
        {features.map((feature, index) => (
          <li key={index} className="flex items-start gap-3">
            <span
              className="mt-0.5 text-zinc-500 dark:text-zinc-400"
              aria-hidden
            >
              ✓
            </span>
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              {feature}
            </span>
          </li>
        ))}
      </ul>
      <CtaWrapper
        {...ctaProps}
        className={cn(
          buttonVariants({
            variant: recommended ? "secondary" : cta.variant,
            size: "lg",
          }),
          "mt-6 w-full inline-flex"
        )}
      >
        {cta.text}
        {cta.variant === "default" && (
          <ArrowRight className="ml-2 h-4 w-4" />
        )}
      </CtaWrapper>
    </div>
  );
}

export default function PricingPage() {
  return (
    <div className="flex flex-col">
      <section className="relative overflow-hidden border-b border-zinc-200 bg-gradient-to-b from-white to-zinc-50 px-6 py-16 dark:border-zinc-800 dark:from-zinc-950 dark:to-zinc-900">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px]" />
        <div className="container relative mx-auto max-w-4xl text-center">
          <h1 className="mb-4 text-5xl font-bold text-zinc-900 dark:text-zinc-50">
            Simple, Transparent Pricing
          </h1>
          <p className="text-xl text-zinc-600 dark:text-zinc-400">
            Choose the plan that&apos;s right for you and your team
          </p>
        </div>
      </section>

      <section className="px-6 py-20">
        <div className="container mx-auto max-w-6xl">
          <h2 className="mb-10 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
            Individual Plans
          </h2>
          <div className="grid gap-8 sm:grid-cols-2 xl:grid-cols-4">
            <PricingCard
              name="Free"
              price="Free"
              period="No credit card required"
              featuresHeading="Includes:"
              features={[
                "1 tenant",
                "3 projects",
                "No AI assistance",
                "Public-only publishing",
              ]}
              cta={{
                text: "Get Started",
                href: "https://app.objectified.dev",
                variant: "outline",
                external: true,
              }}
            />

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
                href: "https://app.objectified.dev",
                variant: "default",
                external: true,
              }}
              recommended
            />

            <PricingCard
              name="Startup"
              price="$40/mo."
              period="per month"
              annualNote="$400/year billed annually"
              featuresHeading="Everything in Pro, plus:"
              features={[
                "5 tenants",
                "20 projects per tenant",
              ]}
              cta={{
                text: "Get Startup",
                href: "https://app.objectified.dev",
                variant: "outline",
                external: true,
              }}
            />

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
                href: "mailto:sales@objectified.dev",
                variant: "outline",
                external: true,
              }}
            />
          </div>

          <h2 className="mb-10 mt-16 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
            Organization & Self-Hosted
          </h2>
          <div className="grid gap-8 sm:grid-cols-2">
            <PricingCard
              name="Enterprise Unlimited"
              price="Contact sales"
              period=""
              featuresHeading="Includes:"
              features={[
                "Unlimited tenants",
                "Unlimited projects",
                "AI assistance",
                "Public & private publishing",
                "Dedicated support & SLA",
                "SSO & advanced security",
                "Priority New Feature Access",
              ]}
              cta={{
                text: "Contact Sales",
                href: "mailto:sales@objectified.dev",
                variant: "outline",
                external: true,
              }}
            />

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
                href: "mailto:sales@objectified.dev",
                variant: "outline",
                external: true,
              }}
            />
          </div>
        </div>
      </section>

      <section className="border-t border-zinc-200 bg-zinc-50 px-6 py-20 dark:border-zinc-800 dark:bg-zinc-900/50">
        <div className="container mx-auto max-w-3xl">
          <h2 className="mb-12 text-center text-3xl font-bold text-zinc-900 dark:text-zinc-50">
            Frequently Asked Questions
          </h2>
          <div className="space-y-6">
            <FAQ
              question="Can I change plans later?"
              answer="Yes! You can upgrade or downgrade your plan at any time. Changes take effect immediately, and we'll prorate any charges."
            />
            <FAQ
              question="Is there a free trial?"
              answer="Yes! Pro and paid plans come with a free trial. No credit card required to start with the Free plan."
            />
            <FAQ
              question="What payment methods do you accept?"
              answer="We accept all major credit cards. For Enterprise and Self-Hosted, we can arrange invoicing."
            />
            <FAQ
              question="What happens to my data if I cancel?"
              answer="You can export all your data before canceling. We'll keep your data for 30 days after cancellation in case you want to reactivate."
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function FAQ({
  question,
  answer,
}: {
  question: string;
  answer: string;
}) {
  return (
    <div>
      <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        {question}
      </h3>
      <p className="text-zinc-600 dark:text-zinc-400">{answer}</p>
    </div>
  );
}
