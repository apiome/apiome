/**
 * Protocol Buffers / Avro import as classes — REPO-3.7 (#2776).
 *
 * The project import path converts `.proto` (`protobuf-converter.ts`) and `.avsc` (`avro-converter.ts`) to
 * OpenAPI, and the OpenAPI importer turns each schema into an Apiome class. These tests pin the three
 * acceptance criteria end to end:
 *
 * 1. proto3 messages, enums, `oneof`, `repeated` and `map` all map — a `oneof` member stays an optional
 *    property tagged `x-proto-oneof`, and the message lists its groups under `x-proto-oneofs`;
 * 2. Avro records, unions and logical types map — a logical type becomes the OpenAPI type it stands for,
 *    tagged `x-avro-logical-type` (decimal keeps precision / scale; an unknown one keeps its base type);
 * 3. a semantic round trip on a representative fixture set: the focused fixtures in
 *    `fixtures/serialization-import/` read back from the imported classes construct by construct, and every
 *    `.proto` / `.avsc` of the corpus imports each of its messages, enums and records as a class.
 */

import { describe, expect, it } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import {
  PROTO_ONEOF_EXTENSION,
  PROTO_ONEOFS_EXTENSION,
  convertProtobufToOpenAPI,
} from '../src/app/utils/protobuf-converter';
import { AVRO_LOGICAL_TYPE_EXTENSION, convertAvroToOpenAPI as convertAvroSchema } from '../src/app/utils/avro-converter';
import { openApiImporter } from '../lib/importers/openapi';

const FIXTURES = path.join(__dirname, 'fixtures/serialization-import');
const EXAMPLES = path.join(__dirname, '../examples');

type OpenApiDocument = { components: { schemas: Record<string, unknown> } };
type Converter = (content: string, fileName?: string) => { success: boolean; document: unknown; error?: string };

/** Convert, then import every schema as a class — the import's own two steps. */
function importClasses(convert: Converter, content: string) {
  const result = convert(content);
  expect(result.error).toBeUndefined();
  expect(result.success).toBe(true);
  const document = result.document as OpenApiDocument;
  const schemas = Object.keys(document.components.schemas);
  const normalized = openApiImporter.normalize({ document, options: { selectedSchemas: schemas } });
  return Object.fromEntries(normalized.classes.map((cls) => [cls.originalSchemaKey ?? cls.name, cls]));
}

type PropertyData = Record<string, unknown> & { items?: unknown; oneOf?: unknown[]; additionalProperties?: unknown };
type ImportedClass = { properties?: Array<{ name: string; data?: PropertyData }> };

function prop(cls: ImportedClass, name: string): PropertyData {
  const found = (cls.properties ?? []).find((p) => p.name === name);
  expect(found).toBeDefined();
  return found!.data ?? {};
}

const read = (file: string) => fs.readFileSync(path.join(FIXTURES, file), 'utf-8');

/** The Avro converter takes the parsed schema JSON; the import parses the `.avsc` text first. */
const convertAvroToOpenAPI: Converter = (content) => convertAvroSchema(JSON.parse(content));

