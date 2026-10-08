/**
 * Admin console → Property Templates, rendered for the documentation site (DOCS-1.10, #5627).
 *
 * `PropertyTemplateManagementClient` reads and writes through the server actions in
 * `lib/db/admin-helper.ts`; they are mocked here with a realistic catalogue so the screen renders
 * the way an operator sees it. Besides checking the list, the row menu and the dialogs render
 * real content, the suite writes the dumps the docs screenshots are captured from:
 *
 *     A11Y_FIXTURE_DUMP=1 npx jest tests/docs-admin-templates.test.tsx
 *
 * The screen is drawn inside the admin console's own frame — `AdminSidebar` beside the page, as
 * `admin/dashboard/layout.tsx` lays it out.
 */
import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import AdminSidebar from '../src/app/admin/dashboard/AdminSidebar';
import PropertyTemplateManagementClient from '../src/app/admin/dashboard/templates/PropertyTemplateManagementClient';
import { DialogProvider } from '../src/app/components/providers/DialogProvider';
import * as adminHelper from '../lib/db/admin-helper';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/admin/dashboard/templates',
}));

jest.mock('../lib/db/admin-helper', () => ({
  getAllPropertyTemplates: jest.fn(),
  getPropertyTemplateStats: jest.fn(),
  getPropertyTemplateCategoriesAdmin: jest.fn(),
  createPropertyTemplateAdmin: jest.fn(),
  updatePropertyTemplateAdmin: jest.fn(),
  deletePropertyTemplateAdmin: jest.fn(),
  togglePropertyTemplateStatus: jest.fn(),
}));

const helper = adminHelper as jest.Mocked<typeof adminHelper>;

/**
 * One template row as `getAllPropertyTemplates` returns it.
 *
 * @param overrides Fields that differ from a system, public, enabled identifier template.
 * @returns The row.
 */
function template(overrides: Record<string, unknown>) {
  return {
    id: 'tpl-uuid',
    name: 'UUID',
    description: 'A universally unique identifier (RFC 9562).',
    category: 'identifiers',
    schema: { type: 'string', format: 'uuid', description: 'Unique identifier', example: '3f6c2b9e-8d41-4c0a-9b7e-2a5f1d6e8c30' },
    tags: ['id', 'uuid', 'primary-key'],
    tenant_id: null,
    created_by: null,
    is_system: true,
    is_public: true,
    usage_count: 412,
    enabled: true,
    created_at: '2026-03-02T10:00:00Z',
    updated_at: '2026-08-14T16:20:00Z',
    ...overrides,
  };
}

/** A catalogue an operator might really hold: system templates plus two tenants' own. */
const DOCS_TEMPLATES = [
  template({}),
  template({
    id: 'tpl-created-at',
    name: 'Created At',
    description: 'When the record was created, in UTC.',
    category: 'timestamps',
    schema: { type: 'string', format: 'date-time', example: '2026-06-15T09:30:00Z' },
    tags: ['created', 'timestamp', 'audit'],
    usage_count: 388,
  }),
  template({
    id: 'tpl-email',
    name: 'Email',
    description: 'An email address.',
    category: 'contact',
    schema: { type: 'string', format: 'email', example: 'ada@example.com' },
    tags: ['email', 'contact'],
    usage_count: 251,
  }),
  template({
    id: 'tpl-money',
    name: 'Money Amount',
    description: 'An amount and its ISO 4217 currency code.',
    category: 'money',
    schema: {
      type: 'object',
      properties: { amount: { type: 'string', pattern: '^-?\\d+(\\.\\d{1,4})?$' }, currency: { type: 'string', pattern: '^[A-Z]{3}$' } },
      required: ['amount', 'currency'],
    },
    tags: ['money', 'currency', 'iso-4217'],
    usage_count: 97,
  }),
  template({
    id: 'tpl-cursor',
    name: 'Page Cursor',
    description: 'An opaque cursor for the next page of results.',
    category: 'pagination',
    schema: { type: 'string', example: 'eyJpZCI6MTIzfQ' },
    tags: ['cursor', 'pagination'],
    usage_count: 64,
  }),
  template({
    id: 'tpl-sku',
    name: 'Product SKU',
    description: 'Northwind stock-keeping unit: three letters, a dash, six digits.',
    category: 'retail',
    schema: { type: 'string', pattern: '^[A-Z]{3}-\\d{6}$', example: 'NWT-004211' },
    tags: ['sku', 'catalog'],
    tenant_id: 't-northwind',
    tenant_name: 'Northwind',
    created_by: 'u-priya',
    creator_name: 'Priya Raman',
    creator_email: 'priya.raman@northwind.io',
    is_system: false,
    is_public: false,
    usage_count: 23,
  }),
  template({
    id: 'tpl-legacy-id',
    name: 'Legacy Customer ID',
    description: 'Numeric id from the pre-2024 CRM; kept for old integrations.',
    category: 'identifiers',
    schema: { type: 'integer', format: 'int64', example: 1048576 },
    tags: ['legacy', 'crm'],
    tenant_id: 't-contoso',
    tenant_name: 'Contoso',
    created_by: 'u-marcus',
    creator_name: 'Marcus Lee',
    creator_email: 'marcus.lee@contoso.example',
    is_system: false,
    is_public: false,
    usage_count: 4,
    enabled: false,
  }),
];

