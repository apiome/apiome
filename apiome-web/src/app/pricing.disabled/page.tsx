import type { Metadata } from "next";
import Link from "next/link";
import { Check, ArrowRight } from "lucide-react";
import { Button } from "../components/ui/Button";

export const metadata: Metadata = {
  title: "Pricing - Apiome",
  description: "Simple, transparent pricing for teams of all sizes",
};

export default function PricingPage() {
  return (
    <div className="flex flex-col">
      <section className="border-b border-zinc-200 bg-gradient-to-b from-white to-zinc-50 px-6 py-16 dark:border-zinc-800 dark:from-zinc-950 dark:to-zinc-900">
        <div className="container mx-auto max-w-4xl text-center">
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
          <div className="grid gap-8 lg:grid-cols-3">
            <PricingCard
              name="Free"
              description="Perfect for personal projects and learning"
              price="$0"
              period="forever"
              features={[
                "Up to 3 projects",
                "Unlimited schemas",
                "Basic export options",
                "Community support",
                "Public API sharing",
              ]}
              cta={{ text: "Get Started", href: "/signup", variant: "outline" as const }}
            />

            <PricingCard
              name="Pro"
              description="For professional developers and small teams"
              price="$29"
              period="per user/month"
              popular
              features={[
                "Unlimited projects",
                "Unlimited schemas",
                "Advanced export options",
                "Priority support",
                "Private API sharing",
                "Version control & history",
                "Code generation",
              ]}
              cta={{ text: "Start Free Trial", href: "/signup", variant: "default" as const }}
            />

            <PricingCard
              name="Enterprise"
              description="For large teams and organizations"
              price="Custom"
              period="contact us"
              features={[
                "Everything in Pro",
                "Unlimited team members",
                "SSO & advanced security",
                "Dedicated support",
                "Custom integrations",
                "SLA guarantees",
                "On-premise deployment option",
              ]}
              cta={{ text: "Contact Sales", href: "/contact", variant: "outline" as const }}
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
              answer="Yes! The Pro plan comes with a 14-day free trial. No credit card required to start."
            />
            <FAQ
              question="What payment methods do you accept?"
              answer="We accept all major credit cards, PayPal, and for Enterprise customers, we can arrange invoicing."
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

interface PricingCardProps {
  name: string;
  description: string;
  price: string;
  period: string;
  features: string[];
  cta: {
    text: string;
    href: string;
    variant: "default" | "outline";
  };
  popular?: boolean;
}

function PricingCard({ name, description, price, period, features, cta, popular }: PricingCardProps) {
  return (
    <div className={`relative rounded-2xl bg-white p-8 dark:bg-zinc-950 ${
      popular ? 'border-2 border-blue-600 shadow-xl' : 'border border-zinc-200 dark:border-zinc-800'
    }`}>
      {popular && (
        <div className="absolute -top-4 left-1/2 -translate-x-1/2 rounded-full bg-blue-600 px-4 py-1 text-sm font-medium text-white">
          Most Popular
        </div>
      )}
      <div className="mb-6">
        <h3 className="mb-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{name}</h3>
        <p className="text-zinc-600 dark:text-zinc-400">{description}</p>
      </div>
      <div className="mb-6">
        <div className="text-4xl font-bold text-zinc-900 dark:text-zinc-50">{price}</div>
        <div className="text-zinc-600 dark:text-zinc-400">{period}</div>
      </div>
      <Link href={cta.href}>
        <Button variant={cta.variant} className="mb-6 w-full">
          {cta.text}
          {cta.variant === "default" && <ArrowRight className="ml-2 h-4 w-4" />}
        </Button>
      </Link>
      <ul className="space-y-3">
        {features.map((feature, index) => (
          <li key={index} className="flex items-start gap-3">
            <Check className="mt-0.5 h-5 w-5 shrink-0 text-green-600" />
            <span className="text-sm text-zinc-600 dark:text-zinc-400">{feature}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FAQ({ question, answer }: { question: string; answer: string }) {
  return (
    <div>
      <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{question}</h3>
      <p className="text-zinc-600 dark:text-zinc-400">{answer}</p>
    </div>
  );
}
