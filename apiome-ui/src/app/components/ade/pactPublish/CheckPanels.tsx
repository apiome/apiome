'use client';

/**
 * The Publish page's pre-publish check (PFX-8.4, #7301): **Compare with** (step 3), the result card
 * in the aside — one pill per provider version, match / differs / not in spec per interaction — and
 * the difference drawer. Pure presentation: the page holds the state, and `lib/pact-publish-check.ts`
 * decides every sentence.
 */

import * as React from 'react';
import Link from 'next/link';
import { CircleCheck, CircleHelp, CircleX, GitBranch, PencilRuler, Plus, RefreshCw, Server, Tag } from 'lucide-react';
import {
  Badge,
  Button,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  EmptyState,
  Input,
  Tabs,
  TabsContent,
  TabsCount,
  TabsList,
  TabsTrigger,
} from '@/app/components/ui';
import {
  OUTCOME_LABELS,
  VISIBLE_INTERACTIONS,
  interactionName,
  interactionNote,
  nothingToCompare,
  orderedInteractions,
  pillCount,
  pillLabel,
  type CheckInteraction,
  type CheckResult,
  type CompareAnswer,
  type CompareChoice,
  type DifferenceView,
  type Outcome,
} from '@lib/pact-publish-check';

/** The glyph of each selector kind. */
const KIND_GLYPH = { main: GitBranch, deployed: Server, version: Tag, draft: PencilRuler } as const;

/** Props for {@link CompareWith}. */
export interface CompareWithProps {
  /** Every chip, the offered ones and those typed in. */
  choices: CompareChoice[];
  /** The selectors switched on. */
  selected: string[];
  /** Switch a chip on or off. */
  onToggle: (selector: string) => void;
  /** Add a typed selector; returns why it was not added, or `null`. */
  onAdd: (text: string) => string | null;
  /** Why the environments could not be read, when they could not. */
  problem?: string | null;
}

/**
 * **Compare with**: one chip per provider version, and **+ Another version**.
 *
 * @param props - See {@link CompareWithProps}.
 * @returns The field.
 */
export function CompareWith({ choices, selected, onToggle, onAdd, problem }: CompareWithProps) {
  const [adding, setAdding] = React.useState(false);
  const [typed, setTyped] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const add = () => {
    const refused = onAdd(typed);
    setError(refused);
    if (!refused) {
      setTyped('');
      setAdding(false);
    }
  };
  return (
    <div className="ppub-field" data-testid="ppub-compare-with">
      <span className="ppub-field__label" id="ppub-compare-label">
        Compare with
      </span>
      <div className="ppub-chips" role="group" aria-labelledby="ppub-compare-label">
        {choices.map((choice) => {
          const Glyph = KIND_GLYPH[choice.kind];
          const on = selected.includes(choice.selector);
          return (
            <button
              key={choice.selector}
              type="button"
              className={on ? 'ppub-chip is-active' : 'ppub-chip'}
              aria-pressed={on}
              onClick={() => onToggle(choice.selector)}
              data-testid={`ppub-chip-${choice.selector}`}
            >
              <Glyph aria-hidden className="ppub-chip__glyph" />
              {choice.label}
            </button>
          );
        })}
        {adding ? null : (
          <Button type="button" variant="link" size="sm" onClick={() => setAdding(true)} data-testid="ppub-chip-add">
            <Plus aria-hidden />
            Another version
          </Button>
        )}
      </div>
      {adding ? (
        <div className="ppub-row-actions">
          <Input
            aria-label="Another provider version"
            className="ppx__mono ppub-chip-input"
            value={typed}
            placeholder="2.7.0, deployed:staging or draft:2.8.0-rc1"
            maxLength={300}
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                add();
              }
            }}
            data-testid="ppub-chip-input"
          />
          <Button type="button" size="sm" variant="outline" onClick={add}>
            Add
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => { setAdding(false); setError(null); }}>
            Cancel
          </Button>
        </div>
      ) : null}
      {error ? (
        <p className="ppub-hint ppub-hint--danger" role="alert">
          {error}
        </p>
      ) : null}
      {problem ? <p className="ppub-hint">{problem}</p> : null}
      <p className="ppub-hint">One pact, several provider versions at once — you see today’s answer and tomorrow’s. Checks write nothing.</p>
    </div>
  );
}

