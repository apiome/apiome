/**
 * Tests for the PrimitiveSelector type picker (#3474).
 *
 * Covers the scope-classification + `$ref` helpers and the rendered picker:
 * Standard / Core / Tenant / Custom tabs, selecting `std/v0/types/date` emitting
 * a stable `$ref`, tenant scoping, the bound-type chip, and legacy (namespace-less)
 * primitives that bind by inline schema only.
 */

import React, { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
  PrimitiveSelector,
  classifyPrimitive,
  buildTypeRef,
  Primitive,
} from '../src/app/components/ade/studio/PrimitiveSelector';
import { PropertyFormData } from '../src/app/components/ade/studio/PropertyFormFields';

// Mock the useDarkMode hook (same module the component imports via `@/`).
jest.mock('../src/app/hooks/useDarkMode', () => ({
  useDarkMode: () => false,
}));

// Radix Dialog needs a few browser APIs jsdom does not implement.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = () => {};
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = () => {};
  }
  Element.prototype.scrollIntoView = () => {};
});

// Helper to build a fully-populated Primitive with sensible defaults.
const makePrimitive = (overrides: Partial<Primitive>): Primitive => ({
  id: 'id-' + Math.random().toString(36).slice(2),
  tenant_id: 'tenant-1',
  name: 'thing',
  description: 'A thing',
  category: 'string',
  schema: { type: 'string' },
  tags: [],
  created_by: null,
  is_system: false,
  is_public: false,
  usage_count: 0,
  enabled: true,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  namespace: null,
  base_uri: null,
  schema_id: null,
  draft: '2020-12',
  source: 'human',
  refs: [],
  ...overrides,
});

// A string-category type for each of the four scopes.
const stdString = makePrimitive({
  id: 'std-string',
  name: 'string',
  description: 'JSON Schema base string type.',
  is_system: true,
  is_public: true,
  namespace: 'std/v0/primitives',
  schema: { type: 'string' },
});

const coreDate = makePrimitive({
  id: 'core-date',
  name: 'date',
  description: 'Calendar date (ISO 8601).',
  is_system: true,
  is_public: true,
  namespace: 'std/v0/types',
  schema: { type: 'string', format: 'date' },
});

const legacyEmail = makePrimitive({
  id: 'legacy-email',
  name: 'Email Address',
  description: 'RFC 5322 email address.',
  is_system: true,
  is_public: true,
  namespace: null, // legacy flat primitive — no stable $ref
  schema: { type: 'string', format: 'email' },
});

const tenantSku = makePrimitive({
  id: 'tenant-sku',
  name: 'sku',
  description: 'Stock keeping unit.',
  is_system: false,
  source: 'human',
  namespace: 'tenant/acme/types',
  schema: { type: 'string', pattern: '^[A-Z0-9-]+$' },
});

const customHumanName = makePrimitive({
  id: 'custom-humanname',
  name: 'HumanName',
  description: 'Imported FHIR HumanName.',
  is_system: false,
  source: 'imported',
  namespace: 'vendor/fhir/r4',
  schema: { type: 'string' },
});

const ALL = [stdString, coreDate, legacyEmail, tenantSku, customHumanName];

// Stateful harness so the bound-type chip reflects onChange updates.
const Harness: React.FC<{
  onChangeSpy?: (field: keyof PropertyFormData, value: unknown) => void;
  onTypeBound?: jest.Mock;
  initial?: PropertyFormData;
}> = ({ onChangeSpy, onTypeBound, initial }) => {
  const [formData, setFormData] = useState<PropertyFormData>(initial || {});
  return (
    <PrimitiveSelector
      formData={formData}
      onChange={(field, value) => {
        onChangeSpy?.(field, value);
        setFormData((prev) => ({ ...prev, [field]: value }));
      }}
      propertyType="string"
      onTypeBound={onTypeBound}
    />
  );
};

