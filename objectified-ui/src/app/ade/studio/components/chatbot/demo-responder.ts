/**
 * Default offline responder used by the Studio AI chatbot when Ollama is
 * unavailable or `ollamaTransport` is off (#265).
 *
 * The replies are deterministic and intentionally cover every UI affordance
 * the interface guidelines call for so designers and reviewers can see the
 * chrome end-to-end without running a model:
 *   - Markdown rendering (headings, lists, inline code)
 *   - A fenced code block with copy + syntax highlighting
 *   - A ```json``` block holding a small but valid OpenAPI 3.1 spec so the
 *     "Import OpenAPI spec" affordance lights up
 *
 * As of #259 the responder is also context-aware: when the chat shell hands
 * us a `studioContext` snapshot we mention the user's project / version,
 * acknowledge canvas selection, and reuse existing class / property names
 * inside the demo OpenAPI spec.
 *
 * #260 layers in multi-turn awareness. Each call asks
 * `summarizeConversationHistory` to classify the prompt against the prior
 * transcript and we branch on the result:
 *   - `refine-spec`: take the last spec we shipped, apply the requested
 *     edits via `applyRefinementsToSpec`, and reship it so the Import
 *     button keeps working.
 *   - `comparison`: acknowledge the "more like X" subject inside the reply
 *     and the regenerated spec.
 *   - `clarification`: answer the question without re-shipping a schema.
 *   - `iteration`: rebuild the spec from scratch but flag it as a redo.
 *   - `standalone` / `first-turn`: behave as before.
 */

import type { ChatStudioContext, ChatStudioProperty } from './chat-context';
import { getSelectedClasses, isChatStudioContextEmpty } from './chat-context';
import {
  applyRefinementsToSpec,
  summarizeConversationHistory,
  type ChatHistorySummary,
  type ChatRefinementOp,
} from './conversation-history';
import type { ChatSendFn } from './types';

const SPEC_DEMO_PROMPTS = ['openapi', 'spec', 'schema', 'api'];

export const createDemoChatResponder = (): ChatSendFn => async ({
  messages,
  prompt,
  isRegenerate,
  studioContext,
}) => {
  const history = summarizeConversationHistory(messages, prompt);
  const lower = prompt.toLowerCase();
  const variation = isRegenerate ? '\n\n_Regenerated with a slightly different angle._' : '';
  const groundingLine = describeGrounding(studioContext);
  const continuityLine = describeContinuity(history);

  if (history.intent === 'clarification') {
    return buildClarificationReply({ history, groundingLine, continuityLine, variation });
  }

  if (history.intent === 'refine-spec' && history.lastAssistantSpec) {
    return buildRefinementReply({
      history,
      groundingLine,
      continuityLine,
      variation,
    });
  }

  const wantsSpec =
    history.intent === 'comparison' ||
    SPEC_DEMO_PROMPTS.some((needle) => lower.includes(needle));

  if (wantsSpec) {
    const spec = buildSampleSpec(studioContext, history);
    const intro =
      history.intent === 'comparison' && history.comparisonSubject
        ? `Reworked the sketch to lean more like **${history.comparisonSubject}**${groundingLine ? ` ${groundingLine}` : ''} — review the JSON below and click **Import OpenAPI spec** to load it into Studio.`
        : `Here's a small OpenAPI 3.1 sketch for what you described${groundingLine ? ` ${groundingLine}` : ''} — review the JSON below and click **Import OpenAPI spec** to load it into Studio.`;
    const suggestions = buildContextAwareSuggestions(studioContext);
    const lines: string[] = [intro];
    if (continuityLine) lines.push('', continuityLine);
    lines.push(
      '',
      '```json',
      JSON.stringify(spec, null, 2),
      '```',
      '',
      'A few things to consider next:',
      ...suggestions,
    );
    return lines.join('\n') + variation;
  }

  const lines: string[] = [
    `I'm the offline preview of the Studio AI assistant${groundingLine ? ` ${groundingLine}` : ''} — the live model lands in a follow-up ticket. Until then, here's what the chat surface supports today:`,
  ];
  if (continuityLine) lines.push('', continuityLine);
  lines.push(
    '',
    '- **Markdown** rendering with headings, lists, and inline `code`',
    '- Code blocks with copy + syntax highlighting:',
    '',
    '```ts',
    "function greet(name: string): string {",
    "  return `Hello, ${name}!`;",
    "}",
    '```',
    '',
    'Try asking for an "OpenAPI spec" to see the import affordance.',
  );
  return lines.join('\n') + variation;
};

interface ReplyBuilderInput {
  history: ChatHistorySummary;
  groundingLine: string | null;
  continuityLine: string | null;
  variation: string;
}

