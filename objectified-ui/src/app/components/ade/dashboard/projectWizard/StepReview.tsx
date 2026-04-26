'use client';

import { CheckCircle2, ClipboardCheck, FileText, Tag, User } from 'lucide-react';
import {
  PROJECT_DOMAIN_CATEGORIES,
  PROJECT_DOMAIN_CATEGORY_NONE,
} from '../../../../utils/project-domain-categories';
import { getProjectStartTemplate } from '../../../../utils/project-templates';
import type { WizardState } from './wizardTypes';

export interface StepReviewProps {
  state: WizardState;
  /** Validation errors collected by the dialog. Shown above the summary so
   *  the user can jump back to the relevant step before submitting. */
  warnings: string[];
}

function findDomainLabel(id: string): string {
  if (!id || id === PROJECT_DOMAIN_CATEGORY_NONE) return 'None';
  return PROJECT_DOMAIN_CATEGORIES.find((c) => c.id === id)?.label ?? 'None';
}

export function StepReview({ state, warnings }: StepReviewProps) {
  const template = getProjectStartTemplate(state.template.templateId);
  const meta = state.template.metadata;

  return (
    <div className="space-y-5">
      <header className="flex items-start gap-3">
        <div className="p-2 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300">
          <ClipboardCheck className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">Review &amp; create</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            One more look before we create the project. You can edit anything later in
            Settings.
          </p>
        </div>
      </header>

      {warnings.length > 0 ? (
        <div className="rounded-md border border-amber-200 dark:border-amber-700/40 bg-amber-50/60 dark:bg-amber-900/10 px-4 py-3 text-xs text-amber-800 dark:text-amber-200 space-y-1">
          {warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      ) : null}

      <SummarySection
        Icon={Tag}
        label="Basics"
        items={[
          { label: 'Name', value: state.basics.name || '—' },
          { label: 'Slug', value: state.basics.slug || '—', mono: true },
          { label: 'Domain', value: findDomainLabel(state.basics.domainCategory) },
          {
            label: 'Description',
            value: state.basics.description || (
              <span className="italic text-gray-400">none</span>
            ),
          },
        ]}
      />

      <SummarySection
        Icon={FileText}
        label="Template & OpenAPI metadata"
        items={[
          { label: 'Template', value: template?.label ?? state.template.templateId },
          {
            label: 'Summary',
            value: meta.summary || <span className="italic text-gray-400">none</span>,
          },
          {
            label: 'License',
            value:
              meta.license?.name || meta.license?.identifier || (
                <span className="italic text-gray-400">none</span>
              ),
          },
          {
            label: 'Terms of service',
            value: meta.termsOfService ? (
              <span className="font-mono text-xs">{meta.termsOfService}</span>
            ) : (
              <span className="italic text-gray-400">none</span>
            ),
          },
        ]}
      />

      <SummarySection
        Icon={User}
        label="Contact"
        items={[
          {
            label: 'Name',
            value: meta.contact?.name || <span className="italic text-gray-400">none</span>,
          },
          {
            label: 'Email',
            value: meta.contact?.email ? (
              <span className="font-mono text-xs">{meta.contact.email}</span>
            ) : (
              <span className="italic text-gray-400">none</span>
            ),
          },
          {
            label: 'URL',
            value: meta.contact?.url ? (
              <span className="font-mono text-xs">{meta.contact.url}</span>
            ) : (
              <span className="italic text-gray-400">none</span>
            ),
          },
        ]}
      />

      {warnings.length === 0 ? (
        <p className="inline-flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="w-4 h-4" /> Ready to create.
        </p>
      ) : null}
    </div>
  );
}

interface SummaryItem {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}

function SummarySection({
  Icon,
  label,
  items,
}: {
  Icon: typeof Tag;
  label: string;
  items: SummaryItem[];
}) {
  return (
    <section className="rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center gap-2">
        <Icon className="w-4 h-4 text-indigo-500" />
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-300">
          {label}
        </p>
      </div>
      <dl className="divide-y divide-gray-100 dark:divide-gray-700/60 text-sm">
        {items.map((item) => (
          <div key={item.label} className="px-4 py-2.5 grid grid-cols-3 gap-3">
            <dt className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
              {item.label}
            </dt>
            <dd
              className={`col-span-2 break-words ${item.mono ? 'font-mono text-xs' : ''}`}
            >
              {item.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
