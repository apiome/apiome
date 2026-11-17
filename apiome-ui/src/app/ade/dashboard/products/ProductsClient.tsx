'use client';

/**
 * Ship → Products — `/ade/dashboard/products` (APX-1.1, #6098).
 *
 * Every API product in the workspace: the thing a consumer is granted access to ("Payments API"),
 * bundling projects at a version or at latest, MCP servers and catalog items. Each row shows the
 * product's name and handle, its lifecycle state, its visibility, how many members it has and (when
 * Teams is released) its owner team. **New product** creates one; the name opens the editor.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Plus, RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  FormField,
  GatedState,
  Input,
  Textarea,
} from '@/app/components/ui';
import { useAuthSession } from '@lib/auth/session-client';
import { isFeatureReleased } from '@lib/feature-release';
import { STATE_LABELS, VISIBILITY_LABELS, productHref, type ApiProduct } from '@lib/api-products';
import { createProduct, fetchProducts } from '@/app/components/ade/apiProducts/apiProductsApi';

const HOME_ROUTE = '/ade/dashboard';

/**
 * The Products list.
 *
 * @returns The page.
 */
export default function ProductsClient() {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [products, setProducts] = React.useState<ApiProduct[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const showOwner = isFeatureReleased('teams');

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setProducts(await fetchProducts());
    } catch (caught) {
      setProducts(null);
      setError(caught instanceof Error ? caught.message : 'Could not load the API products');
    }
  }, []);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Ship' }, { label: 'Products' }]}
        title="Products"
        description="Bundles of projects, versions and MCP servers that consumers are given access to."
        actions={
          tenantId ? (
            <Button onClick={() => setCreating(true)} data-testid="products-new">
              <Plus aria-hidden />
              New product
            </Button>
          ) : null
        }
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="API products belong to one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The API products could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : products === null ? (
          <p className="apx-note" data-testid="products-loading">
            Reading your API products…
          </p>
        ) : products.length === 0 ? (
          <EmptyState
            variant="compact"
            surface={false}
            title="No API products yet"
            description="Create one to bundle the projects and MCP servers a consumer gets access to."
            action={
              <Button variant="soft" onClick={() => setCreating(true)}>
                <Plus aria-hidden />
                New product
              </Button>
            }
          />
        ) : (
          <div className="apx-table-wrap">
            <table className="apx-table" data-testid="products-table">
              <caption className="sr-only">API products in this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col">State</th>
                  <th scope="col">Visibility</th>
                  <th scope="col">Members</th>
                  {showOwner ? <th scope="col">Owner</th> : null}
                </tr>
              </thead>
              <tbody>
                {products.map((product) => (
                  <tr key={product.id} data-testid={`product-row-${product.slug}`}>
                    <td>
                      <Link className="apx-name" href={productHref(product.slug)}>
                        {product.name}
                      </Link>
                      <span className="apx-slug mono">{product.slug}</span>
                      {product.summary ? <span className="apx-summary">{product.summary}</span> : null}
                    </td>
                    <td>
                      <Badge status={product.state}>{STATE_LABELS[product.state]}</Badge>
                    </td>
                    <td>{VISIBILITY_LABELS[product.visibility].label}</td>
                    <td className="apx-num">{product.member_count}</td>
                    {showOwner ? <td>{product.owner_team?.name ?? <span className="apx-muted">—</span>}</td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>
      <NewProductDialog open={creating} onOpenChange={setCreating} />
    </Page>
  );
}

/**
 * The **New product** dialog: a name, an optional handle and a summary. Visibility starts
 * `private` and state `draft`; members are added in the editor it opens.
 *
 * @param props - Whether it is open, and the setter.
 * @returns The dialog.
 */
export function NewProductDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const [name, setName] = React.useState('');
  const [slug, setSlug] = React.useState('');
  const [summary, setSummary] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      setName('');
      setSlug('');
      setSummary('');
      setError(null);
    }
  }, [open]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const created = await createProduct({
        name: name.trim(),
        ...(slug.trim() ? { slug: slug.trim() } : {}),
        ...(summary.trim() ? { summary: summary.trim() } : {}),
      });
      onOpenChange(false);
      router.push(productHref(created.slug));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create the product');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="product-new-dialog">
        <form onSubmit={(event) => void submit(event)} noValidate>
          <DialogHeader>
            <DialogTitle>New product</DialogTitle>
            <DialogDescription>Name the product the way a consumer would ask for it.</DialogDescription>
          </DialogHeader>
          <DialogBody className="apx-form">
            <FormField label="Name" required htmlFor="product-new-name">
              <Input id="product-new-name" value={name} onChange={(event) => setName(event.target.value)} autoFocus />
            </FormField>
            <FormField
              label="Handle"
              helperText="Used in URLs and plans. Derived from the name when left empty; cannot change later."
              htmlFor="product-new-slug"
            >
              <Input
                id="product-new-slug"
                className="mono"
                value={slug}
                placeholder="payments"
                onChange={(event) => setSlug(event.target.value)}
              />
            </FormField>
            <FormField label="Summary" htmlFor="product-new-summary">
              <Textarea id="product-new-summary" rows={3} value={summary} onChange={(event) => setSummary(event.target.value)} />
            </FormField>
            {error ? (
              <p className="apx-error" role="alert">
                {error}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || saving} data-testid="product-new-create">
              {saving ? 'Creating…' : 'Create product'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
