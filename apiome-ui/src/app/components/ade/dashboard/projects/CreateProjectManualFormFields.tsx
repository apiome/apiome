'use client';

import { ExternalLink, Layers } from 'lucide-react';
import { useMemo } from 'react';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { Textarea } from '@/app/components/ui/Textarea';
import {
  PROJECT_DOMAIN_CATEGORIES,
  PROJECT_DOMAIN_CATEGORY_NONE,
  getProjectDomainCategory,
} from '@/app/utils/project-domain-categories';
import {
  PROJECT_START_TEMPLATES,
  applyProjectStartTemplate,
  getProjectStartTemplate,
  BLANK_TEMPLATE_ID,
} from '@/app/utils/project-templates';
import { filterSlugInput, generateSlug } from '@/app/utils/slug';
import { SPDX_LICENSES, getLicenseUrl, type SPDXLicense } from '@/app/utils/spdx-licenses';

export type CreateProjectManualFormModel = {
  projectName: string;
  projectSlug: string;
  projectDescription: string;
  selectedStartTemplateId: string;
  projectDomainCategoryId: string;
  metadataSummary: string;
  metadataTermsOfService: string;
  metadataContactName: string;
  metadataContactUrl: string;
  metadataContactEmail: string;
  metadataLicenseName: string;
  metadataLicenseIdentifier: string;
  metadataLicenseUrl: string;
};

export const EMPTY_CREATE_PROJECT_MANUAL_FORM: CreateProjectManualFormModel = {
  projectName: '',
  projectSlug: '',
  projectDescription: '',
  selectedStartTemplateId: BLANK_TEMPLATE_ID,
  projectDomainCategoryId: PROJECT_DOMAIN_CATEGORY_NONE,
  metadataSummary: '',
  metadataTermsOfService: '',
  metadataContactName: '',
  metadataContactUrl: '',
  metadataContactEmail: '',
  metadataLicenseName: '',
  metadataLicenseIdentifier: '',
  metadataLicenseUrl: '',
};

