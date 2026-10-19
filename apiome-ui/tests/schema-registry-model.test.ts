/**
 * The schema registry rules — CDG-4.5 (#5977).
 *
 * Which formats get the Subjects tab, how subjects map onto catalog items, the level label, the
 * attach form's name check, the Confluent URL and serializer snippets, and the proxy's allowlist.
 */

import { describe, expect, it } from '@jest/globals';
import {
  API_KEY_PLACEHOLDER,
  isRegistryFormat,
  registryBaseUrl,
  registryProxyBody,
  registryProxyPath,
  serializerSnippets,
  subjectLevelLabel,
  subjectNameProblem,
  subjectNamesByItem,
  subjectsForItem,
  type SchemaSubject,
} from '../lib/schema-registry';
import { catalogDetailTabs } from '../src/app/components/ade/catalog/detail/catalogItemView';

const ITEM = '11111111-1111-4111-8111-111111111111';

function subject(name: string, over: Partial<SchemaSubject> = {}): SchemaSubject {
  return {
    name,
    strategy: 'topic',
    compatibilityLevel: null,
    effectiveCompatibilityLevel: 'BACKWARD',
    mode: 'READWRITE',
    projectId: ITEM,
    versionCount: 1,
    latestVersion: 1,
    createdAt: '2026-10-19T10:00:00Z',
    updatedAt: '2026-10-19T10:00:00Z',
    ...over,
  };
}

describe('isRegistryFormat', () => {
  it.each(['avro', 'avsc', 'json-schema', 'jsonschema', 'protobuf', 'proto'])('is true for %s', (format) => {
    expect(isRegistryFormat(format)).toBe(true);
  });

  it.each(['openapi', 'asyncapi', 'graphql', '', null, undefined])('is false for %s', (format) => {
    expect(isRegistryFormat(format)).toBe(false);
  });
});

describe('the Subjects tab', () => {
  it('is left out unless the item can back a subject', () => {
    expect(catalogDetailTabs().map((tab) => tab.id)).not.toContain('subjects');
    const tabs = catalogDetailTabs({ subjects: 2 }, { subjects: true });
    expect(tabs.at(-1)).toEqual({ id: 'subjects', label: 'Subjects', icon: 'subjects', count: 2 });
  });
});

describe('subjects and items', () => {
  const subjects = [
    subject('orders-value'),
    subject('a-orders-key'),
    subject('other', { projectId: '22222222-2222-4222-8222-222222222222' }),
    subject('unbacked', { projectId: null }),
  ];

  it('picks one item’s subjects, by name', () => {
    expect(subjectsForItem(subjects, ITEM).map((s) => s.name)).toEqual(['a-orders-key', 'orders-value']);
  });

  it('maps every backing item to its subject names', () => {
    const byItem = subjectNamesByItem(subjects);
    expect(byItem.get(ITEM)).toEqual(['a-orders-key', 'orders-value']);
    expect(byItem.size).toBe(2);
  });

  it('labels a level that comes from the workspace', () => {
    expect(subjectLevelLabel(subject('s'))).toBe('BACKWARD (workspace default)');
    expect(subjectLevelLabel(subject('s', { compatibilityLevel: 'NONE' }))).toBe('NONE');
  });
});

describe('subjectNameProblem', () => {
  it('accepts a normal name', () => {
    expect(subjectNameProblem('orders-value')).toBeNull();
  });

  it('refuses empty, over-long and control-character names', () => {
    expect(subjectNameProblem('  ')).toMatch(/Enter a subject name/);
    expect(subjectNameProblem('x'.repeat(256))).toMatch(/at most 255/);
    expect(subjectNameProblem('a\nb')).toMatch(/control characters/);
  });
});

describe('the serializer snippets', () => {
  it('builds the Confluent URL from the REST base', () => {
    expect(registryBaseUrl('https://api.example.com/v1', 'acme')).toBe('https://api.example.com/registry/schema/acme');
    expect(registryBaseUrl('http://localhost:8000/v1/', 'a b')).toBe('http://localhost:8000/registry/schema/a%20b');
  });

  it('gives Python, Java and Spring, each pointing at the URL and never at a real key', () => {
    const url = 'https://api.example.com/registry/schema/acme';
    const snippets = serializerSnippets(url);
    expect(snippets.map((s) => s.id)).toEqual(['python', 'java', 'spring']);
    for (const snippet of snippets) {
      expect(snippet.code).toContain(url);
      expect(snippet.code).toContain(API_KEY_PLACEHOLDER);
    }
    expect(snippets[1].code).toContain('basic.auth.credentials.source=USER_INFO');
  });
});

describe('registryProxyPath', () => {
  it.each([
    [['config'], 'GET', 'config'],
    [['config'], 'PUT', 'config'],
    [['subjects'], 'GET', 'subjects'],
    [['subjects', 'orders-value'], 'GET', 'subjects/orders-value'],
    [['subjects', 'orders-value'], 'PUT', 'subjects/orders-value'],
    [['subjects', 'orders-value'], 'DELETE', 'subjects/orders-value'],
    [['subjects', 'orders/v1'], 'GET', 'subjects/orders%2Fv1'],
    [['subjects', 'orders-value', 'versions'], 'GET', 'subjects/orders-value/versions'],
    [['subjects', 'orders-value', 'versions', 'latest'], 'GET', 'subjects/orders-value/versions/latest'],
    [['subjects', 'orders-value', 'versions', '3'], 'GET', 'subjects/orders-value/versions/3'],
    [['subjects', 'orders-value', 'attach'], 'POST', 'subjects/orders-value/attach'],
  ] as const)('allows %j %s', (segments, method, expected) => {
    expect(registryProxyPath(segments, method)).toBe(expected);
  });

  it.each([
    [['config'], 'DELETE'],
    [['subjects'], 'POST'],
    [['subjects', 'orders-value'], 'POST'],
    [['subjects', 'orders-value', 'versions'], 'POST'],
    [['subjects', 'orders-value', 'versions', '0'], 'GET'],
    [['subjects', 'orders-value', 'versions', '../x'], 'GET'],
    [['subjects', 'orders-value', 'attach'], 'GET'],
    [['subjects', 'a\nb'], 'GET'],
    [['schemas', 'ids', '1'], 'GET'],
    [['subjects', 'a', 'versions', '1', 'schema'], 'GET'],
    [[], 'GET'],
  ] as const)('refuses %j %s', (segments, method) => {
    expect(registryProxyPath(segments, method)).toBeNull();
  });
});

describe('registryProxyBody', () => {
  it('forwards only each write’s own string fields', () => {
    expect(registryProxyBody('config', { compatibilityLevel: 'NONE', mode: 'READONLY', evil: 1 })).toEqual({
      compatibilityLevel: 'NONE',
      mode: 'READONLY',
    });
    expect(registryProxyBody('subjects/s/attach', { projectId: ITEM, strategy: 'topic', mode: 'READONLY' })).toEqual({
      projectId: ITEM,
      strategy: 'topic',
    });
    expect(registryProxyBody('subjects/s', { compatibilityLevel: 'FULL', projectId: ITEM, mode: 7 })).toEqual({
      compatibilityLevel: 'FULL',
    });
    expect(registryProxyBody('config', null)).toEqual({});
  });
});
