import { links } from "@/lib/links";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Camera, LayoutGrid, Route, Import, Globe } from "lucide-react";
import { Button } from "../components/ui/Button";
import { Aurora } from "../components/ui/Aurora";
import { GlassCard } from "../components/ui/GlassCard";
import { Reveal, StaggerGroup, StaggerItem } from "../components/motion/Reveal";

export const metadata: Metadata = {
  title: "Screenshots - Apiome",
  description:
    "Recent captures of Apiome Studio, the public API browser, and suite previews — visual API and schema design in the product.",
};

type Shot = {
  src: string;
  alt: string;
  title: string;
  description: string;
  icon: React.ReactNode;
};

const PRODUCT_SHOTS: Shot[] = [
  {
    src: "/features-01.png",
    alt: "Apiome Studio — visual schema canvas with classes, relationships, and themes",
    title: "Schema canvas",
    description:
      "Live Studio surface for classes, relationships, groups, and canvas themes — the same experience you get after launching the app.",
    icon: <LayoutGrid className="h-5 w-5" />,
  },
  {
    src: "/features-02.png",
    alt: "Paths designer — HTTP operations, parameters, and response bindings",
    title: "Paths designer",
    description:
      "Visual path authoring with method-colored operations, parameters, request bodies, and OpenAPI-aligned validation.",
    icon: <Route className="h-5 w-5" />,
  },
  {
    src: "/features-03.png",
    alt: "Enterprise import wizard with sources and quality scoring",
    title: "Import",
    description:
      "Multi-source import flow with progress, scoring, and review — matching what teams use to onboard existing specs.",
    icon: <Import className="h-5 w-5" />,
  },
  {
    src: "/browser-01.png",
    alt: "Public API browser — explore published OpenAPI specifications",
    title: "Public API browser",
    description:
      "Community and tenant-published specs at browse.apiome.app — discover endpoints and schemas without signing in.",
    icon: <Globe className="h-5 w-5" />,
  },
];

export default function ScreenshotsPage() {
  return (
    <div className="flex flex-col">
      <section className="relative overflow-hidden border-b border-zinc-200/70 px-6 py-24 dark:border-zinc-800/70 sm:py-32">
        <Aurora />
        <div className="container relative mx-auto max-w-4xl text-center">
          <Reveal>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-violet-200/60 bg-violet-50/80 px-4 py-2 text-sm font-medium text-violet-800 backdrop-blur dark:border-violet-900/60 dark:bg-violet-950/50 dark:text-violet-200">
              <Camera className="h-4 w-4" />
              Product gallery
            </div>
          </Reveal>
          <Reveal delay={0.06}>
            <h1 className="mb-6 text-5xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-6xl">
              Screenshots from the <span className="display-accent">application</span>
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mx-auto max-w-2xl text-lg leading-relaxed text-zinc-600 dark:text-zinc-400 sm:text-xl">
              Current marketing captures of Studio, Paths, Import, and the public browser. Suite preview tiles on{" "}
              <Link href="/suite" className="text-blue-600 underline decoration-blue-600/30 underline-offset-4 hover:decoration-blue-600 dark:text-blue-400 dark:decoration-blue-400/30">
                /suite
              </Link>{" "}
              are refreshed from the same mockup sources used in-product.
            </p>
          </Reveal>
          <Reveal delay={0.2}>
            <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <a href={links.app} target="_blank" rel="noopener noreferrer">
                <Button size="lg" className="group">
                  Open the live app
                  <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Button>
              </a>
              <Link href="/features">
                <Button size="lg" variant="outline">
                  Feature tour
                </Button>
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="border-b border-zinc-200/70 px-6 py-20 dark:border-zinc-800/70">
        <div className="container mx-auto max-w-6xl">
          <StaggerGroup className="grid gap-10 md:grid-cols-2">
            {PRODUCT_SHOTS.map((shot) => (
              <StaggerItem key={shot.src}>
                <GlassCard interactive={false} className="overflow-hidden p-0" data-always="true">
                  <div className="flex items-start gap-3 border-b border-zinc-200/70 p-5 dark:border-zinc-800/70">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300">
                      {shot.icon}
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{shot.title}</h2>
                      <p className="mt-1 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{shot.description}</p>
                    </div>
                  </div>
                  <div className="relative aspect-video w-full bg-zinc-100 dark:bg-zinc-900/80">
                    <Image
                      src={shot.src}
                      alt={shot.alt}
                      fill
                      className="object-cover object-top"
                      sizes="(max-width: 768px) 100vw, 50vw"
                      priority={shot.src === "/features-01.png"}
                    />
                  </div>
                </GlassCard>
              </StaggerItem>
            ))}
          </StaggerGroup>
        </div>
      </section>

      <section className="px-6 py-20">
        <div className="container mx-auto max-w-3xl text-center">
          <Reveal>
            <h2 className="mb-4 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Automate with <Link href="/mcp" className="display-accent hover:underline">MCP</Link>
            </h2>
            <p className="mb-8 text-lg text-zinc-600 dark:text-zinc-400">
              Connect your IDE or agent host to published OpenAPI in Apiome — list, search, and pull specs without leaving the editor.
            </p>
            <Link href="/mcp">
              <Button size="lg" variant="outline" className="group">
                Model Context Protocol overview
                <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Button>
            </Link>
          </Reveal>
        </div>
      </section>
    </div>
  );
}
