'use client';

/**
 * The OpenAPI 3.2 constructs of a revision's document, listed above the spec viewer's code
 * (COA-2.5, #7048).
 *
 * The code block shows everything, but a QUERY operation, a `REPORT` method in
 * `additionalOperations`, a tag's `parent`, a stream's `itemSchema` or an `in: querystring`
 * parameter is easy to miss in a long document. This lists each group that has entries. It renders
 * nothing for a 3.0 / 3.1 document, or a 3.2 document that uses none of them
 * ({@link summarizeOpenapi32Constructs} returns null).
 */

import * as React from 'react';

import { MethodChip } from '@/app/components/ui/MethodChip';

import { summarizeOpenapi32Constructs, type Openapi32Summary } from './openapi32Constructs';

export interface Openapi32ConstructsPanelProps {
  /** The spec, as JSON text. */
  spec: string;
}

/**
 * One titled group of entries.
 *
 * @param props.title - the group heading.
 * @param props.testId - the group's test id.
 * @param props.children - the `<li>` entries.
 * @returns the group.
 */
function Group({ title, testId, children }: { title: string; testId: string; children: React.ReactNode }) {
  return (
    <div className="ver-oas32__group" data-testid={testId}>
      <h3 className="ver-oas32__group-title">{title}</h3>
      <ul className="ver-oas32__list">{children}</ul>
    </div>
  );
}

/**
 * Render the groups of a summary.
 *
 * @param summary - the constructs found.
 * @returns the groups that have entries.
 */
function Groups({ summary }: { summary: Openapi32Summary }) {
  return (
    <>
      {summary.operations.length > 0 ? (
        <Group title="QUERY and custom methods" testId="oas32-operations">
          {summary.operations.map((op) => (
            <li key={`${op.path} ${op.method}`} className="ver-oas32__item">
              <MethodChip method={op.method} block={false} />
              <span className="mono">{op.path}</span>
              {op.operationId ? <span className="ver-oas32__meta mono">{op.operationId}</span> : null}
              <span className="ver-oas32__meta mono">{op.source === 'query' ? 'query' : 'additionalOperations'}</span>
            </li>
          ))}
        </Group>
      ) : null}
      {summary.tags.length > 0 ? (
        <Group title="Tag hierarchy" testId="oas32-tags">
          {summary.tags.map((tag) => (
            <li key={tag.name} className="ver-oas32__item">
              <span className="mono">{tag.name}</span>
              {tag.parent ? <span className="ver-oas32__meta">under <span className="mono">{tag.parent}</span></span> : null}
              {tag.kind ? <span className="ver-oas32__meta">kind <span className="mono">{tag.kind}</span></span> : null}
              {tag.summary ? <span className="ver-oas32__meta">{tag.summary}</span> : null}
            </li>
          ))}
        </Group>
      ) : null}
      {summary.streams.length > 0 ? (
        <Group title="Streaming media types" testId="oas32-streams">
          {summary.streams.map((stream) => (
            <li key={`${stream.location} ${stream.mediaType}`} className="ver-oas32__item">
              <span className="mono">{stream.mediaType}</span>
              <span className="ver-oas32__meta">{stream.kindLabel}</span>
              <span className="ver-oas32__meta mono">{stream.location}</span>
              {stream.hasItemSchema ? <span className="ver-oas32__meta mono">itemSchema</span> : null}
            </li>
          ))}
        </Group>
      ) : null}
      {summary.querystring.length > 0 ? (
        <Group title="Query string parameters" testId="oas32-querystring">
          {summary.querystring.map((param) => (
            <li key={`${param.path} ${param.method} ${param.name}`} className="ver-oas32__item">
              <MethodChip method={param.method} block={false} />
              <span className="mono">{param.path}</span>
              <span className="mono">{param.name}</span>
              {param.mediaType ? <span className="ver-oas32__meta mono">{param.mediaType}</span> : null}
            </li>
          ))}
        </Group>
      ) : null}
    </>
  );
}

/**
 * Render the panel. See {@link Openapi32ConstructsPanelProps}.
 *
 * @returns the panel, or null when the document has no OpenAPI 3.2 constructs.
 */
export default function Openapi32ConstructsPanel({ spec }: Openapi32ConstructsPanelProps) {
  const summary = React.useMemo(() => summarizeOpenapi32Constructs(spec), [spec]);
  if (!summary) return null;
  return (
    <section className="ver-oas32" aria-label="OpenAPI 3.2 constructs" data-testid="oas32-constructs">
      <h2 className="ver-oas32__title">OpenAPI {summary.openapi} constructs</h2>
      <div className="ver-oas32__groups">
        <Groups summary={summary} />
      </div>
    </section>
  );
}
