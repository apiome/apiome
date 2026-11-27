'use client';

/**
 * The parts of the **Contracts** landing (PFX-8.1, #7298): the integrations table, the network view,
 * the "Start something" entry points, the first-run checklist and the command dialog an action with
 * no screen yet opens. Built to `docs/mockups/contracts/overview.html`; every visual is a `ctx-`
 * class in `globals.css`.
 */

import * as React from 'react';
import Link from 'next/link';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { ArrowRight, ChevronRight, Circle, CircleCheck, Ellipsis, Terminal } from 'lucide-react';
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  SkeletonTableRows,
} from '@/app/components/ui';
import { formatWhen, pacticipantRoute } from '@lib/pact-pacticipants';
import { pactRoute } from '@lib/pact-detail';
import { verificationRoute } from '@lib/pact-verification';
import { pairHealthRoute } from '@lib/pact-health';
import { CAN_I_DEPLOY_ROUTE } from '@lib/pact-matrix';
import {
  KIND_LABEL,
  WAYS_IN,
  initials,
  verdictText,
  type FirstRunStep,
  type PactIntegration,
  type WayIn,
} from '@lib/pact-overview';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';

/** The column widths the loading rows draw, matching the table's six columns. */
const SKELETON_COLUMNS = ['40%', '6rem', '7rem', '8rem', '9rem', ''] as const;

/** An action with no screen yet, opened as a command. */
export interface CommandRequest {
  title: string;
  description: string;
  command: string;
}

/**
 * The dialog an action with no screen yet opens: what to run, and where.
 *
 * @param props - The action, and how to close.
 * @returns The dialog.
 */
