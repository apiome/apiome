/**
 * Studio chat context — gather + summarize (#259).
 *
 * The chatbot needs to talk about the user's actual workspace, not generic
 * schemas. This module owns the small, UI-agnostic data structure that the
 * Studio layout assembles from `useStudio()` plus the loaded classes and
 * properties, and the helpers that turn that snapshot into:
 *
 *   - a compact human-readable summary used by the in-chat "context" chip
 *   - a system-style preamble that gets injected into prompts so the
 *     responder (today the offline demo, tomorrow Ollama) can reference the
 *     active project, version, classes, schemas, and selection
 *
 * The summary is *capped* on every dimension so a large project cannot blow
 * the prompt budget on the eventual model call. The caps live here as
 * exported constants so tests pin the contract.
 */

import {
  collectStudioAiBestPracticeLinesFromStudio,
  studioAiBestPracticeDomainHeadingFromStudio,
} from '@/app/utils/studio-ai-best-practice-tips';
import {
  getProjectDomainCategoryLabel,
  PROJECT_DOMAIN_CATEGORY_NONE,
} from '@/app/utils/project-domain-categories';

export interface ChatStudioProject {
  id: string;
  name: string | null;
  /** Project metadata `domainCategory` when set (#243, #615). */
  domainCategory?: string | null;
}

export interface ChatStudioVersion {
  id: string;
  label: string | null;
}

export interface ChatStudioClass {
  id: string;
  name: string;
  description?: string | null;
  /**
   * Raw class schema as stored in the DB — may be a string, object, or null.
   * Kept loose so callers don't have to pre-normalise.
   */
  schema?: unknown;
}

export interface ChatStudioProperty {
  id: string;
  name: string;
  description?: string | null;
  /** JSON Schema type, e.g. `string`, `integer`, `boolean`. */
  type?: string | null;
  /** JSON Schema format, e.g. `email`, `date-time`. */
  format?: string | null;
  /** True if this property requires a value when used on a class. */
  required?: boolean | null;
}

export interface ChatStudioContext {
  project: ChatStudioProject | null;
  version: ChatStudioVersion | null;
  classes: ChatStudioClass[];
  properties: ChatStudioProperty[];
  /** IDs of nodes the user has selected on the canvas. */
  selectedClassIds: string[];
}

/** Token-budget caps. Conservative defaults so prompts stay small. */
export const CHAT_CONTEXT_CLASS_CAP = 30;
export const CHAT_CONTEXT_PROPERTY_CAP = 30;
export const CHAT_CONTEXT_SELECTION_CAP = 10;
export const CHAT_CONTEXT_SCHEMA_CHAR_CAP = 600;
export const CHAT_CONTEXT_DESCRIPTION_CHAR_CAP = 160;

/** An empty snapshot — useful as a default and for the no-context branch. */
export const EMPTY_CHAT_STUDIO_CONTEXT: ChatStudioContext = {
  project: null,
  version: null,
  classes: [],
  properties: [],
  selectedClassIds: [],
};

/**
 * True when the snapshot contains nothing the assistant can use. Cheap guard
 * so callers can skip emitting the "Sharing context" chip and prompt
 * preamble entirely when the user is on a fresh / empty workspace.
 */
export function isChatStudioContextEmpty(ctx: ChatStudioContext | null | undefined): boolean {
  if (!ctx) return true;
  return (
    !ctx.project &&
    !ctx.version &&
    ctx.classes.length === 0 &&
    ctx.properties.length === 0 &&
    ctx.selectedClassIds.length === 0
  );
}

/**
 * Selected classes, materialised against the class list. Selection IDs that
 * don't resolve (stale canvas state) are silently dropped so we never
 * pollute the prompt with phantom names.
 */
