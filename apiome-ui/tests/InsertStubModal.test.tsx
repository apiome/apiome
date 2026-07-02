/**
 * Unit tests for InsertStubModal (database insert record modal).
 * Covers schema loading, initial form data with defaults, and insert API call.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import InsertStubModal from '../src/app/ade/database/components/InsertStubModal';

const mockSchema = {
  type: 'object',
  properties: {
    name: { type: 'string', default: 'Default Name', title: 'Name' },
    count: { type: 'integer', default: 42 },
    active: { type: 'boolean', default: true },
    status: { type: 'string', enum: ['draft', 'published'], default: 'draft' },
  },
  required: ['name'],
};

describe('InsertStubModal', () => {
  const defaultProps = {
    open: true,
    onClose: jest.fn(),
    tableName: 'TestTable',
    classSchemaId: 'schema-id-123',
    onInserted: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn();
  });

  test('fetches schema when opened with classSchemaId', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, schema: mockSchema, class_name: 'TestTable' }),
    });

    render(<InsertStubModal {...defaultProps} />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/database/schema?classSchemaId=schema-id-123'
      );
    });
  });

  test('shows loading then form when schema loads', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, schema: mockSchema, class_name: 'TestTable' }),
    });

    render(<InsertStubModal {...defaultProps} />);

    expect(screen.getByText(/Loading schema/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/Loading schema/i)).not.toBeInTheDocument();
    });

    expect(screen.getByText('Insert record')).toBeInTheDocument();
    expect(screen.getByText(/TestTable/)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /form/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /json/i })).toBeInTheDocument();
  });

  test('pre-fills form with schema default values', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, schema: mockSchema, class_name: 'TestTable' }),
    });

    render(<InsertStubModal {...defaultProps} />);

    await waitFor(() => {
      expect(screen.queryByText(/Loading schema/i)).not.toBeInTheDocument();
    });

    const formTab = screen.getByRole('tab', { name: /form/i });
    expect(formTab).toBeInTheDocument();

    const nameInput = screen.getByLabelText(/name/i);
    expect(nameInput).toHaveValue('Default Name');

    const countInput = screen.getByLabelText(/count/i);
    expect(countInput).toHaveValue(42);

    const activeCheckbox = screen.getByRole('checkbox');
    expect(activeCheckbox).toBeChecked();
  });

  test('shows schema error when fetch fails', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

    render(<InsertStubModal {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText(/Failed to load schema|Network error/i)).toBeInTheDocument();
    });
  });

  test('calls onInserted and POST insert with form data on submit', async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, schema: mockSchema, class_name: 'TestTable' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, record_id: 'new-record-id' }),
      });

    render(<InsertStubModal {...defaultProps} />);

    await waitFor(() => {
      expect(screen.queryByText(/Loading schema/i)).not.toBeInTheDocument();
    });

    const insertButton = screen.getByRole('button', { name: /^insert$/i });
    expect(insertButton).toBeInTheDocument();
    await userEvent.click(insertButton);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    const postCall = (global.fetch as jest.Mock).mock.calls[1];
    expect(postCall[0]).toBe('/api/database/snapshot/insert');
    expect(postCall[1]).toMatchObject({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const body = JSON.parse(postCall[1].body);
    expect(body.classSchemaId).toBe('schema-id-123');
    expect(body.data).toMatchObject({
      name: 'Default Name',
      count: 42,
      active: true,
      status: 'draft',
    });

    expect(defaultProps.onInserted).toHaveBeenCalled();
    expect(defaultProps.onClose).toHaveBeenCalled();
  });

  test('does not fetch when open is false', () => {
    render(<InsertStubModal {...defaultProps} open={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test('JSON tab shows stringified form data', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, schema: mockSchema, class_name: 'TestTable' }),
    });

    render(<InsertStubModal {...defaultProps} />);

    await waitFor(() => {
      expect(screen.queryByText(/Loading schema/i)).not.toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('tab', { name: /json/i }));

    await waitFor(() => {
      const textarea = document.querySelector('textarea[placeholder*="key"]');
      expect(textarea).toBeInTheDocument();
      expect((textarea as HTMLTextAreaElement).value).toContain('Default Name');
      expect((textarea as HTMLTextAreaElement).value).toContain('42');
    });
  });
});