/** The glyph and tone of an outcome. */
const OUTCOME_LOOK: Record<Outcome, { Glyph: typeof CircleCheck; tone: 'ok' | 'danger' | 'warn' }> = {
  match: { Glyph: CircleCheck, tone: 'ok' },
  differs: { Glyph: CircleX, tone: 'danger' },
  'not-in-spec': { Glyph: CircleHelp, tone: 'warn' },
};

/** One interaction row. */
function InteractionRow({
  row,
  result,
  onOpen,
}: {
  row: CheckInteraction;
  result: CheckResult;
  onOpen: (row: CheckInteraction, result: CheckResult) => void;
}) {
  const { Glyph, tone } = OUTCOME_LOOK[row.outcome];
  return (
    <li className="ppub-ix" data-testid="ppub-ix">
      <Glyph aria-hidden className={`ppub-ix__glyph ppub-ix__glyph--${tone}`} />
      <div className="ppub-ix__main">
        <span className="ppx__mono ppub-ix__name">{interactionName(row)}</span>
        <span className="ppub-ix__sub">
          {interactionNote(row, result.providerVersion)}
          {row.outcome === 'match' ? null : (
            <>
              {' '}
              <Button type="button" variant="link" size="sm" className="ppub-ix__open" onClick={() => onOpen(row, result)}>
                See the difference
              </Button>
            </>
          )}
        </span>
      </div>
      <Badge variant={tone}>{OUTCOME_LABELS[row.outcome]}</Badge>
    </li>
  );
}

/** One provider version's interactions, what needs attention first. */
function ResultPanel({
  result,
  onOpen,
}: {
  result: CheckResult;
  onOpen: (row: CheckInteraction, result: CheckResult) => void;
}) {
  const [all, setAll] = React.useState(false);
  const rows = orderedInteractions(result.interactions);
  const shown = all ? rows : rows.slice(0, VISIBLE_INTERACTIONS);
  const hidden = rows.length - shown.length;
  if (result.error) {
    return (
      <p className="ppub-hint ppub-hint--danger" role="status">
        {result.providerVersion} could not be compared: {result.error}
      </p>
    );
  }
  if (rows.length && result.counts.match === rows.length) {
    return (
      <EmptyState
        variant="inline"
        tone="neutral"
        icon={<CircleCheck aria-hidden />}
        titleAs="p"
        title={`All ${rows.length} interactions match ${result.providerVersion}`}
        description={result.draft ? 'This draft already satisfies the pact.' : 'This provider version already satisfies the pact.'}
      />
    );
  }
  return (
    <>
      <ul className="ppub-ix__list">
        {shown.map((row) => (
          <InteractionRow key={row.index} row={row} result={result} onOpen={onOpen} />
        ))}
      </ul>
      {hidden > 0 ? (
        <p className="ppub-hint">
          {hidden} more {hidden === 1 ? 'matches' : 'match'} ·{' '}
          <Button type="button" variant="link" size="sm" onClick={() => setAll(true)}>
            Show all {rows.length}
          </Button>
        </p>
      ) : null}
      {result.verdict === 'unverified' ? (
        <p className="ppub-hint">
          The provider contract has no passing self-verification evidence ({result.selfVerification ?? 'missing'}), so a publish
          would record this as unverified.
        </p>
      ) : null}
    </>
  );
}

/** What the result card holds for one pact. */
export type CheckState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'done'; answer: CompareAnswer };

/** Props for {@link CheckResultCard}. */
export interface CheckResultCardProps {
  /** `Orders UI → Billing Service`. */
  pair: string;
  state: CheckState;
  onRecheck: () => void;
  onOpen: (row: CheckInteraction, result: CheckResult, provider: string) => void;
}

/**
 * The result of the check for one pact: one pill per provider version.
 *
 * @param props - See {@link CheckResultCardProps}.
 * @returns The card.
 */