export function getSelectedClasses(ctx: ChatStudioContext): ChatStudioClass[] {
  if (ctx.selectedClassIds.length === 0) return [];
  const byId = new Map(ctx.classes.map((cls) => [cls.id, cls]));
  const out: ChatStudioClass[] = [];
  for (const id of ctx.selectedClassIds) {
    const cls = byId.get(id);
    if (cls) out.push(cls);
  }
  return out;
}

/**
 * Render the snapshot as a compact bullet list suitable for the "Sharing
 * context" popover. Returns an empty string when nothing is shareable so the
 * caller can render a fallback line.
 */
export function summarizeChatStudioContext(ctx: ChatStudioContext): string {
  if (isChatStudioContextEmpty(ctx)) return '';

  const lines: string[] = [];
  if (ctx.project) {
    lines.push(`- **Project:** ${ctx.project.name ?? ctx.project.id}`);
    const domainLabel =
      ctx.project.domainCategory && ctx.project.domainCategory !== PROJECT_DOMAIN_CATEGORY_NONE
        ? getProjectDomainCategoryLabel(ctx.project.domainCategory)
        : undefined;
    if (domainLabel) {
      lines.push(`- **Project domain:** ${domainLabel}`);
    }
  }
  if (ctx.version) {
    lines.push(`- **Version:** ${ctx.version.label ?? ctx.version.id}`);
  }

  const selected = getSelectedClasses(ctx);
  if (selected.length > 0) {
    const visible = selected.slice(0, CHAT_CONTEXT_SELECTION_CAP);
    const overflow = selected.length - visible.length;
    const names = visible.map((cls) => cls.name).join(', ');
    const suffix = overflow > 0 ? ` (+${overflow} more)` : '';
    lines.push(`- **Selected on canvas:** ${names}${suffix}`);
  }

  if (ctx.classes.length > 0) {
    lines.push(`- **Classes (${ctx.classes.length}):** ${formatNameList(ctx.classes, CHAT_CONTEXT_CLASS_CAP)}`);
  }

  if (ctx.properties.length > 0) {
    lines.push(`- **Properties (${ctx.properties.length}):** ${formatNameList(ctx.properties, CHAT_CONTEXT_PROPERTY_CAP)}`);
  }

  return lines.join('\n');
}

/**
 * Build the system-style preamble that the responder receives alongside the
 * user prompt. Keeps schema bodies short, names capped, and selection
 * highlighted so the model can prioritise the user's current focus.
 */
export function buildChatContextPreamble(ctx: ChatStudioContext): string {
  if (isChatStudioContextEmpty(ctx)) return '';

  const sections: string[] = ['### Current Studio context'];

  if (ctx.project) {
    sections.push(`- Project: ${ctx.project.name ?? '(unnamed)'} (id: ${ctx.project.id})`);
  }
  if (ctx.version) {
    sections.push(`- Version: ${ctx.version.label ?? '(unlabeled)'} (id: ${ctx.version.id})`);
  }

  const selected = getSelectedClasses(ctx);
  if (selected.length > 0) {
    sections.push('');
    sections.push('#### Selected on canvas');
    for (const cls of selected.slice(0, CHAT_CONTEXT_SELECTION_CAP)) {
      sections.push(formatClassEntry(cls, { includeSchema: true }));
    }
    if (selected.length > CHAT_CONTEXT_SELECTION_CAP) {
      sections.push(`- … and ${selected.length - CHAT_CONTEXT_SELECTION_CAP} more selected`);
    }
  }

  if (ctx.classes.length > 0) {
    sections.push('');
    sections.push(`#### Classes in this version (${ctx.classes.length})`);
    const visible = ctx.classes.slice(0, CHAT_CONTEXT_CLASS_CAP);
    for (const cls of visible) {
      sections.push(formatClassEntry(cls, { includeSchema: false }));
    }
    if (ctx.classes.length > visible.length) {
      sections.push(`- … and ${ctx.classes.length - visible.length} more classes not shown`);
    }
  }

  if (ctx.properties.length > 0) {
    sections.push('');
    sections.push(`#### Reusable property definitions (${ctx.properties.length})`);
    const visible = ctx.properties.slice(0, CHAT_CONTEXT_PROPERTY_CAP);
    for (const prop of visible) {
      sections.push(formatPropertyEntry(prop));
    }
    if (ctx.properties.length > visible.length) {
      sections.push(`- … and ${ctx.properties.length - visible.length} more properties not shown`);
    }
  }

  const domainTips = collectStudioAiBestPracticeLinesFromStudio(ctx);
  if (domainTips.length > 0) {
    const headingLabel = studioAiBestPracticeDomainHeadingFromStudio(ctx.project);
    sections.push('');
    sections.push(
      headingLabel
        ? `#### Domain-aware best practices (${headingLabel})`
        : '#### Domain-aware best practices',
    );
    for (const line of domainTips) {
      sections.push(line.startsWith('-') ? line : `- ${line}`);
    }
  }

  sections.push('');
  sections.push('Use this context to ground answers in the user\'s actual project. Reference class and property names from the lists above when relevant.');

  return sections.join('\n');
}

