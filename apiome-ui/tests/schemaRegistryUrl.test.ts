/**
 * Unit tests for the schema-registry helper of the catalog URL intake (MFI-12.6, #3787).
 *
 * `schemaRegistryRawSchemaUrl` must map a Confluent subject-version envelope, schema-id envelope and
 * version list to the raw-schema routes the CLI's `apiome import avro --registry` reads — and leave
 * every other response, including a raw schema and a non-Avro envelope, as it is.
 */

import { schemaRegistryRawSchemaUrl } from '../src/app/utils/schema-registry-url';

const REGISTRY = 'https://registry.example.com:8081';
const SCHEMA = '{"type":"record","name":"Order","fields":[]}';
const ENVELOPE = JSON.stringify({ subject: 'orders-value', version: 3, id: 21, schema: SCHEMA });

describe('schemaRegistryRawSchemaUrl', () => {
  it.each([
    [`${REGISTRY}/subjects/orders-value/versions/3`, ENVELOPE, `${REGISTRY}/subjects/orders-value/versions/3/schema`],
    [
      `${REGISTRY}/subjects/orders-value/versions/latest/`,
      ENVELOPE,
      `${REGISTRY}/subjects/orders-value/versions/latest/schema`,
    ],
    [`${REGISTRY}/subjects/orders-value/versions`, '[1, 2, 3]', `${REGISTRY}/subjects/orders-value/versions/latest/schema`],
    [`${REGISTRY}/schemas/ids/21`, JSON.stringify({ schema: SCHEMA }), `${REGISTRY}/schemas/ids/21/schema`],
    [
      'https://host/apis/ccompat/v7/subjects/s/versions/1?tenant=a#x',
      JSON.stringify({ subject: 's', version: 1, id: 2, schema: SCHEMA, schemaType: 'AVRO' }),
      'https://host/apis/ccompat/v7/subjects/s/versions/1/schema?tenant=a',
    ],
  ])('%s → %s', (url, body, expected) => {
    expect(schemaRegistryRawSchemaUrl(url, body)).toBe(expected);
  });

  it('leaves a raw schema as it is, so the followed URL never loops', () => {
    expect(schemaRegistryRawSchemaUrl(`${REGISTRY}/subjects/orders-value/versions/3/schema`, SCHEMA)).toBeNull();
  });

  it.each(['JSON', 'PROTOBUF'])('leaves a %s envelope as it is', (schemaType) => {
    const body = JSON.stringify({ subject: 's', version: 1, id: 2, schema: '{}', schemaType });
    expect(schemaRegistryRawSchemaUrl(`${REGISTRY}/subjects/s/versions/1`, body)).toBeNull();
  });

  it.each([
    ['an envelope on an unrelated path', `${REGISTRY}/api/schemas/21`, ENVELOPE],
    ['a version list on a version path', `${REGISTRY}/subjects/s/versions/1`, '[1, 2]'],
    ['an envelope on the versions path', `${REGISTRY}/subjects/s/versions`, ENVELOPE],
    ['an empty version list', `${REGISTRY}/subjects/s/versions`, '[]'],
    ['a list of strings', `${REGISTRY}/subjects/s/versions`, '["a"]'],
    ['an object without a schema string', `${REGISTRY}/schemas/ids/4`, '{"schema": {"type": "string"}}'],
    ['a registry error body', `${REGISTRY}/subjects/s/versions/9`, '{"error_code": 40402, "message": "Version not found"}'],
    ['text that is not JSON', `${REGISTRY}/subjects/s/versions/1`, 'protocol P {}'],
    ['malformed JSON', `${REGISTRY}/subjects/s/versions/1`, '{"schema": '],
    ['a non-http URL', 'ftp://registry/subjects/s/versions/1', ENVELOPE],
    ['a relative URL', '/subjects/s/versions/1', ENVELOPE],
  ])('leaves %s alone', (_label, url, body) => {
    expect(schemaRegistryRawSchemaUrl(url, body)).toBeNull();
  });
});
