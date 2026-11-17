'use client';

/**
 * Ship → Products → one product — `/ade/dashboard/products/{slug}` (APX-1.1, #6098).
 *
 * The product editor, in four parts:
 *
 * - **Details** — name, summary, owner team (when Teams is released), visibility and state, saved
 *   together with **Save product**. **Portal** is offered only while every member is published,
 *   and the unpublished members are named under the picker.
 * - **Members** — what the product includes, each with the version it means today: a project at
 *   latest follows every new publish, a project at a version or range (`2.x`) shows the newest
 *   published version in range. **Add member** names one by slug or id; **Remove** drops one.
 * - **Plans** — the tiers consumers subscribe to (APX-1.2, #6099): auth strategy, limits, approval,
 *   environments and terms, edited in place ({@link ProductPlansSection}).
 * - **Delete product** — soft-deletes it after a confirmation; the members themselves are untouched.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  FormField,
  FormFrame,
  FormSection,
  GatedState,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from '@/app/components/ui';
import { useAuthSession } from '@lib/auth/session-client';
import { isFeatureReleased } from '@lib/feature-release';
import type { Team } from '@lib/owners';
import {
  MEMBER_KIND_LABELS,
  PRODUCTS_HREF,
  PRODUCT_MEMBER_KINDS,
  PRODUCT_STATES,
  PRODUCT_VISIBILITIES,
  STATE_LABELS,
  VISIBILITY_LABELS,
  memberInputError,
  memberVersionText,
  unpublishedMembers,
  type ApiProduct,
  type ApiProductPatch,
  type ProductMember,
  type ProductMemberKind,
  type ProductState,
  type ProductVisibility,
} from '@lib/api-products';
import {
  addProductMember,
  deleteProduct,
  fetchProduct,
  removeProductMember,
  updateProduct,
} from '@/app/components/ade/apiProducts/apiProductsApi';
import ProductPlansSection from '@/app/components/ade/apiProducts/ProductPlansSection';
import { fetchTeams } from '@/app/components/ade/owners/ownersApi';

const HOME_ROUTE = '/ade/dashboard';

/** The owner-team picker's value for "no owner" (a Select item cannot be empty). */
const NO_OWNER = '__none__';

/**
 * The editor for one product.
 *
 * @param props - The product's slug.
 * @returns The page.
 */
export default function ProductEditorClient({ slug }: { slug: string }) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [product, setProduct] = React.useState<ApiProduct | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [teams, setTeams] = React.useState<Team[]>([]);
  const showOwner = isFeatureReleased('teams');

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setProduct(await fetchProduct(slug));
    } catch (caught) {
      setProduct(null);
      setError(caught instanceof Error ? caught.message : 'Could not load the product');
    }
  }, [slug]);

  React.useEffect(() => {
    if (!tenantId) return;
    void load();
    // The owner picker is secondary: without teams it offers only "No owner".
    if (showOwner) fetchTeams().then(setTeams).catch(() => setTeams([]));
  }, [tenantId, load, showOwner]);

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Ship' },
          { label: 'Products', href: PRODUCTS_HREF },
          { label: product?.name ?? slug },
        ]}
        title={product?.name ?? 'Product'}
        description={product?.summary ?? 'What this product bundles, and who can see it.'}
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="API products belong to one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The product could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : product === null ? (
          <p className="apx-note" data-testid="product-loading">
            Reading the product…
          </p>
        ) : (
          <div className="apx-editor" data-testid="product-editor">
            <DetailsForm product={product} teams={teams} showOwner={showOwner} onSaved={setProduct} />
            <MembersSection product={product} onChanged={setProduct} />
            <ProductPlansSection product={product} />
            <DeleteSection product={product} />
          </div>
        )}
      </PageBody>
    </Page>
  );
}

/**
 * The **Details** form.
 *
 * @param props - The product, the workspace's teams, whether the owner picker shows, and what to
 *   do with the saved product.
 * @returns The form.
 */
