'use client';

/**
 * **Export a contract** — PFX-8.18 (#7315), `/ade/dashboard/pacts/export`
 * (docs/mockups/contracts/export.html).
 *
 * Three kinds as option cards, one visible at a time: **A pact from a project**
 * (`apiome pact export-consumer-contract`), **A Postman collection** (`apiome pact export-postman`)
 * and **A pact file** (any published pact, or every pact for a provider). Each kind has one primary
 * action and its own **The same, from anywhere** block; the header carries no primary
 * (DESIGN.md §5.3), only a link to Export studio for specifications. Problems and refusals share
 * one status line (§5.4). `?kind=`, `?provider=`, `?consumer=`, `?version=` and `?project=` pre-fill
 * the page — a pact's page, a pacticipant and Export studio link here — and anything else is
 * reported. Every kind needs only `pacts:view` (REST enforces it); **Review and publish** shows with
 * `pacts:create`.
 */

import * as React from 'react';
import Link from 'next/link';
import { FileJson2, Mailbox, PackageOpen, WandSparkles } from 'lucide-react';
import { Alert, Button } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { CONTRACTS_CRUMBS } from '@lib/pact-overview';
import {
  EMPTY_DERIVE_EXPORT,
  EMPTY_PACT_FILE,
  EMPTY_POSTMAN,
  EXPORT_KIND_CARDS,
  EXPORT_KINDS,
  type DeriveExportDraft,
  type ExportKind,
  type ExportPrefill,
  type PactFileDraft,
  type PostmanDraft,
} from '@lib/pact-export';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { fetchProviders } from '../pactVerifyRun/verifyRunApi';
import { DerivePanel } from './DerivePanel';
import { PactFilePanel } from './PactFilePanel';
import { PostmanPanel } from './PostmanPanel';

/** Export studio, for exporting a specification rather than a contract. */
export const EXPORT_STUDIO_ROUTE = '/ade/dashboard/export/studio';

/** Each kind's glyph. */
const KIND_GLYPHS: Record<ExportKind, React.ComponentType<{ 'aria-hidden'?: boolean; className?: string }>> = {
  pact: WandSparkles,
  postman: Mailbox,
  file: FileJson2,
};

/** The page's one status line. */
type Status = { tone: 'warn' | 'danger'; text: string } | null;

/** Props of {@link ExportPactClient}. */
export interface ExportPactClientProps {
  prefill: ExportPrefill;
}

export function ExportPactClient({ prefill }: ExportPactClientProps) {
  const permissions = useMyPermissions();
  const canPublish = permissions.status === 'ready' && permissions.can('pacts:create');
  const [kind, setKind] = React.useState<ExportKind>(prefill.kind);
  const [status, setStatus] = React.useState<Status>(prefill.problems.length ? { tone: 'warn', text: prefill.problems.join(' ') } : null);
  const [pacticipants, setPacticipants] = React.useState<string[]>([]);
  const [derive, setDerive] = React.useState<DeriveExportDraft>({ ...EMPTY_DERIVE_EXPORT, project: prefill.project, provider: prefill.provider });
  const versionChoice = prefill.version ? { choice: 'version' as const, choiceValue: prefill.version } : {};
  const [postman, setPostman] = React.useState<PostmanDraft>({ ...EMPTY_POSTMAN, provider: prefill.provider, consumer: prefill.consumer, ...versionChoice });
  const [file, setFile] = React.useState<PactFileDraft>({ ...EMPTY_PACT_FILE, provider: prefill.provider, consumer: prefill.consumer, ...versionChoice });

  // The provider and consumer suggestions: the first page of pacticipants, read once.
  React.useEffect(() => {
    void fetchProviders().then((answer) => {
      if (Array.isArray(answer)) setPacticipants(answer.map((row) => row.name));
    });
  }, []);

  const choose = (next: ExportKind) => {
    setKind(next);
    setStatus(null);
  };

  return (
    <Page>
      <PageHeader
        title="Export a contract"
        breadcrumb={[...CONTRACTS_CRUMBS, { label: 'Export' }]}
        description="Take a contract out as a pact, a Postman collection or a file."
        tabs={<ContractsTabs active="overview" />}
        actions={
          <Button variant="outline" asChild>
            <Link href={EXPORT_STUDIO_ROUTE}>
              <PackageOpen aria-hidden />
              Export studio
            </Link>
          </Button>
        }
      />
      <PageBody>
        <div className="ppub" data-testid="pact-export">
          {status ? (
            <Alert variant={status.tone} data-testid="pexp-status">
              {status.text}
            </Alert>
          ) : null}
          <div className="pexp-kinds" role="radiogroup" aria-label="What to export" data-testid="pexp-kinds">
            {EXPORT_KINDS.map((id) => {
              const Glyph = KIND_GLYPHS[id];
              const inputId = `pexp-kind-${id}`;
              return (
                <label key={id} htmlFor={inputId} className={kind === id ? 'ppc-option is-active' : 'ppc-option'} data-testid={inputId}>
                  <input id={inputId} type="radio" name="pexp-kind" className="ppc-option__radio" checked={kind === id} onChange={() => choose(id)} aria-describedby={`${inputId}-desc`} />
                  <Glyph aria-hidden className="pexp-kind__glyph" />
                  <span className="ppc-option__body">
                    <span className="ppc-option__title">{EXPORT_KIND_CARDS[id].title}</span>
                    <span className="ppc-option__desc" id={`${inputId}-desc`}>
                      {EXPORT_KIND_CARDS[id].description}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
          {kind === 'pact' ? <DerivePanel draft={derive} onDraft={setDerive} canPublish={canPublish} onStatus={setStatus} /> : null}
          {kind === 'postman' ? <PostmanPanel draft={postman} onDraft={setPostman} pacticipants={pacticipants} onStatus={setStatus} /> : null}
          {kind === 'file' ? <PactFilePanel draft={file} onDraft={setFile} pacticipants={pacticipants} onStatus={setStatus} /> : null}
        </div>
      </PageBody>
    </Page>
  );
}
