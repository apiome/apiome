'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertOctagon, FileText, Settings2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';
import { Button } from '../../../ui/Button';
import { Input } from '../../../ui/Input';
import { Label } from '../../../ui/Label';
import { Textarea } from '../../../ui/Textarea';
import { Alert } from '../../../ui/Alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../ui/Select';
import { useDialog } from '../../../providers/DialogProvider';
import {
  deleteProject,
  permanentDeleteProject,
  updateProject,
} from '../../../../../../lib/db/helper';
import { filterSlugInput } from '../../../../utils/slug';
import {
  PROJECT_DOMAIN_CATEGORIES,
  PROJECT_DOMAIN_CATEGORY_NONE,
} from '../../../../utils/project-domain-categories';
import { SPDX_LICENSES, getLicenseUrl } from '../../../../utils/spdx-licenses';
import type { Project, ProjectMetadata } from '../projectTypes';

export interface SettingsTabProps {
  project: Project;
  /** Notifies the page after a successful save (so it can refetch). */
  onSaved?: (updated: Partial<Project>) => void;
  /** Notifies the page after the project was soft- or hard-deleted. */
  onDeleted?: (kind: 'soft' | 'hard') => void;
}

interface FormState {
  name: string;
  slug: string;
  description: string;
  enabled: boolean;
  domainCategory: string;
  summary: string;
  termsOfService: string;
  contactName: string;
  contactEmail: string;
  contactUrl: string;
  licenseIdentifier: string;
  licenseName: string;
  licenseUrl: string;
}

const LICENSE_CUSTOM = '__custom__';
const LICENSE_NONE = '__none__';

function fromProject(project: Project): FormState {
  const meta = project.metadata ?? {};
  return {
    name: project.name ?? '',
    slug: project.slug ?? '',
    description: project.description ?? '',
    enabled: project.enabled,
    domainCategory: meta.domainCategory ?? PROJECT_DOMAIN_CATEGORY_NONE,
    summary: meta.summary ?? '',
    termsOfService: meta.termsOfService ?? '',
    contactName: meta.contact?.name ?? '',
    contactEmail: meta.contact?.email ?? '',
    contactUrl: meta.contact?.url ?? '',
    licenseIdentifier: meta.license?.identifier ?? '',
    licenseName: meta.license?.name ?? '',
    licenseUrl: meta.license?.url ?? '',
  };
}

function buildMetadata(form: FormState): ProjectMetadata {
  const metadata: ProjectMetadata = {};
  if (form.summary.trim()) metadata.summary = form.summary.trim();
  if (form.termsOfService.trim()) metadata.termsOfService = form.termsOfService.trim();

  if (form.contactName.trim() || form.contactEmail.trim() || form.contactUrl.trim()) {
    metadata.contact = {};
    if (form.contactName.trim()) metadata.contact.name = form.contactName.trim();
    if (form.contactEmail.trim()) metadata.contact.email = form.contactEmail.trim();
    if (form.contactUrl.trim()) metadata.contact.url = form.contactUrl.trim();
  }

  const wantsLicense =
    form.licenseIdentifier.trim() ||
    form.licenseName.trim() ||
    form.licenseUrl.trim();
  if (wantsLicense) {
    metadata.license = {};
    if (form.licenseIdentifier.trim()) {
      metadata.license.identifier = form.licenseIdentifier.trim();
    }
    if (form.licenseName.trim()) metadata.license.name = form.licenseName.trim();
    if (form.licenseUrl.trim()) metadata.license.url = form.licenseUrl.trim();
  }

  if (form.domainCategory && form.domainCategory !== PROJECT_DOMAIN_CATEGORY_NONE) {
    metadata.domainCategory = form.domainCategory;
  }

  return metadata;
}

function isDirty(form: FormState, baseline: FormState): boolean {
  return (Object.keys(form) as Array<keyof FormState>).some(
    (key) => form[key] !== baseline[key]
  );
}