function buildClarificationReply({
  history,
  groundingLine,
  continuityLine,
  variation,
}: ReplyBuilderInput): string {
  const turnLabel = `turn ${history.userTurnCount}`;
  const lines: string[] = [
    `Happy to clarify (${turnLabel})${groundingLine ? ` ${groundingLine}` : ''}.`,
  ];
  if (continuityLine) lines.push('', continuityLine);
  lines.push(
    '',
    'In the previous reply I sketched a small OpenAPI fragment. The most common follow-up questions look like:',
    '',
    '- _What does field X mean?_ — describe its role in the schema',
    '- _Why is field Y required?_ — explain the constraint',
    '- _How would I change Z?_ — suggest a refinement you can ask for next',
    '',
    'Drop a follow-up like "make `name` required" or "remove `priceCents`" and I\'ll re-ship the same schema with the edit applied.',
  );
  return lines.join('\n') + variation;
}

function buildRefinementReply({
  history,
  groundingLine,
  continuityLine,
  variation,
}: ReplyBuilderInput): string {
  const lastSpec = history.lastAssistantSpec!;
  const refined = applyRefinementsToSpec(lastSpec.spec, history.refinementOps);
  const opSummary = summarizeOps(history.refinementOps);
  const introBits: string[] = [
    `Updated the previous schema${groundingLine ? ` ${groundingLine}` : ''}.`,
  ];
  if (opSummary) introBits.push(opSummary);
  introBits.push('Click **Import OpenAPI spec** to apply the refined version.');

  const lines: string[] = [introBits.join(' ')];
  if (continuityLine) lines.push('', continuityLine);
  lines.push(
    '',
    '```json',
    JSON.stringify(refined, null, 2),
    '```',
    '',
    'Need another change? Ask me to add, remove, rename, or require a property and I\'ll keep iterating.',
  );
  return lines.join('\n') + variation;
}

function describeContinuity(history: ChatHistorySummary): string | null {
  if (history.assistantTurnCount === 0) return null;
  switch (history.intent) {
    case 'refine-spec':
      return `_Building on turn ${history.userTurnCount - 1} — applying ${history.refinementOps.length === 1 ? '1 edit' : `${history.refinementOps.length} edits`} to the previous spec._`;
    case 'comparison':
      return history.comparisonSubject
        ? `_Reframing the previous answer to look more like **${history.comparisonSubject}**._`
        : '_Reframing the previous answer with a new reference point._';
    case 'iteration':
      return `_Trying a different angle on turn ${history.userTurnCount - 1}._`;
    case 'standalone':
      return `_Continuing the thread — turn ${history.userTurnCount} of ${history.userTurnCount}._`;
    default:
      return null;
  }
}

function summarizeOps(ops: ChatRefinementOp[]): string | null {
  if (ops.length === 0) return null;
  const verbs = ops.map(opToVerb);
  if (verbs.length === 1) return `Applied: ${verbs[0]}.`;
  if (verbs.length === 2) return `Applied: ${verbs[0]} and ${verbs[1]}.`;
  return `Applied: ${verbs.slice(0, -1).join(', ')}, and ${verbs[verbs.length - 1]}.`;
}

function opToVerb(op: ChatRefinementOp): string {
  switch (op.kind) {
    case 'add-property':
      return op.type ? `added \`${op.name}\` (${op.type})` : `added \`${op.name}\``;
    case 'remove-property':
      return `removed \`${op.name}\``;
    case 'require-property':
      return `marked \`${op.name}\` required`;
    case 'rename-property':
      return `renamed \`${op.from}\` → \`${op.to}\``;
  }
}

function describeGrounding(ctx: ChatStudioContext | undefined): string | null {
  if (!ctx || isChatStudioContextEmpty(ctx)) return null;
  const parts: string[] = [];
  const projectName = ctx.project?.name;
  const versionLabel = ctx.version?.label;
  if (projectName && versionLabel) {
    parts.push(`for **${projectName}** ${versionLabel}`);
  } else if (projectName) {
    parts.push(`for **${projectName}**`);
  } else if (versionLabel) {
    parts.push(`on version ${versionLabel}`);
  }
  const selected = getSelectedClasses(ctx).map((cls) => cls.name);
  if (selected.length === 1) {
    parts.push(`while looking at \`${selected[0]}\``);
  } else if (selected.length > 1) {
    const visible = selected.slice(0, 3).map((name) => `\`${name}\``).join(', ');
    const overflow = selected.length - Math.min(selected.length, 3);
    parts.push(`while looking at ${visible}${overflow > 0 ? ` (+${overflow} more)` : ''}`);
  }
  return parts.length > 0 ? `(${parts.join(' ')})` : null;
}

