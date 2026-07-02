import {
  buildBaseChain,
  buildExampleInstance,
  deriveOwner,
  deriveVersionRoot,
  exportFileName,
  scopeLabel,
  serializeSchemaExport,
  summarizeUsage,
} from '../src/app/ade/dashboard/primitives/primitiveDetailModel';

describe('primitiveDetailModel helpers', () => {
  describe('buildBaseChain', () => {
    it('starts with the type itself then one node per ref edge', () => {
      const chain = buildBaseChain('money', [
        { relative_ref: './decimal', resolved_target: 'std/v0/types/decimal', status: 'resolved' },
        { relative_ref: './currency-code', resolved_target: 'std/v0/types/currency-code', status: 'resolved' },
      ]);
      expect(chain).toHaveLength(3);
      expect(chain[0]).toEqual({ label: 'money', kind: 'self' });
      expect(chain[1]).toMatchObject({ label: './decimal', target: 'std/v0/types/decimal', kind: 'ref', status: 'resolved' });
      expect(chain[2].label).toBe('./currency-code');
    });

    it('returns only the self node when there are no refs', () => {
      expect(buildBaseChain('decimal')).toEqual([{ label: 'decimal', kind: 'self' }]);
      expect(buildBaseChain('decimal', [])).toEqual([{ label: 'decimal', kind: 'self' }]);
    });

    it('skips edges that have no relative_ref', () => {
      const chain = buildBaseChain('money', [{ resolved_target: 'x' }, { relative_ref: './ok' }]);
      expect(chain).toHaveLength(2);
      expect(chain[1].label).toBe('./ok');
    });
  });

  describe('deriveVersionRoot', () => {
    it('reads the version segment from a namespace path', () => {
      expect(deriveVersionRoot('std/v0/types')).toBe('v0');
      expect(deriveVersionRoot('tenant/acme/v12/payments')).toBe('v12');
    });

    it('falls back to the base URI when namespace is empty', () => {
      expect(deriveVersionRoot(null, 'https://api.apiome.app/types/std/v0/types/')).toBe('v0');
    });

    it('returns null when no version root is present', () => {
      expect(deriveVersionRoot('std/types')).toBeNull();
      expect(deriveVersionRoot(null, null)).toBeNull();
    });
  });

  describe('scopeLabel / deriveOwner', () => {
    it('labels scope by system flag', () => {
      expect(scopeLabel(true)).toBe('System · core');
      expect(scopeLabel(false)).toBe('Tenant');
    });

    it('derives owner from system flag or tenant namespace', () => {
      expect(deriveOwner(true, 'std/v0/types')).toBe('system');
      expect(deriveOwner(false, 'tenant/acme/v1/payments')).toBe('acme');
      expect(deriveOwner(false, null)).toBe('tenant');
    });
  });

  describe('summarizeUsage', () => {
    it('counts dependent types, properties, and distinct tenants', () => {
      const summary = summarizeUsage(
        [
          { scope: 'tenant', tenant_label: 'acme', property: 'amount' },
          { scope: 'tenant', tenant_label: 'acme', property: 'total' },
          { scope: 'tenant', tenant_label: 'globex', property: 'grandTotal' },
          { scope: 'system', name: 'core-type' },
        ],
        11
      );
      expect(summary).toEqual({ dependentTypes: 4, properties: 11, tenants: 2 });
    });

    it('degrades to zero dependents/tenants when the reverse index is empty', () => {
      expect(summarizeUsage(undefined, 3)).toEqual({ dependentTypes: 0, properties: 3, tenants: 0 });
      expect(summarizeUsage([], -5)).toEqual({ dependentTypes: 0, properties: 0, tenants: 0 });
    });
  });

  describe('exportFileName / serializeSchemaExport', () => {
    it('slugifies the type name into a safe filename', () => {
      expect(exportFileName('Money')).toBe('money.schema.json');
      expect(exportFileName('US Dollar (amount)')).toBe('us-dollar-amount.schema.json');
      expect(exportFileName('   ')).toBe('primitive.schema.json');
    });

    it('pretty-prints the schema document', () => {
      expect(serializeSchemaExport({ type: 'string' })).toBe('{\n  "type": "string"\n}');
      expect(serializeSchemaExport(undefined)).toBe('{}');
    });
  });

  describe('buildExampleInstance', () => {
    it('prefers an explicit examples entry', () => {
      expect(buildExampleInstance({ type: 'string', examples: ['USD', 'EUR'] })).toBe('USD');
    });

    it('falls back to default, then const, then enum', () => {
      expect(buildExampleInstance({ type: 'number', default: 42 })).toBe(42);
      expect(buildExampleInstance({ const: 'fixed' })).toBe('fixed');
      expect(buildExampleInstance({ enum: ['a', 'b'] })).toBe('a');
    });

    it('derives values from primitive types', () => {
      expect(buildExampleInstance({ type: 'string' })).toBe('string');
      expect(buildExampleInstance({ type: 'string', format: 'date' })).toBe('date');
      expect(buildExampleInstance({ type: 'integer' })).toBe(0);
      expect(buildExampleInstance({ type: 'boolean' })).toBe(true);
      expect(buildExampleInstance({ type: 'array' })).toEqual([]);
      expect(buildExampleInstance({ type: 'null' })).toBeNull();
    });

    it('walks object properties and omits unresolvable $ref-only properties', () => {
      const example = buildExampleInstance({
        type: 'object',
        properties: {
          label: { type: 'string' },
          amount: { $ref: './decimal' },
        },
      });
      expect(example).toEqual({ label: 'string' });
    });

    it('keeps an explicit null-typed property', () => {
      const example = buildExampleInstance({
        type: 'object',
        properties: { note: { type: 'null' }, name: { type: 'string' } },
      });
      expect(example).toEqual({ note: null, name: 'string' });
    });

    it('returns null when no meaningful example can be produced', () => {
      expect(buildExampleInstance({ $ref: './decimal' })).toBeNull();
      expect(buildExampleInstance({ type: 'object', properties: { a: { $ref: './x' } } })).toBeNull();
      expect(buildExampleInstance(null)).toBeNull();
      expect(buildExampleInstance('not-an-object')).toBeNull();
    });
  });
});