export function CommandDialog({
  request,
  onClose,
}: {
  request: CommandRequest | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={request !== null} onOpenChange={(open) => !open && onClose()}>
      {request ? (
        <DialogContent data-testid="ctx-command-dialog">
          <DialogHeader>
            <DialogTitle>{request.title}</DialogTitle>
            <DialogDescription>{request.description}</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className="ctx-dialog__lead">
              Run this from your build or a terminal signed in to this workspace with{' '}
              <span className="ppx__mono">apiome login</span>:
            </p>
            <CliSnippet label={request.title} command={request.command} />
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

/**
 * A pacticipant's hex avatar and name.
 *
 * @param props - The handle and name.
 * @returns The avatar and name.
 */
function Party({ slug, name }: { slug: string; name: string }) {
  return (
    <Link className="ctx-party" href={pacticipantRoute(slug)}>
      <span className="ctx-avatar" aria-hidden>
        {initials(name)}
      </span>
      <b className="ctx-party__name">{name}</b>
    </Link>
  );
}

/**
 * One row's ⋯ menu.
 *
 * @param props - The integration.
 * @returns The menu.
 */
function RowMenu({ row }: { row: PactIntegration }) {
  const canIDeploy = `${CAN_I_DEPLOY_ROUTE}?${new URLSearchParams({
    pacticipant: row.consumer,
    version: row.consumer_version,
  }).toString()}`;
  const items: Array<{ id: string; label: string; href: string }> = [
    { id: 'pact', label: 'Open the pact', href: pactRoute(row.consumer, row.provider) },
    { id: 'verification', label: 'Verification history', href: verificationRoute(row.provider, row.consumer) },
    { id: 'health', label: 'Pair health', href: pairHealthRoute(row.provider, row.consumer) },
    { id: 'can-i-deploy', label: 'Can I deploy?', href: canIDeploy },
  ];
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="ctx-row-menu"
          aria-label={`Actions for ${row.consumer_name} → ${row.provider_name}`}
          data-testid={`ctx-row-menu-${row.consumer}-${row.provider}`}
        >
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="tnt-menu" sideOffset={4} align="end">
          {items.map((item) => (
            <DropdownMenu.Item key={item.id} className="tnt-menu__item" asChild>
              <Link href={item.href} data-testid={`ctx-row-${item.id}`}>
                {item.label}
              </Link>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/**
 * The integrations table: pair, kind, latest verdict, the environments both sides run in, and
 * when it was last verified. Loading draws skeleton rows, never a spinner (DESIGN.md §8).
 *
 * @param props - The rows, or `null` while they load.
 * @returns The table.
 */
export function IntegrationsTable({ rows }: { rows: PactIntegration[] | null }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table ctx-table" data-testid="ctx-integrations-table">
        <caption className="sr-only">Integrations, worst verdict first</caption>
        <thead>
          <tr>
            <th scope="col">Integration</th>
            <th scope="col">Kind</th>
            <th scope="col">Latest verdict</th>
            <th scope="col">Deployed together in</th>
            <th scope="col">Verified</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        {rows === null ? (
          <SkeletonTableRows columns={SKELETON_COLUMNS} data-testid="ctx-skeleton" />
        ) : (
          <tbody>
            {rows.map((row) => {
              const verdict = verdictText(row.verdict);
              return (
                <tr key={`${row.consumer}|${row.provider}`} data-testid={`ctx-row-${row.consumer}-${row.provider}`}>
                  <th scope="row" className="ctx-pair-cell">
                    <span className="ctx-pair">
                      <Party slug={row.consumer} name={row.consumer_name} />
                      <ArrowRight className="ctx-pair__arrow" aria-label="calls" />
                      <Party slug={row.provider} name={row.provider_name} />
                    </span>
                    <span className="ppx__mono ppx__muted ctx-pair__versions">
                      consumer {row.consumer_version}
                      {row.provider_version ? ` · provider ${row.provider_version}` : ''}
                    </span>
                  </th>
                  <td>
                    <Badge variant={row.kind === 'bidirectional' ? 'violet' : 'outline'}>
                      {KIND_LABEL[row.kind]}
                    </Badge>
                  </td>
                  <td>
                    <div className="ctx-verdict">
                      <Badge status={verdict.status} dot>
                        {verdict.label}
                      </Badge>
                      {row.pending ? (
                        <Badge variant="outline" title="The provider has not passed this pact yet">
                          Pending
                        </Badge>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    {row.environments.length > 0 ? (
                      <span className="ppx__chips">
                        {row.environments.map((name) => (
                          <Badge key={name} variant="neutral">
                            {name}
                          </Badge>
                        ))}
                      </span>
                    ) : (
                      <span className="ppx__muted">—</span>
                    )}
                  </td>
                  <td className="ppx__when">{row.verified_at ? formatWhen(row.verified_at) : 'never'}</td>
                  <td className="ctx-actions-cell">
                    <RowMenu row={row} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        )}
      </table>
    </div>
  );
}

/**
 * One entry point: a link to its screen, or a button that opens its command.
 *
 * @param props - The entry point, and what opening a command does.
 * @returns The row.
 */
function Way({ way, onCommand }: { way: WayIn; onCommand: (request: CommandRequest) => void }) {
  const body = (
    <>
      <span className="ctx-way__icon" aria-hidden>
        {way.route ? <ChevronRight /> : <Terminal />}
      </span>
      <span className="ctx-way__text">
        <span className="ctx-way__title">{way.title}</span>
        <span className="ctx-way__desc">{way.description}</span>
      </span>
    </>
  );
  if (way.route) {
    return (
      <Link className="ctx-way" href={way.route} data-testid={`ctx-way-${way.id}`}>
        {body}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className="ctx-way"
      data-testid={`ctx-way-${way.id}`}
      onClick={() =>
        onCommand({ title: way.title, description: way.description, command: way.command ?? '' })
      }
    >
      {body}
    </button>
  );
}

/**
 * "Start something", grouped by who is asking: consumer, provider, pipeline owner.
 *
 * @param props - What opening a command does.
 * @returns The groups.
 */
export function WaysIn({ onCommand }: { onCommand: (request: CommandRequest) => void }) {
  return (
    <div className="ctx-ways" data-testid="ctx-ways">
      {WAYS_IN.map((group) => (
        <section key={group.id} className="ctx-ways__group" aria-labelledby={`ctx-ways-${group.id}`}>
          <h3 className="ctx-ways__caption" id={`ctx-ways-${group.id}`}>
            {group.title}
          </h3>
          {group.ways.map((way) => (
            <Way key={way.id} way={way} onCommand={onCommand} />
          ))}
        </section>
      ))}
    </div>
  );
}

/**
 * The first-run checklist (a honey card), shown until one integration is verified.
 *
 * @param props - The steps.
 * @returns The card.
 */
export function FirstRunChecklist({ steps }: { steps: FirstRunStep[] }) {
  const done = steps.filter((step) => step.done).length;
  return (
    <div className="ctx-first-run" data-testid="ctx-first-run">
      <div className="ctx-first-run__head">
        <h3 className="ctx-first-run__title">Your first contract, in four steps</h3>
        <span className="ppx__meta">
          {done} of {steps.length} done
        </span>
      </div>
      <progress className="ctx-first-run__progress" max={steps.length} value={done} aria-label="Steps done" />
      <ul className="ctx-first-run__steps">
        {steps.map((step) => (
          <li key={step.id} className="ctx-first-run__step" data-done={step.done ? 'true' : 'false'}>
            {step.done ? (
              <CircleCheck className="ctx-first-run__glyph ctx-first-run__glyph--done" aria-label="Done" />
            ) : (
              <Circle className="ctx-first-run__glyph" aria-label="To do" />
            )}
            {step.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
