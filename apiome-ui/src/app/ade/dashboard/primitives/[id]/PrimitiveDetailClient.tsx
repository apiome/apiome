'use client';

/**
 * One registry type, beyond the edit dialog (HIVE-6.6, #5317).
 *
 * Authority: `docs/mockups/build/primitive-detail.html`, whose **Notes → Keeps (1:1)** list is
 * this ticket's acceptance criteria, and `docs/mockups/DESIGN.md` §5.3 (page header), §7
 * (component vocabulary) and §8 (the list pattern).
 *
 * ### What this file is now
 *
 * One read and the page's few writes — export, copy, and the deprecation lifecycle (#3482) — and
 * nothing else. Every surface it draws lives in
 * `components/ade/primitives/detail`: the schema pane, the test form, the reference and dependent
 * tables, the example, the metadata aside, the usage tiles and the base chain; every rule they
 * share lives in `primitiveDetailView.ts`. What that removed from here was 400 lines of markup —
 * a white `<header>` with an indigo library glyph, two hand-built `<table>`s with `px-5 py-3`
 * cells, six pill palettes, a `bg-gray-900` example block and a local `SchemaActionButton` that
 * re-derived the `Button` outline variant.
 *
 * ### The one card the mockup draws that this page does not
 *
 * The mockup opens the main column with a description card *and* a `page-desc` line under the
 * title, because its author wrote two different sentences. A stored type has **one**
 * `description`, and printing the same sentence twice, 24 px apart, is worse than either — so it
 * goes in the slot DESIGN.md §5.3 provides for exactly this, the header's own description line,
 * and the card is gone. Everything else on the Keeps (1:1) list is here.
 *
 * ### The dead deep-link
 *
 * The mockup's Keeps list flags it: Edit used to point at `/ade/dashboard/primitives?edit=<id>`,
 * and **nothing on the registry screen read that parameter** — the one affordance offered for
 * "edit this type" landed on an unfiltered list. `PrimitivesManagementClient` reads `?edit=` now
 * (`primitiveIdFromEditParam`), the same fix HIVE-6.5 made for its sibling `?focus=`, so the link
 * opens the editor on the type the reader was looking at.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Archive, ArchiveRestore, Library, Pencil, Upload } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { downloadBlob } from '@/app/components/ade/dashboard/export/exportDownload';
import {
  BaseChainCard,
  COPY_ACK_MS,
  DependentsCard,
  DeprecateTypeDialog,
  DeprecationNotice,
  PropertyDependentsCard,
  ExampleInstanceCard,
  LOADING_MESSAGE,
  PrimitiveMetadataCard,
  PrimitiveSchemaCard,
  PrimitiveTestForm,
  PrimitiveUsageCard,
  ReferenceResolutionCard,
  deprecateAffordance,
  deprecationNotice,
  detailBreadcrumb,
  editAffordance,
  headerBadges,
  lifecycleLabel,
  type PrimitiveDetail,
} from '@/app/components/ade/primitives/detail';
import {
  buildBaseChain,
  buildExampleInstance,
  deriveOwner,
  deriveVersionRoot,
  effectiveNamespace,
  exportFileName,
  serializeSchemaExport,
  summarizeUsage,
} from '../primitiveDetailModel';
import { todayIsoDate } from '../primitiveLifecycleModel';

/**
 * The type-detail screen.
 *
 * @returns The page: header, main column and aside — or the loading region / failure in place of
 *   both.
 */