export function CreateProjectManualFormFields({
  model,
  onChange,
  disabled = false,
  fieldIdPrefix,
  errorMessage,
  showStartTemplatePicker = true,
}: {
  model: CreateProjectManualFormModel;
  onChange: (patch: Partial<CreateProjectManualFormModel>) => void;
  disabled?: boolean;
  /** Prefix for element ids (must be unique per mount). */
  fieldIdPrefix: string;
  errorMessage?: string | null;
  /** Hide the starting-template preset row (e.g. repository import uses spec copy instead). */
  showStartTemplatePicker?: boolean;
}) {
  const selectedStartTemplateHint = showStartTemplatePicker
    ? getProjectStartTemplate(model.selectedStartTemplateId)?.hint
    : undefined;
  const selectedProjectDomainCategory = useMemo(
    () => getProjectDomainCategory(model.projectDomainCategoryId),
    [model.projectDomainCategoryId]
  );

  const applyLicenseByIdentifier = (identifier: string) => {
    const license = SPDX_LICENSES.find((l: SPDXLicense) => l.identifier === identifier);
    if (license) {
      const url = getLicenseUrl(license.identifier);
      onChange({
        metadataLicenseIdentifier: license.identifier,
        metadataLicenseName: license.name,
        metadataLicenseUrl: url ?? model.metadataLicenseUrl,
      });
    }
  };

  return (
    <>
      {errorMessage ? (
        <Alert variant="error" className="mb-4">
          {errorMessage}
        </Alert>
      ) : null}
      {showStartTemplatePicker ? (
        <div className="mb-6 rounded-xl border border-gray-200 bg-gray-50/80 p-4 dark:border-gray-700 dark:bg-gray-900/40">
          <div className="flex items-start gap-3">
            <div className="shrink-0 rounded-lg border border-gray-200 bg-white p-2 dark:border-gray-600 dark:bg-gray-800">
              <Layers className="h-5 w-5 text-indigo-600 dark:text-indigo-400" aria-hidden />
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              <Label
                htmlFor={`${fieldIdPrefix}projectStartTemplate`}
                className="text-sm font-semibold text-gray-900 dark:text-gray-100"
              >
                Starting template
              </Label>
              <p className="text-xs text-gray-600 dark:text-gray-400">
                Choose a preset for OpenAPI-oriented fields (summary, contact, license, terms). You can edit everything
                before continuing.
              </p>
              <Select
                value={model.selectedStartTemplateId}
                onValueChange={(id) => {
                  const { metadata, suggestedDescription } = applyProjectStartTemplate(id);
                  onChange({
                    selectedStartTemplateId: id,
                    projectDescription: suggestedDescription,
                    metadataSummary: metadata.summary ?? '',
                    metadataTermsOfService: metadata.termsOfService ?? '',
                    metadataContactName: metadata.contact?.name ?? '',
                    metadataContactUrl: metadata.contact?.url ?? '',
                    metadataContactEmail: metadata.contact?.email ?? '',
                    metadataLicenseName: metadata.license?.name ?? '',
                    metadataLicenseIdentifier: metadata.license?.identifier ?? '',
                    metadataLicenseUrl: metadata.license?.url ?? '',
                    projectDomainCategoryId: metadata.domainCategory ?? PROJECT_DOMAIN_CATEGORY_NONE,
                  });
                }}
                disabled={disabled}
              >
                <SelectTrigger id={`${fieldIdPrefix}projectStartTemplate`} className="max-w-xl">
                  <SelectValue placeholder="Select a template" />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {PROJECT_START_TEMPLATES.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedStartTemplateHint ? (
                <p className="max-w-3xl text-xs text-gray-500 dark:text-gray-500">{selectedStartTemplateHint}</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-0 divide-x divide-gray-200 lg:grid-cols-2 dark:divide-gray-700">
        <div className="flex flex-col pr-4 lg:pr-6">
          <h3 className="mb-4 text-sm font-semibold text-gray-900 dark:text-gray-100">Basic Information</h3>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`${fieldIdPrefix}projectName`}>Project Name *</Label>
              <Input
                id={`${fieldIdPrefix}projectName`}
                value={model.projectName}
                onChange={(e) => {
                  const v = e.target.value;
                  const nextSlug =
                    !model.projectSlug || model.projectSlug === generateSlug(model.projectName)
                      ? generateSlug(v)
                      : model.projectSlug;
                  onChange({ projectName: v, projectSlug: nextSlug });
                }}
                disabled={disabled}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${fieldIdPrefix}projectSlug`}>Slug *</Label>
              <Input
                id={`${fieldIdPrefix}projectSlug`}
                value={model.projectSlug}
                onChange={(e) => onChange({ projectSlug: filterSlugInput(e.target.value) })}
                disabled={disabled}
                className="font-mono"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400">
                URL-friendly identifier (lowercase letters, numbers, and dashes only)
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${fieldIdPrefix}projectDescription`}>Description</Label>
              <Textarea
                id={`${fieldIdPrefix}projectDescription`}
                value={model.projectDescription}
                onChange={(e) => onChange({ projectDescription: e.target.value })}
                disabled={disabled}
                rows={4}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${fieldIdPrefix}projectDomainCategory`}>Domain category</Label>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Optional. Classifies the kind of entities and schemas this project models.
              </p>
              <Select
                value={model.projectDomainCategoryId}
                onValueChange={(id) => onChange({ projectDomainCategoryId: id })}
                disabled={disabled}
              >
                <SelectTrigger id={`${fieldIdPrefix}projectDomainCategory`} className="max-w-xl">
                  <SelectValue placeholder="None" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PROJECT_DOMAIN_CATEGORY_NONE}>None</SelectItem>
                  {PROJECT_DOMAIN_CATEGORIES.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedProjectDomainCategory?.hint ? (
                <p className="max-w-xl text-xs text-gray-500 dark:text-gray-500">{selectedProjectDomainCategory.hint}</p>
              ) : null}
            </div>
          </div>
        </div>
        <div className="flex flex-col pl-4 pt-4 lg:pl-6 lg:pt-0">
          <h3 className="mb-4 text-sm font-semibold text-gray-900 dark:text-gray-100">API Metadata</h3>
          <div className="space-y-6">
            <div className="space-y-4">
              <h4 className="text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">OpenAPI</h4>
              <div className="space-y-2">
                <Label htmlFor={`${fieldIdPrefix}createSummary`}>API Summary</Label>
                <Input
                  id={`${fieldIdPrefix}createSummary`}
                  value={model.metadataSummary}
                  onChange={(e) => onChange({ metadataSummary: e.target.value })}
                  disabled={disabled}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${fieldIdPrefix}createTermsOfService`}>Terms of Service URL</Label>
                <div className="flex gap-2">
                  <Input
                    id={`${fieldIdPrefix}createTermsOfService`}
                    type="url"
                    value={model.metadataTermsOfService}
                    onChange={(e) => onChange({ metadataTermsOfService: e.target.value })}
                    disabled={disabled}
                    placeholder="https://example.com/terms"
                    className="min-w-0 flex-1"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    disabled={
                      disabled ||
                      !model.metadataTermsOfService.trim() ||
                      (!model.metadataTermsOfService.trim().startsWith('http://') &&
                        !model.metadataTermsOfService.trim().startsWith('https://'))
                    }
                    onClick={() => window.open(model.metadataTermsOfService.trim(), '_blank', 'noopener,noreferrer')}
                    title="Open URL in new window"
                    className="shrink-0"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
            <div className="space-y-4">
              <h4 className="text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">Contact</h4>
              <div className="grid grid-cols-1 gap-3">
                <div className="space-y-2">
                  <Label htmlFor={`${fieldIdPrefix}createContactName`}>Name</Label>
                  <Input
                    id={`${fieldIdPrefix}createContactName`}
                    value={model.metadataContactName}
                    onChange={(e) => onChange({ metadataContactName: e.target.value })}
                    disabled={disabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`${fieldIdPrefix}createContactUrl`}>URL</Label>
                  <div className="flex gap-2">
                    <Input
                      id={`${fieldIdPrefix}createContactUrl`}
                      type="url"
                      value={model.metadataContactUrl}
                      onChange={(e) => onChange({ metadataContactUrl: e.target.value })}
                      disabled={disabled}
                      className="min-w-0 flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      disabled={
                        disabled ||
                        !model.metadataContactUrl.trim() ||
                        (!model.metadataContactUrl.trim().startsWith('http://') &&
                          !model.metadataContactUrl.trim().startsWith('https://'))
                      }
                      onClick={() => window.open(model.metadataContactUrl.trim(), '_blank', 'noopener,noreferrer')}
                      title="Open URL in new window"
                      className="shrink-0"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`${fieldIdPrefix}createContactEmail`}>Email</Label>
                  <Input
                    id={`${fieldIdPrefix}createContactEmail`}
                    type="email"
                    value={model.metadataContactEmail}
                    onChange={(e) => onChange({ metadataContactEmail: e.target.value })}
                    disabled={disabled}
                  />
                </div>
              </div>
            </div>
            <div className="space-y-4">
              <h4 className="text-xs font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">License</h4>
              <div className="space-y-2">
                <Label htmlFor={`${fieldIdPrefix}createLicenseIdentifier`}>License (SPDX)</Label>
                <Select value={model.metadataLicenseIdentifier} onValueChange={applyLicenseByIdentifier}>
                  <SelectTrigger id={`${fieldIdPrefix}createLicenseIdentifier`}>
                    <SelectValue placeholder="Select a license..." />
                  </SelectTrigger>
                  <SelectContent className="max-h-60">
                    {SPDX_LICENSES.slice(0, 50).map((license: SPDXLicense) => (
                      <SelectItem key={license.identifier} value={license.identifier}>
                        {license.name} ({license.identifier})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-1 gap-3">
                <div className="space-y-2">
                  <Label htmlFor={`${fieldIdPrefix}createLicenseName`}>License Name</Label>
                  <Input
                    id={`${fieldIdPrefix}createLicenseName`}
                    value={model.metadataLicenseName}
                    onChange={(e) => onChange({ metadataLicenseName: e.target.value })}
                    disabled={disabled}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`${fieldIdPrefix}createLicenseUrl`}>License URL</Label>
                  <div className="flex gap-2">
                    <Input
                      id={`${fieldIdPrefix}createLicenseUrl`}
                      type="url"
                      value={model.metadataLicenseUrl}
                      onChange={(e) => onChange({ metadataLicenseUrl: e.target.value })}
                      disabled={disabled}
                      className="min-w-0 flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      disabled={
                        disabled ||
                        !model.metadataLicenseUrl.trim() ||
                        (!model.metadataLicenseUrl.trim().startsWith('http://') &&
                          !model.metadataLicenseUrl.trim().startsWith('https://'))
                      }
                      onClick={() => window.open(model.metadataLicenseUrl.trim(), '_blank', 'noopener,noreferrer')}
                      title="Open URL in new window"
                      className="shrink-0"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