export function CheckResultCard({ pair, state, onRecheck, onOpen }: CheckResultCardProps) {
  const answer = state.status === 'done' ? state.answer : null;
  const [tab, setTab] = React.useState('0');
  return (
    <section className="ppub-card" aria-label={`Result of the check: ${pair}`} data-testid="ppub-check-result">
      <div className="ppub-card__head">
        <span className="ppub-caps">{pair}</span>
        <Button type="button" variant="ghost" size="sm" onClick={onRecheck} disabled={state.status === 'loading'}>
          <RefreshCw aria-hidden />
          Re-check
        </Button>
      </div>
      {state.status === 'loading' ? (
        <p className="ppub-hint" role="status">
          Comparing with each provider version…
        </p>
      ) : null}
      {state.status === 'error' ? (
        <p className="ppub-hint ppub-hint--danger" role="alert">
          {state.error}
        </p>
      ) : null}
      {answer && nothingToCompare(answer) ? (
        <p className="ppub-hint" data-testid="ppub-check-nothing">
          {nothingToCompare(answer)}
        </p>
      ) : null}
      {answer && answer.results.length ? (
        <Tabs value={answer.results[Number(tab)] ? tab : '0'} onValueChange={setTab}>
          <TabsList variant="pills" aria-label="Provider versions">
            {answer.results.map((result, index) => (
              <TabsTrigger key={`${result.providerVersion}-${index}`} value={String(index)} variant="pills" data-testid="ppub-check-pill">
                {pillLabel(result)}
                <TabsCount>{pillCount(result)}</TabsCount>
              </TabsTrigger>
            ))}
          </TabsList>
          {answer.results.map((result, index) => (
            <TabsContent key={`${result.providerVersion}-${index}`} value={String(index)} className="ppub-panel">
              <p className="ppub-hint">Selected by {result.reasons.join(', ')}.</p>
              <ResultPanel result={result} onOpen={(row, picked) => onOpen(row, picked, answer.provider)} />
            </TabsContent>
          ))}
        </Tabs>
      ) : null}
      {answer && (answer.unresolved.length || answer.skipped.length) ? (
        <ul className="ppub-check__notes" data-testid="ppub-check-unresolved">
          {answer.unresolved.map((note) => (
            <li key={note.selector}>
              <span className="ppx__mono">{note.selector}</span> — not compared: {note.reason}.
            </li>
          ))}
          {answer.skipped.map((note) => (
            <li key={`${note.selector}-${note.providerVersion}`}>
              <span className="ppx__mono">{note.providerVersion}</span> — skipped: {note.reason}.
            </li>
          ))}
        </ul>
      ) : null}
      {answer ? (
        <p className="ppub-hint">
          You can still publish. The pact records what the consumer needs; a difference becomes a failing verdict the provider sees.
        </p>
      ) : null}
    </section>
  );
}

/** Props for {@link DifferenceDrawer}. */
export interface DifferenceDrawerProps {
  view: DifferenceView | null;
  onClose: () => void;
}

/**
 * What the pact needs beside what the spec declares, and the spec change.
 *
 * @param props - See {@link DifferenceDrawerProps}.
 * @returns The drawer.
 */
export function DifferenceDrawer({ view, onClose }: DifferenceDrawerProps) {
  return (
    <Drawer open={view !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DrawerContent size="lg" data-testid="ppub-difference">
        {view ? (
          <>
            <DrawerHeader>
              <DrawerTitle className="ppx__mono">{view.title}</DrawerTitle>
              <DrawerDescription>{view.subtitle}</DrawerDescription>
            </DrawerHeader>
            <DrawerBody className="ppub-diff">
              <div className="ppub-diff__grid">
                <div>
                  <p className="ppub-caps">Pact expects</p>
                  <pre className="ppub-diff__code" aria-label="Pact expects">
                    {view.expected}
                  </pre>
                </div>
                <div>
                  <p className="ppub-caps">Spec declares</p>
                  <pre className="ppub-diff__code" aria-label="Spec declares">
                    {view.declared}
                  </pre>
                  {view.declaredPointer ? <p className="ppub-hint ppx__mono">{view.declaredPointer}</p> : null}
                </div>
              </div>
              {view.findings.length ? (
                <ul className="ppub-diff__findings" aria-label="Why it differs">
                  {view.findings.map((finding, index) => (
                    <li key={`${finding.code}-${index}`}>
                      <span className="ppx__mono">{finding.code}</span> — {finding.message}
                      {finding.pactPointer ? <span className="ppub-hint ppx__mono"> {finding.pactPointer}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {view.specChangeHref ? (
                <div className="ppub-row-actions">
                  <Button asChild size="sm" variant="outline">
                    <Link href={view.specChangeHref}>{view.specChangeLabel}</Link>
                  </Button>
                </div>
              ) : (
                <p className="ppub-hint">This provider contract was uploaded, not rendered from an Apiome project, so there is no spec change to open.</p>
              )}
            </DrawerBody>
          </>
        ) : null}
      </DrawerContent>
    </Drawer>
  );
}
