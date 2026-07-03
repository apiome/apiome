"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { SiteLinks } from "@/lib/links";

const LinksContext = createContext<SiteLinks | null>(null);

export function LinksProvider({
  links,
  children,
}: {
  links: SiteLinks;
  children: ReactNode;
}) {
  return (
    <LinksContext.Provider value={links}>{children}</LinksContext.Provider>
  );
}

/** Runtime link destinations injected by the root layout. */
export function useLinks(): SiteLinks {
  const links = useContext(LinksContext);
  if (!links) {
    throw new Error("useLinks must be used within LinksProvider");
  }
  return links;
}