export default function PrimitiveDetailClient() {
  const params = useParams<{ id: string }>();
  const [primitive, setPrimitive] = useState<PrimitiveDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Transient "Copied" / "Copy failed" acknowledgement on the schema card's Copy button. */
  const [schemaCopied, setSchemaCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  /** The Deprecate dialog (#3482), and the Restore write that needs no dialog. */
  const [showDeprecate, setShowDeprecate] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);

  const loadPrimitive = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/primitives/${params.id}`);
      const data = await response.json();
      if (!response.ok || !data.success) {
        setError(data.error || 'Failed to load primitive');
        setPrimitive(null);
        return;
      }
      setPrimitive(data.primitive as PrimitiveDetail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load primitive');
      setPrimitive(null);
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    if (params.id) {
      void loadPrimitive();
    }
  }, [params.id, loadPrimitive]);

  // Let the copy acknowledgement fall back to the idle label after a beat.
  useEffect(() => {
    if (!schemaCopied && !copyFailed) return undefined;
    const timer = setTimeout(() => {
      setSchemaCopied(false);
      setCopyFailed(false);
    }, COPY_ACK_MS);
    return () => clearTimeout(timer);
  }, [schemaCopied, copyFailed]);

  // The header's Export action and the schema card's Download button are the same operation, so
  // both go through here — one filename and one serialization for the file the user ends up with.
  const handleExport = useCallback(() => {
    if (!primitive) return;
    const blob = new Blob([serializeSchemaExport(primitive.schema)], { type: 'application/json' });
    downloadBlob(blob, exportFileName(primitive.name));
  }, [primitive]);

  const handleCopySchema = useCallback(async () => {
    if (!primitive) return;
    try {
      await navigator.clipboard.writeText(serializeSchemaExport(primitive.schema));
      setSchemaCopied(true);
    } catch {
      // Clipboard unavailable (insecure context / denied permission) — say so rather than
      // flashing "Copied" for a write that never landed.
      setCopyFailed(true);
    }
  }, [primitive]);

  // The lifecycle writes answer with the type's row, which carries no dependents or annotated
  // refs — those only come from the detail read — so the answer is merged over what is on screen
  // rather than replacing it.
  const applyLifecycle = useCallback((updated: PrimitiveDetail) => {
    setPrimitive((current) =>
      current
        ? {
            ...current,
            deprecated: updated.deprecated,
            deprecated_at: updated.deprecated_at ?? null,
            sunset_date: updated.sunset_date ?? null,
            deprecation_message: updated.deprecation_message ?? null,
            replacement_id: updated.replacement_id ?? null,
            replacement: updated.replacement ?? null,
          }
        : current
    );
  }, []);

  // Restoring is harmless and undone by deprecating again, so it asks for no confirmation.
  const handleRestore = useCallback(async () => {
    if (!primitive || restoring) return;
    setRestoring(true);
    setLifecycleError(null);
    try {
      const response = await fetch(`/api/primitives/${encodeURIComponent(primitive.id)}/deprecate`, {
        method: 'DELETE',
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setLifecycleError(data.error || 'The type could not be restored.');
        return;
      }
      applyLifecycle(data.primitive as PrimitiveDetail);
    } catch (err) {
      setLifecycleError(err instanceof Error ? err.message : 'The type could not be restored.');
    } finally {
      setRestoring(false);
    }
  }, [primitive, restoring, applyLifecycle]);

  const baseChain = useMemo(
    () => (primitive ? buildBaseChain(primitive.name, primitive.refs) : []),
    [primitive]
  );
  const usage = useMemo(
    () => (primitive ? summarizeUsage(primitive.dependents, primitive.usage_count) : null),
    [primitive]
  );
  const exampleInstance = useMemo(
    () => (primitive ? buildExampleInstance(primitive.schema) : null),
    [primitive]
  );
  const schemaJson = useMemo(
    () => (primitive ? serializeSchemaExport(primitive.schema) : ''),
    [primitive]
  );

  // The schema's own `$id` is the authority for where the type lives, so the namespace is read back
  // out of it; the stored column only stands in when the id carries no recoverable namespace (an
  // explicit `base_uri`, or an author-declared `$id` outside the registry mount). Preferring the
  // document's `$id` over the `schema_id` column keeps the display tied to the schema on screen.
  const schemaIdentity =
    (typeof primitive?.schema?.$id === 'string' ? primitive.schema.$id : null) ??
    primitive?.schema_id ??
    null;
  const namespacePath = primitive ? effectiveNamespace(schemaIdentity, primitive.namespace) : null;
  const versionRoot = primitive ? deriveVersionRoot(namespacePath, primitive.base_uri) : null;
  const edit = primitive ? editAffordance(primitive) : null;
  const lifecycle = primitive ? deprecateAffordance(primitive) : null;
  const notice = primitive ? deprecationNotice(primitive, todayIsoDate()) : null;

  return (
    <Page>
      <PageHeader
        breadcrumb={detailBreadcrumb(namespacePath)}
        title={
          <>
            <Library aria-hidden className="pd-title-glyph" />
            {loading ? 'Loading type…' : primitive?.name ?? 'Type detail'}
          </>
        }
        badge={
          primitive ? (
            <span className="pd-badges">
              {headerBadges(primitive).map((badge) => (
                <Badge
                  key={badge.id}
                  variant={badge.tone}
                  mono={badge.mono}
                  data-testid={`primitive-detail-badge-${badge.id}`}
                >
                  {badge.label}
                </Badge>
              ))}
            </span>
          ) : null
        }
        description={primitive?.description ?? undefined}
        actions={
          primitive && edit && lifecycle ? (
            <>
              {edit.href ? (
                <Button variant="outline" asChild title={edit.title}>
                  <Link href={edit.href} data-testid="primitive-detail-edit">
                    <Pencil aria-hidden />
                    Edit
                  </Link>
                </Button>
              ) : (
                <Button variant="outline" disabled title={edit.title} data-testid="primitive-detail-edit">
                  <Pencil aria-hidden />
                  Edit
                </Button>
              )}
              <Button variant="outline" onClick={handleExport} data-testid="primitive-detail-export">
                <Upload aria-hidden />
                Export
              </Button>
              {lifecycle.action === 'restore' ? (
                <>
                  <Button
                    variant="outline"
                    onClick={() => setShowDeprecate(true)}
                    title="Change the sunset date, message or replacement"
                    data-testid="primitive-detail-edit-deprecation"
                  >
                    <Archive aria-hidden />
                    Edit deprecation
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void handleRestore()}
                    disabled={restoring}
                    title={restoring ? 'Restoring this type…' : lifecycle.title}
                    data-testid="primitive-detail-restore"
                  >
                    <ArchiveRestore aria-hidden />
                    {restoring ? 'Restoring…' : lifecycle.label}
                  </Button>
                </>
              ) : (
                <Button
                  variant="danger-soft"
                  disabled={lifecycle.disabled}
                  onClick={() => setShowDeprecate(true)}
                  title={lifecycle.title}
                  data-testid="primitive-detail-deprecate"
                >
                  <Archive aria-hidden />
                  {lifecycle.label}
                </Button>
              )}
            </>
          ) : undefined
        }
      />

      <PageBody>
        {loading ? (
          <LoadingState minHeightClassName="min-h-[15rem]" message={LOADING_MESSAGE} />
        ) : error ? (
          <ErrorState
            title="This type could not be loaded"
            description={error}
            onRetry={() => void loadPrimitive()}
            data-testid="primitive-detail-error"
          />
        ) : primitive ? (
          <div className="pd-grid">
            <div className="pd-col">
              {lifecycleError ? (
                <Alert variant="error" data-testid="primitive-detail-lifecycle-error">
                  <span>{lifecycleError}</span>
                </Alert>
              ) : null}

              {notice ? <DeprecationNotice notice={notice} /> : null}

              <PrimitiveSchemaCard
                name={primitive.name}
                draft={primitive.draft}
                json={schemaJson}
                copied={schemaCopied}
                copyFailed={copyFailed}
                onCopy={() => void handleCopySchema()}
                onDownload={handleExport}
              />

              <PrimitiveTestForm schema={primitive.schema} name={primitive.name} />

              <ReferenceResolutionCard refs={primitive.refs ?? []} baseUri={primitive.base_uri} />

              {exampleInstance !== null ? (
                <ExampleInstanceCard instance={exampleInstance} />
              ) : null}

              <DependentsCard
                dependents={primitive.dependents ?? []}
                identity={primitive.schema_id ?? primitive.name}
              />

              <PropertyDependentsCard
                dependents={primitive.property_dependents ?? []}
                identity={primitive.schema_id ?? primitive.name}
              />
            </div>

            <aside className="pd-col">
              <PrimitiveMetadataCard
                isSystem={primitive.is_system}
                schemaId={primitive.schema_id}
                namespace={namespacePath}
                versionRoot={versionRoot}
                owner={deriveOwner(primitive.is_system, namespacePath)}
                source={primitive.source}
                createdAt={primitive.created_at}
                lifecycle={lifecycleLabel(primitive)}
              />

              {usage ? <PrimitiveUsageCard usage={usage} /> : null}

              <BaseChainCard chain={baseChain} category={primitive.category} />
            </aside>
          </div>
        ) : null}
      </PageBody>

      {showDeprecate && primitive ? (
        <DeprecateTypeDialog
          primitive={primitive}
          onClose={() => setShowDeprecate(false)}
          onSaved={(updated) => {
            applyLifecycle(updated);
            setLifecycleError(null);
            setShowDeprecate(false);
          }}
        />
      ) : null}
    </Page>
  );
}
