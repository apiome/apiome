"use client";

import { useEffect, useState } from "react";
import { GitBranch, Import, LayoutGrid, Route, Sparkles, Zap } from "lucide-react";

type CarouselItem = {
  icon: React.ReactNode;
  text: string;
};

const CAROUSEL_ITEMS: CarouselItem[] = [
  {
    icon: <LayoutGrid className="h-4 w-4" />,
    text: "Design schemas on a visual canvas",
  },
  {
    icon: <Route className="h-4 w-4" />,
    text: "Author API paths and responses visually",
  },
  {
    icon: <Import className="h-4 w-4" />,
    text: "Import from file, URL, Git, or AI",
  },
  {
    icon: <Zap className="h-4 w-4" />,
    text: "Export OpenAPI, generate code & migrations",
  },
  {
    icon: <GitBranch className="h-4 w-4" />,
    text: "Version control with side-by-side diffs",
  },
  {
    icon: <Sparkles className="h-4 w-4" />,
    text: "AI-powered design with quality scoring",
  },
];

const INTERVAL_MS = 4000;

export function FeatureCarousel() {
  const [active, setActive] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setActive((prev) => (prev + 1) % CAROUSEL_ITEMS.length);
    }, INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      className="relative mx-auto mt-8 flex h-10 w-full max-w-lg items-center justify-center overflow-hidden"
      aria-live="polite"
      aria-atomic="true"
      data-testid="feature-carousel"
    >
      {CAROUSEL_ITEMS.map((item, i) => (
        <div
          key={item.text}
          className={`absolute inset-0 flex items-center justify-center gap-2 text-sm font-medium transition-all duration-500 ease-in-out sm:text-base ${
            i === active
              ? "translate-y-0 opacity-100"
              : i === (active - 1 + CAROUSEL_ITEMS.length) % CAROUSEL_ITEMS.length
                ? "-translate-y-full opacity-0"
                : "translate-y-full opacity-0"
          }`}
          aria-hidden={i !== active}
        >
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600 dark:bg-indigo-950/60 dark:text-indigo-300">
            {item.icon}
          </span>
          <span className="text-zinc-700 dark:text-zinc-300">{item.text}</span>
        </div>
      ))}
      <div className="pointer-events-none absolute bottom-0 left-1/2 flex -translate-x-1/2 gap-1.5">
        {CAROUSEL_ITEMS.map((item, i) => (
          <span
            key={item.text}
            className={`block h-1 rounded-full transition-all duration-300 ${
              i === active
                ? "w-4 bg-indigo-500 dark:bg-indigo-400"
                : "w-1.5 bg-zinc-300 dark:bg-zinc-600"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
