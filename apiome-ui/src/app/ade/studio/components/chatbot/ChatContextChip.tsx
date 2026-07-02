'use client';

import * as React from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Sparkles } from 'lucide-react';

import {
  CHAT_CONTEXT_CLASS_CAP,
  CHAT_CONTEXT_PROPERTY_CAP,
  CHAT_CONTEXT_SELECTION_CAP,
  getSelectedClasses,
  isChatStudioContextEmpty,
  type ChatStudioContext,
} from './chat-context';
import {
  getProjectDomainCategoryLabel,
  PROJECT_DOMAIN_CATEGORY_NONE,
} from '@/app/utils/project-domain-categories';

/**
 * "Sharing context" chip rendered just above the chat composer (#259).
 *
 * Surfaces the snapshot the chat will inject into the next prompt so the
 * user is never surprised by what the assistant can see. Clicking the chip
 * opens a popover with a structured breakdown:
 *   - Project / version (one line each)
 *   - Selected classes (capped, with overflow marker)
 *   - All classes in the version (capped, with overflow marker)
 *   - Reusable property definitions (capped, with overflow marker)
 *
 * Renders nothing for an empty context so the chip never shows up on a
 * blank workspace.
 */
export interface ChatContextChipProps {
  studioContext: ChatStudioContext;
  /** Allows callers to override the default popover side (defaults to `top`). */
  side?: 'top' | 'bottom' | 'left' | 'right';
}

export function ChatContextChip({ studioContext, side = 'top' }: ChatContextChipProps) {
  if (isChatStudioContextEmpty(studioContext)) return null;

  const summary = describeSummary(studioContext);

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={`Sharing context with the assistant: ${summary}`}
          data-testid="studio-ai-chat-context-chip"
          className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200 dark:hover:bg-indigo-900/60"
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
          <span className="truncate max-w-[18rem]">Sharing context · {summary}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side={side}
          align="start"
          sideOffset={8}
          collisionPadding={12}
          data-testid="studio-ai-chat-context-popover"
          className="z-[1400] w-[22rem] max-w-[calc(100vw-1.5rem)] rounded-xl border border-gray-200 bg-white p-4 text-xs text-gray-700 shadow-xl dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
        >
          <ContextDetails studioContext={studioContext} />
          <Popover.Arrow className="fill-white stroke-gray-200 dark:fill-gray-900 dark:stroke-gray-700" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function describeSummary(ctx: ChatStudioContext): string {
  const bits: string[] = [];
  if (ctx.project?.name) bits.push(ctx.project.name);
  if (ctx.version?.label) bits.push(ctx.version.label);
  const counts: string[] = [];
  if (ctx.classes.length > 0) {
    counts.push(`${ctx.classes.length} class${ctx.classes.length === 1 ? '' : 'es'}`);
  }
  if (ctx.properties.length > 0) {
    counts.push(`${ctx.properties.length} propert${ctx.properties.length === 1 ? 'y' : 'ies'}`);
  }
  if (ctx.selectedClassIds.length > 0) {
    counts.push(`${ctx.selectedClassIds.length} selected`);
  }
  if (counts.length > 0) bits.push(counts.join(', '));
  return bits.length > 0 ? bits.join(' • ') : 'workspace state';
}

interface ContextDetailsProps {
  studioContext: ChatStudioContext;
}

function ContextDetails({ studioContext }: ContextDetailsProps) {
  const selectedClasses = getSelectedClasses(studioContext);
  return (
    <div className="space-y-3">
      <header>
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          What the assistant can see
        </p>
        <p className="mt-0.5 text-[11px] leading-snug text-gray-500 dark:text-gray-400">
          Each message you send includes the snapshot below so replies stay grounded in this workspace.
        </p>
      </header>

      <DetailSection
        label="Project"
        value={studioContext.project?.name ?? studioContext.project?.id ?? null}
      />
      {studioContext.project?.domainCategory &&
      studioContext.project.domainCategory !== PROJECT_DOMAIN_CATEGORY_NONE ? (
        <DetailSection
          label="Project domain"
          value={
            getProjectDomainCategoryLabel(studioContext.project.domainCategory) ??
            studioContext.project.domainCategory
          }
        />
      ) : null}
      <DetailSection
        label="Version"
        value={studioContext.version?.label ?? studioContext.version?.id ?? null}
      />

      {selectedClasses.length > 0 && (
        <DetailListSection
          label={`Selected on canvas (${selectedClasses.length})`}
          items={selectedClasses.map((cls) => cls.name)}
          cap={CHAT_CONTEXT_SELECTION_CAP}
          testId="studio-ai-chat-context-selection"
        />
      )}

      {studioContext.classes.length > 0 && (
        <DetailListSection
          label={`Classes (${studioContext.classes.length})`}
          items={studioContext.classes.map((cls) => cls.name)}
          cap={CHAT_CONTEXT_CLASS_CAP}
          testId="studio-ai-chat-context-classes"
        />
      )}

      {studioContext.properties.length > 0 && (
        <DetailListSection
          label={`Properties (${studioContext.properties.length})`}
          items={studioContext.properties.map((prop) =>
            prop.type ? `${prop.name} (${prop.type})` : prop.name
          )}
          cap={CHAT_CONTEXT_PROPERTY_CAP}
          testId="studio-ai-chat-context-properties"
        />
      )}
    </div>
  );
}

interface DetailSectionProps {
  label: string;
  value: string | null;
}

function DetailSection({ label, value }: DetailSectionProps) {
  if (!value) return null;
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
        {label}
      </p>
      <p className="mt-0.5 text-sm text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  );
}

interface DetailListSectionProps {
  label: string;
  items: string[];
  cap: number;
  testId?: string;
}

function DetailListSection({ label, items, cap, testId }: DetailListSectionProps) {
  if (items.length === 0) return null;
  const visible = items.slice(0, cap);
  const overflow = items.length - visible.length;
  return (
    <div data-testid={testId}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
        {label}
      </p>
      <ul className="mt-1 flex flex-wrap gap-1">
        {visible.map((item, index) => (
          <li
            key={`${item}-${index}`}
            className="rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-700 dark:bg-gray-800 dark:text-gray-200"
          >
            {item}
          </li>
        ))}
        {overflow > 0 && (
          <li className="rounded-md bg-gray-100 px-1.5 py-0.5 text-[11px] italic text-gray-500 dark:bg-gray-800 dark:text-gray-400">
            +{overflow} more
          </li>
        )}
      </ul>
    </div>
  );
}
