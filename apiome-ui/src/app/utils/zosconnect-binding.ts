/**
 * z/OS Connect copybook ↔ REST binding (MFI-21.2, #3992): the shape
 * `GET /v1/identity/{tenant}/projects/{id}/zosconnect-binding` answers with, and the helpers the
 * catalog item's **z/OS Connect binding** panel reads it through.
 */

import { relatedArtifactHref } from "./catalog-related-artifacts";

/** A catalog item that holds one side of the binding. */
export interface ZosConnectBindingItem {
  projectId: string;
  name: string;
  sourceFormat?: string | null;
  publishable?: boolean;
  /** Linked to the descriptor (same identity group); an unlinked item is a match to confirm. */
  linked: boolean;
}

/** One COBOL structure an operation passes, and the copybook items that declare it. */
export interface ZosConnectBindingSide {
  structure: string;
  copybooks: ZosConnectBindingItem[];
}

/** One bound REST operation. */
export interface ZosConnectBindingOperation {
  operation: string;
  operationId?: string | null;
  method?: string | null;
  path?: string | null;
  program?: string | null;
  request?: ZosConnectBindingSide | null;
  response?: ZosConnectBindingSide | null;
  openapi: ZosConnectBindingItem[];
}

/** The resolved binding. */
export interface ZosConnectBinding {
  kind?: string | null;
  api: {
    title?: string | null;
    specification?: string | null;
    basePath?: string | null;
  };
  operations: ZosConnectBindingOperation[];
  summary: {
    operations: number;
    structures: number;
    structuresWithCopybook: number;
    structuresLinked: number;
    operationsWithOpenApi: number;
  };
}

/** Where a bound item opens: a project's versions page or a catalog item's detail. */
export function bindingItemHref(item: ZosConnectBindingItem): string {
  return relatedArtifactHref({
    projectId: item.projectId,
    name: item.name,
    slug: item.projectId,
    publishable: Boolean(item.publishable),
  });
}

/** The panel's one-line summary, e.g. "2 operations · 3 of 4 structures in the catalog (2 linked)". */
export function bindingSummaryText(binding: ZosConnectBinding): string {
  const { operations, structures, structuresWithCopybook, structuresLinked } =
    binding.summary;
  const ops = `${operations} operation${operations === 1 ? "" : "s"}`;
  const found = `${structuresWithCopybook} of ${structures} structure${structures === 1 ? "" : "s"} in the catalog`;
  return `${ops} · ${found} (${structuresLinked} linked)`;
}

/** "API requester" / "API provider" for the descriptor kind. */
export function bindingKindLabel(kind?: string | null): string {
  if (kind === "requester") return "API requester";
  if (kind === "provider") return "API provider";
  return "z/OS Connect";
}
