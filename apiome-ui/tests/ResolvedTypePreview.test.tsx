/**
 * Tests for ResolvedTypePreview (#3476).
 *
 * Covers resolving a bound type by its FK (fetching the primitive), rendering
 * the effective type / format / constraints, validating an example value live
 * (the acceptance criterion: "a bound property shows its resolved type; an
 * example value validates"), and the no-binding / error paths.
 *
 * This is a thin standalone component (it is NOT the ClassPropertyEditDialog,
 * which cannot be unit-rendered under jsdom), so it renders safely here.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ResolvedTypePreview } from '../src/app/components/ade/studio/ResolvedTypePreview';

const dateSchema = { type: 'string', format: 'date' };

const mockFetchPrimitive = (schema: Record<string, unknown>, namespace = 'std/v0/types', name = 'date') => {
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: true,
    json: async () => ({
      success: true,
      primitive: { id: 'core-date', name, namespace, schema },
    }),
  });
};

describe('ResolvedTypePreview', () => {
  beforeAll(() => {
    global.fetch = jest.fn();
  });

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders nothing when the property has no binding', () => {
    const { container } = render(<ResolvedTypePreview />);
    expect(container).toBeEmptyDOMElement();
  });

  it('fetches the primitive by id and shows the resolved type, format and ref', async () => {
    mockFetchPrimitive(dateSchema);
    render(<ResolvedTypePreview propertyRef="std/v0/types/date" primitiveId="core-date" />);

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/primitives/core-date'),
    );
    expect(await screen.findByText('std/v0/types/date')).toBeInTheDocument();
    expect(await screen.findByText('string')).toBeInTheDocument();
    expect(screen.getByText('format: date')).toBeInTheDocument();
  });

  it('uses a directly-provided schema without fetching', async () => {
    render(
      <ResolvedTypePreview
        propertyRef="tenant/acme/types/sku"
        schema={{ type: 'string', pattern: '^[A-Z0-9-]+$' }}
      />,
    );
    expect(await screen.findByText('pattern: ^[A-Z0-9-]+$')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('validates a valid example value against the resolved type', async () => {
    render(<ResolvedTypePreview propertyRef="std/v0/types/date" schema={dateSchema} />);

    const input = await screen.findByLabelText(/try an example value/i);
    fireEvent.change(input, { target: { value: '2026-06-23' } });

    expect(await screen.findByText(/valid against the resolved type/i)).toBeInTheDocument();
  });

  it('reports an invalid example value', async () => {
    render(<ResolvedTypePreview propertyRef="std/v0/types/date" schema={dateSchema} />);

    const input = await screen.findByLabelText(/try an example value/i);
    fireEvent.change(input, { target: { value: 'not-a-date' } });

    await waitFor(() =>
      expect(input).toHaveAttribute('aria-invalid', 'true'),
    );
    // The valid message must not be shown for a bad value.
    expect(screen.queryByText(/valid against the resolved type/i)).not.toBeInTheDocument();
  });

  it('surfaces a resolution error when the fetch fails', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, json: async () => ({}) });
    render(<ResolvedTypePreview propertyRef="std/v0/types/date" primitiveId="core-date" />);

    expect(await screen.findByText(/failed to resolve bound type/i)).toBeInTheDocument();
  });
});