function DetailsForm({
  product,
  teams,
  showOwner,
  onSaved,
}: {
  product: ApiProduct;
  teams: Team[];
  showOwner: boolean;
  onSaved: (product: ApiProduct) => void;
}) {
  const [name, setName] = React.useState(product.name);
  const [summary, setSummary] = React.useState(product.summary ?? '');
  const [owner, setOwner] = React.useState(product.owner_team?.slug ?? NO_OWNER);
  const [visibility, setVisibility] = React.useState<ProductVisibility>(product.visibility);
  const [state, setState] = React.useState<ProductState>(product.state);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | undefined>();

  const patch = React.useMemo<ApiProductPatch>(() => {
    const out: ApiProductPatch = {};
    if (name.trim() !== product.name) out.name = name.trim();
    if ((summary.trim() || null) !== (product.summary ?? null)) out.summary = summary.trim() || null;
    if (showOwner && owner !== (product.owner_team?.slug ?? NO_OWNER)) out.owner_team = owner === NO_OWNER ? null : owner;
    if (visibility !== product.visibility) out.visibility = visibility;
    if (state !== product.state) out.state = state;
    return out;
  }, [name, summary, owner, visibility, state, product, showOwner]);
  const dirty = Object.keys(patch).length > 0;
  const blockers = unpublishedMembers(product.members ?? []);
  const portalBlocked = blockers.length > 0 && product.visibility !== 'portal';

  const save = async () => {
    setSaving(true);
    setError(undefined);
    try {
      onSaved(await updateProduct(product.slug, patch));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the product');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormFrame
      width="default"
      submitLabel={saving ? 'Saving…' : 'Save product'}
      submitDisabled={!dirty || !name.trim()}
      submitDisabledReason={!name.trim() ? 'A product needs a name.' : 'Nothing has changed.'}
      submitting={saving}
      dirty={dirty}
      error={error}
      onSubmit={() => void save()}
      data-testid="product-details"
    >
      <FormSection title="Details" headingLevel="h2" description={`Handle: ${product.slug} — it cannot change.`}>
        <FormField label="Name" required htmlFor="product-name">
          <Input id="product-name" value={name} onChange={(event) => setName(event.target.value)} />
        </FormField>
        <FormField label="Summary" htmlFor="product-summary">
          <Textarea id="product-summary" rows={2} value={summary} onChange={(event) => setSummary(event.target.value)} />
        </FormField>
        {showOwner ? (
          <FormField label="Owner team" htmlFor="product-owner">
            <Select value={owner} onValueChange={setOwner}>
              <SelectTrigger id="product-owner">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_OWNER}>No owner</SelectItem>
                {teams.map((team) => (
                  <SelectItem key={team.slug} value={team.slug}>
                    {team.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        ) : null}
        <FormField
          label="Visibility"
          htmlFor="product-visibility"
          helperText={
            portalBlocked
              ? `Portal needs every member published. Not published: ${blockers.map(memberName).join(', ')}.`
              : VISIBILITY_LABELS[visibility].hint
          }
        >
          <Select value={visibility} onValueChange={(value) => setVisibility(value as ProductVisibility)}>
            <SelectTrigger id="product-visibility" data-testid="product-visibility">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRODUCT_VISIBILITIES.map((value) => (
                <SelectItem key={value} value={value} disabled={value === 'portal' && portalBlocked}>
                  {VISIBILITY_LABELS[value].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="State" htmlFor="product-state">
          <Select value={state} onValueChange={(value) => setState(value as ProductState)}>
            <SelectTrigger id="product-state">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRODUCT_STATES.map((value) => (
                <SelectItem key={value} value={value}>
                  {STATE_LABELS[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </FormSection>
    </FormFrame>
  );
}

/**
 * A member's display name: its entity's name, else its slug, else its id.
 *
 * @param member - The member.
 * @returns The name.
 */
function memberName(member: ProductMember): string {
  return member.name ?? member.slug ?? member.ref;
}

/**
 * The **Members** section: the member table and the add-member row.
 *
 * @param props - The product, and what to do with the product a change returns.
 * @returns The section.
 */
function MembersSection({ product, onChanged }: { product: ApiProduct; onChanged: (product: ApiProduct) => void }) {
  const members = product.members ?? [];
  const [removing, setRemoving] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const remove = async (member: ProductMember) => {
    setRemoving(member.id);
    setError(null);
    try {
      onChanged(await removeProductMember(product.slug, member.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not remove the member');
    } finally {
      setRemoving(null);
    }
  };

  return (
    <section className="apx-section" aria-labelledby="apx-members" data-testid="product-members">
      <h2 id="apx-members" className="apx-section__title">
        Members <span className="apx-muted">{members.length}</span>
      </h2>
      {members.length === 0 ? (
        <p className="apx-muted">No members yet. Add the projects and MCP servers this product bundles.</p>
      ) : (
        <div className="apx-table-wrap">
          <table className="apx-table" data-testid="product-members-table">
            <caption className="sr-only">Members of {product.name}</caption>
            <thead>
              <tr>
                <th scope="col">Member</th>
                <th scope="col">Kind</th>
                <th scope="col">Version</th>
                <th scope="col">Environment</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr key={member.id} data-testid={`product-member-${member.id}`}>
                  <td>
                    <span className="apx-name">{memberName(member)}</span>
                    {member.slug ? <span className="apx-slug mono">{member.slug}</span> : null}
                  </td>
                  <td>{MEMBER_KIND_LABELS[member.kind].label}</td>
                  <td className="mono">{memberVersionText(member) ?? <span className="apx-muted">—</span>}</td>
                  <td>{member.environment ?? <span className="apx-muted">All</span>}</td>
                  <td>
                    {member.missing ? (
                      <Badge variant="danger">Deleted</Badge>
                    ) : member.published ? (
                      <Badge status="published">Published</Badge>
                    ) : (
                      <Badge status="draft">Not published</Badge>
                    )}
                  </td>
                  <td className="apx-actions">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void remove(member)}
                      disabled={removing === member.id}
                      aria-label={`Remove ${memberName(member)}`}
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error ? (
        <p className="apx-error" role="alert">
          {error}
        </p>
      ) : null}
      <AddMemberForm product={product} onAdded={onChanged} />
    </section>
  );
}

/**
 * The add-member row: kind, slug or id, version (for a project at a version) and environment.
 *
 * @param props - The product, and what to do with the product the add returns.
 * @returns The form.
 */
function AddMemberForm({ product, onAdded }: { product: ApiProduct; onAdded: (product: ApiProduct) => void }) {
  const [kind, setKind] = React.useState<ProductMemberKind>('project_latest');
  const [ref, setRef] = React.useState('');
  const [version, setVersion] = React.useState('');
  const [environment, setEnvironment] = React.useState('');
  const [adding, setAdding] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    const input = {
      kind,
      ref: ref.trim(),
      ...(kind === 'project_version' ? { version: version.trim() } : {}),
      ...(environment.trim() ? { environment: environment.trim() } : {}),
    };
    const invalid = memberInputError(input);
    if (invalid) {
      setError(invalid);
      return;
    }
    setAdding(true);
    setError(null);
    try {
      onAdded(await addProductMember(product.slug, input));
      setRef('');
      setVersion('');
      setEnvironment('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add the member');
    } finally {
      setAdding(false);
    }
  };

  return (
    <form className="apx-add" onSubmit={(event) => void add(event)} noValidate data-testid="product-add-member">
      <FormField label="Kind" htmlFor="member-kind" helperText={MEMBER_KIND_LABELS[kind].hint}>
        <Select value={kind} onValueChange={(value) => setKind(value as ProductMemberKind)}>
          <SelectTrigger id="member-kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRODUCT_MEMBER_KINDS.map((value) => (
              <SelectItem key={value} value={value}>
                {MEMBER_KIND_LABELS[value].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label={kind === 'mcp_server' ? 'MCP server' : kind === 'catalog_item' ? 'Catalog item' : 'Project'} required htmlFor="member-ref">
        <Input id="member-ref" className="mono" value={ref} placeholder="slug or id" onChange={(event) => setRef(event.target.value)} />
      </FormField>
      {kind === 'project_version' ? (
        <FormField label="Version" required htmlFor="member-version">
          <Input id="member-version" className="mono" value={version} placeholder="2.x" onChange={(event) => setVersion(event.target.value)} />
        </FormField>
      ) : null}
      <FormField label="Environment" htmlFor="member-environment">
        <Input
          id="member-environment"
          value={environment}
          placeholder="All"
          onChange={(event) => setEnvironment(event.target.value)}
        />
      </FormField>
      <div className="apx-add__submit">
        <Button type="submit" variant="soft" disabled={adding} data-testid="product-add-member-submit">
          <Plus aria-hidden />
          {adding ? 'Adding…' : 'Add member'}
        </Button>
      </div>
      {error ? (
        <p className="apx-error apx-add__error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

/**
 * **Delete product**, behind a confirmation.
 *
 * @param props - The product.
 * @returns The section.
 */
function DeleteSection({ product }: { product: ApiProduct }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const remove = async () => {
    setDeleting(true);
    setError(null);
    try {
      await deleteProduct(product.slug);
      router.push(PRODUCTS_HREF);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete the product');
      setDeleting(false);
    }
  };

  return (
    <section className="apx-section apx-danger" aria-labelledby="apx-delete">
      <h2 id="apx-delete" className="apx-section__title">
        Delete product
      </h2>
      <p className="apx-muted">
        The projects and MCP servers it bundles are untouched. The handle <span className="mono">{product.slug}</span>{' '}
        becomes free again. <Link className="apx-link" href={PRODUCTS_HREF}>Back to Products</Link>
      </p>
      <div>
        <Button variant="danger" onClick={() => setOpen(true)} data-testid="product-delete">
          <Trash2 aria-hidden />
          Delete product
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {product.name}?</DialogTitle>
            <DialogDescription>Consumers lose this bundle; its members stay in the catalog.</DialogDescription>
          </DialogHeader>
          {error ? (
            <p className="apx-error" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void remove()} disabled={deleting} data-testid="product-delete-confirm">
              {deleting ? 'Deleting…' : 'Delete product'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
