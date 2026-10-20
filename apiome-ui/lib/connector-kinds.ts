/**
 * Connector kinds as the add-connector wizard and the settings tab draw them (CDG-1.7, #5958).
 *
 * One entry per kind: what it reads, whether it takes a base URL, the **scope** fields (coordinates,
 * never secrets) and the **credential** fields (sealed by REST on `PUT …/credentials`, never shown
 * again). The shapes mirror the REST scope validators (`app.kong_connector_source`,
 * `app.aws_apigateway_connector_source`, `app.azure_apim_connector_source`,
 * `app.apigee_connector_source`, `app.mcp_registry_connector_source`, `app.schema_registry_connector_source`),
 * which stay the authority: this model only lays the form out and
 * turns its values into the request body.
 */

/** A form field of a connector kind. */
export interface ConnectorField {
  /** The scope or credential key REST expects. */
  key: string;
  /** The field's label. */
  label: string;
  /** `text`, a comma-separated `list`, a `select`, a `boolean` or a multi-line `secret`. */
  type: 'text' | 'list' | 'select' | 'boolean' | 'secret';
  /** Required before the dry run can run. */
  required?: boolean;
  /** Options of a `select`. */
  options?: readonly { value: string; label: string }[];
  /** One line of help under the field. */
  help?: string;
  /** Example input. */
  placeholder?: string;
  /** A secret pasted as a whole file (a JSON key) rather than one line. */
  multiline?: boolean;
}

/** One connector kind. */
export interface ConnectorKind {
  /** The REST kind. */
  kind: string;
  /** Its name in the UI. */
  label: string;
  /** What it reads, in one sentence. */
  description: string;
  /** Whether a base URL is `required`, `optional` or not taken (`none`). */
  baseUrl: 'required' | 'optional' | 'none';
  /** Help for the base URL field. */
  baseUrlHelp?: string;
  /** Scope fields. */
  scope: readonly ConnectorField[];
  /** Credential fields; empty when the kind stores none (AWS assumes a role). */
  credentials: readonly ConnectorField[];
  /** What the credential step says when there are no credential fields, or why one is optional. */
  credentialNote?: string;
}