describe('proto3 messages, enums, oneof, repeated and map (#2776 AC 1)', () => {
  const classes = () => importClasses(convertProtobufToOpenAPI, read('shipments.proto'));

  it('imports each message and enum as a class', () => {
    expect(Object.keys(classes()).sort()).toEqual(['Address', 'Carrier', 'Shipment']);
    expect(classes().Carrier.schema.enum).toEqual(['CARRIER_UNSPECIFIED', 'CARRIER_POST', 'CARRIER_COURIER']);
  });

  it('maps repeated to an array and map to an object of values', () => {
    const shipment = classes().Shipment;
    expect(prop(shipment, 'tracking_numbers').type).toBe('array');
    expect(prop(shipment, 'labels')).toMatchObject({ type: 'object', additionalProperties: { type: 'string' } });
    expect(prop(shipment, 'stops').items).toEqual({ $ref: '#/components/schemas/Address' });
    expect(prop(shipment, 'carrier').enum).toEqual(['CARRIER_UNSPECIFIED', 'CARRIER_POST', 'CARRIER_COURIER']);
  });

  it('keeps each oneof member as an optional property tagged with its group', () => {
    const shipment = classes().Shipment;
    expect(prop(shipment, 'address')[PROTO_ONEOF_EXTENSION]).toBe('destination');
    expect(prop(shipment, 'pickup_point_id')[PROTO_ONEOF_EXTENSION]).toBe('destination');
    expect(prop(shipment, 'address').required).toBeUndefined();
    expect(prop(shipment, 'weight_grams')[PROTO_ONEOF_EXTENSION]).toBeUndefined();
    expect(shipment.schema[PROTO_ONEOFS_EXTENSION]).toEqual({ destination: ['address', 'pickup_point_id'] });
  });

  it('does not tag a field with the oneof of a nested message', () => {
    const doc = convertProtobufToOpenAPI(
      'syntax = "proto3";\nmessage Outer {\n  string id = 1;\n  message Inner {\n    oneof choice {\n      string id = 1;\n      int32 n = 2;\n    }\n  }\n}\n',
    ).document;
    expect(doc.components.schemas.Outer[PROTO_ONEOFS_EXTENSION]).toBeUndefined();
    expect(doc.components.schemas.Outer.properties.id[PROTO_ONEOF_EXTENSION]).toBeUndefined();
    expect(doc.components.schemas.Outer_Inner[PROTO_ONEOFS_EXTENSION]).toEqual({ choice: ['id', 'n'] });
  });

  it('keeps a proto2 oneof member out of required', () => {
    const doc = convertProtobufToOpenAPI(
      'syntax = "proto2";\nmessage M {\n  required string id = 1;\n  oneof v {\n    string a = 2;\n    string b = 3;\n  }\n}\n',
    ).document;
    expect(doc.components.schemas.M.required).toEqual(['id']);
  });
});

describe('Avro records, unions and logical types (#2776 AC 2)', () => {
  const classes = () => importClasses(convertAvroToOpenAPI, read('shipments.avsc'));

  it('imports each named record and enum as a class', () => {
    expect(Object.keys(classes()).sort()).toEqual(['Address', 'Carrier', 'shipping_v1_Shipment'].sort());
  });

  it('maps each logical type to what it stands for, tagged x-avro-logical-type', () => {
    const shipment = classes().shipping_v1_Shipment;
    expect(prop(shipment, 'id')).toMatchObject({ type: 'string', format: 'uuid', [AVRO_LOGICAL_TYPE_EXTENSION]: 'uuid' });
    expect(prop(shipment, 'shippedOn')).toMatchObject({ type: 'string', format: 'date', [AVRO_LOGICAL_TYPE_EXTENSION]: 'date' });
    expect(prop(shipment, 'createdAt')).toMatchObject({ format: 'date-time', [AVRO_LOGICAL_TYPE_EXTENSION]: 'timestamp-millis' });
    expect(prop(shipment, 'cutOff')).toMatchObject({ format: 'time', [AVRO_LOGICAL_TYPE_EXTENSION]: 'time-millis' });
    expect(prop(shipment, 'insuredValue')).toMatchObject({
      type: 'number', [AVRO_LOGICAL_TYPE_EXTENSION]: 'decimal', 'x-avro-precision': 10, 'x-avro-scale': 2,
    });
  });

  it('keeps an unknown logical type on its base type', () => {
    expect(prop(classes().shipping_v1_Shipment, 'custom')).toMatchObject({
      type: 'integer', format: 'int64', [AVRO_LOGICAL_TYPE_EXTENSION]: 'x-epoch-seconds',
    });
  });

  it('maps a nullable union to null-or-type and a multi-type union to oneOf', () => {
    const shipment = classes().shipping_v1_Shipment;
    expect(prop(shipment, 'trackingCode').oneOf).toEqual([{ type: 'null' }, { type: 'string' }]);
    expect(prop(shipment, 'destination').oneOf).toHaveLength(2);
    expect(prop(shipment, 'tags').type).toBe('array');
    expect(prop(shipment, 'labels').additionalProperties).toEqual({ type: 'string' });
  });
});

