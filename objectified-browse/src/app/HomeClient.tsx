'use client';

import { DataTable } from './components/DataTable';

interface Tenant {
  id: string;
  name: string;
  slug: string;
  description?: string;
  created_at?: string;
}

export function HomeClient({ tenants }: { tenants: Tenant[] }) {
  return (
    <div className="py-8">
      <div className="container mx-auto px-4">

        {/* Page Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                Organizations
              </h1>
              <p className="mt-1 text-zinc-600 dark:text-zinc-400">
                Browse API specifications by organization
              </p>
            </div>
          </div>
        </div>

        {/* Data Table */}
        <DataTable
          data={tenants}
          keyField="id"
          getRowHref={(tenant) => `/tenant/${tenant.slug}`}
          searchable={true}
          searchPlaceholder="Search organizations..."
          searchFields={['name', 'slug', 'description']}
          emptyMessage="No organizations with published specifications available."
          columns={[
            {
              key: 'name',
              header: 'Organization',
              sortable: true,
              render: (tenant) => (
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 text-white font-bold">
                    {tenant.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div className="font-medium text-zinc-900 group-hover:text-blue-600 dark:text-zinc-50 dark:group-hover:text-blue-400">
                      {tenant.name}
                    </div>
                    <div className="text-xs text-zinc-500 dark:text-zinc-400">
                      /{tenant.slug}
                    </div>
                  </div>
                </div>
              ),
            },
            {
              key: 'description',
              header: 'Description',
              sortable: false,
              render: (tenant) => (
                <span className="text-zinc-600 dark:text-zinc-400 line-clamp-2">
                  {tenant.description || '—'}
                </span>
              ),
            },
            {
              key: 'created_at',
              header: 'Created',
              width: 'w-32',
              sortable: true,
              render: (tenant) => (
                <span className="text-zinc-500 dark:text-zinc-400">
                  {tenant.created_at ? new Date(tenant.created_at).toLocaleDateString() : '—'}
                </span>
              ),
            },
            {
              key: 'actions',
              header: '',
              width: 'w-12',
              render: () => (
                <svg className="h-5 w-5 text-zinc-400 group-hover:text-blue-600 dark:group-hover:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              ),
            },
          ]}
        />

        {/* Quick Stats */}
        {/*{tenants.length > 0 && (*/}
        {/*  <div className="mt-8 grid gap-4 sm:grid-cols-3">*/}
        {/*    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">*/}
        {/*      <div className="flex items-center gap-3">*/}
        {/*        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400">*/}
        {/*          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">*/}
        {/*            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />*/}
        {/*          </svg>*/}
        {/*        </div>*/}
        {/*        <div>*/}
        {/*          <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Public APIs</div>*/}
        {/*          <div className="text-sm text-zinc-500 dark:text-zinc-400">All specifications are published</div>*/}
        {/*        </div>*/}
        {/*      </div>*/}
        {/*    </div>*/}
        {/*    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">*/}
        {/*      <div className="flex items-center gap-3">*/}
        {/*        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400">*/}
        {/*          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">*/}
        {/*            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />*/}
        {/*          </svg>*/}
        {/*        </div>*/}
        {/*        <div>*/}
        {/*          <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Multiple Formats</div>*/}
        {/*          <div className="text-sm text-zinc-500 dark:text-zinc-400">OpenAPI, Arazzo, JSON Schema</div>*/}
        {/*        </div>*/}
        {/*      </div>*/}
        {/*    </div>*/}
        {/*    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">*/}
        {/*      <div className="flex items-center gap-3">*/}
        {/*        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400">*/}
        {/*          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">*/}
        {/*            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />*/}
        {/*          </svg>*/}
        {/*        </div>*/}
        {/*        <div>*/}
        {/*          <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Version Compare</div>*/}
        {/*          <div className="text-sm text-zinc-500 dark:text-zinc-400">Compare API versions side-by-side</div>*/}
        {/*        </div>*/}
        {/*      </div>*/}
        {/*    </div>*/}
        {/*  </div>*/}
        {/*)}*/}
      </div>
    </div>
  );
}