/** Every kind the wizard can configure. Kinds without a source on the deployment are shown disabled. */
export const CONNECTOR_KINDS: readonly ConnectorKind[] = [
  {
    kind: 'kong-konnect',
    label: 'Kong Konnect',
    description: 'Services and routes of Kong Konnect control planes.',
    baseUrl: 'none',
    scope: [
      {
        key: 'region',
        label: 'Region',
        type: 'select',
        required: true,
        options: ['us', 'eu', 'au', 'me', 'in', 'sg'].map((value) => ({ value, label: value.toUpperCase() })),
      },
      {
        key: 'controlPlanes',
        label: 'Control planes',
        type: 'list',
        help: 'Control plane ids, comma-separated. Leave empty for every control plane the token can read.',
      },
    ],
    credentials: [{ key: 'token', label: 'Personal or system access token', type: 'secret', required: true }],
  },
  {
    kind: 'kong-admin',
    label: 'Kong Gateway (Admin API)',
    description: 'Services and routes of a Kong Gateway Admin API.',
    baseUrl: 'required',
    baseUrlHelp: 'The Admin API address, for example https://kong-admin.example.com:8001.',
    scope: [
      { key: 'workspace', label: 'Workspace', type: 'text', placeholder: 'default' },
      { key: 'environment', label: 'Environment', type: 'text', placeholder: 'production' },
    ],
    credentials: [{ key: 'token', label: 'Admin token', type: 'secret' }],
    credentialNote: 'Leave the token empty when the Admin API needs none.',
  },
  {
    kind: 'aws-apigateway',
    label: 'AWS API Gateway',
    description: 'Every deployed stage of the REST and HTTP APIs in an AWS account.',
    baseUrl: 'none',
    scope: [
      {
        key: 'roleArn',
        label: 'Role ARN',
        type: 'text',
        required: true,
        placeholder: 'arn:aws:iam::123456789012:role/apiome-catalog',
      },
      { key: 'externalId', label: 'External ID', type: 'text', required: true, placeholder: 'apiome-7c1d9a2f' },
      { key: 'regions', label: 'Regions', type: 'list', required: true, placeholder: 'eu-west-1, us-east-1' },
    ],
    credentials: [],
    credentialNote: 'Apiome assumes the role in your account, so no key is stored.',
  },
  {
    kind: 'azure-apim',
    label: 'Azure API Management',
    description: 'The current revision of every API in an APIM instance, with its policies.',
    baseUrl: 'none',
    scope: [
      { key: 'tenantId', label: 'Directory (tenant) ID', type: 'text', required: true },
      { key: 'clientId', label: 'Application (client) ID', type: 'text', required: true },
      { key: 'subscriptionId', label: 'Subscription ID', type: 'text', required: true },
      { key: 'resourceGroup', label: 'Resource group', type: 'text', required: true },
      { key: 'serviceName', label: 'API Management instance', type: 'text', required: true },
      {
        key: 'authMethod',
        label: 'Sign-in',
        type: 'select',
        options: [
          { value: 'client-secret', label: 'Client secret' },
          { value: 'federated', label: 'Federated credential' },
        ],
      },
      { key: 'includeNonCurrentRevisions', label: 'Import non-current revisions too', type: 'boolean' },
    ],
    credentials: [{ key: 'clientSecret', label: 'Client secret', type: 'secret' }],
    credentialNote: 'Leave the client secret empty when the application uses a federated credential.',
  },
  {
    kind: 'apigee',
    label: 'Apigee',
    description: 'Every deployed proxy of an Apigee organization, one item per proxy.',
    baseUrl: 'none',
    scope: [
      { key: 'organization', label: 'Organization', type: 'text', required: true, placeholder: 'acme-prod' },
      {
        key: 'environments',
        label: 'Environments',
        type: 'list',
        help: 'Comma-separated. Leave empty to read every environment.',
        placeholder: 'test, prod',
      },
    ],
    credentials: [
      {
        key: 'credentialJson',
        label: 'Service-account key or workload identity configuration (JSON)',
        type: 'secret',
        required: true,
        multiline: true,
      },
    ],
  },
  {
    kind: 'url',
    label: 'Specification URL',
    description: 'A specification published at a URL.',
    baseUrl: 'required',
    scope: [],
    credentials: [],
  },
  {
    kind: 'schema-registry',
    label: 'Schema registry',
    description:
      'Subjects of a Confluent, Karapace or Apicurio schema registry, mirrored as schema subjects with their versions.',
    baseUrl: 'required',
    baseUrlHelp:
      'The registry REST address, for example https://psrc-123.eu-west-1.aws.confluent.cloud. For Apicurio, its ' +
      'compatibility API: https://<apicurio>/apis/ccompat/v7.',
    scope: [],
    credentials: [
      { key: 'username', label: 'Username or API key', type: 'secret' },
      { key: 'password', label: 'Password or API secret', type: 'secret' },
      { key: 'token', label: 'Bearer token', type: 'secret' },
    ],
    credentialNote:
      'Leave all empty for an open registry. Confluent Cloud takes its API key and secret as username and password.',
  },
  {
    kind: 'mcp-registry',
    label: 'MCP registry',
    description: 'MCP servers listed in an MCP registry, added to the MCP server catalog.',
    baseUrl: 'required',
    baseUrlHelp:
      'The registry root, for example https://registry.modelcontextprotocol.io, an Azure API Center or Kong ' +
      'registry, or another Apiome workspace at https://<apiome>/registry/mcp/<workspace>.',
    scope: [
      {
        key: 'search',
        label: 'Search',
        type: 'text',
        help: 'Only servers whose name matches. Leave empty for every server the registry lists.',
        placeholder: 'io.github.acme',
      },
      {
        key: 'updatedSince',
        label: 'Updated since',
        type: 'text',
        help: 'Only servers updated at or after this RFC 3339 instant. Servers it hides are reported missing.',
        placeholder: '2026-01-01T00:00:00Z',
      },
    ],
    credentials: [
      { key: 'token', label: 'Bearer token', type: 'secret' },
      { key: 'apiKey', label: 'Apiome workspace API key', type: 'secret' },
    ],
    credentialNote: 'Leave both empty for a public registry. An Apiome workspace takes its API key.',
  },
];

/**
 * Whether a kind's inventory lands in the MCP server catalog rather than the API catalog (CDG-4.4).
 *
 * @param kind - The REST kind.
 * @returns `true` for `mcp-registry`.
 */
export function landsInMcpCatalog(kind: string | null | undefined): boolean {
  return kind === 'mcp-registry';
}

