/**
 * The connector-kind model (CDG-1.7, #5958): form fields per kind and the request bodies they build.
 */

import {
  CONNECTOR_KINDS,
  buildCredentials,
  buildScope,
  cadenceSeconds,
  cadenceValue,
  connectorKind,
  connectorKindLabel,
  landsInMcpCatalog,
  missingFields,
  scopeToValues,
} from '../lib/connector-kinds';
import { runOutcome } from '../lib/connectors-api';

describe('connector kinds', () => {
  it('covers every REST kind once', () => {
    expect(CONNECTOR_KINDS.map((k) => k.kind)).toEqual([
      'kong-konnect',
      'kong-admin',
      'aws-apigateway',
      'azure-apim',
      'apigee',
      'url',
      'schema-registry',
      'mcp-registry',
    ]);
    expect(connectorKindLabel('apigee')).toBe('Apigee');
    expect(connectorKindLabel('mystery')).toBe('mystery');
  });

  it('sends MCP registry entries to the MCP server catalog with optional credentials (CDG-4.4)', () => {
    expect(landsInMcpCatalog('mcp-registry')).toBe(true);
    expect(landsInMcpCatalog('kong-admin')).toBe(false);
    const registry = connectorKind('mcp-registry')!;
    expect(registry.scope.map((f) => f.key)).toEqual(['search', 'updatedSince']);
    expect(registry.credentials.every((f) => !f.required)).toBe(true);
    expect(missingFields(registry, 'scope', {}, '')).toEqual(['Base URL']);
    expect(buildCredentials(registry, {})).toBeNull();
  });

  it('crawls a schema registry with optional basic or bearer credentials (MFI-12.3)', () => {
    const registry = connectorKind('schema-registry')!;
    expect(landsInMcpCatalog('schema-registry')).toBe(false);
    expect(registry.scope).toEqual([]);
    expect(registry.credentials.map((f) => f.key)).toEqual(['username', 'password', 'token']);
    expect(registry.credentials.every((f) => !f.required)).toBe(true);
    expect(missingFields(registry, 'scope', {}, '')).toEqual(['Base URL']);
    expect(buildCredentials(registry, {})).toBeNull();
    expect(buildCredentials(registry, { username: 'KEY', password: 'SECRET' })).toEqual({
      username: 'KEY',
      password: 'SECRET',
    });
  });

  it('never puts a secret in the scope', () => {
    for (const kind of CONNECTOR_KINDS) {
      for (const field of kind.scope) expect(field.type).not.toBe('secret');
      for (const field of kind.credentials) expect(field.type).toBe('secret');
    }
    expect(connectorKind('aws-apigateway')?.credentials).toEqual([]);
  });

  it('builds the scope: lists split, empties dropped, booleans only when true', () => {
    const azure = connectorKind('azure-apim')!;
    expect(
      buildScope(azure, { tenantId: ' t ', clientId: '', includeNonCurrentRevisions: false, serviceName: 'svc' })
    ).toEqual({ tenantId: 't', serviceName: 'svc' });
    const aws = connectorKind('aws-apigateway')!;
    expect(buildScope(aws, { regions: 'eu-west-1, us-east-1,' })).toEqual({ regions: ['eu-west-1', 'us-east-1'] });
    expect(buildScope(azure, { includeNonCurrentRevisions: true })).toEqual({ includeNonCurrentRevisions: true });
  });

  it('reads a stored scope back into form values', () => {
    const apigee = connectorKind('apigee')!;
    expect(scopeToValues(apigee, { organization: 'acme', environments: ['test', 'prod'] })).toEqual({
      organization: 'acme',
      environments: 'test, prod',
    });
  });

  it('builds credentials only when something was entered', () => {
    const kong = connectorKind('kong-admin')!;
    expect(buildCredentials(kong, { token: '  ' })).toBeNull();
    expect(buildCredentials(kong, { token: ' abc ' })).toEqual({ token: 'abc' });
  });

  it('names the missing required fields of a step', () => {
    const kong = connectorKind('kong-admin')!;
    expect(missingFields(kong, 'scope', {}, '')).toEqual(['Base URL']);
    expect(missingFields(kong, 'credentials', {}, '')).toEqual([]);
    const konnect = connectorKind('kong-konnect')!;
    expect(missingFields(konnect, 'credentials', {}, '')).toEqual(['Personal or system access token']);
    expect(missingFields(konnect, 'scope', { region: 'eu' }, '')).toEqual([]);
  });

  it('maps cadences both ways', () => {
    expect(cadenceValue(null)).toBe('default');
    expect(cadenceValue(86400)).toBe('86400');
    expect(cadenceValue(900)).toBe('900');
    expect(cadenceSeconds('default')).toBeNull();
    expect(cadenceSeconds('3600')).toBe(3600);
  });

  it('states a run outcome', () => {
    const base = { errorClass: null, httpStatus: null, source: 'connector' as const };
    expect(runOutcome({ ...base, status: 'succeeded', summary: { imported: 2, candidates: 5 } })).toBe('Imported 2 of 5');
    expect(runOutcome({ ...base, status: 'succeeded', summary: { imported: 0, candidates: 5 } })).toBe(
      'Unchanged (5 checked)'
    );
    expect(runOutcome({ ...base, status: 'failed', summary: {}, errorClass: 'auth', httpStatus: 401 })).toBe(
      'Failed: auth (HTTP 401)'
    );
    expect(runOutcome({ ...base, source: 'git', status: 'succeeded', summary: {} })).toBe('Refreshed');
  });
});