const mockFetchOk = (primitives: Primitive[]) => {
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: true,
    json: async () => ({ success: true, primitives }),
  });
};

describe('classifyPrimitive', () => {
  it('classifies system /primitives rows as standard', () => {
    expect(classifyPrimitive(stdString)).toBe('standard');
  });

  it('classifies other system rows as core (incl. legacy flat ones)', () => {
    expect(classifyPrimitive(coreDate)).toBe('core');
    expect(classifyPrimitive(legacyEmail)).toBe('core');
  });

  it('classifies tenant-authored rows as tenant', () => {
    expect(classifyPrimitive(tenantSku)).toBe('tenant');
  });

  it('classifies imported tenant rows as custom', () => {
    expect(classifyPrimitive(customHumanName)).toBe('custom');
  });
});

describe('buildTypeRef', () => {
  it('joins namespace and name into a stable $ref', () => {
    expect(buildTypeRef(coreDate)).toBe('std/v0/types/date');
    expect(buildTypeRef(tenantSku)).toBe('tenant/acme/types/sku');
    expect(buildTypeRef(customHumanName)).toBe('vendor/fhir/r4/HumanName');
  });

  it('tolerates trailing slashes on the namespace', () => {
    expect(buildTypeRef(makePrimitive({ namespace: 'std/v0/types/', name: 'uuid' }))).toBe('std/v0/types/uuid');
  });

  it('returns null for primitives with no namespace', () => {
    expect(buildTypeRef(legacyEmail)).toBeNull();
  });
});