/** Refresh cadences the schedule step offers (`null` = the deployment default). */
export const CADENCE_OPTIONS: readonly { value: string; label: string; seconds: number | null }[] = [
  { value: 'default', label: 'Deployment default', seconds: null },
  { value: '3600', label: 'Hourly', seconds: 3600 },
  { value: '21600', label: 'Every 6 hours', seconds: 21600 },
  { value: '86400', label: 'Daily', seconds: 86400 },
  { value: '604800', label: 'Weekly', seconds: 604800 },
];

/** The field values a form holds: strings for text, lists and secrets; booleans for checkboxes. */
export type FieldValues = Record<string, string | boolean>;

/**
 * Look a kind up.
 *
 * @param kind - The REST kind.
 * @returns The entry, or `undefined` for a kind this UI does not know.
 */
export function connectorKind(kind: string | null | undefined): ConnectorKind | undefined {
  return CONNECTOR_KINDS.find((entry) => entry.kind === kind);
}

/**
 * A kind's label, falling back to the raw kind.
 *
 * @param kind - The REST kind.
 */
export function connectorKindLabel(kind: string | null | undefined): string {
  return connectorKind(kind)?.label ?? String(kind ?? '');
}

/**
 * Turn scope field values into the REST `scope` object.
 *
 * Empty values are left out (REST treats a missing key as "use the default"); a `list` is split on
 * commas and trimmed; a `boolean` is sent only when true.
 *
 * @param kind - The kind entry.
 * @param values - The form values.
 * @returns The scope object.
 */
export function buildScope(kind: ConnectorKind, values: FieldValues): Record<string, unknown> {
  const scope: Record<string, unknown> = {};
  for (const field of kind.scope) {
    const value = values[field.key];
    if (field.type === 'boolean') {
      if (value === true) scope[field.key] = true;
      continue;
    }
    const text = typeof value === 'string' ? value.trim() : '';
    if (!text) continue;
    scope[field.key] =
      field.type === 'list'
        ? text
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
        : text;
  }
  return scope;
}

/**
 * Turn scope values from REST back into form values (the settings tab edits an existing scope).
 *
 * @param kind - The kind entry.
 * @param scope - The connector's stored scope.
 * @returns The form values.
 */
export function scopeToValues(kind: ConnectorKind, scope: Record<string, unknown>): FieldValues {
  const values: FieldValues = {};
  for (const field of kind.scope) {
    const value = scope[field.key];
    if (field.type === 'boolean') values[field.key] = value === true;
    else if (Array.isArray(value)) values[field.key] = value.join(', ');
    else if (value !== undefined && value !== null) values[field.key] = String(value);
  }
  return values;
}

/**
 * Turn credential field values into the REST `credentials` object, or `null` when none was entered.
 *
 * @param kind - The kind entry.
 * @param values - The form values.
 */
export function buildCredentials(kind: ConnectorKind, values: FieldValues): Record<string, string> | null {
  const credentials: Record<string, string> = {};
  for (const field of kind.credentials) {
    const value = values[field.key];
    if (typeof value === 'string' && value.trim()) credentials[field.key] = value.trim();
  }
  return Object.keys(credentials).length > 0 ? credentials : null;
}

/**
 * What still has to be filled in before a step can continue.
 *
 * @param kind - The kind entry.
 * @param step - `credentials` or `scope` (the scope step also checks the base URL).
 * @param values - The form values.
 * @param baseUrl - The base URL value.
 * @returns The labels of the missing required fields (empty when the step is complete).
 */
export function missingFields(
  kind: ConnectorKind,
  step: 'credentials' | 'scope',
  values: FieldValues,
  baseUrl: string
): string[] {
  const missing: string[] = [];
  if (step === 'scope' && kind.baseUrl === 'required' && !baseUrl.trim()) missing.push('Base URL');
  const fields = step === 'scope' ? kind.scope : kind.credentials;
  for (const field of fields) {
    if (!field.required) continue;
    const value = values[field.key];
    if (typeof value !== 'string' || !value.trim()) missing.push(field.label);
  }
  return missing;
}

/**
 * The cadence option a stored refresh interval corresponds to.
 *
 * @param seconds - `refreshIntervalSeconds` (null = deployment default).
 * @returns The option value, or the seconds as a string when no option matches.
 */
export function cadenceValue(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'default';
  return CADENCE_OPTIONS.find((option) => option.seconds === seconds)?.value ?? String(seconds);
}

/**
 * The refresh interval a cadence option stands for.
 *
 * @param value - An option value (or a number of seconds as a string).
 * @returns The seconds, or `null` for the deployment default.
 */
export function cadenceSeconds(value: string): number | null {
  if (value === 'default') return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}
