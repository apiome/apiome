'use client';

import { useMemo } from 'react';
import { LayoutTemplate, ScrollText } from 'lucide-react';
import { Input } from '../../../ui/Input';
import { Label } from '../../../ui/Label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../ui/Select';
import {
  PROJECT_START_TEMPLATES,
  applyProjectStartTemplate,
} from '../../../../utils/project-templates';
import { SPDX_LICENSES, getLicenseUrl } from '../../../../utils/spdx-licenses';
import type { WizardTemplate } from './wizardTypes';

export interface StepTemplateProps {
  value: WizardTemplate;
  onChange: (next: WizardTemplate) => void;
  /** Suggested description from the chosen template. The wizard uses it to
   *  pre-fill the description field on the basics step if the user did not
   *  enter one themselves. Returned alongside metadata so the parent can
   *  decide what to do. */
  onTemplatePicked?: (suggestedDescription: string) => void;
}

const LICENSE_CUSTOM = '__custom__';
const LICENSE_NONE = '__none__';

export function StepTemplate({ value, onChange, onTemplatePicked }: StepTemplateProps) {
  function pickTemplate(id: string) {
    const applied = applyProjectStartTemplate(id);
    onChange({ templateId: id, metadata: applied.metadata });
    onTemplatePicked?.(applied.suggestedDescription);
  }

  function updateMeta(mutator: (meta: WizardTemplate['metadata']) => WizardTemplate['metadata']) {
    onChange({ ...value, metadata: mutator({ ...value.metadata }) });
  }

  function selectLicense(licenseValue: string) {
    if (licenseValue === LICENSE_NONE) {
      updateMeta((meta) => {
        delete meta.license;
        return meta;
      });
      return;
    }
    if (licenseValue === LICENSE_CUSTOM) {
      updateMeta((meta) => {
        meta.license = { ...(meta.license ?? {}), identifier: undefined };
        return meta;
      });
      return;
    }
    const license = SPDX_LICENSES.find((l) => l.identifier === licenseValue);
    if (!license) return;
    updateMeta((meta) => {
      meta.license = {
        identifier: license.identifier,
        name: license.name,
        url: getLicenseUrl(license.identifier) ?? undefined,
      };
      return meta;
    });
  }

  const license = value.metadata.license;
  const contact = value.metadata.contact;
  const licenseSelectValue = useMemo(() => {
    if (!license) return LICENSE_NONE;
    if (license.identifier && SPDX_LICENSES.some((l) => l.identifier === license.identifier)) {
      return license.identifier;
    }
    return LICENSE_CUSTOM;
  }, [license]);

  return (
    <div className="space-y-5">
      <header className="flex items-start gap-3">
        <div className="p-2 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300">
          <LayoutTemplate className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">Pick a starter template</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Templates pre-fill OpenAPI metadata (summary, license, contact). You can edit
            everything in the next step or in Settings later.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {PROJECT_START_TEMPLATES.map((template) => {
          const isSelected = template.id === value.templateId;
          return (
            <button
              key={template.id}
              type="button"
              onClick={() => pickTemplate(template.id)}
              className={`text-left rounded-lg border p-4 transition-colors ${
                isSelected
                  ? 'border-indigo-500 bg-indigo-50/60 dark:bg-indigo-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700'
              }`}
            >
              <p className="text-sm font-semibold">{template.label}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 leading-relaxed">
                {template.hint}
              </p>
              {isSelected ? (
                <span className="inline-block mt-3 text-[9px] uppercase font-semibold px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300">
                  Selected
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <section className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 space-y-4">
        <div className="flex items-center gap-2">
          <ScrollText className="w-4 h-4 text-indigo-500" />
          <p className="text-sm font-semibold">OpenAPI metadata</p>
          <span className="text-[10px] font-mono text-gray-500">
            optional — you can fill these later
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-4">
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="wiz-summary">Summary</Label>
            <Input
              id="wiz-summary"
              value={value.metadata.summary ?? ''}
              onChange={(e) =>
                updateMeta((meta) => {
                  if (e.target.value) meta.summary = e.target.value;
                  else delete meta.summary;
                  return meta;
                })
              }
              placeholder="Public REST API — invoices, taxes, settlements."
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="wiz-contact-name">Contact name</Label>
            <Input
              id="wiz-contact-name"
              value={contact?.name ?? ''}
              onChange={(e) =>
                updateMeta((meta) => {
                  meta.contact = { ...(meta.contact ?? {}), name: e.target.value || undefined };
                  return meta;
                })
              }
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wiz-contact-email">Contact email</Label>
            <Input
              id="wiz-contact-email"
              type="email"
              className="font-mono"
              value={contact?.email ?? ''}
              onChange={(e) =>
                updateMeta((meta) => {
                  meta.contact = { ...(meta.contact ?? {}), email: e.target.value || undefined };
                  return meta;
                })
              }
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="wiz-license">License</Label>
            <Select value={licenseSelectValue} onValueChange={selectLicense}>
              <SelectTrigger id="wiz-license">
                <SelectValue placeholder="Select a license" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={LICENSE_NONE}>None</SelectItem>
                {SPDX_LICENSES.map((l) => (
                  <SelectItem key={l.identifier} value={l.identifier}>
                    {l.name}
                  </SelectItem>
                ))}
                <SelectItem value={LICENSE_CUSTOM}>Custom…</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="wiz-tos">Terms of service</Label>
            <Input
              id="wiz-tos"
              type="url"
              className="font-mono"
              value={value.metadata.termsOfService ?? ''}
              onChange={(e) =>
                updateMeta((meta) => {
                  if (e.target.value) meta.termsOfService = e.target.value;
                  else delete meta.termsOfService;
                  return meta;
                })
              }
            />
          </div>
        </div>
      </section>
    </div>
  );
}
