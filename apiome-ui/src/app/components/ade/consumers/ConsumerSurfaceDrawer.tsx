'use client';

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/app/components/ui/Drawer';

import {
  contractProvenanceLine,
  contractSummaryLine,
  groupUnresolved,
  operationLabel,
  type ConsumerSummary,
} from './consumersModel';

/**
 * One consumer's declared surface, in full — CTG-4.1 (#4479).
 *
 * The list row previews three operations because a cell cannot hold forty. This is where the
 * rest lives: every declared operation, the fields under it, and — separately — everything the
 * contract could not resolve.
 *
 * ### Unresolved entries are shown first, not last
 *
 * They are the part of a contract that has *changed meaning* since it was declared: an
 * operation that no longer exists, a field that has been removed. Putting them under a
 * forty-operation list would hide the only part of the page that needs acting on.
 */

/** Props for {@link ConsumerSurfaceDrawer}. */
export interface ConsumerSurfaceDrawerProps {
  /** Whether the drawer is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** The row being inspected; `null` while closed. */
  summary: ConsumerSummary | null;
}

/**
 * The declared-surface drawer.
 *
 * @param props See {@link ConsumerSurfaceDrawerProps}.
 * @returns The drawer.
 */
export default function ConsumerSurfaceDrawer({
  open,
  onOpenChange,
  summary,
}: ConsumerSurfaceDrawerProps) {
  const contract = summary?.contract ?? null;
  const groups = groupUnresolved(contract?.unresolved ?? []);

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent size="lg">
        <DrawerHeader>
          <DrawerTitle>{summary?.consumer.name ?? 'Consumer'}</DrawerTitle>
          <DrawerDescription>
            {contract ? contractProvenanceLine(contract) : 'This consumer has declared nothing yet.'}
          </DrawerDescription>
        </DrawerHeader>

        <DrawerBody>
          {!contract && (
            <Alert variant="neutral">
              Import a Pact file or pick operations to declare what this consumer uses. Until it
              does, a change to this project cannot be judged against it.
            </Alert>
          )}

          {contract && (
            <>
              <p className="cns-drawer__summary">{contractSummaryLine(contract)}</p>

              {groups.length > 0 && (
                <section className="cns-drawer__section" data-testid="drawer-unresolved">
                  <h3 className="cns-drawer__heading">Could not be resolved</h3>
                  {groups.map((group) => (
                    <div className="cns-drawer__group" key={group.reason}>
                      <h4 className="cns-drawer__grouphead">
                        {group.label}
                        <span className="cns-drawer__count">{group.entries.length}</span>
                      </h4>
                      <ul className="cns-drawer__list">
                        {group.entries.map((entry, index) => (
                          <li className="cns-drawer__item" key={`${group.reason}-${index}`}>
                            <code className="mono">{entry.message}</code>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </section>
              )}

              <section className="cns-drawer__section">
                <h3 className="cns-drawer__heading">Declared operations</h3>
                {contract.surface.operations.length === 0 ? (
                  <p className="cns-drawer__empty">
                    No operation of this project resolved from the declaration.
                  </p>
                ) : (
                  <ul className="cns-drawer__ops">
                    {contract.surface.operations.map((operation) => (
                      <li className="cns-drawer__op" key={operation.pointer}>
                        <div className="cns-drawer__opline">
                          <code className="mono">{operationLabel(operation)}</code>
                          <Badge variant="neutral">
                            {operation.fields.length === 1
                              ? '1 field'
                              : `${operation.fields.length} fields`}
                          </Badge>
                        </div>
                        {operation.summary && (
                          <p className="cns-drawer__opsummary">{operation.summary}</p>
                        )}
                        {operation.fields.length > 0 && (
                          <ul className="cns-drawer__fields">
                            {operation.fields.map((field) => (
                              <li className="cns-drawer__field" key={field.pointer}>
                                <code className="mono">{field.path || '(body)'}</code>
                                <span className="cns-drawer__where">
                                  {field.location}
                                  {field.status ? ` · ${field.status}` : ''}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
