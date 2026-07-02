/**
 * Unit tests for Feature Compatibility (#573): identify unsupported features
 * in OpenAPI/spec documents during pre-import analysis.
 */

import { analyzeSpecification, UnsupportedFeature } from '../src/app/utils/openapi-analyzer';

describe('Feature compatibility – unsupported features (#573)', () => {
  describe('result shape', () => {
    it('always returns unsupportedFeatures array on analysis result', async () => {
      const minimal = `
openapi: 3.1.0
info:
  title: Minimal
  version: 1.0.0
components:
  schemas:
    Foo:
      type: object
      properties:
        id:
          type: string
`;
      const analysis = await analyzeSpecification(minimal, 'minimal.yaml');
      expect(analysis).toHaveProperty('unsupportedFeatures');
      expect(Array.isArray(analysis.unsupportedFeatures)).toBe(true);
    });

    it('each unsupported feature has required fields', async () => {
      const withExternalRef = `
openapi: 3.1.0
info:
  title: With ref
  version: 1.0.0
components:
  schemas:
    A:
      type: object
      properties:
        ext:
          $ref: 'https://example.com/schema.json#/External'
`;
      const analysis = await analyzeSpecification(withExternalRef, 'spec.yaml');
      expect(analysis.unsupportedFeatures.length).toBeGreaterThan(0);
      analysis.unsupportedFeatures.forEach((f: UnsupportedFeature) => {
        expect(f).toHaveProperty('id');
        expect(typeof f.id).toBe('string');
        expect(f.id.length).toBeGreaterThan(0);
        expect(f).toHaveProperty('label');
        expect(typeof f.label).toBe('string');
        expect(f).toHaveProperty('description');
        expect(typeof f.description).toBe('string');
        expect(f).toHaveProperty('severity');
        expect(['warning', 'info']).toContain(f.severity);
      });
    });
  });

  describe('no unsupported features', () => {
    it('returns empty unsupportedFeatures for minimal valid OpenAPI with simple schemas', async () => {
      const minimal = `
openapi: 3.1.0
info:
  title: Simple API
  version: 1.0.0
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
        name:
          type: string
`;
      const analysis = await analyzeSpecification(minimal, 'minimal.yaml');
      expect(analysis.unsupportedFeatures).toEqual([]);
    });
  });

  describe('external references', () => {
    it('detects external $ref and reports external-refs with warning severity', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: External refs
  version: 1.0.0
components:
  schemas:
    A:
      type: object
      properties:
        ref1:
          $ref: 'https://example.com/schema.json#/External'
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'external-refs');
      expect(f).toBeDefined();
      expect(f?.severity).toBe('warning');
      expect(f?.count).toBe(1);
    });

    it('counts multiple external refs', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Multiple refs
  version: 1.0.0
components:
  schemas:
    A:
      type: object
      properties:
        a:
          $ref: 'https://a.com/s.json'
        b:
          $ref: 'https://b.com/s.json'
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'external-refs');
      expect(f).toBeDefined();
      expect(f?.count).toBe(2);
    });

    it('does not report in-document $ref as unsupported', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Local refs
  version: 1.0.0
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
    RefUser:
      type: object
      properties:
        user:
          $ref: '#/components/schemas/User'
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'external-refs');
      expect(f).toBeUndefined();
    });
  });

  describe('custom extensions (x-) (#574)', () => {
    it('lists all x- custom extensions in metrics and reports in unsupportedFeatures', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: With extensions
  version: 1.0.0
  x-api-owner: platform
paths:
  /users:
    x-rate-limit: 100
    get:
      summary: List users
      x-internal: true
      responses:
        '200':
          description: OK
components:
  schemas:
    User:
      type: object
      x-schema-version: "1"
      properties:
        id:
          type: string
          x-field-hint: optional
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      expect(analysis.metrics.customExtensions).toBeDefined();
      expect(Array.isArray(analysis.metrics.customExtensions)).toBe(true);
      const extSet = new Set(analysis.metrics.customExtensions);
      expect(extSet.has('x-api-owner')).toBe(true);
      expect(extSet.has('x-rate-limit')).toBe(true);
      expect(extSet.has('x-internal')).toBe(true);
      expect(extSet.has('x-schema-version')).toBe(true);
      expect(extSet.has('x-field-hint')).toBe(true);
      expect(analysis.metrics.customExtensions.length).toBe(5);

      const f = analysis.unsupportedFeatures.find(x => x.id === 'custom-extensions');
      expect(f).toBeDefined();
      expect(f?.label).toBe('Custom extensions (x-)');
      expect(f?.severity).toBe('info');
      expect(f?.count).toBe(5);
    });

    it('does not report custom-extensions when spec has no x- fields', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: No extensions
  version: 1.0.0
components:
  schemas:
    Foo:
      type: object
      properties:
        id:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      expect(analysis.metrics.customExtensions).toEqual([]);
      const f = analysis.unsupportedFeatures.find(x => x.id === 'custom-extensions');
      expect(f).toBeUndefined();
    });

    it('deduplicates extension names when same x- appears in multiple places', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Dupes
  version: 1.0.0
  x-tag: info
paths:
  /a:
    x-tag: path
    get:
      x-tag: op
      responses:
        '200':
          description: OK
components:
  schemas:
    S:
      type: object
      x-tag: schema
      properties:
        p:
          type: string
          x-tag: prop
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      expect(analysis.metrics.customExtensions).toContain('x-tag');
      expect(analysis.metrics.customExtensions.filter((e: string) => e === 'x-tag')).toHaveLength(1);
      const f = analysis.unsupportedFeatures.find(x => x.id === 'custom-extensions');
      expect(f?.count).toBe(1);
    });

    it('finds x- extensions in nested structures (responses, requestBody, etc.)', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Nested
  version: 1.0.0
paths:
  /post:
    post:
      requestBody:
        content:
          application/json:
            schema:
              type: object
              x-request-schema: true
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                x-response-schema: true
components:
  schemas:
    Dummy:
      type: object
      properties: {}
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const extSet = new Set(analysis.metrics.customExtensions);
      expect(extSet.has('x-request-schema')).toBe(true);
      expect(extSet.has('x-response-schema')).toBe(true);
      expect(analysis.unsupportedFeatures.some((x: UnsupportedFeature) => x.id === 'custom-extensions')).toBe(true);
    });

    it('detects x- extensions in OpenAPI 3.0 spec after conversion to 3.1', async () => {
      const spec = `
openapi: 3.0.3
info:
  title: OAS3
  version: 1.0.0
  x-oas3-extension: true
paths:
  /health:
    get:
      summary: Health
      responses:
        '200':
          description: OK
components:
  schemas:
    Empty:
      type: object
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      expect(analysis.metrics.customExtensions).toContain('x-oas3-extension');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'custom-extensions');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });

    it('detects x- extensions in Swagger 2.0 spec after conversion to OpenAPI 3.1', async () => {
      // Swagger converter preserves x- on definitions (via convertSchema spread); top-level info x- are not copied
      const spec = `
swagger: "2.0"
info:
  title: Swagger with x-
  version: 1.0.0
paths:
  /ping:
    get:
      summary: Ping
      responses:
        200:
          description: OK
definitions:
  Empty:
    type: object
    x-definition-extension: true
  Other:
    type: object
    x-another-extension: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const extSet = new Set(analysis.metrics.customExtensions);
      expect(extSet.has('x-definition-extension')).toBe(true);
      expect(extSet.has('x-another-extension')).toBe(true);
      const f = analysis.unsupportedFeatures.find(x => x.id === 'custom-extensions');
      expect(f).toBeDefined();
      expect(f?.count).toBe(2);
    });

    it('custom-extensions feature has expected label and description', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Label check
  version: 1.0.0
  x-test: true
components:
  schemas:
    S:
      type: object
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'custom-extensions');
      expect(f).toBeDefined();
      expect(f?.label).toBe('Custom extensions (x-)');
      expect(f?.description).toContain('x-');
      expect(f?.description.length).toBeGreaterThan(10);
    });

    it('metrics.customExtensions contains only x- prefixed names', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Prefix check
  version: 1.0.0
  x-valid: true
  x-another: true
components:
  schemas:
    S:
      type: object
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      analysis.metrics.customExtensions.forEach((name: string) => {
        expect(name).toMatch(/^x-/);
      });
      expect(analysis.metrics.customExtensions.length).toBe(2);
    });
  });

  describe('variant-type schemas (oneOf/anyOf only)', () => {
    it('detects oneOf-only schema with no properties', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Variant
  version: 1.0.0
components:
  schemas:
    StringOrInt:
      oneOf:
        - type: string
        - type: integer
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'oneof-anyof-only');
      expect(f).toBeDefined();
      expect(f?.severity).toBe('warning');
      expect(f?.count).toBe(1);
    });

    it('detects anyOf-only schema', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: AnyOf
  version: 1.0.0
components:
  schemas:
    Flexible:
      anyOf:
        - type: string
        - type: number
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'oneof-anyof-only');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });

    it('does not flag schema with oneOf and inline properties', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Mixed
  version: 1.0.0
components:
  schemas:
    WithProps:
      type: object
      properties:
        id:
          type: string
      oneOf:
        - type: object
          properties:
            kind:
              type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'oneof-anyof-only');
      expect(f).toBeUndefined();
    });
  });

  describe('conditional schemas (if/then/else)', () => {
    it('detects if/then/else in schema', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Conditional
  version: 1.0.0
components:
  schemas:
    Conditional:
      type: object
      if:
        properties:
          type:
            const: A
      then:
        required: [name]
      properties:
        type:
          type: string
        name:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'conditional-schemas');
      expect(f).toBeDefined();
      expect(f?.severity).toBe('info');
      expect((f?.count ?? 0)).toBeGreaterThan(0);
    });
  });

  describe('patternProperties', () => {
    it('detects patternProperties in schema', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Pattern props
  version: 1.0.0
components:
  schemas:
    WithPattern:
      type: object
      properties:
        id:
          type: string
      patternProperties:
        "^x-":
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'pattern-properties');
      expect(f).toBeDefined();
      expect(f?.severity).toBe('info');
    });
  });

  describe('discriminator', () => {
    it('detects discriminator on schema', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Discriminator
  version: 1.0.0
components:
  schemas:
    Polymorphic:
      type: object
      discriminator:
        propertyName: kind
      properties:
        kind:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'discriminator');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.path).toBeDefined();
    });
  });

  describe('callbacks', () => {
    it('detects operation callbacks', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Callbacks
  version: 1.0.0
paths:
  /subscribe:
    post:
      summary: Subscribe
      callbacks:
        onData:
          "{$request.body#/url}":
            post:
              summary: Callback
components:
  schemas:
    Empty:
      type: object
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'callbacks');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.path).toBe('paths');
    });
  });

  describe('webhooks', () => {
    it('detects webhooks section (OpenAPI 3.1)', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Webhooks
  version: 1.0.0
webhooks:
  onEvent:
    post:
      summary: Webhook
components:
  schemas:
    Empty:
      type: object
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'webhooks');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.path).toBe('webhooks');
    });
  });

  describe('readOnly / writeOnly', () => {
    it('detects readOnly on property', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: ReadOnly
  version: 1.0.0
components:
  schemas:
    Entity:
      type: object
      properties:
        id:
          type: string
          readOnly: true
        name:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'readonly-writeonly');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.severity).toBe('info');
    });

    it('detects writeOnly on property', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: WriteOnly
  version: 1.0.0
components:
  schemas:
    Credentials:
      type: object
      properties:
        password:
          type: string
          writeOnly: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'readonly-writeonly');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });
  });

  describe('multiple unsupported features', () => {
    it('reports all applicable features in one analysis', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Many features
  version: 1.0.0
webhooks:
  w1:
    post:
      summary: W1
paths:
  /p:
    post:
      callbacks:
        c1:
          "https://example.com":
            post: {}
components:
  schemas:
    Variant:
      oneOf:
        - type: string
        - type: integer
    WithExtRef:
      type: object
      properties:
        ext:
          $ref: 'https://example.com/schema.json'
    WithDiscriminator:
      type: object
      discriminator:
        propertyName: type
      properties:
        type:
          type: string
    WithReadOnly:
      type: object
      properties:
        id:
          type: string
          readOnly: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');

      expect(analysis.unsupportedFeatures.length).toBeGreaterThanOrEqual(4);

      expect(analysis.unsupportedFeatures.some(x => x.id === 'external-refs')).toBe(true);
      expect(analysis.unsupportedFeatures.some(x => x.id === 'oneof-anyof-only')).toBe(true);
      expect(analysis.unsupportedFeatures.some(x => x.id === 'discriminator')).toBe(true);
      expect(analysis.unsupportedFeatures.some(x => x.id === 'callbacks')).toBe(true);
      expect(analysis.unsupportedFeatures.some(x => x.id === 'webhooks')).toBe(true);
      expect(analysis.unsupportedFeatures.some(x => x.id === 'readonly-writeonly')).toBe(true);
    });
  });

  describe('converted formats', () => {
    it('reports unsupported features on Swagger 2 converted to OpenAPI 3.1', async () => {
      const swagger = `
swagger: "2.0"
info:
  title: Swagger with external ref
  version: 1.0.0
definitions:
  Model:
    type: object
    properties:
      ref:
        $ref: 'https://other.com/schema.json'
`;
      const analysis = await analyzeSpecification(swagger, 'swagger.yaml');
      expect(analysis.format === 'swagger' || analysis.format === 'openapi').toBe(true);
      expect(analysis.unsupportedFeatures).toBeDefined();
      const f = analysis.unsupportedFeatures.find(x => x.id === 'external-refs');
      expect(f).toBeDefined();
    });
  });

  describe('Deprecated constructs (#575)', () => {
    it('does not report deprecated features when none present', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: No deprecated
  version: 1.0.0
paths:
  /users:
    get:
      summary: List users
      responses:
        "200":
          description: OK
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      expect(analysis.unsupportedFeatures.filter(f => f.id.startsWith('deprecated-'))).toEqual([]);
    });

    it('flags deprecated operations with deprecated-operations', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Deprecated ops
  version: 1.0.0
paths:
  /legacy:
    get:
      deprecated: true
      summary: Old endpoint
      responses:
        "200":
          description: OK
  /new:
    get:
      summary: New endpoint
      responses:
        "200":
          description: OK
  /old:
    post:
      deprecated: true
      summary: Old post
      responses:
        "201":
          description: Created
components:
  schemas: {}
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-operations');
      expect(f).toBeDefined();
      expect(f?.count).toBe(2);
      expect(f?.severity).toBe('warning');
    });

    it('flags deprecated parameters with deprecated-parameters', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Deprecated params
  version: 1.0.0
paths:
  /search:
    get:
      parameters:
        - name: q
          in: query
          schema:
            type: string
        - name: legacy
          in: query
          deprecated: true
          schema:
            type: string
      responses:
        "200":
          description: OK
components:
  schemas: {}
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-parameters');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.severity).toBe('warning');
    });

    it('flags deprecated schemas with deprecated-schemas', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Deprecated schema
  version: 1.0.0
components:
  schemas:
    OldModel:
      deprecated: true
      type: object
      properties:
        id:
          type: string
    NewModel:
      type: object
      properties:
        id:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-schemas');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.severity).toBe('warning');
    });

    it('flags deprecated schema properties with deprecated-properties', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Deprecated props
  version: 1.0.0
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
        legacyField:
          type: string
          deprecated: true
        name:
          type: string
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-properties');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.severity).toBe('warning');
    });

    it('flags deprecated nullable keyword with deprecated-nullable', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Nullable usage
  version: 1.0.0
components:
  schemas:
    WithNull:
      type: object
      properties:
        opt:
          type: string
          nullable: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-nullable');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
      expect(f?.severity).toBe('warning');
      expect(f?.description).toMatch(/type:.*null/i);
    });

    it('reports multiple deprecated construct types in one analysis', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Multiple deprecated
  version: 1.0.0
paths:
  /old:
    get:
      deprecated: true
      parameters:
        - name: legacy
          in: query
          deprecated: true
          schema:
            type: string
      responses:
        "200":
          description: OK
components:
  schemas:
    DeprecatedSchema:
      deprecated: true
      type: object
      properties:
        oldProp:
          type: string
          deprecated: true
        opt:
          type: string
          nullable: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      expect(analysis.unsupportedFeatures.find(x => x.id === 'deprecated-operations')).toBeDefined();
      expect(analysis.unsupportedFeatures.find(x => x.id === 'deprecated-parameters')).toBeDefined();
      expect(analysis.unsupportedFeatures.find(x => x.id === 'deprecated-schemas')).toBeDefined();
      expect(analysis.unsupportedFeatures.find(x => x.id === 'deprecated-properties')).toBeDefined();
      expect(analysis.unsupportedFeatures.find(x => x.id === 'deprecated-nullable')).toBeDefined();
    });

    it('counts path-level deprecated parameters', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Path-level params
  version: 1.0.0
paths:
  /items/{id}:
    parameters:
      - name: id
        in: path
        required: true
        schema:
          type: string
      - name: legacy
        in: query
        deprecated: true
        schema:
          type: string
    get:
      responses:
        "200":
          description: OK
components:
  schemas: {}
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-parameters');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });

    it('counts deprecated parameters in components.parameters', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Reusable deprecated param
  version: 1.0.0
paths:
  /search:
    get:
      parameters:
        - $ref: '#/components/parameters/LegacyQuery'
      responses:
        "200":
          description: OK
components:
  parameters:
    LegacyQuery:
      name: legacy
      in: query
      deprecated: true
      schema:
        type: string
  schemas: {}
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-parameters');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });

    it('counts multiple deprecated properties correctly', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Two deprecated props
  version: 1.0.0
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
        old1:
          type: string
          deprecated: true
        old2:
          type: integer
          deprecated: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-properties');
      expect(f).toBeDefined();
      expect(f?.count).toBe(2);
    });

    it('counts multiple nullable usages correctly', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Multiple nullable
  version: 1.0.0
components:
  schemas:
    A:
      type: object
      properties:
        a:
          type: string
          nullable: true
        b:
          type: integer
          nullable: true
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-nullable');
      expect(f).toBeDefined();
      expect(f?.count).toBe(2);
    });

    it('deprecated feature entries have required fields (id, label, description, severity)', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Deprecated check shape
  version: 1.0.0
paths:
  /x:
    get:
      deprecated: true
      responses:
        "200":
          description: OK
components:
  schemas: {}
`;
      const analysis = await analyzeSpecification(spec, 'spec.yaml');
      const deprecatedFeatures = analysis.unsupportedFeatures.filter(f => f.id.startsWith('deprecated-'));
      expect(deprecatedFeatures.length).toBeGreaterThan(0);
      deprecatedFeatures.forEach((f: UnsupportedFeature) => {
        expect(f.id).toBeDefined();
        expect(typeof f.id).toBe('string');
        expect(f.label).toBeDefined();
        expect(typeof f.label).toBe('string');
        expect(f.description).toBeDefined();
        expect(typeof f.description).toBe('string');
        expect(f.severity).toBe('warning');
      });
    });

    it('flags deprecated operations in Swagger 2.0 spec after conversion to OpenAPI 3.1', async () => {
      const swagger = `
swagger: "2.0"
info:
  title: Swagger deprecated op
  version: 1.0.0
paths:
  /legacy:
    get:
      deprecated: true
      responses:
        200:
          description: OK
definitions: {}
`;
      const analysis = await analyzeSpecification(swagger, 'swagger.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-operations');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });

    it('flags deprecated schema in definitions (Swagger 2 / converted)', async () => {
      const swagger = `
swagger: "2.0"
info:
  title: Swagger deprecated schema
  version: 1.0.0
paths: {}
definitions:
  OldDef:
    deprecated: true
    type: object
    properties:
      id:
        type: string
`;
      const analysis = await analyzeSpecification(swagger, 'swagger.yaml');
      const f = analysis.unsupportedFeatures.find(x => x.id === 'deprecated-schemas');
      expect(f).toBeDefined();
      expect(f?.count).toBe(1);
    });
  });
});