export function SettingsTab({ project, onSaved, onDeleted }: SettingsTabProps) {
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const baseline = useMemo(() => fromProject(project), [project]);
  const [form, setForm] = useState<FormState>(baseline);
  const [errorMessage, setErrorMessage] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    setForm(baseline);
    setErrorMessage('');
  }, [baseline]);

  const dirty = useMemo(() => isDirty(form, baseline), [form, baseline]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function selectLicense(value: string) {
    if (value === LICENSE_NONE) {
      update('licenseIdentifier', '');
      update('licenseName', '');
      update('licenseUrl', '');
      return;
    }
    if (value === LICENSE_CUSTOM) {
      update('licenseIdentifier', '');
      update('licenseName', form.licenseName || '');
      update('licenseUrl', form.licenseUrl || '');
      return;
    }
    const license = SPDX_LICENSES.find((l) => l.identifier === value);
    if (!license) return;
    update('licenseIdentifier', license.identifier);
    update('licenseName', license.name);
    update('licenseUrl', getLicenseUrl(license.identifier) ?? '');
  }

  const licenseSelectValue = form.licenseIdentifier
    ? SPDX_LICENSES.some((l) => l.identifier === form.licenseIdentifier)
      ? form.licenseIdentifier
      : LICENSE_CUSTOM
    : form.licenseName
      ? LICENSE_CUSTOM
      : LICENSE_NONE;

  async function handleSave() {
    if (!form.name.trim()) {
      setErrorMessage('Project name is required');
      return;
    }
    if (!form.slug.trim()) {
      setErrorMessage('Project slug is required');
      return;
    }
    setIsSaving(true);
    setErrorMessage('');
    try {
      const result = await updateProject(
        project.id,
        form.name.trim(),
        form.description.trim(),
        form.slug.trim(),
        form.enabled,
        buildMetadata(form)
      );
      const response = JSON.parse(result);
      if (!response.success) {
        setErrorMessage(response.error || 'Failed to save changes');
        return;
      }
      toast.success('Project settings saved');
      onSaved?.({
        name: form.name.trim(),
        slug: form.slug.trim(),
        description: form.description.trim(),
        enabled: form.enabled,
        metadata: buildMetadata(form),
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'An error occurred');
    } finally {
      setIsSaving(false);
    }
  }

  async function handleToggleEnabled() {
    const next = !form.enabled;
    setIsSaving(true);
    setErrorMessage('');
    try {
      const result = await updateProject(
        project.id,
        baseline.name,
        baseline.description,
        baseline.slug,
        next,
        buildMetadata(baseline)
      );
      const response = JSON.parse(result);
      if (!response.success) {
        setErrorMessage(response.error || 'Failed to update project');
        return;
      }
      toast.success(next ? 'Project enabled' : 'Project disabled');
      onSaved?.({ enabled: next });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'An error occurred');
    } finally {
      setIsSaving(false);
    }
  }

  async function handleSoftDelete() {
    const ok = await confirmDialog({
      title: 'Delete project?',
      message: `Soft-delete "${project.name}". The project will be hidden from the list but can be restored within 30 days.`,
      confirmLabel: 'Delete',
      variant: 'warning',
    });
    if (!ok) return;
    setIsDeleting(true);
    try {
      const result = await deleteProject(project.id);
      const response = JSON.parse(result);
      if (!response.success) {
        await alertDialog({
          message: response.error || 'Failed to delete project',
          variant: 'error',
        });
        return;
      }
      toast.success('Project deleted');
      onDeleted?.('soft');
    } catch (error) {
      await alertDialog({
        message: error instanceof Error ? error.message : 'An error occurred',
        variant: 'error',
      });
    } finally {
      setIsDeleting(false);
    }
  }

  async function handlePermanentDelete() {
    const ok = await confirmDialog({
      title: 'Permanently delete project?',
      message: `This will destroy "${project.name}" and ALL of its versions, classes, properties and audit history. This cannot be undone.`,
      confirmLabel: 'Permanently delete',
      variant: 'danger',
    });
    if (!ok) return;
    setIsDeleting(true);
    try {
      const result = await permanentDeleteProject(project.id);
      const response = JSON.parse(result);
      if (!response.success) {
        await alertDialog({
          message: response.error || 'Failed to permanently delete project',
          variant: 'error',
        });
        return;
      }
      toast.success('Project permanently deleted');
      onDeleted?.('hard');
    } catch (error) {
      await alertDialog({
        message: error instanceof Error ? error.message : 'An error occurred',
        variant: 'error',
      });
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {errorMessage ? <Alert variant="error">{errorMessage}</Alert> : null}

      <section className={projectPanelClass}>
        <div className={`${projectPanelHeaderClass} flex items-center justify-between`}>
          <div className="flex items-center gap-3">
            <Settings2 className="w-5 h-5 text-indigo-500" />
            <div>
              <h3 className="text-base font-semibold">General</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Name, slug, classification &amp; description
              </p>
            </div>
          </div>
          {dirty ? (
            <span className="text-[10px] font-mono text-amber-600 dark:text-amber-400 px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30">
              unsaved
            </span>
          ) : null}
        </div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="settings-name">
              Name <span className="text-rose-500">*</span>
            </Label>
            <Input
              id="settings-name"
              value={form.name}
              onChange={(e) => update('name', e.target.value)}
            />
            <p className="text-[11px] text-gray-500">Display name for this project.</p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-slug">
              Slug <span className="text-rose-500">*</span>
            </Label>
            <Input
              id="settings-slug"
              value={form.slug}
              onChange={(e) => update('slug', filterSlugInput(e.target.value))}
              className="font-mono"
            />
            <p className="text-[11px] text-amber-600 dark:text-amber-400">
              Changing this breaks consumer URLs &amp; CI tokens.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-domain">Domain category</Label>
            <Select
              value={form.domainCategory}
              onValueChange={(v) => update('domainCategory', v)}
            >
              <SelectTrigger id="settings-domain">
                <SelectValue placeholder="Select a category" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={PROJECT_DOMAIN_CATEGORY_NONE}>None</SelectItem>
                {PROJECT_DOMAIN_CATEGORIES.map((cat) => (
                  <SelectItem key={cat.id} value={cat.id}>
                    {cat.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="settings-description">Description</Label>
            <Textarea
              id="settings-description"
              rows={3}
              value={form.description}
              onChange={(e) => update('description', e.target.value)}
            />
            <p className="text-[11px] text-gray-500">
              Shown on the project card and in published docs.
            </p>
          </div>
        </div>
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!dirty || isSaving}
            onClick={() => setForm(baseline)}
          >
            Reset
          </Button>
          <Button size="sm" disabled={!dirty || isSaving} onClick={handleSave}>
            {isSaving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </section>

      <section className={projectPanelClass}>
        <div className={projectPanelHeaderClass}>
          <div className="flex items-center gap-3">
            <FileText className="w-5 h-5 text-indigo-500" />
            <div>
              <h3 className="text-base font-semibold">OpenAPI metadata</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Embedded into every generated spec
              </p>
            </div>
          </div>
        </div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="settings-summary">Summary</Label>
            <Input
              id="settings-summary"
              value={form.summary}
              onChange={(e) => update('summary', e.target.value)}
              placeholder="Public REST API — invoices, taxes, settlements."
            />
            <p className="text-[11px] text-gray-500">
              Short tagline rendered above the description in docs.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-contact-name">Contact name</Label>
            <Input
              id="settings-contact-name"
              value={form.contactName}
              onChange={(e) => update('contactName', e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="settings-contact-email">Contact email</Label>
            <Input
              id="settings-contact-email"
              type="email"
              className="font-mono"
              value={form.contactEmail}
              onChange={(e) => update('contactEmail', e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="settings-contact-url">Contact URL</Label>
            <Input
              id="settings-contact-url"
              type="url"
              className="font-mono"
              value={form.contactUrl}
              onChange={(e) => update('contactUrl', e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="settings-tos">Terms of service</Label>
            <Input
              id="settings-tos"
              type="url"
              className="font-mono"
              value={form.termsOfService}
              onChange={(e) => update('termsOfService', e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-license">License</Label>
            <Select value={licenseSelectValue} onValueChange={selectLicense}>
              <SelectTrigger id="settings-license">
                <SelectValue placeholder="Select a license" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={LICENSE_NONE}>None</SelectItem>
                {SPDX_LICENSES.map((license) => (
                  <SelectItem key={license.identifier} value={license.identifier}>
                    {license.name}
                  </SelectItem>
                ))}
                <SelectItem value={LICENSE_CUSTOM}>Custom…</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[11px] text-gray-500">
              Picking an SPDX license auto-fills the URL.
            </p>
          </div>
          {licenseSelectValue === LICENSE_CUSTOM ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="settings-license-name">License name</Label>
                <Input
                  id="settings-license-name"
                  value={form.licenseName}
                  onChange={(e) => update('licenseName', e.target.value)}
                />
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <Label htmlFor="settings-license-url">License URL</Label>
                <Input
                  id="settings-license-url"
                  type="url"
                  className="font-mono"
                  value={form.licenseUrl}
                  onChange={(e) => update('licenseUrl', e.target.value)}
                />
              </div>
            </>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="settings-license-url">
                License URL <span className="text-gray-400 font-normal">· auto</span>
              </Label>
              <Input
                id="settings-license-url"
                value={form.licenseUrl}
                readOnly
                className="font-mono bg-gray-50 dark:bg-gray-900/60 text-gray-500"
              />
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!dirty || isSaving}
            onClick={() => setForm(baseline)}
          >
            Reset
          </Button>
          <Button size="sm" disabled={!dirty || isSaving} onClick={handleSave}>
            {isSaving ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </section>

      <section className={`${projectPanelClass} border-rose-200 dark:border-rose-700/40`}>
        <div className="px-5 py-4 border-b border-rose-200 dark:border-rose-700/40 bg-rose-50/40 dark:bg-rose-900/10 flex items-center gap-3">
          <AlertOctagon className="w-5 h-5 text-rose-500" />
          <div>
            <h3 className="text-base font-semibold text-rose-700 dark:text-rose-300">
              Danger zone
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Irreversible actions</p>
          </div>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-700/60 text-sm">
          <div className="p-5 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="font-semibold">
                {form.enabled ? 'Disable project' : 'Enable project'}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {form.enabled
                  ? 'Hides from list and freezes all version edits. Re-enable any time.'
                  : 'Make this project visible and editable again.'}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={isSaving || isDeleting}
              onClick={handleToggleEnabled}
            >
              {form.enabled ? 'Disable' : 'Enable'}
            </Button>
          </div>
          <div className="p-5 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="font-semibold">Soft delete</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Marks the project deleted. Recoverable by an admin within 30 days.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="border-rose-200 dark:border-rose-700/40 text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/10"
              disabled={isDeleting || Boolean(project.deleted_at)}
              onClick={handleSoftDelete}
            >
              {project.deleted_at ? 'Already deleted' : 'Delete'}
            </Button>
          </div>
          <div className="p-5 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="font-semibold text-rose-600 dark:text-rose-400">
                Permanently delete
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                Destroys all versions, classes, properties, and audit history.{' '}
                <span className="font-semibold text-rose-600">No recovery.</span>
              </p>
            </div>
            <Button
              size="sm"
              variant="destructive"
              disabled={isDeleting}
              onClick={handlePermanentDelete}
            >
              <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Permanently…
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