/**
 * Inject the preamble in front of the user prompt. Returns the prompt
 * untouched when there is no context worth injecting, so calling this is
 * always safe.
 */
export function injectChatContext(prompt: string, ctx: ChatStudioContext | null | undefined): string {
  if (!ctx || isChatStudioContextEmpty(ctx)) return prompt;
  const preamble = buildChatContextPreamble(ctx);
  if (!preamble) return prompt;
  return `${preamble}\n\n---\n\n### User request\n${prompt}`;
}

function formatNameList(items: Array<{ name: string }>, cap: number): string {
  const visible = items.slice(0, cap).map((item) => item.name);
  const overflow = items.length - visible.length;
  return overflow > 0 ? `${visible.join(', ')} (+${overflow} more)` : visible.join(', ');
}

function formatClassEntry(cls: ChatStudioClass, opts: { includeSchema: boolean }): string {
  const parts: string[] = [`- \`${cls.name}\``];
  const desc = truncate(cls.description, CHAT_CONTEXT_DESCRIPTION_CHAR_CAP);
  if (desc) parts.push(`— ${desc}`);

  if (opts.includeSchema) {
    const schemaText = stringifySchema(cls.schema);
    if (schemaText) {
      return `${parts.join(' ')}\n  schema: ${schemaText}`;
    }
  }

  return parts.join(' ');
}

function formatPropertyEntry(prop: ChatStudioProperty): string {
  const parts: string[] = [`- \`${prop.name}\``];
  const typeBits: string[] = [];
  if (prop.type) typeBits.push(prop.type);
  if (prop.format) typeBits.push(`format: ${prop.format}`);
  if (prop.required) typeBits.push('required');
  if (typeBits.length > 0) parts.push(`(${typeBits.join(', ')})`);
  const desc = truncate(prop.description, CHAT_CONTEXT_DESCRIPTION_CHAR_CAP);
  if (desc) parts.push(`— ${desc}`);
  return parts.join(' ');
}

function truncate(value: string | null | undefined, cap: number): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;
  if (trimmed.length <= cap) return trimmed;
  return `${trimmed.slice(0, cap - 1).trimEnd()}…`;
}

function stringifySchema(schema: unknown): string | null {
  if (schema == null) return null;
  let text: string;
  try {
    if (typeof schema === 'string') {
      const trimmed = schema.trim();
      if (trimmed.length === 0) return null;
      text = trimmed;
    } else {
      text = JSON.stringify(schema);
    }
  } catch {
    return null;
  }
  if (text.length === 0) return null;
  if (text.length <= CHAT_CONTEXT_SCHEMA_CHAR_CAP) return text;
  return `${text.slice(0, CHAT_CONTEXT_SCHEMA_CHAR_CAP - 1)}…`;
}