describe('PrimitiveSelector type picker', () => {
  beforeAll(() => {
    global.fetch = jest.fn();
  });

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchOk(ALL);
  });

  const openPicker = async () => {
    fireEvent.click(screen.getByRole('button', { name: /select type/i }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  };

  it('renders the four scope tabs when opened', async () => {
    render(<Harness />);
    await openPicker();

    expect(await screen.findByRole('tab', { name: /standard/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /core system types/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /tenant types/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /custom · imported/i })).toBeInTheDocument();
  });

  it('fetches primitives filtered by the property category', async () => {
    render(<Harness />);
    await openPicker();
    expect(global.fetch).toHaveBeenCalledWith('/api/primitives?category=string');
  });

  it('selecting std/v0/types/date sets the $ref on the property and emits a binding', async () => {
    const onChangeSpy = jest.fn();
    const onTypeBound = jest.fn();
    render(<Harness onChangeSpy={onChangeSpy} onTypeBound={onTypeBound} />);
    await openPicker();

    // Core tab is the default landing tab and holds std/v0/types/date.
    const dateRow = await screen.findByRole('button', { name: /std\/v0\/types\/date/i });
    fireEvent.click(dateRow);
    fireEvent.click(screen.getByRole('button', { name: /apply type/i }));

    await waitFor(() =>
      expect(onChangeSpy).toHaveBeenCalledWith('$ref', 'std/v0/types/date'),
    );
    expect(onTypeBound).toHaveBeenCalledWith(
      expect.objectContaining({ ref: 'std/v0/types/date' }),
    );
  });

  it('scopes tenant types under the Tenant tab and emits a tenant $ref', async () => {
    const onChangeSpy = jest.fn();
    render(<Harness onChangeSpy={onChangeSpy} />);
    await openPicker();

    fireEvent.click(await screen.findByRole('tab', { name: /tenant types/i }));
    const skuRow = await screen.findByRole('button', { name: /tenant\/acme\/types\/sku/i });
    fireEvent.click(skuRow);
    fireEvent.click(screen.getByRole('button', { name: /apply type/i }));

    await waitFor(() =>
      expect(onChangeSpy).toHaveBeenCalledWith('$ref', 'tenant/acme/types/sku'),
    );
  });

  it('lists imported types under the Custom tab', async () => {
    render(<Harness />);
    await openPicker();

    fireEvent.click(await screen.findByRole('tab', { name: /custom · imported/i }));
    expect(await screen.findByRole('button', { name: /vendor\/fhir\/r4\/HumanName/i })).toBeInTheDocument();
  });

  it('clears the $ref when binding a legacy primitive that has no namespace', async () => {
    const onChangeSpy = jest.fn();
    const onTypeBound = jest.fn();
    render(<Harness onChangeSpy={onChangeSpy} onTypeBound={onTypeBound} />);
    await openPicker();

    // legacyEmail lives under Core (system, no namespace). It still applies its
    // schema inline but records no stable $ref.
    const emailRow = await screen.findByRole('button', { name: /Email Address/i });
    fireEvent.click(emailRow);
    fireEvent.click(screen.getByRole('button', { name: /apply type/i }));

    await waitFor(() => expect(onChangeSpy).toHaveBeenCalledWith('format', 'email'));
    expect(onChangeSpy).toHaveBeenCalledWith('$ref', '');
    expect(onTypeBound).not.toHaveBeenCalled();
  });

  it('shows a bound-type chip and clears the binding on demand', async () => {
    const onChangeSpy = jest.fn();
    render(<Harness onChangeSpy={onChangeSpy} initial={{ $ref: 'std/v0/types/date' }} />);

    // The chip shows the current binding without opening the picker.
    expect(screen.getByText('std/v0/types/date')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /change type/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /clear type binding/i }));
    await waitFor(() => expect(onChangeSpy).toHaveBeenCalledWith('$ref', ''));
  });

  it('persists the resolved primitive id alongside the $ref when binding (#3475)', async () => {
    const onChangeSpy = jest.fn();
    render(<Harness onChangeSpy={onChangeSpy} />);
    await openPicker();

    const dateRow = await screen.findByRole('button', { name: /std\/v0\/types\/date/i });
    fireEvent.click(dateRow);
    fireEvent.click(screen.getByRole('button', { name: /apply type/i }));

    // Both the $ref string and the FK target (the primitive's id) are recorded
    // so the binding can round-trip through class_properties.primitive_ref/_id.
    await waitFor(() =>
      expect(onChangeSpy).toHaveBeenCalledWith('$ref', 'std/v0/types/date'),
    );
    expect(onChangeSpy).toHaveBeenCalledWith('primitive_id', 'core-date');
  });

  it('clears the primitive id for a legacy namespace-less primitive (#3475)', async () => {
    const onChangeSpy = jest.fn();
    render(<Harness onChangeSpy={onChangeSpy} />);
    await openPicker();

    const emailRow = await screen.findByRole('button', { name: /Email Address/i });
    fireEvent.click(emailRow);
    fireEvent.click(screen.getByRole('button', { name: /apply type/i }));

    // No stable $ref → no FK binding either; falls back to inline-schema merge.
    await waitFor(() => expect(onChangeSpy).toHaveBeenCalledWith('$ref', ''));
    expect(onChangeSpy).toHaveBeenCalledWith('primitive_id', '');
  });

  it('drops both the $ref and the primitive id when the binding is cleared (#3475)', async () => {
    const onChangeSpy = jest.fn();
    render(
      <Harness
        onChangeSpy={onChangeSpy}
        initial={{ $ref: 'std/v0/types/date', primitive_id: 'core-date' }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /clear type binding/i }));
    await waitFor(() => expect(onChangeSpy).toHaveBeenCalledWith('$ref', ''));
    expect(onChangeSpy).toHaveBeenCalledWith('primitive_id', '');
  });

  it('searches across namespaces within the active tab', async () => {
    render(<Harness />);
    await openPicker();

    const search = await screen.findByPlaceholderText(/search standard & custom types/i);
    // Core tab holds date + Email Address; searching the namespace narrows to date.
    fireEvent.change(search, { target: { value: 'std/v0/types' } });

    expect(await screen.findByRole('button', { name: /std\/v0\/types\/date/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Email Address/i })).not.toBeInTheDocument();
  });
});