const DOCS_STATS = {
  total_templates: 7,
  system_templates: 5,
  tenant_templates: 2,
  enabled_templates: 6,
  disabled_templates: 1,
  total_usage: 1239,
  category_count: 6,
};

const DOCS_CATEGORIES = [
  { category: 'contact', count: 1, system_count: 1, tenant_count: 0 },
  { category: 'identifiers', count: 2, system_count: 1, tenant_count: 1 },
  { category: 'money', count: 1, system_count: 1, tenant_count: 0 },
  { category: 'pagination', count: 1, system_count: 1, tenant_count: 0 },
  { category: 'retail', count: 1, system_count: 0, tenant_count: 1 },
  { category: 'timestamps', count: 1, system_count: 1, tenant_count: 0 },
];

beforeEach(() => {
  helper.getAllPropertyTemplates.mockResolvedValue(JSON.stringify({ success: true, templates: DOCS_TEMPLATES }));
  helper.getPropertyTemplateStats.mockResolvedValue(JSON.stringify({ success: true, stats: DOCS_STATS }));
  helper.getPropertyTemplateCategoriesAdmin.mockResolvedValue(
    JSON.stringify({ success: true, categories: DOCS_CATEGORIES })
  );
});

/** Render the screen inside the admin console frame. */
function renderScreen() {
  return render(
    <DialogProvider>
      <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <AdminSidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <PropertyTemplateManagementClient />
        </div>
      </div>
    </DialogProvider>
  );
}

/** The row of a template, as a `within` scope. */
function row(name: string) {
  return within(screen.getByText(name).closest('tr') as HTMLElement);
}

/** The frame's root element. */
const frame = () => document.body.firstElementChild as HTMLElement;

describe('Property Templates — the docs fixtures', () => {
  it('lists the templates with their stats, categories and status', async () => {
    renderScreen();
    await screen.findByText('Product SKU');
    expect(screen.getByText('Total Templates')).toBeInTheDocument();
    expect(row('Product SKU').getByText('Tenant')).toBeInTheDocument();
    expect(row('Legacy Customer ID').getByText('Disabled')).toBeInTheDocument();
    expect(row('UUID').getByText('string (uuid)')).toBeInTheDocument();
    writeA11yFixture('admin-property-templates', liveMarkup(frame()));
  });

  it('opens the row menu with every action', async () => {
    renderScreen();
    await screen.findByText('Product SKU');
    // A row near the top: the menu opens downward and the table clips it at its bottom edge.
    fireEvent.click(row('Email').getAllByRole('button').at(-1) as HTMLElement);
    for (const action of ['View Details', 'Edit Template', 'Copy Schema', 'Disable Template', 'Delete Template']) {
      expect(screen.getByRole('button', { name: action })).toBeInTheDocument();
    }
    writeA11yFixture('admin-property-template-menu', liveMarkup(frame()));
  });

  it('shows a template’s details', async () => {
    renderScreen();
    await screen.findByText('Product SKU');
    fireEvent.click(row('Product SKU').getAllByRole('button').at(-1) as HTMLElement);
    fireEvent.click(screen.getByRole('button', { name: 'View Details' }));
    expect(screen.getByText('Usage Count')).toBeInTheDocument();
    expect(screen.getByText('Created By')).toBeInTheDocument();
    expect(screen.getAllByText('Priya Raman').length).toBeGreaterThan(0);
    writeA11yFixture('admin-property-template-view', liveMarkup(frame()));
  });

  it('opens Create New Template filled in, and saves it through the server action', async () => {
    helper.createPropertyTemplateAdmin.mockResolvedValue(JSON.stringify({ success: true }));
    renderScreen();
    await screen.findByText('Product SKU');
    fireEvent.click(screen.getByRole('button', { name: /Add Template/ }));
    expect(screen.getByRole('heading', { name: 'Create New Template' })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('e.g., UUID, Email, Created At'), { target: { value: 'Country Code' } });
    fireEvent.change(screen.getByPlaceholderText('Brief description of the template'), {
      target: { value: 'ISO 3166-1 alpha-2 country code.' },
    });
    // The dialog's category select is the second on screen; the first is the list's filter.
    fireEvent.change(screen.getAllByRole('combobox').at(-1) as HTMLElement, { target: { value: 'i18n' } });
    const schema = JSON.stringify({ type: 'string', pattern: '^[A-Z]{2}$', example: 'NZ' }, null, 2);
    fireEvent.change(screen.getByPlaceholderText(/"type": "string", "format": "uuid"/), { target: { value: schema } });
    fireEvent.change(screen.getByPlaceholderText('id, uuid, identifier, primary-key'), {
      target: { value: 'country, iso-3166, address' },
    });
    writeA11yFixture('admin-property-template-create', liveMarkup(frame()));

    fireEvent.click(screen.getByRole('button', { name: 'Create Template' }));
    await screen.findByText('Template created successfully');
    expect(helper.createPropertyTemplateAdmin).toHaveBeenCalledWith(
      'Country Code',
      'ISO 3166-1 alpha-2 country code.',
      'i18n',
      { type: 'string', pattern: '^[A-Z]{2}$', example: 'NZ' },
      ['country', 'iso-3166', 'address'],
      true,
      true
    );
  });
});
