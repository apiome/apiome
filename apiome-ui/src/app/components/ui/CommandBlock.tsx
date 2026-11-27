'use client';

import * as React from 'react';
import { Check, Copy } from 'lucide-react';
import { Button } from './Button';
import { LiveRegion } from './LiveRegion';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './Tabs';
import { scrubSecrets, type CommandSurface } from '../../../../lib/command-block';
import { cn } from '../../../../lib/utils';

/**
 * CommandBlock — **The same, from anywhere** (PFX-8.2, #7299).
 *
 * Authority: `docs/mockups/contracts/*.html` (`.ct-cli`): a card under a screen's form with one pill
 * per surface (for Contracts: apiome · Pact CLI · GitHub Action · REST), the command for the
 * selected one, and Copy. The page builds the surfaces from its form state on every render (see
 * `lib/pact-commands.ts`), so the block always shows what the form would do now.
 *
 * - A surface that cannot do the action has `text: null` and its reason, which the panel shows in
 *   place of a command; Copy is then disabled.
 * - `unsupported` lists what the form holds that no command carries, each with its reason, so
 *   nothing is dropped silently.
 * - The text is put through `scrubSecrets` once more here, so a credential-shaped value is never
 *   drawn or copied even if a builder missed it.
 * - A copy that the browser refuses is said out loud ("select the text and copy it"), not ignored.
 *
 * ```tsx
 * <CommandBlock surfaces={pactCommandSurfaces(action)} unsupported={unsupportedLines(action)} />
 * ```
 */
export interface CommandBlockProps {
  /** The surfaces, in pill order. At least one. */
  surfaces: CommandSurface[];
  /** The heading. Defaults to “The same, from anywhere”. */
  title?: string;
  /** The heading's level where the block sits (default 3; a block in a dialog under its title). */
  headingLevel?: 2 | 3 | 4;
  /** Form values no command carries, one sentence each. */
  unsupported?: string[];
  /** A line under the block, e.g. what CI fills in by default. */
  footnote?: React.ReactNode;
  /** The pill selected first; defaults to the first surface. */
  defaultSurface?: string;
  className?: string;
  'data-testid'?: string;
}

/** How a copy went, for the button and the live message. */
type CopyState = 'idle' | 'copied' | 'failed';

/** What the block says when the browser refuses the clipboard. */
export const COPY_FAILED = 'Could not copy: select the text and copy it.';

export function CommandBlock({
  surfaces,
  title = 'The same, from anywhere',
  headingLevel = 3,
  unsupported = [],
  footnote,
  defaultSurface,
  className,
  'data-testid': testId = 'command-block',
}: CommandBlockProps) {
  const headingId = React.useId();
  const first = surfaces.find((surface) => surface.id === defaultSurface) ?? surfaces[0];
  const [selected, setSelected] = React.useState<string>(first?.id ?? '');
  const [copy, setCopy] = React.useState<CopyState>('idle');

  // A surface list that changes under the block (a different action) keeps a valid selection.
  const current = surfaces.find((surface) => surface.id === selected) ?? first;
  const text = current?.text == null ? null : scrubSecrets(current.text);

  // The message is about the text that was copied; once the text changes it no longer applies.
  React.useEffect(() => setCopy('idle'), [text]);

  if (!current) return null;

  const Heading = `h${headingLevel}` as const;

  const copyText = async () => {
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopy('copied');
    } catch {
      setCopy('failed');
    }
  };

  return (
    // A group, not a `<section>`: a named section is a region landmark, and a page (or the
    // gallery) with two blocks would have two landmarks of the same name.
    <div role="group" className={cn('command-block', className)} aria-labelledby={headingId} data-testid={testId}>
      <div className="command-block__header">
        <Heading className="command-block__title" id={headingId}>
          {title}
        </Heading>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="command-block__copy"
          onClick={() => void copyText()}
          disabled={text === null}
          aria-label={copy === 'copied' ? `Copied the ${current.label} command` : `Copy the ${current.label} command`}
          title={copy === 'copied' ? 'Copied' : 'Copy'}
        >
          {copy === 'copied' ? <Check aria-hidden /> : <Copy aria-hidden />}
        </Button>
      </div>
      <Tabs value={current.id} onValueChange={setSelected}>
        <TabsList variant="pills" aria-label="Surface" className="command-block__pills">
          {surfaces.map((surface) => (
            <TabsTrigger key={surface.id} value={surface.id} variant="pills" size="sm">
              {surface.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {surfaces.map((surface) => (
          <TabsContent key={surface.id} value={surface.id} className="command-block__panel">
            {surface.id === current.id ? (
              <>
                {text === null ? (
                  <p className="command-block__unavailable" data-testid="command-block-unavailable">
                    {surface.unavailable ?? `${surface.label} cannot do this.`}
                  </p>
                ) : (
                  <pre className="command-block__code" aria-label={`${surface.label} command`} data-testid="command-block-code">
                    <code>{text}</code>
                  </pre>
                )}
                {surface.notes && surface.notes.length > 0 ? (
                  <ul className="command-block__notes">
                    {surface.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : null}
          </TabsContent>
        ))}
      </Tabs>
      {unsupported.length > 0 ? (
        <div className="command-block__unsupported" data-testid="command-block-unsupported">
          <p className="command-block__unsupported-title">Not carried by the command</p>
          <ul>
            {unsupported.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <LiveRegion message={copy === 'copied' ? 'Copied.' : copy === 'failed' ? COPY_FAILED : ''} />
      {copy === 'failed' ? (
        <p className="command-block__status" data-testid="command-block-copy-failed">
          {COPY_FAILED}
        </p>
      ) : null}
      {footnote ? <p className="command-block__footnote">{footnote}</p> : null}
    </div>
  );
}
