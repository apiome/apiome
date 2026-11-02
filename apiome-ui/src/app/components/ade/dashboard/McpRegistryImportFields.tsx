'use client';

/**
 * "From a registry" fields of the Add MCP server form (AAU-5.4, #5725).
 *
 * A controlled view of {@link McpRegistryForm}: the registry root, an optional name search, the
 * registry credential and whether to keep the servers in sync. The dialog registers an
 * `mcp-registry` connector from these values and runs its first sync — see `mcpRegistryImport.ts`.
 */

import { Library } from 'lucide-react';
import { Card } from '../../../components/ui/Card';
import { Checkbox } from '../../../components/ui/Checkbox';
import { FormField } from '../../../components/ui/FormField';
import { Input } from '../../../components/ui/Input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/Select';
import {
  MCP_REGISTRY_CREDENTIAL_OPTIONS,
  type McpRegistryCredentialType,
  type McpRegistryForm,
} from './mcp/mcpRegistryImport';

export interface McpRegistryImportFieldsProps {
  form: McpRegistryForm;
  onChange: (form: McpRegistryForm) => void;
}

export default function McpRegistryImportFields({ form, onChange }: McpRegistryImportFieldsProps) {
  const set = <K extends keyof McpRegistryForm>(key: K, value: McpRegistryForm[K]) =>
    onChange({ ...form, [key]: value });
  const credentialOption =
    MCP_REGISTRY_CREDENTIAL_OPTIONS.find((option) => option.value === form.credentialType) ??
    MCP_REGISTRY_CREDENTIAL_OPTIONS[0];

  return (
    <div className="flex flex-col gap-6" data-testid="mcp-registry-fields">
      <Card variant="flat" className="overflow-hidden">
        <div className="flex items-start gap-3 p-4">
          <span className="tnt-icon-tile" data-tone="accent" aria-hidden>
            <Library />
          </span>
          <div>
            <h3 className="font-semibold text-fg">Import from a registry</h3>
            <p className="mt-0.5 text-sm text-fg-muted">
              Bring in every server an MCP registry lists: the official registry, Azure API Center, a
              Kong registry or another Apiome workspace. Each server with a reachable remote is added
              here, discovered and graded. Servers Apiome cannot reach are listed with the reason.
            </p>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <FormField
          label="Registry URL"
          htmlFor="mcp-registry-url"
          required
          helperText="The registry root. For another Apiome workspace: https://<apiome>/registry/mcp/<workspace>."
        >
          <Input
            id="mcp-registry-url"
            type="text"
            inputMode="url"
            placeholder="https://registry.modelcontextprotocol.io"
            value={form.registryUrl}
            onChange={(e) => set('registryUrl', e.target.value)}
          />
        </FormField>

        <FormField
          label="Search"
          htmlFor="mcp-registry-search"
          helperText="Optional — only servers whose name matches. Leave empty for every server."
        >
          <Input
            id="mcp-registry-search"
            type="text"
            placeholder="io.github.acme"
            value={form.search}
            onChange={(e) => set('search', e.target.value)}
          />
        </FormField>

        <FormField label="Registry credential" htmlFor="mcp-registry-credential-type" helperText={credentialOption.hint}>
          <Select
            value={form.credentialType}
            onValueChange={(value) => set('credentialType', value as McpRegistryCredentialType)}
          >
            <SelectTrigger id="mcp-registry-credential-type">
              <SelectValue placeholder="Select a credential" />
            </SelectTrigger>
            <SelectContent>
              {MCP_REGISTRY_CREDENTIAL_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        {form.credentialType !== 'none' ? (
          <FormField
            label={form.credentialType === 'token' ? 'Bearer token' : 'API key'}
            htmlFor="mcp-registry-credential"
            required
            helperText="Stored encrypted with the connector; it is never shown again."
          >
            <Input
              id="mcp-registry-credential"
              type="password"
              autoComplete="off"
              placeholder="••••••••"
              value={form.credential}
              onChange={(e) => set('credential', e.target.value)}
            />
          </FormField>
        ) : null}
      </div>

      <label className="flex items-start gap-2 text-sm text-fg" htmlFor="mcp-registry-keep-in-sync">
        <Checkbox
          id="mcp-registry-keep-in-sync"
          checked={form.keepInSync}
          onCheckedChange={(checked) => set('keepInSync', checked === true)}
          className="mt-0.5"
        />
        <span>
          Keep these servers in sync
          <span className="block text-xs text-fg-muted">
            Re-sync daily. Only servers whose registry entry changed are imported again. Change the cadence
            later under Bring in → Connectors.
          </span>
        </span>
      </label>
    </div>
  );
}