describe('semantic round trip on a representative fixture set (#2776 AC 3)', () => {
  /** A class's construct inventory: each property's type, format and the source extensions it carries. */
  function inventory(cls: ImportedClass) {
    return Object.fromEntries((cls.properties ?? []).map((p) => {
      const d = p.data ?? {};
      const kind = d.$ref ? 'ref' : d.oneOf ? 'union' : d.additionalProperties ? 'map' : d.type;
      return [p.name, [kind, d.format ?? d[AVRO_LOGICAL_TYPE_EXTENSION] ?? d[PROTO_ONEOF_EXTENSION] ?? null]];
    }));
  }

  it('reads the proto fixture back from the classes, field by field', () => {
    expect(inventory(importClasses(convertProtobufToOpenAPI, read('shipments.proto')).Shipment)).toEqual({
      id: ['string', null],
      carrier: ['string', null],
      tracking_numbers: ['array', null],
      labels: ['map', null],
      stops: ['array', null],
      address: ['ref', 'destination'],
      pickup_point_id: ['string', 'destination'],
      weight_grams: ['integer', 'int64'],
    });
  });

  it('reads the Avro fixture back from the classes, field by field', () => {
    expect(inventory(importClasses(convertAvroToOpenAPI, read('shipments.avsc')).shipping_v1_Shipment)).toEqual({
      id: ['string', 'uuid'],
      shippedOn: ['string', 'date'],
      createdAt: ['string', 'date-time'],
      cutOff: ['string', 'time'],
      insuredValue: ['number', 'decimal'],
      trackingCode: ['union', null],
      destination: ['union', null],
      carrier: ['ref', null],
      tags: ['array', null],
      labels: ['map', null],
      custom: ['integer', 'int64'],
    });
  });

  const protoFiles = fs.readdirSync(path.join(EXAMPLES, 'protobuf')).filter((f) => f.endsWith('.proto'));
  it.each(protoFiles)('imports every message and enum of protobuf/%s as a class', (file) => {
    const text = fs.readFileSync(path.join(EXAMPLES, 'protobuf', file), 'utf-8');
    const declared = Array.from(text.matchAll(/^\s*(?:message|enum)\s+(\w+)\s*\{/gm), (m) => m[1]);
    const names = Object.keys(importClasses(convertProtobufToOpenAPI, text));
    for (const name of declared) {
      expect(names.some((n) => n === name || n.endsWith(`_${name}`))).toBe(true);
    }
  });

  const avroFiles = fs.readdirSync(path.join(EXAMPLES, 'avro')).filter((f) => f.endsWith('.avsc'));
  it.each(avroFiles)('imports every named record and enum of avro/%s as a class, logical types tagged', (file) => {
    const text = fs.readFileSync(path.join(EXAMPLES, 'avro', file), 'utf-8');
    const named = Array.from(text.matchAll(/"type"\s*:\s*"(?:record|enum)"\s*,\s*"name"\s*:\s*"(\w+)"/g), (m) => m[1]);
    const classes = importClasses(convertAvroToOpenAPI, text);
    const names = Object.keys(classes);
    for (const name of named) {
      expect(names.some((n) => n === name || n.endsWith(`_${name}`))).toBe(true);
    }
    const logical = (text.match(/"logicalType"/g) ?? []).length;
    const tagged = JSON.stringify(Object.values(classes).map((c) => c.properties)).split(`"${AVRO_LOGICAL_TYPE_EXTENSION}"`).length - 1;
    expect(tagged).toBeGreaterThanOrEqual(logical > 0 ? 1 : 0);
  });

  it('tags the corpus oneof (protobuf/04-telemetry-stress.proto)', () => {
    const text = fs.readFileSync(path.join(EXAMPLES, 'protobuf', '04-telemetry-stress.proto'), 'utf-8');
    const classes = importClasses(convertProtobufToOpenAPI, text);
    expect(Object.values(classes).some((c) => c.schema[PROTO_ONEOFS_EXTENSION])).toBe(true);
  });
});