function buildContextAwareSuggestions(ctx: ChatStudioContext | undefined): string[] {
  const suggestions = [
    '- Tighten property descriptions for documentation scoring',
    '- Add `examples` arrays where missing',
    '- Decide whether to expose this through a path operation in a follow-up',
  ];
  if (!ctx || isChatStudioContextEmpty(ctx)) return suggestions;
  const selected = getSelectedClasses(ctx);
  if (selected.length > 0) {
    const names = selected.slice(0, 3).map((cls) => `\`${cls.name}\``).join(', ');
    suggestions.unshift(`- Cross-check the new schema against your selected ${selected.length === 1 ? 'class' : 'classes'} (${names})`);
  } else if (ctx.classes.length > 0) {
    const sample = ctx.classes.slice(0, 3).map((cls) => `\`${cls.name}\``).join(', ');
    suggestions.unshift(`- Reuse the names already in this version when possible (e.g. ${sample})`);
  }
  return suggestions;
}

interface SampleSpec {
  openapi: string;
  info: {
    title: string;
    version: string;
    description: string;
  };
  components: {
    schemas: Record<string, {
      type: string;
      description: string;
      properties: Record<string, { type: string; format?: string; description: string; minimum?: number }>;
      required: string[];
    }>;
  };
}

function buildSampleSpec(
  ctx: ChatStudioContext | undefined,
  history: ChatHistorySummary,
): SampleSpec {
  const titleBase = ctx?.project?.name ? `${ctx.project.name} (Studio AI sketch)` : 'Sample Catalog API';
  const title =
    history.intent === 'comparison' && history.comparisonSubject
      ? `${titleBase} — inspired by ${history.comparisonSubject}`
      : titleBase;
  const version = ctx?.version?.label ?? '0.1.0';
  const className = pickReferenceClassName(ctx) ?? 'Product';
  const properties = buildSpecProperties(ctx);

  const description = ctx?.project?.name
    ? `Sketch generated by the Studio AI demo responder, grounded in ${ctx.project.name}.`
    : 'Tiny catalog API generated by the Studio AI demo responder.';
  const finalDescription =
    history.intent === 'comparison' && history.comparisonSubject
      ? `${description} Adjusted to look more like ${history.comparisonSubject}.`
      : description;

  return {
    openapi: '3.1.0',
    info: {
      title,
      version,
      description: finalDescription,
    },
    components: {
      schemas: {
        [className]: {
          type: 'object',
          description: ctx?.project?.name
            ? `A representative ${className} for ${ctx.project.name}.`
            : 'A purchasable item in the catalog.',
          properties,
          required: deriveRequired(properties),
        },
      },
    },
  };
}

function pickReferenceClassName(ctx: ChatStudioContext | undefined): string | null {
  if (!ctx) return null;
  const selected = getSelectedClasses(ctx);
  if (selected.length > 0) return selected[0].name;
  if (ctx.classes.length > 0) return ctx.classes[0].name;
  return null;
}

function buildSpecProperties(
  ctx: ChatStudioContext | undefined
): Record<string, { type: string; format?: string; description: string; minimum?: number }> {
  const fallback: Record<string, { type: string; format?: string; description: string; minimum?: number }> = {
    id: { type: 'string', format: 'uuid', description: 'Catalog identifier' },
    name: { type: 'string', description: 'Display name shown to shoppers' },
    priceCents: { type: 'integer', minimum: 0, description: 'Price in cents' },
  };

  if (!ctx || ctx.properties.length === 0) return fallback;

  const properties: Record<string, { type: string; format?: string; description: string; minimum?: number }> = {};
  for (const prop of ctx.properties.slice(0, 4)) {
    properties[prop.name] = describeReusableProperty(prop);
  }
  if (Object.keys(properties).length === 0) return fallback;
  // Always make sure there's an id-shaped field so the spec is useful as a starting point.
  if (!properties.id) {
    properties.id = { type: 'string', format: 'uuid', description: 'Identifier reused from Studio properties.' };
  }
  return properties;
}

function describeReusableProperty(prop: ChatStudioProperty): {
  type: string;
  format?: string;
  description: string;
  minimum?: number;
} {
  const type = prop.type ?? 'string';
  const description = prop.description?.trim().length
    ? prop.description.trim()
    : `Reused Studio property "${prop.name}".`;
  const entry: { type: string; format?: string; description: string; minimum?: number } = {
    type,
    description,
  };
  if (prop.format) entry.format = prop.format;
  if (type === 'integer' || type === 'number') entry.minimum = 0;
  return entry;
}

function deriveRequired(
  properties: Record<string, { type: string }>
): string[] {
  const required = Object.keys(properties).filter((name) => name === 'id' || name === 'name');
  return required.length > 0 ? required : Object.keys(properties).slice(0, 1);
}
